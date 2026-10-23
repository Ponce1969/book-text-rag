"""Integración: `health` y la consulta operan con el archivo en **solo lectura** (`D-08`, `D-14` ítem 2).

El almacén se deja sin permiso de escritura antes de invocar la CLI: si alguna operación intentara
escribir, abrir en lectura-escritura fallaría y la prueba lo detectaría. Se comprueba además que no
aparecen archivos laterales y que la huella no cambia.
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

from book_text_rag.adapters.storage.sqlite import SqliteStore
from book_text_rag.cli import main
from book_text_rag.domain.identity import chunk_id, content_hash
from book_text_rag.ports.storage import EstadoIngesta

DOCUMENT_ID = "doc"
VERSION = "b" * 64


def _huella(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def _laterales(ruta: Path) -> list[str]:
    return sorted(path.name for path in ruta.parent.glob(f"{ruta.name}-*"))


def _sembrar(ruta: Path) -> None:
    """Documento publicado y consultable: referencia en «ingesta completada» (`D-13`)."""
    SqliteStore(ruta).initialize()
    conexion = sqlite3.connect(ruta)
    try:
        conexion.execute(
            "INSERT INTO fuente (document_id, source_format, page_count) VALUES (?, 'pdf', 25)", (DOCUMENT_ID,)
        )
        conexion.execute(
            "INSERT INTO referencia_fuente (document_id, alias, tipo_asignacion, fecha, estado_ingesta) "
            "VALUES (?, 'alias', 'deliberada', '2026-10-22', ?)",
            (DOCUMENT_ID, EstadoIngesta.COMPLETADA.value),
        )
        conexion.execute(
            "INSERT INTO version_documento (document_id, document_version) VALUES (?, ?)", (DOCUMENT_ID, VERSION)
        )
        contenido = "evidencia textual con procedencia verificable"
        conexion.execute(
            "INSERT INTO fragmento (document_id, document_version, ordinal, chunk_id, section_path, level, "
            "block_type, captions, pdf_page_start, pdf_page_end, content, content_hash, anchor_level) "
            "VALUES (?, ?, ?, ?, '[]', 1, 'prose', '[]', 25, 25, ?, ?, 'posicional')",
            (DOCUMENT_ID, VERSION, 1, chunk_id(DOCUMENT_ID, VERSION[:12], 1), contenido, content_hash(contenido)),
        )
        conexion.execute(
            "INSERT INTO fragmento_fts (document_id, document_version, ordinal, content) VALUES (?, ?, ?, ?)",
            (DOCUMENT_ID, VERSION, 1, contenido),
        )
        conexion.commit()
    finally:
        conexion.close()


def test_health_y_busqueda_funcionan_con_el_archivo_en_solo_lectura(tmp_path: Path, capsys) -> None:
    ruta = tmp_path / "solo_lectura.sqlite"
    _sembrar(ruta)
    antes = _huella(ruta)
    ruta.chmod(0o444)
    try:
        assert main(["health", "--store", str(ruta)]) == 0
        assert capsys.readouterr().out.splitlines() == [
            "status: ok",
            "dependencies: []",
            'available_modes: ["lexical"]',
        ]

        assert main(["search", "procedencia", "--store", str(ruta)]) == 0
        assert "resultados: 1" in capsys.readouterr().out
    finally:
        ruta.chmod(0o666)

    assert _huella(ruta) == antes
    assert _laterales(ruta) == []
