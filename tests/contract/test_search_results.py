"""Contrato de la proyección interna de resultados léxicos de `D-07`.

Fija la forma, validación, orden preservado, filtros, proyección desde la autoridad y lectura sin
escritura sobre almacenes mínimos sembrados con SQL.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import re
import sqlite3
from dataclasses import fields
from pathlib import Path
from typing import cast, get_type_hints

import pytest

from book_text_rag.adapters.storage import sqlite as sqlite_module
from book_text_rag.adapters.storage.sqlite import DDL, SCHEMA_VERSION, SqliteStore
from book_text_rag.application.search_lexical import search_lexical
from book_text_rag.domain.identity import content_hash
from book_text_rag.ports.storage import (
    EstadoIngesta,
    SearchResult,
    StoreError,
    StoreErrorCode,
    StoreReader,
)

VERSION = "a" * 64
FILAS = tuple[str, int, str, tuple[str, ...], int | None, int | None]


def _crear_almacen(tmp_path: Path) -> Path:
    ruta = tmp_path / "almacen.sqlite"
    SqliteStore(ruta).initialize()
    return ruta


def _sembrar(ruta: Path, filas: tuple[FILAS, ...]) -> None:
    """Persiste autoridad e índice derivado de las filas indicadas."""
    conexion = sqlite3.connect(ruta)
    try:
        documentos = tuple(dict.fromkeys(fila[0] for fila in filas))
        for document_id in documentos:
            conexion.execute(
                "INSERT INTO fuente (document_id, source_format, page_count) VALUES (?, ?, ?)",
                (document_id, "pdf", 10),
            )
            conexion.execute(
                "INSERT INTO referencia_fuente "
                "(document_id, alias, tipo_asignacion, fecha, estado_ingesta) VALUES (?, ?, ?, ?, ?)",
                (document_id, "alias", "deliberada", "2026-10-18", EstadoIngesta.COMPLETADA.value),
            )
            conexion.execute(
                "INSERT INTO version_documento (document_id, document_version) VALUES (?, ?)",
                (document_id, VERSION),
            )
        for document_id, ordinal, contenido, seccion, pagina_inicio, pagina_fin in filas:
            chunk = f"{document_id}:{ordinal}"
            conexion.execute(
                "INSERT INTO fragmento (document_id, document_version, ordinal, chunk_id, section_path, level, "
                "block_type, captions, pdf_page_start, pdf_page_end, content, content_hash, anchor_level) "
                "VALUES (?, ?, ?, ?, ?, 1, 'prose', '[]', ?, ?, ?, ?, 'posicional')",
                (
                    document_id,
                    VERSION,
                    ordinal,
                    chunk,
                    json.dumps(list(seccion), ensure_ascii=False, separators=(",", ":")),
                    pagina_inicio,
                    pagina_fin,
                    contenido,
                    content_hash(contenido),
                ),
            )
            conexion.execute(
                "INSERT INTO fragmento_fts (document_id, document_version, ordinal, content) VALUES (?, ?, ?, ?)",
                (document_id, VERSION, ordinal, contenido),
            )
        conexion.commit()
    finally:
        conexion.close()


def _ejecutar(ruta: Path, sql: str, parametros: tuple[object, ...] = ()) -> None:
    conexion = sqlite3.connect(ruta)
    try:
        conexion.execute(sql, parametros)
        conexion.commit()
    finally:
        conexion.close()


def _oraculo(
    ruta: Path,
    query: str,
    *,
    top_k: int = 10,
    document_ids: tuple[str, ...] | None = None,
) -> tuple[tuple[str, float], ...]:
    """Consulta SQL independiente en solo lectura, ordenada directamente por el motor FTS5."""
    sql = (
        "SELECT bm25(fragmento_fts), fragmento.chunk_id FROM fragmento_fts "
        "JOIN fragmento ON fragmento.document_id = fragmento_fts.document_id "
        "AND fragmento.document_version = fragmento_fts.document_version "
        "AND fragmento.ordinal = fragmento_fts.ordinal WHERE fragmento_fts MATCH ?"
    )
    parametros: list[object] = [query]
    if document_ids is not None:
        marcadores = ",".join("?" for _ in document_ids)
        sql += f" AND fragmento.document_id IN ({marcadores})"
        parametros.extend(document_ids)
    sql += " ORDER BY rank LIMIT ?"
    parametros.append(top_k)
    conexion = sqlite3.connect(f"{ruta.as_uri()}?mode=ro", uri=True)
    try:
        filas = conexion.execute(sql, parametros).fetchall()
    finally:
        conexion.close()
    return tuple((str(fila[1]), float(fila[0])) for fila in filas)


def _resultado(rank: int, score: float, chunk_id: str) -> SearchResult:
    return SearchResult(
        rank=rank,
        score=score,
        document_id="doc",
        document_version=VERSION,
        chunk_id=chunk_id,
        content="contenido",
        section_path=(),
        pdf_page_start=None,
        pdf_page_end=None,
    )


class _LectorFalso:
    def __init__(self, resultados: tuple[SearchResult, ...]) -> None:
        self.resultados = resultados
        self.llamadas: list[tuple[str, tuple[str, ...] | None, int]] = []

    def search_results(
        self, query: str, *, document_ids: tuple[str, ...] | None = None, top_k: int = 10
    ) -> tuple[SearchResult, ...]:
        self.llamadas.append((query, document_ids, top_k))
        return self.resultados


class _LectorProhibido:
    def search_results(
        self, query: str, *, document_ids: tuple[str, ...] | None = None, top_k: int = 10
    ) -> tuple[SearchResult, ...]:
        raise AssertionError("la aplicación no debía consultar el almacén")


def test_search_result_tiene_nueve_campos_exactos_y_no_incluye_index_version() -> None:
    assert tuple(campo.name for campo in fields(SearchResult)) == (
        "rank",
        "score",
        "document_id",
        "document_version",
        "chunk_id",
        "content",
        "section_path",
        "pdf_page_start",
        "pdf_page_end",
    )
    assert tuple(get_type_hints(SearchResult).values()) == (
        int,
        float,
        str,
        str,
        str,
        str,
        tuple[str, ...],
        int | None,
        int | None,
    )
    assert not {"index_version", "rowid", "word_count", "anchor_evidence", "ordinal"} & {
        campo.name for campo in fields(SearchResult)
    }
    assert not any("index_version" in sentencia for sentencia in DDL)


def test_aplicacion_conserva_orden_y_rank_recibidos() -> None:
    """T1b: la capa de aplicación no reordena ni renumera una secuencia deliberadamente desordenada."""
    resultados = (_resultado(1, 5.0, "primero"), _resultado(2, 1.0, "segundo"), _resultado(3, 9.0, "tercero"))
    lector = _LectorFalso(resultados)
    salida = search_lexical(cast(StoreReader, lector), query="needle", top_k=3)
    assert salida is resultados
    assert [(fila.chunk_id, fila.rank, fila.score) for fila in salida] == [
        ("primero", 1, 5.0),
        ("segundo", 2, 1.0),
        ("tercero", 3, 9.0),
    ]
    assert lector.llamadas == [('"needle"', None, 3)]


@pytest.mark.parametrize(
    ("query", "top_k"),
    [
        ("", 10),
        ("   ", 10),
        ("a" * 1001, 10),
        ("needle", 0),
        ("needle", -1),
        ("needle", 51),
        ("needle", 10**9),
        ("needle", True),
    ],
)
def test_aplicacion_rechaza_entradas_invalidas_antes_de_consultar(query: str, top_k: int) -> None:
    with pytest.raises(ValueError):
        search_lexical(cast(StoreReader, _LectorProhibido()), query=query, top_k=top_k)


@pytest.mark.parametrize("query", [None, b"needle", 123])
def test_aplicacion_rechaza_tipo_de_query_antes_de_consultar(query: object) -> None:
    """F1: falla si un `query` que no es `str` llega al almacén o se usa antes de rechazarlo."""
    with pytest.raises(ValueError, match="query debe ser str"):
        search_lexical(cast(StoreReader, _LectorProhibido()), query=cast(str, query))


@pytest.mark.parametrize(
    ("document_ids", "mensaje"),
    [
        ("doc", "document_ids no puede ser str ni bytes"),
        (b"doc", "document_ids no puede ser str ni bytes"),
        (("doc", 5), "cada elemento de document_ids debe ser str"),
        ((None,), "cada elemento de document_ids debe ser str"),
        (123, "document_ids debe ser una colección de identificadores str"),
        ((2**70,), "cada elemento de document_ids debe ser str"),
    ],
)
def test_aplicacion_rechaza_document_ids_invalidos_antes_de_consultar(document_ids: object, mensaje: str) -> None:
    """F2: falla si una colección o un elemento inválido llega al almacén o no produce `ValueError`."""
    with pytest.raises(ValueError, match=re.escape(mensaje)):
        search_lexical(
            cast(StoreReader, _LectorProhibido()),
            query="needle",
            document_ids=cast(tuple[str, ...], document_ids),
        )


def test_aplicacion_acepta_1000_caracteres_y_construye_la_expresion() -> None:
    """El límite de longitud se mide sobre el texto crudo; la expresión usa el token entre comillas."""
    query = f" {('a' * 998)} "
    lector = _LectorFalso(())
    salida = search_lexical(cast(StoreReader, lector), query=query)
    assert salida == ()
    assert lector.llamadas == [(f'"{("a" * 998)}"', None, 10)]


def test_document_ids_preserva_none_ids_validos_y_cortocircuita_vacios() -> None:
    """F1/F2: falla si `None` o los IDs válidos se alteran, o si `()`/`[]` consultan el almacén."""
    lector = _LectorFalso(())
    assert search_lexical(cast(StoreReader, lector), query="needle", document_ids=None) == ()
    ids = ("doc-uno", "doc-dos")
    assert search_lexical(cast(StoreReader, lector), query="needle", document_ids=ids) == ()
    assert lector.llamadas == [('"needle"', None, 10), ('"needle"', ids, 10)]
    assert lector.llamadas[1][1] is ids

    ids_vacios = cast(tuple[str, ...], [])
    assert search_lexical(cast(StoreReader, lector), query="needle", document_ids=()) == ()
    assert search_lexical(cast(StoreReader, lector), query="needle", document_ids=ids_vacios) == ()
    assert lector.llamadas == [('"needle"', None, 10), ('"needle"', ids, 10)]


def test_order_by_rank_es_necesario_para_el_orden_de_relevancia(tmp_path: Path) -> None:
    """T1c: quitar `ORDER BY rank` debe hacer fallar esta prueba: el orden por ordinal es distinto."""
    ruta = _crear_almacen(tmp_path)
    _sembrar(
        ruta,
        (
            ("doc", 1, "needle", ("Primero insertado",), None, None),
            ("doc", 2, " ".join(("needle",) * 30), ("Más relevante",), None, None),
        ),
    )
    almacen = SqliteStore(ruta)
    resultados = almacen.search_results("needle", top_k=2)
    oraculo = _oraculo(ruta, "needle", top_k=2)
    orden_relevancia = tuple(resultado.chunk_id for resultado in resultados)
    assert tuple((resultado.chunk_id, resultado.score) for resultado in resultados) == oraculo
    assert orden_relevancia == ("doc:2", "doc:1")
    assert orden_relevancia != ("doc:1", "doc:2")
    assert tuple(resultado.rank for resultado in resultados) == (1, 2)


def test_filtro_de_documentos_se_aplica_antes_del_limite(tmp_path: Path) -> None:
    ruta = _crear_almacen(tmp_path)
    _sembrar(
        ruta,
        (
            ("peor", 1, "needle", (), None, None),
            ("mejor-uno", 1, " ".join(("needle",) * 20), (), None, None),
            ("mejor-dos", 1, " ".join(("needle",) * 40), (), None, None),
        ),
    )
    almacen = SqliteStore(ruta)
    mejores = almacen.search_results("needle", top_k=2)
    assert len(mejores) == 2
    assert all(resultado.document_id != "peor" for resultado in mejores)

    filtrados = almacen.search_results("needle", document_ids=("peor",), top_k=2)
    assert len(filtrados) == 1
    assert filtrados[0].document_id == "peor"


def test_sin_coincidencias_e_ids_desconocidos_devuelven_tupla_vacia(tmp_path: Path) -> None:
    ruta = _crear_almacen(tmp_path)
    _sembrar(ruta, (("doc", 1, "needle", (), None, None),))
    almacen = SqliteStore(ruta)
    assert almacen.search_results("absent", top_k=5) == ()
    assert almacen.search_results("needle", document_ids=("desconocido",)) == ()


def test_proyeccion_toma_la_autoridad_y_conserva_nulos_y_ruta_vacia(tmp_path: Path) -> None:
    ruta = _crear_almacen(tmp_path)
    _sembrar(ruta, (("doc", 1, "needle content", (), None, None),))
    almacen = SqliteStore(ruta)
    resultado = almacen.search_results("needle")[0]
    autoridad = almacen.read_version("doc", VERSION).fragments[0]
    assert resultado.chunk_id == autoridad.chunk_id
    assert resultado.content == autoridad.content
    assert resultado.section_path == autoridad.section_path == ()
    assert resultado.pdf_page_start == autoridad.pdf_page_start is None
    assert resultado.pdf_page_end == autoridad.pdf_page_end is None


def test_content_proyectado_procede_de_la_autoridad_con_indice_divergente(tmp_path: Path) -> None:
    """F6: falla si `content` se proyecta desde `fragmento_fts` en vez de la autoridad `fragmento`."""
    ruta = _crear_almacen(tmp_path)
    contenido_autoridad = "texto de autoridad sin el término buscado"
    contenido_derivado = "needle aparece solo en el índice derivado"
    _sembrar(ruta, (("doc", 1, contenido_autoridad, (), None, None),))
    _ejecutar(
        ruta,
        "UPDATE fragmento_fts SET content = ? WHERE document_id = ? AND document_version = ? AND ordinal = ?",
        (contenido_derivado, "doc", VERSION, 1),
    )

    resultados = SqliteStore(ruta).search_results("needle")

    assert len(resultados) == 1
    assert resultados[0].content == contenido_autoridad
    assert resultados[0].content != contenido_derivado


def test_join_por_version_no_mezcla_dos_versiones_del_mismo_documento(tmp_path: Path) -> None:
    """F7: falla si se quita `document_version` del JOIN, que devolvería cuatro filas contaminadas."""
    ruta = _crear_almacen(tmp_path)
    version_dos = "b" * 64
    contenido_dos = "needle en la segunda versión"
    _sembrar(ruta, (("doc", 1, "needle en la primera versión", (), None, None),))
    _ejecutar(
        ruta,
        "INSERT INTO version_documento (document_id, document_version) VALUES (?, ?)",
        ("doc", version_dos),
    )
    _ejecutar(
        ruta,
        "INSERT INTO fragmento (document_id, document_version, ordinal, chunk_id, section_path, level, "
        "block_type, captions, pdf_page_start, pdf_page_end, content, content_hash, anchor_level) "
        "VALUES (?, ?, ?, ?, '[]', 1, 'prose', '[]', ?, ?, ?, ?, 'posicional')",
        ("doc", version_dos, 1, "doc:version-dos:1", None, None, contenido_dos, content_hash(contenido_dos)),
    )
    _ejecutar(
        ruta,
        "INSERT INTO fragmento_fts (document_id, document_version, ordinal, content) VALUES (?, ?, ?, ?)",
        ("doc", version_dos, 1, contenido_dos),
    )

    resultados = SqliteStore(ruta).search_results("needle")
    pares = tuple((resultado.document_version, resultado.chunk_id) for resultado in resultados)
    esperados = {(VERSION, "doc:1"), (version_dos, "doc:version-dos:1")}

    assert len(resultados) == 2
    assert set(pares) == esperados
    assert len(set(pares)) == len(pares)


def test_lista_completa_con_id_valido_al_final_no_se_trunca(tmp_path: Path) -> None:
    """F8: falla si la lista de IDs se trunca silenciosamente antes de su último elemento válido."""
    ruta = _crear_almacen(tmp_path)
    _sembrar(ruta, (("target", 1, "needle contenido objetivo", (), None, None),))
    maximo = sqlite_module._limite_variables_sqlite() - 3  # MATCH + estado de ingesta + LIMIT
    document_ids = ("desconocido",) * (maximo - 1) + ("target",)

    resultados = SqliteStore(ruta).search_results("needle", document_ids=document_ids)

    assert len(resultados) == 1
    assert (resultados[0].document_id, resultados[0].chunk_id) == ("target", "target:1")


def test_no_deduplica_filas_derivadas_repetidas(tmp_path: Path) -> None:
    """T14: refleja el duplicado; no es una garantía de corrección ante corrupción del índice."""
    ruta = _crear_almacen(tmp_path)
    _sembrar(ruta, (("doc", 1, "needle content", (), None, None),))
    _ejecutar(
        ruta,
        "INSERT INTO fragmento_fts (document_id, document_version, ordinal, content) VALUES (?, ?, ?, ?)",
        ("doc", VERSION, 1, "needle content"),
    )
    resultados = SqliteStore(ruta).search_results("needle")
    assert tuple(resultado.chunk_id for resultado in resultados) == ("doc:1", "doc:1")
    assert tuple(resultado.rank for resultado in resultados) == (1, 2)


def test_errores_fts5_se_mapean_al_codigo_sqlite_existente(tmp_path: Path) -> None:
    ruta = _crear_almacen(tmp_path)
    with pytest.raises(StoreError) as info:
        SqliteStore(ruta).search_results('"')
    assert info.value.code is StoreErrorCode.ERROR_SQLITE


def test_precondiciones_del_adaptador_fallan_antes_de_abrir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def abrir_no_debido(ruta: Path) -> object:
        raise AssertionError("la validación debe ocurrir antes de abrir el almacén")

    monkeypatch.setattr(sqlite_module, "_lectura", abrir_no_debido)
    almacen = SqliteStore(tmp_path / "no-consultar.sqlite")
    for llamada in (
        lambda: almacen.search_results(" "),
        lambda: almacen.search_results("needle", top_k=0),
        lambda: almacen.search_results("needle", top_k=True),
        lambda: almacen.search_results("needle", document_ids=()),
    ):
        with pytest.raises(ValueError):
            llamada()
    assert not almacen.path.exists()


def test_sondeo_mide_el_limite_efectivo_de_variables_en_memoria() -> None:
    """F4: falla si SQLite no admite el límite medido o admite el primer valor no admitido, uno más."""
    limite = sqlite_module._limite_variables_sqlite()
    conexion = sqlite3.connect(":memory:")
    try:
        assert sqlite_module._acepta_variables(conexion, limite) is True
        assert sqlite_module._acepta_variables(conexion, limite + 1) is False
    finally:
        conexion.close()


def test_guardia_rechaza_sobre_limite_antes_de_abrir_y_acepta_el_limite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F4: falla si se rechaza el máximo admitido o si máximo+1 alcanza la apertura del almacén."""
    maximo = sqlite_module._limite_variables_sqlite() - 3  # MATCH + estado de ingesta + LIMIT

    def abrir_no_debido(ruta_ausente: Path) -> object:
        raise AssertionError("el máximo admitido debe alcanzar la lectura")

    monkeypatch.setattr(sqlite_module, "_lectura", abrir_no_debido)
    almacen = SqliteStore(tmp_path / "no-consultar.sqlite")
    with pytest.raises(AssertionError, match="el máximo admitido debe alcanzar la lectura"):
        almacen.search_results("needle", document_ids=("desconocido",) * maximo)
    with pytest.raises(ValueError, match="document_ids excede el máximo"):
        almacen.search_results("needle", document_ids=("desconocido",) * (maximo + 1))
    assert not almacen.path.exists()


def test_guardia_respeta_limite_menor_simulado_antes_de_abrir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """F4: escenario SIMULADO al sobreescribir el sondeo; NO verificado con una compilación real de límite menor."""
    monkeypatch.setattr(sqlite_module, "_limite_variables_sqlite", lambda: 512)

    def abrir_no_debido(ruta_ausente: Path) -> object:
        raise AssertionError("el máximo simulado debe alcanzar la lectura")

    monkeypatch.setattr(sqlite_module, "_lectura", abrir_no_debido)
    almacen = SqliteStore(tmp_path / "no-consultar.sqlite")
    with pytest.raises(AssertionError, match="el máximo simulado debe alcanzar la lectura"):
        almacen.search_results("needle", document_ids=("desconocido",) * (512 - 3))
    with pytest.raises(ValueError, match="document_ids excede el máximo de 509"):
        almacen.search_results("needle", document_ids=("desconocido",) * (512 - 2))
    assert not almacen.path.exists()


def test_lectura_de_resultados_usa_el_lector_y_no_contiene_escrituras() -> None:
    publico = inspect.getsource(SqliteStore.search_results)
    privado = inspect.getsource(sqlite_module._buscar_resultados)
    fuente = publico + privado
    assert "_buscar_resultados(" in publico
    assert "_lectura(" in privado
    sentencias_de_escritura = re.compile(
        r"\b(?:INSERT|UPDATE|DELETE|CREATE|DROP|ALTER|PRAGMA|COMMIT|ROLLBACK|BEGIN|VACUUM|ANALYZE)\b",
        re.IGNORECASE,
    )
    assert sentencias_de_escritura.search(fuente) is None


def test_destino_inexistente_y_ajeno_se_rechazan_sin_crear_ni_modificar(tmp_path: Path) -> None:
    inexistente = tmp_path / "inexistente.sqlite"
    with pytest.raises(StoreError) as no_es_base:
        SqliteStore(inexistente).search_results("needle")
    assert no_es_base.value.code is StoreErrorCode.NO_ES_BASE
    assert not inexistente.exists()

    ajeno = tmp_path / "ajeno.sqlite"
    _ejecutar(ajeno, "CREATE TABLE otra (valor INTEGER)")
    _ejecutar(ajeno, f"PRAGMA user_version = {SCHEMA_VERSION - 1}")
    antes = hashlib.sha256(ajeno.read_bytes()).hexdigest()
    with pytest.raises(StoreError) as incompatible:
        SqliteStore(ajeno).search_results("needle")
    assert incompatible.value.code is StoreErrorCode.INCOMPATIBLE
    assert hashlib.sha256(ajeno.read_bytes()).hexdigest() == antes


def test_construye_expresion_or_con_tokens_entre_comillas() -> None:
    """La consulta del usuario se traduce a tokens alfanuméricos unidos por OR y entre comillas."""
    lector = _LectorFalso(())
    casos = (
        ("needle", '"needle"'),
        ("  needle  ", '"needle"'),
        ("LoRA", '"LoRA"'),
        ("context window", '"context" OR "window"'),
        ("rubric-based evaluation", '"rubric" OR "based" OR "evaluation"'),
        ("TF-IDF", '"TF" OR "IDF"'),
        ("model's limit", '"model" OR "s" OR "limit"'),
        ("How to choose chunk size?", '"How" OR "to" OR "choose" OR "chunk" OR "size"'),
        ("AND OR NOT NEAR", '"AND" OR "OR" OR "NOT" OR "NEAR"'),
        ("a  a\tb", '"a" OR "b"'),
        ("needle…", '"needle"'),
    )
    for consulta, expresion in casos:
        assert search_lexical(cast(StoreReader, lector), query=consulta) == ()
        assert lector.llamadas[-1] == (expresion, None, 10)


@pytest.mark.parametrize("query", ["???", "---", "()", "\"'*^+", "…", "!!!"])
def test_consulta_sin_tokens_alfanumericos_falla_antes_de_consultar(query: str) -> None:
    """Sin ningún token utilizable se rechaza como entrada inválida, sin tocar el almacén."""
    with pytest.raises(ValueError, match="no contiene tokens alfanuméricos utilizables"):
        search_lexical(cast(StoreReader, _LectorProhibido()), query=query)


def test_consulta_de_un_solo_token_conserva_los_mismos_resultados(tmp_path: Path) -> None:
    """Un token entre comillas produce los mismos aciertos, puntuaciones y orden que el token desnudo."""
    ruta = _crear_almacen(tmp_path)
    _sembrar(
        ruta,
        (
            ("doc-uno", 1, "needle needle needle", (), None, None),
            ("doc-dos", 2, "needle", (), None, None),
        ),
    )
    almacen = SqliteStore(ruta)
    nuevo = search_lexical(almacen, query="needle", top_k=5)
    directo = almacen.search_results("needle", top_k=5)
    assert [(r.chunk_id, r.rank, r.score) for r in nuevo] == [(r.chunk_id, r.rank, r.score) for r in directo]


def test_puntuacion_y_operadores_de_fts5_no_rompen_la_consulta(tmp_path: Path) -> None:
    """Guiones, apóstrofos, interrogaciones, comillas y operadores dejan de ser errores del motor."""
    ruta = _crear_almacen(tmp_path)
    _sembrar(ruta, (("doc", 1, "needle and or not near tf idf model limit", (), None, None),))
    almacen = SqliteStore(ruta)
    consultas = (
        "TF-IDF",
        "model's",
        "how do I? ",
        "AND",
        "OR",
        "NOT",
        "NEAR",
        '"needle"',
        "(needle)",
        "needle*",
        "a+b",
        "x:y",
        "^needle",
        "needle~2",
    )
    for consulta in consultas:
        assert isinstance(search_lexical(almacen, query=consulta, top_k=5), tuple)
    assert search_lexical(almacen, query="TF-IDF", top_k=5)


def test_multiples_terminos_se_combinan_con_or_y_respetan_el_orden_del_motor(tmp_path: Path) -> None:
    """La expresión construida coincide con el OR explícito y el orden lo sigue fijando BM25."""
    ruta = _crear_almacen(tmp_path)
    _sembrar(
        ruta,
        (
            ("doc-uno", 1, "context", (), None, None),
            ("doc-dos", 2, "window", (), None, None),
            ("doc-tres", 3, "context window window", (), None, None),
        ),
    )
    almacen = SqliteStore(ruta)
    construida = search_lexical(almacen, query="context window", top_k=5)
    explicita = almacen.search_results('"context" OR "window"', top_k=5)
    assert [(r.chunk_id, r.rank, r.score) for r in construida] == [(r.chunk_id, r.rank, r.score) for r in explicita]
    assert len(construida) == 3
