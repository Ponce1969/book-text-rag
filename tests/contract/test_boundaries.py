"""Límites entre unidades, cola del predecesor y encabezados sucesivos (D-18 §2 y §4)."""

from __future__ import annotations

from pathlib import Path

from book_text_rag.application.ingest_in_memory import ingest_in_memory
from book_text_rag.domain.fragmentation import build_units
from book_text_rag.domain.models import BlockType, IngestResult, Line, TocEntry
from tests.conftest import BODY_SIZE, HEADING_SIZE, DocumentBuilder, FakeGeometry, FakeTextExtractor


def _run(tmp_path: Path, text: FakeTextExtractor, geometry: FakeGeometry) -> IngestResult:
    pdf = tmp_path / "sintetico.pdf"
    pdf.write_bytes(b"bytes sinteticos")
    return ingest_in_memory(
        pdf,
        "sintetico",
        text_extractor=text,
        geometry=geometry,
        corpus_start_page=25,
        corpus_end_page=len(text.pages()) + 1,
    )


def test_cola_del_predecesor(tmp_path: Path, unit_with_tail: tuple[FakeTextExtractor, FakeGeometry]) -> None:
    text, geometry = unit_with_tail
    result = _run(tmp_path, text, geometry)

    assert result.trace.counts.tail_words_total == 5
    assert result.trace.counts.tail_words_predecessor_same_page == 0

    tail = "tail words before the heading"
    predecessor = [f for f in result.fragments if f.section_path[-1] == "Filler 45"]
    successor = [f for f in result.fragments if f.section_path[-1] == "Second"]
    assert predecessor and successor
    assert any(tail in fragment.content for fragment in predecessor)
    assert all(tail not in fragment.content for fragment in successor)
    assert successor[0].content.splitlines()[0].strip() == "Second"


def test_predecesor_en_la_misma_pagina(tmp_path: Path) -> None:
    """El texto propio del padre se conserva y el hijo arranca en su propio encabezado (D-05 pto. 4)."""
    builder = DocumentBuilder()
    builder.add_unit(25, "Alpha", [["alpha body"]])
    for page in range(26, 46):
        builder.add_unit(page, f"Filler {page}", [["filler text"]])
    builder.add_unit(46, "Parent", [["parent body"]], y0=100.0, level=2)
    text, geometry = builder.build(50)

    geometry.toc_entries.append(TocEntry(level=3, title="Child", page=46, y_dest=300.0 - 72.0))
    geometry.page_lines[46].extend(
        [
            Line(
                text="Child",
                y0=300.0,
                y1=300.0 + HEADING_SIZE,
                size=HEADING_SIZE,
                font="Fake-Bold",
                bold=True,
            ),
            Line(text="child body", y0=336.0, y1=336.0 + BODY_SIZE, size=BODY_SIZE, font="Fake", bold=False),
        ]
    )
    page_lines = text.pages_list[45].split("\n")
    number = page_lines[-1]
    text.pages_list[45] = "\n".join([*page_lines[:-1], "Child", "child body", "", number])

    result = _run(tmp_path, text, geometry)
    units = build_units(geometry.toc(), start_page=25)
    assert len(units) == 23
    parent = next(unit for unit in units if unit.title == "Parent")
    assert parent.kind.value == "parent_own"
    assert result.trace.counts.anchored_by_level == {"posicional": 23}

    parent_fragments = [f for f in result.fragments if f.section_path[-1] == "Parent"]
    child_fragments = [f for f in result.fragments if f.section_path[-1] == "Child"]
    assert any("parent body" in fragment.content for fragment in parent_fragments)
    assert all("child body" not in fragment.content for fragment in parent_fragments)
    assert child_fragments[0].content.splitlines()[0].strip() == "Child"
    assert all("parent body" not in fragment.content for fragment in child_fragments)


def test_ningun_fragmento_cruza_su_unidad(tmp_path: Path) -> None:
    builder = DocumentBuilder()
    for page in range(25, 47):
        builder.add_unit(page, f"Unit {page}", [["body text here"]])
    text, geometry = builder.build(50)
    result = _run(tmp_path, text, geometry)

    titles = [f.section_path[-1] for f in result.fragments]
    for index, fragment in enumerate(result.fragments):
        for other in titles[index + 1 :]:
            if other != fragment.section_path[-1]:
                assert other not in fragment.content.splitlines()

    pages = [(f.pdf_page_start, f.pdf_page_end) for f in result.fragments]
    assert pages == sorted(pages)
    assert all(f.block_type is BlockType.PROSE for f in result.fragments)
