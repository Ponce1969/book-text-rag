"""`search` gobernada por el estado de ingesta (`D-13`, 004:452-455 y 525).

Un documento cuyas referencias no están **todas** en «ingesta completada» no es consultable, y un
documento **sin** referencia tampoco se habilita por ausencia de filas. El filtro vive en el camino de
consulta (`_buscar_resultados`); no altera `search_lexical`, el ranking, los `score` ni los campos.
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from book_text_rag.adapters.storage.sqlite import SqliteStore
from book_text_rag.application.search_lexical import search_lexical
from book_text_rag.domain.identity import chunk_id, content_hash
from book_text_rag.ports.storage import EstadoIngesta

DOC = "doc"
OTRO = "otro"
V1 = "a" * 64
V2 = "b" * 64
TEXTO = "evidencia textual con procedencia verificable sobre recuperacion lexica"


def _huella(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def _laterales(ruta: Path) -> list[str]:
    return sorted(path.name for path in ruta.parent.glob(f"{ruta.name}-*"))


def _sembrar(
    ruta: Path,
    *,
    document_id: str = DOC,
    estado: EstadoIngesta | None = EstadoIngesta.COMPLETADA,
    version: str = V1,
    estado_extra: EstadoIngesta | None = None,
    con_referencia: bool = True,
) -> None:
    """Almacén válido con un documento, una versión y un fragmento consultable."""
    SqliteStore(ruta).initialize()
    conexion = sqlite3.connect(ruta)
    try:
        conexion.execute(
            "INSERT INTO fuente (document_id, source_format, page_count) VALUES (?, 'pdf', 10)", (document_id,)
        )
        if con_referencia and estado is not None:
            conexion.execute(
                "INSERT INTO referencia_fuente (document_id, alias, tipo_asignacion, fecha, estado_ingesta) "
                "VALUES (?, ?, 'deliberada', '2026-10-22', ?)",
                (document_id, "alias", estado.value),
            )
        if estado_extra is not None:
            conexion.execute(
                "INSERT INTO referencia_fuente (document_id, alias, tipo_asignacion, fecha, estado_ingesta) "
                "VALUES (?, 'alias-2', 'deliberada', '2026-10-22', ?)",
                (document_id, estado_extra.value),
            )
        conexion.execute(
            "INSERT INTO version_documento (document_id, document_version) VALUES (?, ?)", (document_id, version)
        )
        conexion.execute(
            "INSERT INTO fragmento (document_id, document_version, ordinal, chunk_id, section_path, level, "
            "block_type, captions, pdf_page_start, pdf_page_end, content, content_hash, anchor_level) "
            "VALUES (?, ?, 1, ?, '[]', 1, 'prose', '[]', 5, 5, ?, ?, 'posicional')",
            (document_id, version, chunk_id(document_id, version[:12], 1), TEXTO, content_hash(TEXTO)),
        )
        conexion.execute(
            "INSERT INTO fragmento_fts (document_id, document_version, ordinal, content) VALUES (?, ?, 1, ?)",
            (document_id, version, TEXTO),
        )
        conexion.commit()
    finally:
        conexion.close()


def _oraculo(ruta: Path, consulta: str) -> list[tuple[str, str, float]]:
    """Ranking crudo del motor, sin el filtro de estado: `(chunk_id, document_id, bm25)` en orden."""
    conexion = sqlite3.connect(f"{ruta.as_uri()}?mode=ro", uri=True)
    try:
        filas = conexion.execute(
            "SELECT fragmento.chunk_id, fragmento.document_id, bm25(fragmento_fts) "
            "FROM fragmento_fts JOIN fragmento "
            "ON fragmento.document_id = fragmento_fts.document_id "
            "AND fragmento.document_version = fragmento_fts.document_version "
            "AND fragmento.ordinal = fragmento_fts.ordinal "
            "WHERE fragmento_fts MATCH ? ORDER BY rank",
            (consulta,),
        ).fetchall()
    finally:
        conexion.close()
    return [(str(f[0]), str(f[1]), float(f[2])) for f in filas]


@pytest.mark.parametrize("estado", [EstadoIngesta.INCOMPLETA, EstadoIngesta.DECISION_REGISTRADA])
def test_referencia_no_completada_no_devuelve_resultados(tmp_path: Path, estado: EstadoIngesta) -> None:
    ruta = tmp_path / "no_publicada.sqlite"
    _sembrar(ruta, estado=estado)

    assert search_lexical(SqliteStore(ruta), query="procedencia") == ()


def test_referencia_completada_conserva_resultados_orden_y_scores(tmp_path: Path) -> None:
    ruta = tmp_path / "publicada.sqlite"
    _sembrar(ruta)

    esperado = _oraculo(ruta, "procedencia")
    obtenido = search_lexical(SqliteStore(ruta), query="procedencia")

    assert [(r.chunk_id, r.document_id, r.score) for r in obtenido] == esperado
    assert [r.rank for r in obtenido] == [1]


def test_referencias_discrepantes_excluyen_el_documento(tmp_path: Path) -> None:
    ruta = tmp_path / "discrepantes.sqlite"
    _sembrar(ruta, estado=EstadoIngesta.COMPLETADA, estado_extra=EstadoIngesta.INCOMPLETA)

    assert _oraculo(ruta, "procedencia"), "el índice contaminado debe contener la fila"
    assert search_lexical(SqliteStore(ruta), query="procedencia") == ()


def test_documento_sin_referencias_no_se_habilita_por_ausencia_de_filas(tmp_path: Path) -> None:
    ruta = tmp_path / "sin_referencia.sqlite"
    _sembrar(ruta, con_referencia=False)

    assert _oraculo(ruta, "procedencia"), "el índice contaminado debe contener la fila"
    assert search_lexical(SqliteStore(ruta), query="procedencia") == ()


def test_un_documento_no_publicado_no_oculta_al_publicado(tmp_path: Path) -> None:
    ruta = tmp_path / "dos_documentos.sqlite"
    _sembrar(ruta, document_id=DOC, estado=EstadoIngesta.INCOMPLETA)
    _sembrar(ruta, document_id=OTRO, estado=EstadoIngesta.COMPLETADA, version=V2)

    obtenido = search_lexical(SqliteStore(ruta), query="procedencia")

    assert [r.document_id for r in obtenido] == [OTRO]


def test_el_filtro_de_document_ids_conserva_la_regla_de_estado(tmp_path: Path) -> None:
    ruta = tmp_path / "filtro_ids.sqlite"
    _sembrar(ruta, document_id=DOC, estado=EstadoIngesta.INCOMPLETA)
    _sembrar(ruta, document_id=OTRO, estado=EstadoIngesta.COMPLETADA, version=V2)

    assert search_lexical(SqliteStore(ruta), query="procedencia", document_ids=(DOC,)) == ()
    assert [r.document_id for r in search_lexical(SqliteStore(ruta), query="procedencia", document_ids=(OTRO,))] == [
        OTRO
    ]


def test_la_consulta_filtrada_no_escribe_ni_deja_laterales(tmp_path: Path) -> None:
    ruta = tmp_path / "solo_lectura.sqlite"
    _sembrar(ruta, estado=EstadoIngesta.INCOMPLETA)
    antes = _huella(ruta)

    search_lexical(SqliteStore(ruta), query="procedencia")

    assert _huella(ruta) == antes
    assert _laterales(ruta) == []
