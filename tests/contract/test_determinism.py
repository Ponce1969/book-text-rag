"""Determinismo de la unidad 1 (D-20 §6): dos corridas idénticas salvo marcas temporales."""

from __future__ import annotations

from pathlib import Path

from book_text_rag.application.ingest_in_memory import ingest_in_memory
from book_text_rag.domain.manifest import default_manifest
from book_text_rag.domain.models import IngestResult
from tests.conftest import FakeGeometry, FakeTextExtractor


def _run(tmp_path: Path, text: FakeTextExtractor, geometry: FakeGeometry, mark: str) -> IngestResult:
    pdf = tmp_path / "sintetico.pdf"
    pdf.write_bytes(b"bytes sinteticos")
    manifest = default_manifest(geometry.tool())
    return ingest_in_memory(
        pdf,
        "sintetico",
        text_extractor=text,
        geometry=geometry,
        manifest=manifest,
        temporal_mark=mark,
        corpus_start_page=25,
        corpus_end_page=len(text.pages()) + 1,
    )


def test_dos_corridas_producen_registros_identicos(
    tmp_path: Path, two_units: tuple[FakeTextExtractor, FakeGeometry]
) -> None:
    text, geometry = two_units
    first = _run(tmp_path, text, geometry, "2026-10-15T00:00:00")
    second = _run(tmp_path, text, geometry, "2026-10-16T12:34:56")

    assert [fragment.model_dump() for fragment in first.fragments] == [
        fragment.model_dump() for fragment in second.fragments
    ]
    assert first.trace.temporal_mark != second.trace.temporal_mark
    assert first.trace.model_dump(exclude={"temporal_mark"}) == second.trace.model_dump(exclude={"temporal_mark"})
    assert first.trace.manifest_canonical == second.trace.manifest_canonical
    assert first.trace.chunking_config_version == second.trace.chunking_config_version
    assert first.trace.document_version == second.trace.document_version
