"""Integración de `documents`: el catálogo se lee con el archivo en **solo lectura**.

El almacén se deja sin permiso de escritura antes de invocar la CLI: si algo intentara escribir, la apertura
en lectura-escritura fallaría. Se comprueba además que no aparecen laterales y que la huella no cambia.
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

from book_text_rag.adapters.storage.sqlite import SqliteStore
from book_text_rag.cli import main
from book_text_rag.domain.identity import chunk_id, content_hash
from book_text_rag.ports.storage import EstadoIngesta

DOC = "libro"
VERSION = "c" * 64
TEXTO = "evidencia textual con procedencia verificable"


def _huella(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def _laterales(ruta: Path) -> list[str]:
    return sorted(path.name for path in ruta.parent.glob(f"{ruta.name}-*"))


def _sembrar(ruta: Path) -> None:
    SqliteStore(ruta).initialize()
    conexion = sqlite3.connect(ruta)
    try:
        conexion.execute("INSERT INTO fuente (document_id, source_format, page_count) VALUES (?, 'pdf', 25)", (DOC,))
        conexion.execute(
            "INSERT INTO referencia_fuente (document_id, alias, tipo_asignacion, fecha, estado_ingesta) "
            "VALUES (?, 'alias', 'deliberada', '2026-10-22', ?)",
            (DOC, EstadoIngesta.COMPLETADA.value),
        )
        conexion.execute("INSERT INTO version_documento (document_id, document_version) VALUES (?, ?)", (DOC, VERSION))
        conexion.execute(
            "INSERT INTO fragmento (document_id, document_version, ordinal, chunk_id, section_path, level, "
            "block_type, captions, pdf_page_start, pdf_page_end, content, content_hash, anchor_level) "
            "VALUES (?, ?, 1, ?, '[]', 1, 'prose', '[]', 25, 25, ?, ?, 'posicional')",
            (DOC, VERSION, chunk_id(DOC, VERSION[:12], 1), TEXTO, content_hash(TEXTO)),
        )
        conexion.execute(
            "INSERT INTO fragmento_fts (document_id, document_version, ordinal, content) VALUES (?, ?, 1, ?)",
            (DOC, VERSION, TEXTO),
        )
        conexion.commit()
    finally:
        conexion.close()


def test_documents_funciona_con_el_almacen_en_solo_lectura(tmp_path: Path, capsys) -> None:
    ruta = tmp_path / "solo_lectura.sqlite"
    _sembrar(ruta)
    antes = _huella(ruta)
    ruta.chmod(0o444)
    try:
        assert main(["documents", "--store", str(ruta)]) == 0
    finally:
        ruta.chmod(0o666)

    salida = capsys.readouterr().out
    assert salida.splitlines()[0] == "documentos: 1"
    assert f"document_id: {DOC}" in salida
    assert "page_count: 25" in salida
    assert "consultable: sí" in salida
    assert _huella(ruta) == antes
    assert _laterales(ruta) == []
