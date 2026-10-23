"""Recorrido administrativo de la CLI sobre el PDF piloto y un almacén temporal."""

from __future__ import annotations

import hashlib
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from book_text_rag.adapters.storage.sqlite import SqliteStore
from book_text_rag.application.ingest_in_memory import ingest_in_memory
from book_text_rag.domain.models import IngestResult
from book_text_rag.ports.storage import NO_VERIFICADO, SearchResult

REPO_ROOT = Path(__file__).resolve().parents[2]
PILOT = REPO_ROOT / "data" / "Ingeniería de IA - Chip Huyen (EN).pdf"
DOCUMENT_ID = "huyen-ai-engineering"
ALIAS = "huyen"
FECHA = "2026-10-18"
FRAGMENTOS_ESPERADOS = 583  # Valor medido para este PDF piloto; no es una invariante general.

pytestmark = pytest.mark.skipif(not PILOT.exists(), reason="falta el PDF piloto en data/")


@pytest.fixture(scope="module")
def resultado_piloto() -> IngestResult:
    """Una extracción del módulo para fijar versión, corpus medido y término de consulta."""
    return ingest_in_memory(PILOT, DOCUMENT_ID)


def _huella(ruta: Path) -> str:
    """Huella del almacén para comprobar que la verificación no escribe."""
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def _contar(ruta: Path, tabla: str) -> int:
    """Cuenta filas de una tabla del esquema de prueba."""
    conexion = sqlite3.connect(ruta)
    try:
        fila = conexion.execute(f"SELECT count(*) FROM {tabla}").fetchone()
    finally:
        conexion.close()
    assert fila is not None
    return int(fila[0])


def _estado(ruta: Path) -> str:
    """Devuelve el estado persistido de la referencia del piloto."""
    conexion = sqlite3.connect(ruta)
    try:
        fila = conexion.execute("SELECT estado_ingesta FROM referencia_fuente").fetchone()
    finally:
        conexion.close()
    assert fila is not None
    return str(fila[0])


def _laterales(ruta: Path) -> list[str]:
    """Nombres de los laterales SQLite asociados al almacén."""
    return sorted(path.name for path in ruta.parent.glob(f"{ruta.name}-*"))


def _ejecutar_cli(argumentos: list[str]) -> tuple[int, str, str]:
    """Ejecuta `python -m` y devuelve código, salida estándar y error estándar."""
    entorno = os.environ.copy()
    rutas_python = [str(REPO_ROOT / "src"), entorno.get("PYTHONPATH", "")]
    entorno["PYTHONPATH"] = os.pathsep.join(ruta for ruta in rutas_python if ruta)
    entorno["PYTHONIOENCODING"] = "utf-8"
    salida = subprocess.run(
        [sys.executable, "-m", "book_text_rag.cli", *argumentos],
        cwd=REPO_ROOT,
        env=entorno,
        capture_output=True,
        check=False,
        encoding="utf-8",
        text=True,
    )
    return salida.returncode, salida.stdout, salida.stderr


def _version_impresa(salida: str) -> str:
    """Extrae la versión explícita que la CLI imprime para copiarla en la auditoría."""
    linea = next(linea for linea in salida.splitlines() if linea.startswith("document_version: "))
    return linea.split(": ", maxsplit=1)[1]


def _argumentos_ingesta(ruta: Path) -> list[str]:
    """Construye la invocación persistente del piloto."""
    return [
        "ingest",
        str(PILOT),
        "--document-id",
        DOCUMENT_ID,
        "--alias",
        ALIAS,
        "--fecha",
        FECHA,
        "--store",
        str(ruta),
        "--source-format",
        "pdf",
    ]


def _argumentos_verificacion(ruta: Path, document_version: str) -> list[str]:
    """Construye la invocación de auditoría de una versión concreta."""
    return [
        "verify",
        "--store",
        str(ruta),
        "--document-id",
        DOCUMENT_ID,
        "--document-version",
        document_version,
    ]


def test_recorrido_completo_idempotencia_verificacion_y_busqueda(
    tmp_path: Path, resultado_piloto: IngestResult
) -> None:
    ruta = tmp_path / "piloto.sqlite"
    codigo, salida_init, error = _ejecutar_cli(["init", "--store", str(ruta)])
    assert codigo == 0
    assert error == ""
    assert "creado" in salida_init
    assert SqliteStore(ruta).is_initialized() is True

    codigo, primera_ingesta, error = _ejecutar_cli(_argumentos_ingesta(ruta))
    assert codigo == 0
    assert error == ""
    version = _version_impresa(primera_ingesta)
    assert version == resultado_piloto.trace.document_version
    assert f"almacen: {ruta}" in primera_ingesta
    assert f"document_id: {DOCUMENT_ID}" in primera_ingesta
    assert f"fragmentos_escritos: {FRAGMENTOS_ESPERADOS}" in primera_ingesta
    assert "fragmentos_existentes: 0" in primera_ingesta
    assert "sqlite_vec_verificado: " in primera_ingesta

    assert _contar(ruta, "fuente") == 1
    assert _contar(ruta, "referencia_fuente") == 1
    assert _contar(ruta, "version_documento") == 1
    assert _contar(ruta, "fragmento") == FRAGMENTOS_ESPERADOS
    assert _contar(ruta, "fragmento_fts") == FRAGMENTOS_ESPERADOS
    assert _contar(ruta, "anclaje_cache") == FRAGMENTOS_ESPERADOS
    assert _contar(ruta, "construccion") == 1
    assert _estado(ruta) == "ingesta completada e índice disponible para consulta"

    codigo, segunda_ingesta, error = _ejecutar_cli(_argumentos_ingesta(ruta))
    assert codigo == 0
    assert error == ""
    assert _version_impresa(segunda_ingesta) == version
    assert "fragmentos_escritos: 0" in segunda_ingesta
    assert f"fragmentos_existentes: {FRAGMENTOS_ESPERADOS}" in segunda_ingesta
    for tabla, esperado in (
        ("fuente", 1),
        ("referencia_fuente", 1),
        ("version_documento", 1),
        ("fragmento", FRAGMENTOS_ESPERADOS),
        ("fragmento_fts", FRAGMENTOS_ESPERADOS),
        ("anclaje_cache", FRAGMENTOS_ESPERADOS),
        ("construccion", 2),
    ):
        # La tabla de construcciones registra cada operación aceptada; los fragmentos no se duplican.
        assert _contar(ruta, tabla) == esperado
    assert _estado(ruta) == "ingesta completada e índice disponible para consulta"

    token = next(
        token.lower()
        for fragmento in resultado_piloto.fragments
        for token in fragmento.content.split()
        if len(token) >= 10 and token.isalpha()
    )
    resultados = SqliteStore(ruta).search_results(token, top_k=5)
    campos_esperados = {
        "rank",
        "score",
        "document_id",
        "document_version",
        "chunk_id",
        "content",
        "section_path",
        "pdf_page_start",
        "pdf_page_end",
    }
    assert set(SearchResult.__dataclass_fields__) == campos_esperados
    assert resultados
    for resultado in resultados:
        assert {campo for campo in campos_esperados if hasattr(resultado, campo)} == campos_esperados
        assert resultado.document_version == version

    antes_de_verificar = _huella(ruta)
    codigo, primera_verificacion, error = _ejecutar_cli(_argumentos_verificacion(ruta, version))
    assert codigo == 0
    assert error == ""
    assert "ordinales_ok: True" in primera_verificacion
    assert "content_hash_ok: True" in primera_verificacion
    assert "chunk_id_ok: True" in primera_verificacion
    assert "fts5_ok: True" in primera_verificacion
    assert "estado_ok: True" in primera_verificacion
    assert "traza_presente: True" in primera_verificacion
    assert "fuente_presente: True" in primera_verificacion
    assert "ok: True" in primera_verificacion
    assert f"no_verificado: {NO_VERIFICADO}" in primera_verificacion
    assert _huella(ruta) == antes_de_verificar

    codigo, segunda_verificacion, error = _ejecutar_cli(_argumentos_verificacion(ruta, version))
    assert codigo == 0
    assert error == ""
    assert "ok: True" in segunda_verificacion
    assert _huella(ruta) == antes_de_verificar
    assert _laterales(ruta) == []

    conexion = sqlite3.connect(ruta)
    try:
        conexion.execute("DELETE FROM fragmento_fts WHERE document_id = ? AND ordinal = 1", (DOCUMENT_ID,))
        conexion.commit()
    finally:
        conexion.close()
    codigo, verificacion_danada, error = _ejecutar_cli(_argumentos_verificacion(ruta, version))
    assert codigo == 1
    assert error == ""
    assert "fts5_ok: False" in verificacion_danada
    assert "ok: False" in verificacion_danada


def test_ingesta_en_almacen_ajeno_falla_sin_modificarlo(tmp_path: Path) -> None:
    ruta = tmp_path / "ajeno.sqlite"
    conexion = sqlite3.connect(ruta)
    try:
        conexion.execute("CREATE TABLE ajena (valor TEXT)")
        conexion.commit()
    finally:
        conexion.close()
    antes = _huella(ruta)

    codigo, salida, diagnostico = _ejecutar_cli(_argumentos_ingesta(ruta))
    assert codigo == 2
    assert salida == ""
    assert "incompatible" in diagnostico
    assert "user_version" in diagnostico
    assert _huella(ruta) == antes
    assert _laterales(ruta) == []
