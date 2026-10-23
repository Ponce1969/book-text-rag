"""Invariantes I1-I9 de D-20 §4 sobre documentos sintéticos deterministas.

Nota de límite: D-05 pto. 3 corta **en límites de párrafo**, así que un párrafo individual mayor que
`max_words` no se parte (no hay regla que autorice cortar dentro de un párrafo). Las pruebas de tope
usan párrafos pequeños, que es el régimen del piloto (p75 = 48 palabras frente a un tope de 1500).
"""

from __future__ import annotations

from pathlib import Path

from book_text_rag.application.ingest_in_memory import ingest_in_memory
from book_text_rag.domain.identity import content_hash
from book_text_rag.domain.manifest import default_manifest
from book_text_rag.domain.models import BlockType, IngestResult
from tests.conftest import DocumentBuilder, FakeGeometry, FakeTextExtractor


def _run(
    pdf_path: Path,
    text: FakeTextExtractor,
    geometry: FakeGeometry,
    *,
    max_words: int = 1500,
) -> IngestResult:
    manifest = default_manifest(geometry.tool()).model_copy(update={"max_words": max_words})
    return ingest_in_memory(
        pdf_path,
        "sintetico",
        text_extractor=text,
        geometry=geometry,
        manifest=manifest,
        corpus_start_page=25,
        corpus_end_page=len(text.pages()) + 1,
    )


def _source_words(text: FakeTextExtractor, first_page: int, last_page: int) -> list[str]:
    """Palabras del corpus sintético, sin los números impresos de página (D-18 §3)."""
    words: list[str] = []
    for page in range(first_page, last_page + 1):
        for line in text.pages_list[page - 1].split("\n"):
            if line.strip() and line.strip() != str(page - 1):
                words.extend(line.split())
    return words


def test_invariantes_i1_a_i9(tmp_path: Path, two_units: tuple[FakeTextExtractor, FakeGeometry]) -> None:
    text, geometry = two_units
    pdf_path = tmp_path / "sintetico.pdf"
    pdf_path.write_bytes(b"bytes sinteticos")

    result = _run(pdf_path, text, geometry)
    fragments = result.fragments
    counts = result.trace.counts

    # I1 - cobertura contigua y sin solape: los fragmentos reproducen las palabras del corpus en orden.
    produced: list[str] = []
    for fragment in fragments:
        produced.extend(fragment.content.split())
    assert produced == _source_words(text, 25, 46)

    # I2 - todo fragmento de prosa arranca en la primera línea del encabezado de su unidad.
    first_by_unit: dict[str, int] = {}
    for index, fragment in enumerate(fragments):
        first_by_unit.setdefault(fragment.section_path[-1], index)
    for title, index in first_by_unit.items():
        first = fragments[index]
        if first.block_type is BlockType.PROSE:
            assert first.content.splitlines()[0].strip() == title

    # I3 - ningún fragmento contiene el encabezado de una unidad posterior.
    ordered_units: list[str] = []
    for fragment in fragments:
        if fragment.section_path[-1] not in ordered_units:
            ordered_units.append(fragment.section_path[-1])
    for fragment in fragments:
        later = set(ordered_units[ordered_units.index(fragment.section_path[-1]) + 1 :])
        assert not any(line.strip() in later for line in fragment.content.splitlines())

    # I4 - los bloques de tabla son atómicos y etiquetados.
    tables = [fragment for fragment in fragments if fragment.block_type is BlockType.TABLE]
    assert len(tables) == 1
    assert tables[0].captions == ["Table 1-1. Datos"]
    assert tables[0].content.splitlines()[-1].strip() == "b  2"
    assert all(fragment.captions == [] for fragment in fragments if fragment.block_type is BlockType.PROSE)

    # I5 - ninguna línea del contenido es un número de página.
    for fragment in fragments:
        for line in fragment.content.splitlines():
            stripped = line.strip()
            assert not (stripped.isdigit() and 1 <= len(stripped) <= 4)

    # I6 - nada del front matter (el contenedor queda fuera del corpus).
    assert all("Contenedor" not in fragment.content for fragment in fragments)

    # I7 - ningún fragmento supera el tope (no hay tablas con más de 1500 palabras en este documento).
    assert all(fragment.word_count <= 1500 for fragment in fragments)

    # I8 - ordinales contiguos y chunk_id reconstruible.
    assert [fragment.ordinal for fragment in fragments] == list(range(1, len(fragments) + 1))
    for fragment in fragments:
        assert fragment.chunk_id == f"sintetico:{fragment.document_version_short}:{fragment.ordinal}"

    # I9 - content_hash recomputable desde el contenido.
    for fragment in fragments:
        assert fragment.content_hash == content_hash(fragment.content)

    # Recuentos y evidencia de anclaje (D-20 §3.2).
    assert counts.corpus_units == 22
    assert counts.anchored_by_level == {"posicional": 22}
    assert counts.table_blocks == 1
    assert counts.page_number_lines_excluded == 22
    assert counts.page_number_anomalies == 0
    assert counts.tail_words_total == 0
    assert counts.fragments == len(fragments)
    assert all(fragment.anchor_level.value == "posicional" for fragment in fragments)
    assert all(fragment.anchor_evidence.y_dest is not None for fragment in fragments)
    assert all(fragment.pdf_page_start is not None and fragment.pdf_page_end is not None for fragment in fragments)


def test_tope_y_corte_por_parrafo(tmp_path: Path) -> None:
    builder = DocumentBuilder()
    builder.add_unit(25, "Alpha", [["one two three"], ["four five six"], ["seven eight nine"]])
    for page in range(26, 46):
        builder.add_unit(page, f"Filler {page}", [["filler text"]])
    builder.add_unit(46, "Beta", [["beta content"]])
    text, geometry = builder.build(50)
    pdf_path = tmp_path / "sintetico.pdf"
    pdf_path.write_bytes(b"bytes sinteticos")

    result = _run(pdf_path, text, geometry, max_words=4)
    prose = [fragment for fragment in result.fragments if fragment.block_type is BlockType.PROSE]
    assert prose
    assert max(fragment.word_count for fragment in prose) <= 4

    alpha = [fragment for fragment in prose if fragment.section_path[-1] == "Alpha"]
    assert len(alpha) == 3  # tres párrafos de tres palabras con tope cuatro

    produced: list[str] = []
    for fragment in result.fragments:
        produced.extend(fragment.content.split())
    assert produced == _source_words(text, 25, 46)


def test_tabla_atomica_supera_el_tope(tmp_path: Path) -> None:
    builder = DocumentBuilder()
    builder.add_unit(25, "Alpha", [["one two"]])
    for page in range(26, 46):
        builder.add_unit(page, f"Unit{page}", [["filler text"]])
    builder.add_unit(
        46,
        "Beta",
        [["beta content"]],
        table=["Table 2-3. Grande", "row one 1", "row two 2", "row three 3", "row four 4"],
    )
    text, geometry = builder.build(50)
    pdf_path = tmp_path / "sintetico.pdf"
    pdf_path.write_bytes(b"bytes sinteticos")

    result = _run(pdf_path, text, geometry, max_words=3)
    tables = [fragment for fragment in result.fragments if fragment.block_type is BlockType.TABLE]
    assert len(tables) == 1
    assert tables[0].captions == ["Table 2-3. Grande"]
    assert tables[0].word_count > 3
    for fragment in result.fragments:
        if fragment.block_type is BlockType.PROSE:
            assert fragment.word_count <= 3
