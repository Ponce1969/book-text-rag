"""Integración de `get_document`: adaptador real + caso de uso sobre un almacén en **solo lectura**.

El archivo se deja sin permiso de escritura antes de invocar el caso de uso: si alguna operación
intentara escribir, abrir en lectura-escritura fallaría. Se comprueba además que no aparecen laterales y
que la huella no cambia, también en el caso rechazado de dos versiones.
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from book_text_rag.adapters.storage.sqlite import SqliteStore
from book_text_rag.application.get_document import EstadoPorVersionNoDefinido, get_document
from book_text_rag.domain.identity import chunk_id, content_hash
from book_text_rag.ports.storage import DocumentStatus, EstadoIngesta

DOC = "doc"
V1 = "c" * 64
V2 = "d" * 64


def _huella(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def _laterales(ruta: Path) -> list[str]:
    return sorted(path.name for path in ruta.parent.glob(f"{ruta.name}-*"))


def _sembrar(ruta: Path, versiones: tuple[str, ...]) -> None:
    SqliteStore(ruta).initialize()
    conexion = sqlite3.connect(ruta)
    try:
        conexion.execute("INSERT INTO fuente (document_id, source_format, page_count) VALUES (?, 'pdf', 784)", (DOC,))
        conexion.execute(
            "INSERT INTO referencia_fuente (document_id, alias, tipo_asignacion, fecha, estado_ingesta) "
            "VALUES (?, 'alias', 'deliberada', '2026-10-22', ?)",
            (DOC, EstadoIngesta.COMPLETADA.value),
        )
        for version in versiones:
            contenido = "evidencia textual con procedencia verificable"
            conexion.execute(
                "INSERT INTO version_documento (document_id, document_version) VALUES (?, ?)", (DOC, version)
            )
            conexion.execute(
                "INSERT INTO fragmento (document_id, document_version, ordinal, chunk_id, section_path, level, "
                "block_type, captions, pdf_page_start, pdf_page_end, content, content_hash, anchor_level) "
                "VALUES (?, ?, 1, ?, '[]', 1, 'prose', '[]', 25, 25, ?, ?, 'posicional')",
                (DOC, version, chunk_id(DOC, version[:12], 1), contenido, content_hash(contenido)),
            )
            conexion.execute(
                "INSERT INTO fragmento_fts (document_id, document_version, ordinal, content) VALUES (?, ?, 1, ?)",
                (DOC, version, contenido),
            )
        conexion.commit()
    finally:
        conexion.close()


def test_get_document_funciona_con_el_almacen_en_solo_lectura(tmp_path: Path) -> None:
    ruta = tmp_path / "solo_lectura.sqlite"
    _sembrar(ruta, (V1,))
    antes = _huella(ruta)
    ruta.chmod(0o444)
    try:
        vista = get_document(SqliteStore(ruta), DOC)
    finally:
        ruta.chmod(0o666)

    assert vista.document_version == V1
    assert vista.status is DocumentStatus.INDEXED
    assert vista.title is None
    assert vista.source_format == "pdf"
    assert vista.page_count == 784
    assert vista.index_version is None  # sin traza de construcción en este almacén
    assert _huella(ruta) == antes
    assert _laterales(ruta) == []


def test_dos_versiones_se_rechazan_sin_escribir_ni_dejar_laterales(tmp_path: Path) -> None:
    ruta = tmp_path / "dos_solo_lectura.sqlite"
    _sembrar(ruta, (V1, V2))
    antes = _huella(ruta)
    ruta.chmod(0o444)
    try:
        with pytest.raises(EstadoPorVersionNoDefinido):
            get_document(SqliteStore(ruta), DOC, V1)
    finally:
        ruta.chmod(0o666)

    assert _huella(ruta) == antes
    assert _laterales(ruta) == []
