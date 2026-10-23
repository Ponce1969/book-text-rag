"""Cinco causas de disponibilidad de `D-14`, medidas sobre el adaptador SQLite en solo lectura.

`D-14` ítem 3 fija que la disponibilidad **no** se decide comprobando que el archivo existe o que se
puede abrir: se decide validando que el almacén es reconocible y utilizable en modo de solo lectura y
que las capacidades del motor que el modo `lexical` requiere están presentes. El ítem 8 separa
«válido y vacío» (no es degradación) de las cuatro causas de indisponibilidad.
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

from book_text_rag.adapters.storage.sqlite import SCHEMA_VERSION, SqliteStore
from book_text_rag.application.health import health
from book_text_rag.domain.availability import Availability, AvailabilityCause, HealthSummary


def _huella(ruta: Path) -> str:
    """Huella del archivo, para comprobar que la sonda no escribió."""
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def _laterales(ruta: Path) -> list[str]:
    """Archivos laterales de SQLite asociados al almacén."""
    return sorted(path.name for path in ruta.parent.glob(f"{ruta.name}-*"))


def test_almacen_ausente_y_la_sonda_no_crea_el_archivo(tmp_path: Path) -> None:
    ruta = tmp_path / "ausente.sqlite"

    disponibilidad = SqliteStore(ruta).probe_availability()

    assert disponibilidad.cause is AvailabilityCause.AUSENTE
    assert disponibilidad.disponible is False
    assert not ruta.exists(), "la sonda de disponibilidad no debe crear el almacén"


def test_ruta_que_es_directorio_es_inaccesible(tmp_path: Path) -> None:
    ruta = tmp_path / "directorio.sqlite"
    ruta.mkdir()

    assert SqliteStore(ruta).probe_availability().cause is AvailabilityCause.INACCESIBLE


def test_archivo_que_no_es_base_sqlite_es_inaccesible(tmp_path: Path) -> None:
    ruta = tmp_path / "ilegible.sqlite"
    ruta.write_bytes(b"esto no es una base SQLite valida")

    assert SqliteStore(ruta).probe_availability().cause is AvailabilityCause.INACCESIBLE


def test_version_desconocida_es_incompatible(tmp_path: Path) -> None:
    ruta = tmp_path / "ajena.sqlite"
    conexion = sqlite3.connect(ruta)
    try:
        conexion.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
        conexion.execute("CREATE TABLE otra (x INTEGER)")
        conexion.commit()
    finally:
        conexion.close()

    assert SqliteStore(ruta).probe_availability().cause is AvailabilityCause.INCOMPATIBLE


def test_almacen_al_que_le_falta_una_tabla_requerida_es_incompatible(tmp_path: Path) -> None:
    ruta = tmp_path / "parcial.sqlite"
    SqliteStore(ruta).initialize()
    conexion = sqlite3.connect(ruta)
    try:
        conexion.execute("DROP TABLE anclaje_cache")
        conexion.commit()
    finally:
        conexion.close()

    assert SqliteStore(ruta).probe_availability().cause is AvailabilityCause.INCOMPATIBLE


def test_ruta_existente_sin_permiso_de_inspeccion_es_inaccesible(tmp_path: Path, monkeypatch) -> None:
    """`D-14` ítem 3: existente pero no inspeccionable es `inaccesible`, y la sonda no propaga el error.

    La denegación real no se puede provocar en este host (Windows no aplica permisos POSIX a
    directorios), así que se simula el fallo de `stat()`: es exactamente lo que `Path.exists()` deja de
    absorber, porque `EACCES` no figura entre los errores que ignora.
    """
    ruta = tmp_path / "denegado.sqlite"
    SqliteStore(ruta).initialize()
    original = Path.stat

    def stat_denegado(self: Path, *args: object, **kwargs: object) -> object:
        if self == ruta:
            raise PermissionError(13, "Permiso denegado")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", stat_denegado)

    assert SqliteStore(ruta).probe_availability().cause is AvailabilityCause.INACCESIBLE


def test_ruta_que_el_sistema_no_acepta_sigue_siendo_ausente(tmp_path: Path) -> None:
    """Una ruta no codificable (`ValueError`) no designa ninguna entrada: se conserva `ausente`.

    `os.stat` rechaza con `ValueError` una ruta con byte nulo incrustado o no codificable, y
    `Path.exists()` devolvía `False` en ese caso. La sonda mantiene esa clasificación en lugar de
    convertirla en `inaccesible`: no hay recurso existente que pueda estar inaccesible.
    """
    ruta = tmp_path / "nula" / ("x" + chr(0) + "y.sqlite")

    assert SqliteStore(ruta).probe_availability().cause is AvailabilityCause.AUSENTE


def test_almacen_inicializado_vacio_es_disponible(tmp_path: Path) -> None:
    ruta = tmp_path / "vacio.sqlite"
    SqliteStore(ruta).initialize()

    disponibilidad = SqliteStore(ruta).probe_availability()

    assert disponibilidad.cause is AvailabilityCause.DISPONIBLE
    assert disponibilidad.disponible is True


def test_capacidad_fts5_ausente_no_es_disponible(tmp_path: Path, monkeypatch) -> None:
    ruta = tmp_path / "sin_fts5.sqlite"
    SqliteStore(ruta).initialize()
    monkeypatch.setattr("book_text_rag.adapters.storage.sqlite._fts5_disponible", lambda: False)

    assert SqliteStore(ruta).probe_availability().cause is AvailabilityCause.CAPACIDAD_AUSENTE


def test_la_sonda_no_escribe_ni_deja_laterales(tmp_path: Path) -> None:
    ruta = tmp_path / "intacto.sqlite"
    SqliteStore(ruta).initialize()
    antes = _huella(ruta)

    for _ in range(3):
        assert SqliteStore(ruta).probe_availability().disponible is True

    assert _huella(ruta) == antes
    assert _laterales(ruta) == []


class _AlmacenFijo:
    """Doble del puerto: devuelve una disponibilidad predefinida."""

    def __init__(self, disponibilidad: Availability) -> None:
        self._disponibilidad = disponibilidad

    def probe_availability(self) -> Availability:
        return self._disponibilidad


def test_el_resumen_publica_solo_los_campos_autorizados_por_d14() -> None:
    disponible = health(_AlmacenFijo(Availability(AvailabilityCause.DISPONIBLE)))
    degradado = health(_AlmacenFijo(Availability(AvailabilityCause.INCOMPATIBLE)))

    assert disponible == HealthSummary(status="ok", dependencies=(), available_modes=("lexical",))
    assert degradado == HealthSummary(status="degraded", dependencies=("index",), available_modes=())
