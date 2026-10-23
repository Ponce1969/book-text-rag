"""Estados de inicialización del almacén: E1, E2a, E2b, E3, E4 y E5 (CA-1, CA-2, CA-12…CA-20).

Todas las pruebas usan almacenes en **directorio temporal** y **cierran las conexiones antes de medir**
los hashes. Los rechazos deben dejar el contenido previo **intacto**: la inspección se hace en solo
lectura y no aparecen archivos laterales `-journal`, `-wal` ni `-shm`.
"""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

import pytest

from book_text_rag.adapters.storage import sqlite as sqlite_module
from book_text_rag.adapters.storage.sqlite import (
    CHECK_BLOCK_TYPE,
    DDL,
    SCHEMA_VERSION,
    TOKENIZE_FTS,
    SqliteStore,
    _Evidence,
    _verificar_evidencia,
)
from book_text_rag.ports.storage import InitOutcome, StoreError, StoreErrorCode

AJENOS: dict[str, str] = {
    "vista": "CREATE VIEW vista_ajena AS SELECT 1 AS uno",
    "indice": "CREATE INDEX idx_ajeno ON fuente (document_id)",
    "disparador": "CREATE TRIGGER trg_ajeno AFTER INSERT ON fuente BEGIN SELECT 1; END",
}


def _hash(ruta: Path) -> str:
    """Hash del archivo **con todas las conexiones cerradas** (se llama fuera de cualquier `with`)."""
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def _volcado(ruta: Path) -> tuple[int, list[tuple[str, str, str]]]:
    """`user_version` + `sqlite_master`, con la conexión cerrada antes de devolver."""
    conexion = sqlite3.connect(ruta)
    try:
        version = int(conexion.execute("PRAGMA user_version").fetchone()[0])
        filas = conexion.execute("SELECT type, name, sql FROM sqlite_master").fetchall()
    finally:
        conexion.close()
    return version, sorted((str(f[0]), str(f[1]), "" if f[2] is None else str(f[2])) for f in filas)


def _filas(ruta: Path, tabla: str) -> list[tuple[object, ...]]:
    conexion = sqlite3.connect(ruta)
    try:
        return [tuple(fila) for fila in conexion.execute(f"SELECT * FROM {tabla}")]
    finally:
        conexion.close()


def _laterales(ruta: Path) -> list[str]:
    return sorted(p.name for p in ruta.parent.glob(f"{ruta.name}-*"))


def _crear_con_ddl(ruta: Path, ddl: Sequence[str], version: int = SCHEMA_VERSION) -> None:
    """Crea un almacén con un DDL y una versión **alterados** para probar la validación estructural."""
    conexion = sqlite3.connect(ruta)
    try:
        for sentencia in ddl:
            conexion.execute(sentencia)
        conexion.execute(f"PRAGMA user_version = {version}")
        conexion.commit()
    finally:
        conexion.close()


def test_ca1_e1_destino_inexistente_se_crea(tmp_path: Path) -> None:
    ruta = tmp_path / "nuevo.sqlite"
    assert not ruta.exists()
    assert SqliteStore(ruta).initialize() is InitOutcome.CREADO
    assert ruta.exists()
    assert _volcado(ruta)[0] == SCHEMA_VERSION


def test_ca2_ca12_inicializacion_repetida_conserva_estructura_y_version(tmp_path: Path) -> None:
    ruta = tmp_path / "almacen.sqlite"
    almacen = SqliteStore(ruta)
    assert almacen.initialize() is InitOutcome.CREADO
    antes = _volcado(ruta)
    assert almacen.initialize() is InitOutcome.YA_INICIALIZADO
    assert _volcado(ruta) == antes


def test_ca18_e2a_archivo_de_cero_bytes_se_inicializa(tmp_path: Path) -> None:
    ruta = tmp_path / "cero.sqlite"
    ruta.write_bytes(b"")
    assert ruta.stat().st_size == 0
    assert SqliteStore(ruta).initialize() is InitOutcome.INICIALIZADO
    assert _volcado(ruta)[0] == SCHEMA_VERSION


def test_ca19_e2b_sqlite_valido_sin_tablas_se_inicializa(tmp_path: Path) -> None:
    ruta = tmp_path / "sin_tablas.sqlite"
    conexion = sqlite3.connect(ruta)
    try:
        conexion.execute("CREATE TABLE temporal (a INTEGER)")
        conexion.execute("DROP TABLE temporal")
        conexion.commit()
    finally:
        conexion.close()
    assert _volcado(ruta)[1] == []
    assert SqliteStore(ruta).initialize() is InitOutcome.INICIALIZADO
    assert _volcado(ruta)[0] == SCHEMA_VERSION


def test_ca13_e4_esquema_incompatible_se_rechaza_sin_modificar(tmp_path: Path) -> None:
    ruta = tmp_path / "ajena.sqlite"
    conexion = sqlite3.connect(ruta)
    try:
        conexion.execute("CREATE TABLE otra (a INTEGER)")
        conexion.execute("INSERT INTO otra VALUES (1)")
        conexion.commit()
    finally:
        conexion.close()
    antes_hash, antes_volcado, antes_filas = _hash(ruta), _volcado(ruta), _filas(ruta, "otra")
    with pytest.raises(StoreError) as info:
        SqliteStore(ruta).initialize()
    assert info.value.code is StoreErrorCode.INCOMPATIBLE
    assert _hash(ruta) == antes_hash
    assert _volcado(ruta) == antes_volcado
    assert _filas(ruta, "otra") == antes_filas
    assert _laterales(ruta) == []


def test_ca15_marcador_correcto_sin_estructuras_se_rechaza(tmp_path: Path) -> None:
    ruta = tmp_path / "marcador.sqlite"
    conexion = sqlite3.connect(ruta)
    try:
        conexion.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        conexion.commit()
    finally:
        conexion.close()
    antes_hash = _hash(ruta)
    with pytest.raises(StoreError) as info:
        SqliteStore(ruta).initialize()
    assert info.value.code is StoreErrorCode.INCOMPATIBLE
    assert _hash(ruta) == antes_hash


def test_ca15_version_desconocida_se_rechaza(tmp_path: Path) -> None:
    ruta = tmp_path / "version_rara.sqlite"
    conexion = sqlite3.connect(ruta)
    try:
        conexion.execute("CREATE TABLE x (a INTEGER)")
        conexion.execute("PRAGMA user_version = 99")
        conexion.commit()
    finally:
        conexion.close()
    antes_hash = _hash(ruta)
    with pytest.raises(StoreError) as info:
        SqliteStore(ruta).initialize()
    assert info.value.code is StoreErrorCode.INCOMPATIBLE
    assert _hash(ruta) == antes_hash


def test_ca14_ca20_e5_archivo_no_sqlite_se_rechaza_sin_sobrescribir(tmp_path: Path) -> None:
    ruta = tmp_path / "no_sqlite.sqlite"
    ruta.write_bytes(b"esto no es una base SQLite\n" * 20)
    antes_hash = _hash(ruta)
    conexion = sqlite3.connect(ruta)
    conexion.close()
    with pytest.raises(StoreError) as info:
        SqliteStore(ruta).initialize()
    assert info.value.code is StoreErrorCode.NO_ES_BASE
    assert _hash(ruta) == antes_hash
    assert _laterales(ruta) == []


def test_rechazo_de_error_inesperado_no_se_reclasifica(tmp_path: Path) -> None:
    """Un fallo operativo del motor **no** se presenta como `incompatible` ni como `no_es_base`."""
    directorio = tmp_path / "un_directorio"
    directorio.mkdir()
    with pytest.raises(StoreError) as info:
        SqliteStore(directorio).initialize()
    assert info.value.code is StoreErrorCode.ERROR_SQLITE
    assert directorio.is_dir()


def test_is_initialized_refleja_el_estado(tmp_path: Path) -> None:
    ruta = tmp_path / "almacen.sqlite"
    almacen = SqliteStore(ruta)
    assert almacen.is_initialized() is False
    almacen.initialize()
    assert almacen.is_initialized() is True
    ajena = tmp_path / "no_sqlite.sqlite"
    ajena.write_bytes(b"x" * 64)
    assert SqliteStore(ajena).is_initialized() is False


def test_guarda_de_carrera_detecta_cambios_del_destino(tmp_path: Path) -> None:
    """Se prueba la **lógica** de la guarda; la carrera real no se reproduce (no es un bloqueo)."""
    ruta = tmp_path / "x.sqlite"
    vacia = _Evidence(existe=True, tamano=10, mtime_ns=1, user_version=0, objetos=(), valido=False)
    _verificar_evidencia(vacia, vacia, ruta)
    cambios = (
        _Evidence(True, 99, 1, 0, (), False),
        _Evidence(True, 10, 2, 0, (), False),
        _Evidence(True, 10, 1, 1, (), False),
        _Evidence(True, 10, 1, 0, (("view", "v", "CREATE VIEW v AS SELECT 1"),), False),
        _Evidence(False, 0, 0, 0, (), False),
    )
    for actual in cambios:
        with pytest.raises(StoreError) as info:
            _verificar_evidencia(vacia, actual, ruta)
        assert info.value.code is StoreErrorCode.DESTINO_CAMBIADO
    with pytest.raises(StoreError) as info:
        _verificar_evidencia(
            _Evidence(False, 0, 0, 0, (), False),
            _Evidence(True, 0, 7, 0, (("table", "x", ""),), False),
            ruta,
        )
    assert info.value.code is StoreErrorCode.DESTINO_CAMBIADO


def test_p1_fallo_en_el_ddl_revierte_y_es_recuperable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """F-2.1: un fallo a mitad del DDL revierte todo y el almacén queda recuperable."""
    ruta = tmp_path / "fallo.sqlite"
    almacen = SqliteStore(ruta)
    monkeypatch.setattr(sqlite_module, "DDL", (*DDL, "CREATE TABLE rota (a INTEGER, )"))
    with pytest.raises(StoreError) as info:
        almacen.initialize()
    assert info.value.code is StoreErrorCode.ERROR_SQLITE
    # F-2.2: la causa es el error original de SQLite, no uno del ROLLBACK.
    assert isinstance(info.value.__cause__, sqlite3.Error)
    monkeypatch.undo()
    version, objetos = _volcado(ruta)
    assert version == 0
    assert [clase for clase, _, _ in objetos if clase == "table"] == []
    assert _laterales(ruta) == []
    assert almacen.initialize() in (InitOutcome.CREADO, InitOutcome.INICIALIZADO)
    assert almacen.is_initialized() is True


def test_p4_is_initialized_propaga_error_operativo(tmp_path: Path) -> None:
    """F-5.1: un fallo operativo del motor se propaga; no se informa como «no inicializado»."""
    directorio = tmp_path / "un_directorio"
    directorio.mkdir()
    with pytest.raises(StoreError) as info:
        SqliteStore(directorio).is_initialized()
    assert info.value.code is StoreErrorCode.ERROR_SQLITE
    assert directorio.is_dir()


def test_p3b_cambio_en_la_ventana_se_rechaza_sin_escribir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """La verificación **posterior** al bloqueo detecta un cambio de la ventana y revierte sin escribir."""
    ruta = tmp_path / "ventana.sqlite"
    ruta.write_bytes(b"")
    antes_hash = _hash(ruta)
    almacen = SqliteStore(ruta)
    real = sqlite_module._evidencia_de_conexion
    intrusa = (("table", "intrusa", "CREATE TABLE intrusa (a INTEGER)"),)

    def con_intrusa(conexion: sqlite3.Connection, ruta_destino: Path) -> _Evidence:
        return replace(real(conexion, ruta_destino), objetos=intrusa)

    monkeypatch.setattr(sqlite_module, "_evidencia_de_conexion", con_intrusa)
    with pytest.raises(StoreError) as info:
        almacen.initialize()
    assert info.value.code is StoreErrorCode.DESTINO_CAMBIADO
    monkeypatch.undo()
    assert _hash(ruta) == antes_hash
    version, objetos = _volcado(ruta)
    assert version == 0
    assert objetos == []
    assert _laterales(ruta) == []
    assert almacen.initialize() is InitOutcome.INICIALIZADO
    assert almacen.is_initialized() is True


def test_d23_esquema_de_version_1_se_rechaza_sin_migrar(tmp_path: Path) -> None:
    """`D-23`: un almacén con el esquema **anterior** (v1) se rechaza; no se migra ni se convierte."""
    ruta = tmp_path / "v1.sqlite"
    ddl_v1 = tuple(
        "\n".join(
            linea
            for linea in sentencia.splitlines()
            if "recuento_anomalias_pagina" not in linea and "paginas_anomalas" not in linea
        )
        for sentencia in DDL
    )
    assert ddl_v1 != DDL
    _crear_con_ddl(ruta, ddl_v1, version=1)
    antes_hash, antes_volcado = _hash(ruta), _volcado(ruta)
    with pytest.raises(StoreError) as info:
        SqliteStore(ruta).initialize()
    assert info.value.code is StoreErrorCode.INCOMPATIBLE
    assert _hash(ruta) == antes_hash
    assert _volcado(ruta) == antes_volcado
    assert _laterales(ruta) == []


def test_e4_sin_unicidad_de_chunk_id_se_rechaza(tmp_path: Path) -> None:
    ruta = tmp_path / "sin_uq.sqlite"
    ddl = tuple(s.replace("chunk_id TEXT NOT NULL UNIQUE", "chunk_id TEXT NOT NULL") for s in DDL)
    assert ddl != DDL
    _crear_con_ddl(ruta, ddl)
    antes_hash = _hash(ruta)
    with pytest.raises(StoreError) as info:
        SqliteStore(ruta).initialize()
    assert info.value.code is StoreErrorCode.INCOMPATIBLE
    assert _hash(ruta) == antes_hash
    assert _laterales(ruta) == []


def test_e4_tokenizer_distinto_se_rechaza(tmp_path: Path) -> None:
    ruta = tmp_path / "tokenizer.sqlite"
    ddl = tuple(s.replace(TOKENIZE_FTS, "tokenize = 'unicode61'") for s in DDL)
    assert ddl != DDL
    _crear_con_ddl(ruta, ddl)
    antes_hash = _hash(ruta)
    with pytest.raises(StoreError) as info:
        SqliteStore(ruta).initialize()
    assert info.value.code is StoreErrorCode.INCOMPATIBLE
    assert _hash(ruta) == antes_hash
    assert _laterales(ruta) == []


def test_e4_check_faltante_se_rechaza(tmp_path: Path) -> None:
    ruta = tmp_path / "sin_check.sqlite"
    ddl = tuple(s.replace(CHECK_BLOCK_TYPE, "") for s in DDL)
    assert ddl != DDL
    _crear_con_ddl(ruta, ddl)
    antes_hash = _hash(ruta)
    with pytest.raises(StoreError) as info:
        SqliteStore(ruta).initialize()
    assert info.value.code is StoreErrorCode.INCOMPATIBLE
    assert _hash(ruta) == antes_hash
    assert _laterales(ruta) == []


@pytest.mark.parametrize("clase", sorted(AJENOS))
def test_e4_objeto_ajeno_se_rechaza(tmp_path: Path, clase: str) -> None:
    """Vistas, índices y disparadores ajenos: rechazo sin escrituras y archivo intacto."""
    ruta = tmp_path / f"ajeno_{clase}.sqlite"
    almacen = SqliteStore(ruta)
    assert almacen.initialize() is InitOutcome.CREADO
    conexion = sqlite3.connect(ruta)
    try:
        conexion.execute(AJENOS[clase])
        conexion.commit()
    finally:
        conexion.close()
    antes_hash, antes_volcado = _hash(ruta), _volcado(ruta)
    with pytest.raises(StoreError) as info:
        almacen.initialize()
    assert info.value.code is StoreErrorCode.INCOMPATIBLE
    assert _hash(ruta) == antes_hash
    assert _volcado(ruta) == antes_volcado
    assert _laterales(ruta) == []
    assert almacen.is_initialized() is False
