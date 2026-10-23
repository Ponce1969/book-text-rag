"""Identidades y huellas de la unidad 1 (D-11 §§1-3, `001` §6.1)."""

from __future__ import annotations

import hashlib

from book_text_rag.domain.identity import chunk_id, content_hash, document_version, document_version_short


def test_document_version_es_sha256_de_los_bytes() -> None:
    assert document_version(b"") == hashlib.sha256(b"").hexdigest()
    assert document_version(b"abc") == hashlib.sha256(b"abc").hexdigest()
    assert len(document_version(b"abc")) == 64


def test_document_version_short_son_los_primeros_doce() -> None:
    full = document_version(b"contenido")
    assert document_version_short(full) == full[:12]
    assert len(document_version_short(full)) == 12


def test_content_hash_sobre_la_representacion_utf8() -> None:
    assert content_hash("hola") == hashlib.sha256(b"hola").hexdigest()
    assert content_hash("ñ") == hashlib.sha256("ñ".encode()).hexdigest()
    assert len(content_hash("hola")) == 64


def test_chunk_id_reconstruible() -> None:
    assert chunk_id("doc", "0123456789ab", 7) == "doc:0123456789ab:7"
