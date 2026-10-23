"""Contrato de la reconstrucción del índice léxico derivado (incremento 3-b).

No fija el comportamiento de un almacén concreto: fija las propiedades que la reconstrucción debe cumplir
en cualquier almacén —los rechazos con el vocabulario vigente, la separación del protocolo de lectura, la
atomicidad, la idempotencia y que **no** toca la autoridad— sobre almacenes mínimos sembrados con SQL.
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from book_text_rag.adapters.storage import sqlite_write as sqlite_write_module
from book_text_rag.adapters.storage.sqlite import DDL, SCHEMA_VERSION, SqliteStore
from book_text_rag.domain.identity import content_hash
from book_text_rag.ports.storage import (
    EstadoIngesta,
    LexicalIndexMaintainer,
    RebuildOutcome,
    StoreError,
    StoreErrorCode,
    StoreReader,
)

DOCUMENT_ID = "doc"
VERSION = "a" * 64
AUTORIDAD = ("fuente", "referencia_fuente", "version_documento", "fragmento", "construccion", "anclaje_cache")


def _campos(tipo: type[object]) -> set[str]:
    return set(tipo.__dataclass_fields__)  # type: ignore[attr-defined]


def _huella(ruta: Path) -> tuple[str, int]:
    return hashlib.sha256(ruta.read_bytes()).hexdigest(), ruta.stat().st_mtime_ns


def _ejecutar(ruta: Path, sentencias: tuple[str, ...]) -> None:
    conexion = sqlite3.connect(ruta)
    try:
        for sql in sentencias:
            conexion.execute(sql)
        conexion.commit()
    finally:
        conexion.close()


def _volcado(ruta: Path, tablas: tuple[str, ...]) -> tuple[tuple[str, tuple[tuple[object, ...], ...]], ...]:
    """Volcado canónico de las tablas indicadas: ordenado por `repr` para no comparar tipos dispares."""
    conexion = sqlite3.connect(ruta)
    try:
        return tuple(
            (tabla, tuple(sorted((tuple(fila) for fila in conexion.execute(f"SELECT * FROM {tabla}")), key=repr)))
            for tabla in tablas
        )
    finally:
        conexion.close()


def _derivado(ruta: Path) -> tuple[tuple[int, str], ...]:
    """Contenido del índice derivado de la versión, en orden de ordinal."""
    conexion = sqlite3.connect(ruta)
    try:
        filas = conexion.execute(
            "SELECT ordinal, content FROM fragmento_fts WHERE document_id = ? AND document_version = ? "
            "ORDER BY ordinal",
            (DOCUMENT_ID, VERSION),
        ).fetchall()
        return tuple((int(fila[0]), str(fila[1])) for fila in filas)
    finally:
        conexion.close()


def _con_referencia(tmp_path: Path) -> Path:
    """Almacén inicializado con `fuente` y referencia, **sin** versión registrada."""
    ruta = tmp_path / "referencia.sqlite"
    SqliteStore(ruta).initialize()
    conexion = sqlite3.connect(ruta)
    try:
        conexion.execute(
            "INSERT INTO fuente (document_id, source_format, page_count) VALUES (?, ?, ?)",
            (DOCUMENT_ID, "pdf", 3),
        )
        conexion.execute(
            "INSERT INTO referencia_fuente (document_id, alias, tipo_asignacion, fecha, estado_ingesta) "
            "VALUES (?, ?, ?, ?, ?)",
            (DOCUMENT_ID, "alias", "deliberada", "2026-10-18", EstadoIngesta.COMPLETADA.value),
        )
        conexion.commit()
    finally:
        conexion.close()
    return ruta


def _sembrar(ruta: Path, ordinales: tuple[int, ...], derivadas: tuple[int, ...] | None = None) -> None:
    """Siembra autoridad y, si se indica, un estado derivado concreto (para poder dañarlo)."""
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
        for ordinal in derivadas or ():
            conexion.execute(
                "INSERT INTO fragmento_fts (document_id, document_version, ordinal, content) VALUES (?, ?, ?, ?)",
                (DOCUMENT_ID, VERSION, ordinal, f"contenido {ordinal} distintivo"),
            )
        conexion.commit()
    finally:
        conexion.close()


def test_contrato_estructural_y_separacion_de_protocolos() -> None:
    """La reconstrucción **no** pertenece al lector: son protocolos separados, y el resultado no lleva
    `index_version`."""
    assert _campos(RebuildOutcome) == {"document_id", "document_version", "filas_previas", "filas_reconstruidas"}
    assert hasattr(StoreReader, "read_version")
    assert not hasattr(StoreReader, "rebuild_lexical_index")
    assert hasattr(LexicalIndexMaintainer, "rebuild_lexical_index")
    assert not hasattr(LexicalIndexMaintainer, "read_version")


def test_destino_inexistente_se_rechaza_sin_crearlo(tmp_path: Path) -> None:
    ruta = tmp_path / "no_existe.sqlite"
    with pytest.raises(StoreError) as info:
        SqliteStore(ruta).rebuild_lexical_index(DOCUMENT_ID, VERSION)
    assert info.value.code is StoreErrorCode.NO_ES_BASE
    assert not ruta.exists()


def test_almacen_ajeno_se_rechaza_sin_escribir(tmp_path: Path) -> None:
    ruta = tmp_path / "ajeno.sqlite"
    _ejecutar(ruta, ("CREATE TABLE otra (x INTEGER)", f"PRAGMA user_version = {SCHEMA_VERSION - 1}"))
    antes = _huella(ruta)
    with pytest.raises(StoreError) as info:
        SqliteStore(ruta).rebuild_lexical_index(DOCUMENT_ID, VERSION)
    assert info.value.code is StoreErrorCode.INCOMPATIBLE
    assert _huella(ruta) == antes


def test_referencia_ausente_se_rechaza_sin_tocar_el_indice(tmp_path: Path) -> None:
    ruta = tmp_path / "vacio.sqlite"
    almacen = SqliteStore(ruta)
    almacen.initialize()
    antes = _volcado(ruta, AUTORIDAD)
    with pytest.raises(StoreError) as info:
        almacen.rebuild_lexical_index(DOCUMENT_ID, VERSION)
    assert info.value.code is StoreErrorCode.REFERENCIA_AUSENTE
    assert _derivado(ruta) == ()
    assert _volcado(ruta, AUTORIDAD) == antes


def test_version_no_registrada_se_rechaza_sin_tocar_el_indice(tmp_path: Path) -> None:
    ruta = _con_referencia(tmp_path)
    antes = _volcado(ruta, AUTORIDAD)
    with pytest.raises(StoreError) as info:
        SqliteStore(ruta).rebuild_lexical_index(DOCUMENT_ID, VERSION)
    assert info.value.code is StoreErrorCode.VERSION_NO_ENCONTRADA
    assert _derivado(ruta) == ()
    assert _volcado(ruta, AUTORIDAD) == antes


def test_version_registrada_sin_referencia_se_rechaza(tmp_path: Path) -> None:
    """La ausencia de referencia se informa **antes** que la versión: el vocabulario no se confunde."""
    ruta = tmp_path / "sin_referencia.sqlite"
    almacen = SqliteStore(ruta)
    almacen.initialize()
    _ejecutar(
        ruta,
        (
            f"INSERT INTO fuente (document_id, source_format, page_count) VALUES ('{DOCUMENT_ID}', 'pdf', 1)",
            f"INSERT INTO version_documento (document_id, document_version) VALUES ('{DOCUMENT_ID}', '{VERSION}')",
        ),
    )
    with pytest.raises(StoreError) as info:
        almacen.rebuild_lexical_index(DOCUMENT_ID, VERSION)
    assert info.value.code is StoreErrorCode.REFERENCIA_AUSENTE


def test_version_vacia_se_reconstruye_sin_error(tmp_path: Path) -> None:
    """`N = 0` es un caso legítimo (`C-14`): reconstruir no inventa restricciones."""
    ruta = _con_referencia(tmp_path)
    _sembrar(ruta, ())
    resultado = SqliteStore(ruta).rebuild_lexical_index(DOCUMENT_ID, VERSION)
    assert resultado.filas_previas == 0
    assert resultado.filas_reconstruidas == 0
    assert _derivado(ruta) == ()


def test_reconstruccion_idempotente_y_no_toca_la_autoridad(tmp_path: Path) -> None:
    ruta = _con_referencia(tmp_path)
    _sembrar(ruta, (1, 2, 3), derivadas=(1,))
    antes = _volcado(ruta, AUTORIDAD)
    almacen = SqliteStore(ruta)
    primera = almacen.rebuild_lexical_index(DOCUMENT_ID, VERSION)
    assert primera.filas_previas == 1
    assert primera.filas_reconstruidas == 3
    assert _derivado(ruta) == (
        (1, "contenido 1 distintivo"),
        (2, "contenido 2 distintivo"),
        (3, "contenido 3 distintivo"),
    )
    segunda = almacen.rebuild_lexical_index(DOCUMENT_ID, VERSION)
    assert segunda.filas_previas == 3
    assert segunda.filas_reconstruidas == 3
    assert _derivado(ruta) == (
        (1, "contenido 1 distintivo"),
        (2, "contenido 2 distintivo"),
        (3, "contenido 3 distintivo"),
    )
    assert _volcado(ruta, AUTORIDAD) == antes


def test_fallo_a_mitad_conserva_el_indice_previo_danado(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Atomicidad: el rollback devuelve el índice **al estado previo**, aunque ese estado estuviera dañado."""
    ruta = _con_referencia(tmp_path)
    _sembrar(ruta, (1, 2, 3), derivadas=(1,))
    danado = _derivado(ruta)
    autoridad = _volcado(ruta, AUTORIDAD)
    original = sqlite_write_module._insertar_fila_derivada
    llamadas = {"n": 0}

    def fallar(*args: object) -> None:
        llamadas["n"] += 1
        if llamadas["n"] == 2:
            raise StoreError(StoreErrorCode.ERROR_SQLITE, "fallo inyectado a mitad de la reconstrucción")
        original(*args)  # type: ignore[arg-type]

    monkeypatch.setattr(sqlite_write_module, "_insertar_fila_derivada", fallar)
    with pytest.raises(StoreError) as info:
        SqliteStore(ruta).rebuild_lexical_index(DOCUMENT_ID, VERSION)
    assert info.value.code is StoreErrorCode.ERROR_SQLITE
    monkeypatch.undo()
    assert llamadas["n"] == 2
    assert _derivado(ruta) == danado
    assert _volcado(ruta, AUTORIDAD) == autoridad
    assert SqliteStore(ruta).rebuild_lexical_index(DOCUMENT_ID, VERSION).filas_reconstruidas == 3
    assert len(_derivado(ruta)) == 3


def test_no_se_persiste_index_version() -> None:
    """La etiqueta no se persiste: no hay columna ni sentencia de esquema que la mencione (decisión F)."""
    assert not any("index_version" in sentencia for sentencia in DDL)
