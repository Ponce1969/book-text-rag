"""Contrato del camino de lectura (incremento 3): forma de los tipos, rechazos y no-escritura.

No fija el comportamiento de un almacén concreto: fija lo que el lector debe cumplir en cualquier
almacén —los campos acordados, los códigos explícitos ante destinos o versiones que no sirven— y que
**ningún** camino, ni el de éxito ni el de error, altera el archivo.
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from book_text_rag.adapters.storage.sqlite import SCHEMA_VERSION, SqliteStore
from book_text_rag.domain.identity import content_hash
from book_text_rag.ports.storage import (
    EstadoIngesta,
    FragmentRead,
    LexicalHit,
    StoreError,
    StoreErrorCode,
    VerifyOutcome,
    VersionRead,
)

DOCUMENT_ID = "doc"
VERSION = "a" * 64


def _campos(tipo: type[object]) -> set[str]:
    return set(tipo.__dataclass_fields__)  # type: ignore[attr-defined]


def _huella(ruta: Path) -> tuple[str, int]:
    return hashlib.sha256(ruta.read_bytes()).hexdigest(), ruta.stat().st_mtime_ns


def _laterales(ruta: Path) -> list[str]:
    return sorted(p.name for p in ruta.parent.glob(f"{ruta.name}-*"))


def _escribir(ruta: Path, sentencias: tuple[tuple[str, tuple[object, ...]], ...]) -> None:
    conexion = sqlite3.connect(ruta)
    try:
        for sql, parametros in sentencias:
            conexion.execute(sql, parametros)
        conexion.commit()
    finally:
        conexion.close()


def _con_referencia(tmp_path: Path) -> Path:
    ruta = tmp_path / "referencia.sqlite"
    SqliteStore(ruta).initialize()
    _escribir(
        ruta,
        (
            ("INSERT INTO fuente (document_id, source_format, page_count) VALUES (?, ?, ?)", (DOCUMENT_ID, "pdf", 10)),
            (
                "INSERT INTO referencia_fuente (document_id, alias, tipo_asignacion, fecha, estado_ingesta) "
                "VALUES (?, ?, ?, ?, ?)",
                (DOCUMENT_ID, "alias", "deliberada", "2026-10-18", EstadoIngesta.COMPLETADA.value),
            ),
        ),
    )
    return ruta


def test_contrato_estructural_de_los_tipos_de_lectura() -> None:
    """Los campos son **exactamente** los acordados: ni `word_count`, ni `anchor_evidence`, ni `rowid`."""
    assert _campos(FragmentRead) == {
        "ordinal",
        "chunk_id",
        "section_path",
        "level",
        "block_type",
        "captions",
        "pdf_page_start",
        "pdf_page_end",
        "content",
        "content_hash",
        "anchor_level",
    }
    assert _campos(VersionRead) == {
        "document_id",
        "document_version",
        "estados",
        "source_format",
        "page_count",
        "fragments",
    }
    assert _campos(LexicalHit) == {"document_id", "document_version", "ordinal", "chunk_id"}
    assert _campos(VerifyOutcome) == {
        "fragmentos",
        "ordinales_ok",
        "content_hash_ok",
        "chunk_id_ok",
        "fts5_ok",
        "estado_ok",
        "traza_presente",
        "fuente_presente",
        "no_verificado",
    }
    prohibidos = {"word_count", "anchor_evidence", "rowid", "index_version", "score", "rank"}
    for tipo in (FragmentRead, VersionRead, LexicalHit, VerifyOutcome):
        assert not (_campos(tipo) & prohibidos), tipo.__name__


def test_destino_inexistente_se_rechaza_sin_crearlo(tmp_path: Path) -> None:
    ruta = tmp_path / "no_existe.sqlite"
    almacen = SqliteStore(ruta)
    with pytest.raises(StoreError) as info:
        almacen.read_version(DOCUMENT_ID, VERSION)
    assert info.value.code is StoreErrorCode.NO_ES_BASE
    assert not ruta.exists()


def test_archivo_que_no_es_base_se_rechaza(tmp_path: Path) -> None:
    ruta = tmp_path / "basura.sqlite"
    ruta.write_bytes(b"no soy una base de datos" * 10)
    antes = _huella(ruta)
    with pytest.raises(StoreError) as info:
        SqliteStore(ruta).read_version(DOCUMENT_ID, VERSION)
    assert info.value.code is StoreErrorCode.NO_ES_BASE
    assert _huella(ruta) == antes
    assert _laterales(ruta) == []


def test_almacen_de_otra_version_o_estructura_es_incompatible(tmp_path: Path) -> None:
    ruta = tmp_path / "ajeno.sqlite"
    _escribir(ruta, (("CREATE TABLE otra (x INTEGER)", ()), (f"PRAGMA user_version = {SCHEMA_VERSION - 1}", ())))
    antes = _huella(ruta)
    almacen = SqliteStore(ruta)
    for llamada in (
        lambda: almacen.read_version(DOCUMENT_ID, VERSION),
        lambda: almacen.verify_version(DOCUMENT_ID, VERSION),
        lambda: almacen.search_lexical("algo"),
    ):
        with pytest.raises(StoreError) as info:
            llamada()
        assert info.value.code is StoreErrorCode.INCOMPATIBLE
    assert _huella(ruta) == antes
    assert _laterales(ruta) == []


def test_almacen_sin_referencia_se_rechaza(tmp_path: Path) -> None:
    ruta = tmp_path / "vacio.sqlite"
    almacen = SqliteStore(ruta)
    almacen.initialize()
    for llamada in (
        lambda: almacen.read_version(DOCUMENT_ID, VERSION),
        lambda: almacen.verify_version(DOCUMENT_ID, VERSION),
    ):
        with pytest.raises(StoreError) as info:
            llamada()
        assert info.value.code is StoreErrorCode.REFERENCIA_AUSENTE


def test_referencia_sin_version_registrada_se_rechaza(tmp_path: Path) -> None:
    ruta = _con_referencia(tmp_path)
    almacen = SqliteStore(ruta)
    for llamada in (
        lambda: almacen.read_version(DOCUMENT_ID, VERSION),
        lambda: almacen.verify_version(DOCUMENT_ID, VERSION),
    ):
        with pytest.raises(StoreError) as info:
            llamada()
        assert info.value.code is StoreErrorCode.VERSION_NO_ENCONTRADA


def test_version_registrada_sin_fragmentos_es_legitima(tmp_path: Path) -> None:
    """`N = 0` es un caso legítimo (`C-14`): se lee sin error.

    Los indicadores **por fragmento** son aquí **vacuamente verdaderos** —afirman que «todo lo
    persistido cumple» y no hay nada persistido—, así que **no** son prueba de contenido verificado; la
    versión **no** se declara verificada porque le falta la traza.
    """
    ruta = _con_referencia(tmp_path)
    _escribir(
        ruta,
        (("INSERT INTO version_documento (document_id, document_version) VALUES (?, ?)", (DOCUMENT_ID, VERSION)),),
    )
    almacen = SqliteStore(ruta)
    leido = almacen.read_version(DOCUMENT_ID, VERSION)
    assert leido.fragments == ()
    assert leido.estados == (EstadoIngesta.COMPLETADA,)
    assert leido.source_format == "pdf"
    assert leido.page_count == 10
    verificacion = almacen.verify_version(DOCUMENT_ID, VERSION)
    assert verificacion.fragmentos == 0
    assert verificacion.ordinales_ok is True
    assert verificacion.content_hash_ok is True
    assert verificacion.chunk_id_ok is True
    assert verificacion.fts5_ok is True
    assert verificacion.traza_presente is False
    assert verificacion.fuente_presente is True
    assert verificacion.ok is False


@pytest.mark.parametrize(("consulta", "limite"), [("", 10), ("   ", 10), ("algo", 0), ("algo", -1)])
def test_argumentos_invalidos_de_la_busqueda_fallan(tmp_path: Path, consulta: str, limite: int) -> None:
    ruta = tmp_path / "vacio2.sqlite"
    SqliteStore(ruta).initialize()
    with pytest.raises(ValueError):
        SqliteStore(ruta).search_lexical(consulta, limit=limite)


def _sembrar(ruta: Path, ordinales: tuple[int, ...], derivadas: tuple[tuple[int, str | None], ...]) -> None:
    """Siembra autoridad y un estado **derivado concreto**, para poder dañarlo o compensarlo.

    `derivadas` son pares `(ordinal, contenido)`; `None` usa el contenido de la autoridad de ese ordinal.
    """
    conexion = sqlite3.connect(ruta)
    try:
        conexion.execute(
            "INSERT INTO version_documento (document_id, document_version) VALUES (?, ?)", (DOCUMENT_ID, VERSION)
        )
        for ordinal in ordinales:
            contenido = f"contenido {ordinal} distintivo"
            conexion.execute(
                "INSERT INTO fragmento (document_id, document_version, ordinal, chunk_id, section_path, level, "
                "block_type, captions, pdf_page_start, pdf_page_end, content, content_hash, anchor_level) "
                "VALUES (?, ?, ?, ?, '[]', 1, 'prose', '[]', NULL, NULL, ?, ?, 'posicional')",
                (
                    DOCUMENT_ID,
                    VERSION,
                    ordinal,
                    f"{DOCUMENT_ID}:{'a' * 12}:{ordinal}",
                    contenido,
                    content_hash(contenido),
                ),
            )
        for ordinal, contenido in derivadas:
            conexion.execute(
                "INSERT INTO fragmento_fts (document_id, document_version, ordinal, content) VALUES (?, ?, ?, ?)",
                (DOCUMENT_ID, VERSION, ordinal, f"contenido {ordinal} distintivo" if contenido is None else contenido),
            )
        conexion.commit()
    finally:
        conexion.close()


def _filas_derivadas(ruta: Path) -> int:
    conexion = sqlite3.connect(ruta)
    try:
        fila = conexion.execute(
            "SELECT count(*) FROM fragmento_fts WHERE document_id = ? AND document_version = ?",
            (DOCUMENT_ID, VERSION),
        ).fetchone()
    finally:
        conexion.close()
    assert fila is not None
    return int(fila[0])


def _verificacion(ruta: Path) -> VerifyOutcome:
    return SqliteStore(ruta).verify_version(DOCUMENT_ID, VERSION)


def test_indice_derivado_sano_se_verifica(tmp_path: Path) -> None:
    ruta = _con_referencia(tmp_path)
    _sembrar(ruta, (1, 2, 3), ((1, None), (2, None), (3, None)))
    verificacion = _verificacion(ruta)
    assert verificacion.fts5_ok is True
    assert verificacion.fragmentos == 3


def test_fila_derivada_ausente_se_detecta(tmp_path: Path) -> None:
    ruta = _con_referencia(tmp_path)
    _sembrar(ruta, (1, 2, 3), ((1, None), (2, None)))
    assert _verificacion(ruta).fts5_ok is False


def test_fila_derivada_duplicada_se_detecta(tmp_path: Path) -> None:
    """Un duplicado **sin** fila ausente ya lo detectaba el recuento; se fija para no perderlo."""
    ruta = _con_referencia(tmp_path)
    _sembrar(ruta, (1, 2, 3), ((1, None), (1, None), (2, None), (3, None)))
    assert _filas_derivadas(ruta) == 4
    assert _verificacion(ruta).fts5_ok is False


def test_par_compensado_se_detecta(tmp_path: Path) -> None:
    """El patrón que escapaba: duplicar el ordinal 1 y borrar el 3 **conserva el total** (3 == N).

    Sólo se comparaban el total y el cruce de contenido, así que pasaba inadvertido; ahora lo detecta la
    comprobación de ordinales repetidos. La verificación **no** escribe: el archivo queda igual.
    """
    ruta = _con_referencia(tmp_path)
    _sembrar(ruta, (1, 2, 3), ((1, None), (1, None), (2, None)))
    assert _filas_derivadas(ruta) == 3, "el total se conserva: por eso el recuento solo no lo detecta"
    antes = _huella(ruta)
    assert _verificacion(ruta).fts5_ok is False
    assert _huella(ruta) == antes
    assert _laterales(ruta) == []


def test_contenido_derivado_divergente_se_detecta(tmp_path: Path) -> None:
    """La divergencia de `content` la detecta el cruce, **no** la comprobación de ordinales repetidos."""
    ruta = _con_referencia(tmp_path)
    _sembrar(ruta, (1, 2, 3), ((1, None), (2, "otro contenido"), (3, None)))
    assert _filas_derivadas(ruta) == 3
    assert _verificacion(ruta).fts5_ok is False


def test_ninguna_lectura_ni_verificacion_altera_el_almacen(tmp_path: Path) -> None:
    ruta = _con_referencia(tmp_path)
    antes = _huella(ruta)
    almacen = SqliteStore(ruta)
    # Camino de error: la versión no está registrada.
    for llamada in (
        lambda: almacen.read_version(DOCUMENT_ID, VERSION),
        lambda: almacen.verify_version(DOCUMENT_ID, VERSION),
    ):
        with pytest.raises(StoreError):
            llamada()
    # Camino de éxito: un índice vacío no tiene coincidencias, y eso **no** es un error.
    assert almacen.search_lexical("cualquier cosa") == ()
    assert _huella(ruta) == antes
    assert _laterales(ruta) == []
