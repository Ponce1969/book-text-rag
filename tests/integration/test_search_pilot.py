"""Proyección de recuperación léxica sobre el piloto persistido (incremento 4, D-07).

Contrasta orden y puntuación con un oráculo SQL de solo lectura, proyecta campos de la autoridad y
verifica que la consulta no altera el archivo ni crea laterales.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
from collections import Counter
from pathlib import Path

import pytest

from book_text_rag.adapters.storage.sqlite import SqliteStore
from book_text_rag.application.ingest_in_memory import ingest_in_memory
from book_text_rag.application.ingest_persistent import persist_unit
from book_text_rag.application.search_lexical import search_lexical
from book_text_rag.cli import main
from book_text_rag.domain.models import FragmentRecord
from book_text_rag.ports.storage import UnitWrite

REPO_ROOT = Path(__file__).resolve().parents[2]
PILOT = REPO_ROOT / "data" / "Ingeniería de IA - Chip Huyen (EN).pdf"
DOCUMENT_ID = "huyen-ai-engineering"
ALIAS = "huyen"
FECHA = "2026-10-18"
FRAGMENTOS_ESPERADOS = 583
_INDEX_VERSION = re.compile(r"^index_version: (?:[0-9a-f]{12}|null)$", re.MULTILINE)

pytestmark = pytest.mark.skipif(not PILOT.exists(), reason="falta el PDF piloto en data/")


@pytest.fixture(scope="module")
def unidad() -> UnitWrite:
    resultado = ingest_in_memory(PILOT, DOCUMENT_ID)
    return UnitWrite(
        document_id=DOCUMENT_ID,
        alias=ALIAS,
        fecha=FECHA,
        fragments=tuple(resultado.fragments),
        trace=resultado.trace,
        source_format="pdf",
        page_count=784,
    )


@pytest.fixture
def almacen(tmp_path: Path, unidad: UnitWrite) -> Path:
    ruta = tmp_path / "almacen.sqlite"
    SqliteStore(ruta).initialize()
    persist_unit(unidad, store=SqliteStore(ruta))
    return ruta


def _version(unidad: UnitWrite) -> str:
    return unidad.trace.document_version


def _oraculo(
    ruta: Path,
    query: str,
    *,
    top_k: int,
    document_ids: tuple[str, ...] | None = None,
) -> tuple[tuple[str, float], ...]:
    """Oráculo SQL independiente: lee directamente el motor y aplica `ORDER BY rank`."""
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


def _huella(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def _laterales(ruta: Path) -> list[str]:
    return sorted(archivo.name for archivo in ruta.parent.glob(f"{ruta.name}-*"))


def _token(unidad: UnitWrite) -> str:
    return next(
        token.lower()
        for fragmento in unidad.fragments
        for token in fragmento.content.split()
        if len(token) >= 10 and token.isalpha()
    )


def test_resultados_respetan_oraculo_sql_y_score_bm25_crudo(almacen: Path, unidad: UnitWrite) -> None:
    """T1a, T2 y T3: orden SQL independiente, rangos contiguos y score crudo exacto del motor."""
    query = _token(unidad)
    resultados = search_lexical(SqliteStore(almacen), query=query, top_k=50)
    oraculo = _oraculo(almacen, query, top_k=50)
    assert resultados
    assert tuple(resultado.rank for resultado in resultados) == tuple(range(1, len(resultados) + 1))
    assert tuple((resultado.chunk_id, resultado.score) for resultado in resultados) == oraculo
    assert tuple(resultado.chunk_id for resultado in resultados) == tuple(fila[0] for fila in oraculo)


def test_campos_proyectados_coinciden_con_read_version(almacen: Path, unidad: UnitWrite) -> None:
    """T11: los campos proyectados proceden de la autoridad persistida de esa versión."""
    almacen_obj = SqliteStore(almacen)
    resultados = almacen_obj.search_results(_token(unidad), top_k=50)
    autoridad = almacen_obj.read_version(DOCUMENT_ID, _version(unidad))
    por_chunk = {fragmento.chunk_id: fragmento for fragmento in autoridad.fragments}
    assert resultados
    for resultado in resultados:
        fragmento = por_chunk[resultado.chunk_id]
        assert resultado.document_id == DOCUMENT_ID
        assert resultado.document_version == _version(unidad)
        assert resultado.chunk_id == fragmento.chunk_id
        assert resultado.content == fragmento.content
        assert resultado.section_path == fragmento.section_path
        assert resultado.pdf_page_start == fragmento.pdf_page_start
        assert resultado.pdf_page_end == fragmento.pdf_page_end


def test_busqueda_compatible_con_primitiva_lexical_hit(almacen: Path, unidad: UnitWrite) -> None:
    """T12: ambos caminos mantienen los mismos identificadores para consulta y límite iguales."""
    almacen_obj = SqliteStore(almacen)
    query = _token(unidad)
    limite = 20
    resultados = almacen_obj.search_results(query, document_ids=(DOCUMENT_ID,), top_k=limite)
    aciertos = almacen_obj.search_lexical(query, document_id=DOCUMENT_ID, limit=limite)
    assert tuple(resultado.chunk_id for resultado in resultados) == tuple(acierto.chunk_id for acierto in aciertos)


def test_busqueda_no_modifica_el_piloto_ni_crea_archivos_laterales(almacen: Path, unidad: UnitWrite) -> None:
    """T9 conductual: huella SHA-256, laterales y apertura de lectura permanecen intactos."""
    antes = _huella(almacen)
    laterales_antes = _laterales(almacen)
    assert laterales_antes == []
    resultados = SqliteStore(almacen).search_results(_token(unidad), top_k=20)
    assert resultados
    assert _huella(almacen) == antes
    assert _laterales(almacen) == laterales_antes


def test_persistencia_y_proyeccion_conservan_paginas_nulas(tmp_path: Path, unidad: UnitWrite) -> None:
    """T7: se persiste una unidad con páginas nulas y se leen como `None`, no como cero."""
    frecuencias = Counter(
        token.lower()
        for fragmento in unidad.fragments
        for token in fragmento.content.split()
        if len(token) >= 10 and token.isalpha()
    )
    objetivo: FragmentRecord | None = None
    query = ""
    for fragmento in unidad.fragments:
        token_unico = next(
            (
                token.lower()
                for token in fragmento.content.split()
                if len(token) >= 10 and token.isalpha() and frecuencias[token.lower()] == 1
            ),
            None,
        )
        if token_unico is not None:
            objetivo = fragmento
            query = token_unico
            break
    assert objetivo is not None, "el piloto debe contener un token distintivo para el caso nulo"

    modificados = tuple(
        fragmento.model_copy(update={"pdf_page_start": None, "pdf_page_end": None})
        if fragmento.chunk_id == objetivo.chunk_id
        else fragmento
        for fragmento in unidad.fragments
    )
    unidad_nula = UnitWrite(
        document_id=unidad.document_id,
        alias=unidad.alias,
        fecha=unidad.fecha,
        fragments=modificados,
        trace=unidad.trace,
        source_format=unidad.source_format,
        page_count=unidad.page_count,
    )
    ruta = tmp_path / "paginas_nulas.sqlite"
    SqliteStore(ruta).initialize()
    persist_unit(unidad_nula, store=SqliteStore(ruta))
    resultado = next(
        resultado
        for resultado in SqliteStore(ruta).search_results(query, document_ids=(DOCUMENT_ID,), top_k=50)
        if resultado.chunk_id == objetivo.chunk_id
    )
    assert resultado.pdf_page_start is None
    assert resultado.pdf_page_end is None


def test_cli_search_devuelve_evidencia_con_procedencia(
    almacen: Path, unidad: UnitWrite, capsys: pytest.CaptureFixture[str]
) -> None:
    """`search` sobre el piloto real: campos, orden, `index_version` diferido y solo lectura."""
    token = _token(unidad)
    esperados = search_lexical(SqliteStore(almacen), query=token, top_k=5)
    assert esperados
    antes = _huella(almacen)

    assert main(["search", token, "--store", str(almacen), "--top-k", "5"]) == 0
    salida = capsys.readouterr().out
    assert f"consulta: {token}" in salida
    assert "modo: lexical" in salida
    assert _INDEX_VERSION.search(salida) is not None
    assert "index_version: null" not in salida
    assert f"resultados: {len(esperados)}" in salida
    assert "rank: 1" in salida
    for resultado in esperados:
        assert f"chunk_id: {resultado.chunk_id}" in salida
        assert token in resultado.content.lower()
    assert "paginas: " in salida
    assert _huella(almacen) == antes
    assert _laterales(almacen) == []


def test_cli_search_sin_coincidencias_es_exito_y_solo_lectura(
    almacen: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Una consulta válida sin coincidencias devuelve cero resultados, código 0 y no escribe."""
    antes = _huella(almacen)

    assert main(["search", "zzzzzzzzzzzzzzzz", "--store", str(almacen)]) == 0
    salida = capsys.readouterr().out
    assert "resultados: 0" in salida
    assert "index_version: null" in salida
    assert _huella(almacen) == antes
    assert _laterales(almacen) == []


def test_cli_show_refleja_la_autoridad_del_piloto(
    almacen: Path, unidad: UnitWrite, capsys: pytest.CaptureFixture[str]
) -> None:
    """`show` informa metadatos, estados y fragmentos de la versión persistida sin escribir."""
    antes = _huella(almacen)

    assert (
        main(
            [
                "show",
                "--store",
                str(almacen),
                "--document-id",
                DOCUMENT_ID,
                "--document-version",
                _version(unidad),
            ]
        )
        == 0
    )
    salida = capsys.readouterr().out
    assert f"document_id: {DOCUMENT_ID}" in salida
    assert f"document_version: {_version(unidad)}" in salida
    assert _INDEX_VERSION.search(salida) is not None
    assert "index_version: null" not in salida
    assert "estados: ingesta completada e índice disponible para consulta" in salida
    assert "source_format: pdf" in salida
    assert "page_count: 784" in salida
    assert f"fragmentos: {FRAGMENTOS_ESPERADOS}" in salida
    assert _huella(almacen) == antes
    assert _laterales(almacen) == []


def test_cli_search_acepta_guion_apostrofo_y_pregunta(almacen: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """La CLI ya no falla con guiones, apóstrofos ni signos de interrogación."""
    for consulta in ("fine-tuning", "model's limit", "How do I choose the right chunk size for a RAG system?"):
        assert main(["search", consulta, "--store", str(almacen), "--top-k", "3"]) == 0
        salida = capsys.readouterr().out
        assert "resultados: 3" in salida
        assert "error [" not in salida


def test_consulta_natural_recupera_el_pasaje_de_chunking(almacen: Path) -> None:
    """Una pregunta en lenguaje natural recupera el pasaje de chunking en el top-5."""
    resultados = search_lexical(
        SqliteStore(almacen),
        query="How do I choose the right chunk size for a RAG system?",
        top_k=5,
    )
    assert any(resultado.chunk_id.endswith(":327") for resultado in resultados)


def test_consulta_con_guion_recupera_evidencia_de_finetuning(almacen: Path) -> None:
    """`fine-tuning` deja de ser un error de sintaxis y devuelve evidencia del capítulo 7."""
    resultados = search_lexical(SqliteStore(almacen), query="fine-tuning", top_k=5)
    assert resultados
    assert any(
        "finetun" in resultado.content.lower() or "fine-tun" in resultado.content.lower() for resultado in resultados
    )
