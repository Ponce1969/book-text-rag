"""Reconstrucción del índice léxico derivado sobre el piloto (incremento 3-b).

Un almacén **temporal** por prueba y **una** extracción del piloto por módulo. Comprueba la equivalencia
de los resultados de `search_lexical` —comparando los **identificadores** que devuelve, `chunk_id`
incluido— con una línea base tomada **antes** de dañar el índice, la recuperación tras eliminar las filas
derivadas, la idempotencia, la atomicidad y que la autoridad queda intacta.
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from book_text_rag.adapters.extraction.geometry import PyMuPdfGeometry
from book_text_rag.adapters.extraction.pdftotext import PdftotextExtractor
from book_text_rag.adapters.storage import sqlite_write as sqlite_write_module
from book_text_rag.adapters.storage.sqlite import SqliteStore
from book_text_rag.application.ingest_in_memory import ingest_in_memory
from book_text_rag.application.ingest_persistent import persist_unit
from book_text_rag.ports.storage import LexicalHit, StoreError, StoreErrorCode, UnitWrite

REPO_ROOT = Path(__file__).resolve().parents[2]
PILOT = REPO_ROOT / "data" / "Ingeniería de IA - Chip Huyen (EN).pdf"
DOCUMENT_ID = "huyen-ai-engineering"
ALIAS = "huyen"
FECHA = "2026-10-18"
FRAGMENTOS_ESPERADOS = 583
AUTORIDAD = ("fuente", "referencia_fuente", "version_documento", "fragmento", "construccion", "anclaje_cache")
ORDINALES_MUESTRA = (1, 100, 300, 500)

pytestmark = pytest.mark.skipif(not PILOT.exists(), reason="falta el PDF piloto en data/")


@pytest.fixture(scope="module")
def unidad() -> UnitWrite:
    resultado = ingest_in_memory(
        PILOT, DOCUMENT_ID, text_extractor=PdftotextExtractor(PILOT), geometry=PyMuPdfGeometry(PILOT)
    )
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


def _bateria(unidad: UnitWrite) -> tuple[str, ...]:
    """Tokens distintivos repartidos por el documento, más uno sin coincidencias."""
    tokens = set()
    for ordinal in ORDINALES_MUESTRA:
        contenido = unidad.fragments[ordinal - 1].content
        tokens.update(token.lower() for token in contenido.split() if len(token) >= 10 and token.isalpha())
    return (*tuple(sorted(tokens)[:6]), "zzzzqqqqxxxx")


def _linea_base(almacen_obj: SqliteStore, unidad: UnitWrite) -> dict[str, tuple[LexicalHit, ...]]:
    """Resultados reales de `search_lexical` —con `chunk_id`— para la batería de tokens."""
    return {token: almacen_obj.search_lexical(token, document_id=DOCUMENT_ID, limit=50) for token in _bateria(unidad)}


def _ejecutar(ruta: Path, sentencias: tuple[str, ...]) -> None:
    conexion = sqlite3.connect(ruta)
    try:
        for sql in sentencias:
            conexion.execute(sql)
        conexion.commit()
    finally:
        conexion.close()


def _derivado(ruta: Path) -> tuple[tuple[int, str], ...]:
    conexion = sqlite3.connect(ruta)
    try:
        filas = conexion.execute(
            "SELECT ordinal, content FROM fragmento_fts WHERE document_id = ? ORDER BY ordinal", (DOCUMENT_ID,)
        ).fetchall()
        return tuple((int(fila[0]), str(fila[1])) for fila in filas)
    finally:
        conexion.close()


def _huella_tablas(ruta: Path, tablas: tuple[str, ...]) -> str:
    """Hash del volcado canónico de la autoridad: detecta cualquier cambio de campo persistido."""
    conexion = sqlite3.connect(ruta)
    try:
        volcado = tuple(
            (
                tabla,
                tuple(sorted((tuple(fila) for fila in conexion.execute(f"SELECT * FROM {tabla}")), key=repr)),
            )
            for tabla in tablas
        )
    finally:
        conexion.close()
    return hashlib.sha256(repr(volcado).encode("utf-8")).hexdigest()


def test_equivalencia_con_la_linea_base_y_recuperacion(almacen: Path, unidad: UnitWrite) -> None:
    almacen_obj = SqliteStore(almacen)
    base = _linea_base(almacen_obj, unidad)
    assert any(base[token] for token in base), "la línea base debe tener aciertos"

    _ejecutar(almacen, (f"DELETE FROM fragmento_fts WHERE document_id = '{DOCUMENT_ID}'",))
    assert all(almacen_obj.search_lexical(token, document_id=DOCUMENT_ID, limit=50) == () for token in base)

    resultado = almacen_obj.rebuild_lexical_index(DOCUMENT_ID, _version(unidad))
    assert resultado.filas_previas == 0
    assert resultado.filas_reconstruidas == FRAGMENTOS_ESPERADOS
    assert _linea_base(almacen_obj, unidad) == base


def test_idempotencia_y_autoridad_intacta(almacen: Path, unidad: UnitWrite) -> None:
    almacen_obj = SqliteStore(almacen)
    base = _linea_base(almacen_obj, unidad)
    autoridad = _huella_tablas(almacen, AUTORIDAD)
    primera = almacen_obj.rebuild_lexical_index(DOCUMENT_ID, _version(unidad))
    derivado = _derivado(almacen)
    segunda = almacen_obj.rebuild_lexical_index(DOCUMENT_ID, _version(unidad))
    assert primera.filas_previas == FRAGMENTOS_ESPERADOS
    assert segunda.filas_previas == FRAGMENTOS_ESPERADOS
    assert primera.filas_reconstruidas == segunda.filas_reconstruidas == FRAGMENTOS_ESPERADOS
    assert _derivado(almacen) == derivado
    assert _linea_base(almacen_obj, unidad) == base
    assert _huella_tablas(almacen, AUTORIDAD) == autoridad


def test_reconstruccion_deja_el_indice_verificado(almacen: Path, unidad: UnitWrite) -> None:
    verificacion = SqliteStore(almacen).verify_version(DOCUMENT_ID, _version(unidad))
    assert verificacion.fts5_ok is True
    assert verificacion.ok is True


def test_fallo_inyectado_conserva_el_indice_previo(
    almacen: Path, unidad: UnitWrite, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ejecutar(almacen, (f"DELETE FROM fragmento_fts WHERE document_id = '{DOCUMENT_ID}' AND ordinal IN (2, 3)",))
    danado = _derivado(almacen)
    autoridad = _huella_tablas(almacen, AUTORIDAD)
    original = sqlite_write_module._insertar_fila_derivada
    llamadas = {"n": 0}

    def fallar(*args: object) -> None:
        llamadas["n"] += 1
        if llamadas["n"] == 5:
            raise StoreError(StoreErrorCode.ERROR_SQLITE, "fallo inyectado a mitad de la reconstrucción")
        original(*args)  # type: ignore[arg-type]

    monkeypatch.setattr(sqlite_write_module, "_insertar_fila_derivada", fallar)
    with pytest.raises(StoreError) as info:
        SqliteStore(almacen).rebuild_lexical_index(DOCUMENT_ID, _version(unidad))
    assert info.value.code is StoreErrorCode.ERROR_SQLITE
    monkeypatch.undo()
    assert llamadas["n"] == 5
    assert _derivado(almacen) == danado
    assert _huella_tablas(almacen, AUTORIDAD) == autoridad
    assert SqliteStore(almacen).rebuild_lexical_index(DOCUMENT_ID, _version(unidad)).filas_reconstruidas == (
        FRAGMENTOS_ESPERADOS
    )
    assert len(_derivado(almacen)) == FRAGMENTOS_ESPERADOS
