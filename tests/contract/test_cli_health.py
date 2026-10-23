"""Contrato de `health` y del código `index_unavailable` en la CLI (`D-14` ítems 4, 6 y 8)."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

from book_text_rag.adapters.storage.sqlite import SqliteStore
from book_text_rag.cli import main
from book_text_rag.domain.identity import chunk_id, content_hash
from book_text_rag.ports.storage import EstadoIngesta

DOCUMENT_ID = "doc"
VERSION = "a" * 64
LINEAS_DISPONIBLE = ["status: ok", "dependencies: []", 'available_modes: ["lexical"]']
LINEAS_DEGRADADO = ["status: degraded", 'dependencies: ["index"]', "available_modes: []"]


def _huella(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def _laterales(ruta: Path) -> list[str]:
    return sorted(path.name for path in ruta.parent.glob(f"{ruta.name}-*"))


def _sembrar_fragmento(ruta: Path) -> None:
    """Almacén válido con un documento publicado y un fragmento consultable (`D-13`).

    Incluye la referencia en «ingesta completada»: sin ella el documento no es consultable.
    """
    SqliteStore(ruta).initialize()
    conexion = sqlite3.connect(ruta)
    try:
        conexion.execute(
            "INSERT INTO fuente (document_id, source_format, page_count) VALUES (?, 'pdf', 7)", (DOCUMENT_ID,)
        )
        conexion.execute(
            "INSERT INTO referencia_fuente (document_id, alias, tipo_asignacion, fecha, estado_ingesta) "
            "VALUES (?, 'alias', 'deliberada', '2026-10-22', ?)",
            (DOCUMENT_ID, EstadoIngesta.COMPLETADA.value),
        )
        conexion.execute(
            "INSERT INTO version_documento (document_id, document_version) VALUES (?, ?)", (DOCUMENT_ID, VERSION)
        )
        contenido = "contenido de prueba sobre recuperacion lexica"
        conexion.execute(
            "INSERT INTO fragmento (document_id, document_version, ordinal, chunk_id, section_path, level, "
            "block_type, captions, pdf_page_start, pdf_page_end, content, content_hash, anchor_level) "
            "VALUES (?, ?, ?, ?, '[]', 1, 'prose', '[]', 7, 7, ?, ?, 'posicional')",
            (
                DOCUMENT_ID,
                VERSION,
                1,
                chunk_id(DOCUMENT_ID, VERSION[:12], 1),
                contenido,
                content_hash(contenido),
            ),
        )
        conexion.execute(
            "INSERT INTO fragmento_fts (document_id, document_version, ordinal, content) VALUES (?, ?, ?, ?)",
            (DOCUMENT_ID, VERSION, 1, contenido),
        )
        conexion.commit()
    finally:
        conexion.close()


def test_health_almacen_ausente_es_degradado_y_no_crea_el_archivo(tmp_path: Path, capsys) -> None:
    ruta = tmp_path / "ausente.sqlite"

    assert main(["health", "--store", str(ruta)]) == 0

    assert capsys.readouterr().out.splitlines() == LINEAS_DEGRADADO
    assert not ruta.exists()


def test_health_almacen_ajeno_es_degradado(tmp_path: Path, capsys) -> None:
    ruta = tmp_path / "ajena.sqlite"
    ruta.write_bytes(b"no es una base SQLite")

    assert main(["health", "--store", str(ruta)]) == 0

    assert capsys.readouterr().out.splitlines() == LINEAS_DEGRADADO


def test_health_almacen_valido_y_vacio_es_ok_sin_escribir(tmp_path: Path, capsys) -> None:
    ruta = tmp_path / "vacio.sqlite"
    SqliteStore(ruta).initialize()
    antes = _huella(ruta)

    assert main(["health", "--store", str(ruta)]) == 0

    assert capsys.readouterr().out.splitlines() == LINEAS_DISPONIBLE
    assert _huella(ruta) == antes
    assert _laterales(ruta) == []


def test_health_almacen_con_documentos_es_ok(tmp_path: Path, capsys) -> None:
    ruta = tmp_path / "con_documentos.sqlite"
    _sembrar_fragmento(ruta)

    assert main(["health", "--store", str(ruta)]) == 0

    assert capsys.readouterr().out.splitlines() == LINEAS_DISPONIBLE


def test_health_con_ruta_que_no_puede_inspeccionarse_es_degradado(tmp_path: Path, capsys, monkeypatch) -> None:
    """Un almacén existente que el sistema no deja inspeccionar informa `degraded`, no rompe la CLI."""
    ruta = tmp_path / "denegado.sqlite"
    SqliteStore(ruta).initialize()
    original = Path.stat

    def stat_denegado(self: Path, *args: object, **kwargs: object) -> object:
        if self == ruta:
            raise PermissionError(13, "Permiso denegado")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", stat_denegado)

    assert main(["health", "--store", str(ruta)]) == 0
    assert capsys.readouterr().out.splitlines() == LINEAS_DEGRADADO


def test_health_no_publica_la_clase_de_causa(tmp_path: Path, capsys) -> None:
    ruta = tmp_path / "ausente.sqlite"

    assert main(["health", "--store", str(ruta)]) == 0

    salida = capsys.readouterr().out
    assert len(salida.splitlines()) == 3
    for causa in ("ausente", "inaccesible", "incompatible", "capacidad"):
        assert causa not in salida


def test_search_sobre_almacen_degradado_devuelve_index_unavailable(tmp_path: Path, capsys) -> None:
    ruta = tmp_path / "ausente.sqlite"

    assert main(["search", "prueba", "--store", str(ruta)]) == 2

    error = capsys.readouterr().err
    assert "error [index_unavailable]" in error
    assert "incompatible" not in error
    assert "no_es_base" not in error


def test_show_sobre_almacen_degradado_devuelve_index_unavailable(tmp_path: Path, capsys) -> None:
    ruta = tmp_path / "ajena.sqlite"
    ruta.write_bytes(b"no es una base SQLite")

    assert main(["show", "--store", str(ruta), "--document-id", DOCUMENT_ID, "--document-version", VERSION]) == 2

    assert "error [index_unavailable]" in capsys.readouterr().err


def test_search_no_enmascara_errores_ajenos_a_la_disponibilidad(tmp_path: Path, capsys) -> None:
    ruta = tmp_path / "sano.sqlite"
    _sembrar_fragmento(ruta)

    assert main(["search", "  ", "--store", str(ruta)]) == 2

    error = capsys.readouterr().err
    assert "error [uso]" in error
    assert "index_unavailable" not in error


def test_search_sobre_almacen_sano_conserva_sus_resultados(tmp_path: Path, capsys) -> None:
    ruta = tmp_path / "sano.sqlite"
    _sembrar_fragmento(ruta)

    assert main(["search", "prueba", "--store", str(ruta)]) == 0

    salida = capsys.readouterr().out
    assert "resultados: 1" in salida
    assert f"chunk_id: {chunk_id(DOCUMENT_ID, VERSION[:12], 1)}" in salida


def test_search_sobre_almacen_valido_y_vacio_devuelve_lista_vacia_sin_error(tmp_path: Path, capsys) -> None:
    """`D-14` ítem 8: un índice válido y vacío no es degradado; la consulta responde sin resultados."""
    ruta = tmp_path / "vacio.sqlite"
    SqliteStore(ruta).initialize()

    assert main(["search", "prueba", "--store", str(ruta)]) == 0

    salida = capsys.readouterr().out
    assert "resultados: 0" in salida
    assert "index_unavailable" not in salida


def test_recuperacion_al_inicializar_en_la_misma_ruta_sin_reiniciar(tmp_path: Path, capsys) -> None:
    ruta = tmp_path / "tardia.sqlite"

    assert main(["health", "--store", str(ruta)]) == 0
    assert capsys.readouterr().out.splitlines() == LINEAS_DEGRADADO

    assert main(["init", "--store", str(ruta)]) == 0
    capsys.readouterr()

    assert main(["health", "--store", str(ruta)]) == 0
    assert capsys.readouterr().out.splitlines() == LINEAS_DISPONIBLE
