"""Persistencia del piloto: la unidad 1 en el almacén (`D-25`, `D-23`).

Un almacén **temporal** por prueba y **una** extracción del piloto compartida por el módulo. Cubre
conteos, FTS5, hashes, ordinales, representaciones canónicas, anomalías, idempotencia, rechazo de
contenido divergente, la precondición de `D-25` §1 (referencia ausente) y los fallos inyectados en T1,
T2 y T3.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from book_text_rag.adapters.storage import sqlite as sqlite_module
from book_text_rag.adapters.storage import sqlite_write as sqlite_write_module
from book_text_rag.adapters.storage.sqlite import SqliteStore, json_canonico
from book_text_rag.application.ingest_in_memory import ingest_in_memory
from book_text_rag.application.ingest_persistent import persist_unit
from book_text_rag.domain.identity import content_hash
from book_text_rag.ports.storage import EstadoIngesta, StoreError, StoreErrorCode, UnitWrite, WriteOutcome

REPO_ROOT = Path(__file__).resolve().parents[2]
PILOT = REPO_ROOT / "data" / "Ingeniería de IA - Chip Huyen (EN).pdf"
DOCUMENT_ID = "huyen-ai-engineering"
ALIAS = "huyen"
FECHA = "2026-10-17"
FRAGMENTOS_ESPERADOS = 583
LINEAS_EXCLUIDAS_ESPERADAS = 692

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
def almacen(tmp_path: Path) -> Path:
    ruta = tmp_path / "almacen.sqlite"
    SqliteStore(ruta).initialize()
    return ruta


def _consultar(ruta: Path, sql: str, parametros: tuple[object, ...] = ()) -> list[tuple[object, ...]]:
    conexion = sqlite3.connect(ruta)
    try:
        return [tuple(fila) for fila in conexion.execute(sql, parametros)]
    finally:
        conexion.close()


def _contar(ruta: Path, tabla: str) -> int:
    return int(_consultar(ruta, f"SELECT count(*) FROM {tabla}")[0][0])


def _estado(ruta: Path) -> str:
    return str(_consultar(ruta, "SELECT estado_ingesta FROM referencia_fuente")[0][0])


def _escribir(ruta: Path, unidad: UnitWrite) -> WriteOutcome:
    return persist_unit(unidad, store=SqliteStore(ruta))


def _laterales(ruta: Path) -> list[str]:
    return sorted(p.name for p in ruta.parent.glob(f"{ruta.name}-*"))


def test_persistencia_del_piloto(almacen: Path, unidad: UnitWrite) -> None:
    resultado = _escribir(almacen, unidad)
    assert resultado.fragmentos_escritos == FRAGMENTOS_ESPERADOS
    assert resultado.fragmentos_existentes == 0
    assert _contar(almacen, "fuente") == 1
    assert _contar(almacen, "referencia_fuente") == 1
    assert _contar(almacen, "version_documento") == 1
    assert _contar(almacen, "construccion") == 1
    assert _contar(almacen, "fragmento") == FRAGMENTOS_ESPERADOS
    assert _contar(almacen, "anclaje_cache") == FRAGMENTOS_ESPERADOS
    assert _estado(almacen) == EstadoIngesta.COMPLETADA.value


def test_fts5_correspondencia_y_consulta_lexica(almacen: Path, unidad: UnitWrite) -> None:
    _escribir(almacen, unidad)
    assert _contar(almacen, "fragmento_fts") == FRAGMENTOS_ESPERADOS
    fragmento = unidad.fragments[10]
    tokens = [token for token in fragmento.content.split() if len(token) >= 10 and token.isalpha()]
    assert tokens, "el fragmento elegido no tiene un token distintivo"
    filas = _consultar(
        almacen,
        "SELECT ordinal FROM fragmento_fts WHERE fragmento_fts MATCH ?",
        (tokens[0].lower(),),
    )
    assert fragmento.ordinal in {int(fila[0]) for fila in filas}


def test_hashes_recalculados_para_todo_el_contenido(almacen: Path, unidad: UnitWrite) -> None:
    _escribir(almacen, unidad)
    filas = _consultar(almacen, "SELECT ordinal, content, content_hash FROM fragmento ORDER BY ordinal")
    assert len(filas) == FRAGMENTOS_ESPERADOS
    for ordinal, content, hash_persistido in filas:
        assert content_hash(str(content)) == str(hash_persistido), f"ordinal {ordinal}"


def test_ordinales_contiguos_y_chunk_id_unico(almacen: Path, unidad: UnitWrite) -> None:
    _escribir(almacen, unidad)
    filas = _consultar(almacen, "SELECT ordinal, chunk_id FROM fragmento ORDER BY ordinal")
    assert [int(fila[0]) for fila in filas] == list(range(1, FRAGMENTOS_ESPERADOS + 1))
    identificadores = [str(fila[1]) for fila in filas]
    assert len(set(identificadores)) == len(identificadores)


def test_representaciones_canonicas_y_content_sin_normalizar(almacen: Path, unidad: UnitWrite) -> None:
    _escribir(almacen, unidad)
    filas = _consultar(almacen, "SELECT ordinal, section_path, captions, content FROM fragmento ORDER BY ordinal")
    por_ordinal = {fragmento.ordinal: fragmento for fragmento in unidad.fragments}
    for ordinal, section_path, captions, content in filas:
        fragmento = por_ordinal[int(ordinal)]
        assert str(section_path) == json_canonico([sqlite_module._nfc(x) for x in fragmento.section_path])
        assert str(captions) == json_canonico([sqlite_module._nfc(x) for x in fragmento.captions])
        assert json.loads(str(section_path)) == fragmento.section_path
        assert str(content) == fragmento.content


def test_anomalias_cero_y_arreglo_vacio(almacen: Path, unidad: UnitWrite) -> None:
    _escribir(almacen, unidad)
    fila = _consultar(
        almacen,
        "SELECT recuento_anomalias_pagina, paginas_anomalas, recuento_lineas_excluidas FROM construccion",
    )[0]
    assert int(fila[0]) == 0
    assert str(fila[1]) == "[]"
    assert int(fila[2]) == LINEAS_EXCLUIDAS_ESPERADAS
    assert unidad.trace.counts.page_number_anomalies == 0
    assert unidad.trace.counts.paginas_anomalas == []


def test_reintento_idempotente_y_traza_por_operacion(almacen: Path, unidad: UnitWrite) -> None:
    primero = _escribir(almacen, unidad)
    segundo = _escribir(almacen, unidad)
    assert primero.fragmentos_escritos == FRAGMENTOS_ESPERADOS
    assert segundo.fragmentos_escritos == 0
    assert segundo.fragmentos_existentes == FRAGMENTOS_ESPERADOS
    assert _contar(almacen, "fragmento") == FRAGMENTOS_ESPERADOS
    assert _contar(almacen, "version_documento") == 1
    assert _contar(almacen, "fragmento_fts") == FRAGMENTOS_ESPERADOS
    assert _contar(almacen, "construccion") == 2  # una por operación aceptada (D-1 / D-25)
    assert _estado(almacen) == EstadoIngesta.COMPLETADA.value


def test_unidad_internamente_inconsistente_se_rechaza(almacen: Path, unidad: UnitWrite) -> None:
    _escribir(almacen, unidad)
    inconsistente = replace(
        unidad,
        fragments=(
            unidad.fragments[0].model_copy(update={"content_hash": "0" * 64}),
            *unidad.fragments[1:],
        ),
    )
    with pytest.raises(StoreError) as info:
        _escribir(almacen, inconsistente)
    assert info.value.code is StoreErrorCode.CONTENIDO_DIVERGENTE
    assert _contar(almacen, "construccion") == 1


def test_contenido_divergente_con_lo_persistido_se_rechaza(almacen: Path, unidad: UnitWrite) -> None:
    _escribir(almacen, unidad)
    otro = "contenido distinto para el mismo ordinal"
    divergente = replace(
        unidad,
        fragments=(
            unidad.fragments[0].model_copy(update={"content": otro, "content_hash": content_hash(otro)}),
            *unidad.fragments[1:],
        ),
    )
    with pytest.raises(StoreError) as info:
        _escribir(almacen, divergente)
    assert info.value.code is StoreErrorCode.CONTENIDO_DIVERGENTE
    assert _contar(almacen, "fragmento") == FRAGMENTOS_ESPERADOS
    assert _contar(almacen, "construccion") == 1


def test_fallo_en_t1_no_degrada_el_estado_previo(
    almacen: Path, unidad: UnitWrite, monkeypatch: pytest.MonkeyPatch
) -> None:
    _escribir(almacen, unidad)

    def fallar(ruta: Path, unit: UnitWrite) -> None:
        raise StoreError(StoreErrorCode.ERROR_SQLITE, "fallo inyectado en T1")

    monkeypatch.setattr(sqlite_module, "_t1_registrar_referencia", fallar)
    with pytest.raises(StoreError):
        _escribir(almacen, unidad)
    assert _estado(almacen) == EstadoIngesta.COMPLETADA.value
    assert _contar(almacen, "fragmento") == FRAGMENTOS_ESPERADOS


def test_fallo_en_t2_deja_estado_durable_y_el_reintento_completa(
    almacen: Path, unidad: UnitWrite, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fallar(ruta: Path, document_id: str, alias: str) -> None:
        raise StoreError(StoreErrorCode.ERROR_SQLITE, "fallo inyectado en T2")

    monkeypatch.setattr(sqlite_module, "_t2_marcar_incompleta", fallar)
    with pytest.raises(StoreError):
        _escribir(almacen, unidad)
    assert _estado(almacen) == EstadoIngesta.DECISION_REGISTRADA.value
    assert _contar(almacen, "fragmento") == 0
    assert _contar(almacen, "construccion") == 0

    monkeypatch.undo()
    resultado = _escribir(almacen, unidad)
    assert resultado.fragmentos_escritos == FRAGMENTOS_ESPERADOS
    assert _estado(almacen) == EstadoIngesta.COMPLETADA.value


def test_fallo_en_t3_no_deja_unidad_parcial_y_el_reintento_completa(
    almacen: Path, unidad: UnitWrite, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fallar(conexion: sqlite3.Connection, unit: UnitWrite, fragmento: object) -> None:
        raise StoreError(StoreErrorCode.ERROR_SQLITE, "fallo inyectado en T3")

    monkeypatch.setattr(sqlite_write_module, "_insertar_fts", fallar)
    with pytest.raises(StoreError) as info:
        _escribir(almacen, unidad)
    assert info.value.code is StoreErrorCode.ERROR_SQLITE
    for tabla in ("version_documento", "fragmento", "anclaje_cache", "construccion", "fragmento_fts"):
        assert _contar(almacen, tabla) == 0, tabla
    assert _estado(almacen) == EstadoIngesta.INCOMPLETA.value
    assert _laterales(almacen) == []
    assert SqliteStore(almacen).is_initialized() is True

    monkeypatch.undo()
    resultado = _escribir(almacen, unidad)
    assert resultado.fragmentos_escritos == FRAGMENTOS_ESPERADOS
    assert _contar(almacen, "fragmento") == FRAGMENTOS_ESPERADOS
    assert _estado(almacen) == EstadoIngesta.COMPLETADA.value


def test_mark_incomplete_sin_referencia_se_rechaza(almacen: Path) -> None:
    """Precondición de `D-25` §1: T2 sin la referencia de T1 falla y no escribe nada."""
    with pytest.raises(StoreError) as info:
        SqliteStore(almacen).mark_incomplete(DOCUMENT_ID, ALIAS)
    assert info.value.code is StoreErrorCode.REFERENCIA_AUSENTE
    assert _contar(almacen, "referencia_fuente") == 0
    assert _laterales(almacen) == []
    assert SqliteStore(almacen).is_initialized() is True


def test_write_unit_sin_referencia_ni_fuente_se_rechaza(almacen: Path, unidad: UnitWrite) -> None:
    """T3 sin T1: el hecho se informa como referencia ausente, no como `error_sqlite` por la FK."""
    with pytest.raises(StoreError) as info:
        SqliteStore(almacen).write_unit(unidad)
    assert info.value.code is StoreErrorCode.REFERENCIA_AUSENTE
    for tabla in (
        "fuente",
        "referencia_fuente",
        "version_documento",
        "fragmento",
        "anclaje_cache",
        "construccion",
        "fragmento_fts",
    ):
        assert _contar(almacen, tabla) == 0, tabla
    assert _laterales(almacen) == []
    assert SqliteStore(almacen).is_initialized() is True


def test_write_unit_con_fuente_sin_referencia_se_rechaza(almacen: Path, unidad: UnitWrite) -> None:
    """T1 interrumpida entre sus dos `INSERT`: hay `fuente` pero no referencia; mismo código."""
    conexion = sqlite3.connect(almacen)
    try:
        conexion.execute(
            "INSERT INTO fuente (document_id, source_format, page_count) VALUES (?, ?, ?)",
            (DOCUMENT_ID, "pdf", 784),
        )
        conexion.commit()
    finally:
        conexion.close()
    with pytest.raises(StoreError) as info:
        SqliteStore(almacen).write_unit(unidad)
    assert info.value.code is StoreErrorCode.REFERENCIA_AUSENTE
    for tabla in ("version_documento", "fragmento", "anclaje_cache", "construccion", "fragmento_fts"):
        assert _contar(almacen, tabla) == 0, tabla
    assert _contar(almacen, "fuente") == 1
    assert _contar(almacen, "referencia_fuente") == 0
    assert _laterales(almacen) == []


def test_mark_incomplete_es_idempotente_en_estado_incompleto(almacen: Path, unidad: UnitWrite) -> None:
    """T2 repetido sobre una referencia ya en «incompleta» no falla: `rowcount` cuenta coincidencias."""
    almacen_obj = SqliteStore(almacen)
    almacen_obj.register_reference(unidad)
    almacen_obj.mark_incomplete(DOCUMENT_ID, ALIAS)
    assert _estado(almacen) == EstadoIngesta.INCOMPLETA.value
    almacen_obj.mark_incomplete(DOCUMENT_ID, ALIAS)
    assert _estado(almacen) == EstadoIngesta.INCOMPLETA.value
    assert _contar(almacen, "referencia_fuente") == 1
