"""Corrida real sobre el tercer libro: cifras del corpus y límites de sección."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from book_text_rag.adapters.extraction.geometry import PyMuPdfGeometry
from book_text_rag.adapters.extraction.pdftotext import PdftotextExtractor
from book_text_rag.application.ingest_in_memory import ingest_in_memory
from book_text_rag.domain.models import IngestResult

REPO_ROOT = Path(__file__).resolve().parents[2]
TERCERO = REPO_ROOT / "data" / "libro_Agentic_Architectural_Patterns.pdf"
DOCUMENT_ID = "agentic-architectural-patterns"

pytestmark = pytest.mark.skipif(not TERCERO.exists(), reason="falta el PDF del tercer libro en data/")


@pytest.fixture(scope="module")
def tercer_libro() -> IngestResult:
    return ingest_in_memory(
        TERCERO,
        DOCUMENT_ID,
        text_extractor=PdftotextExtractor(TERCERO),
        geometry=PyMuPdfGeometry(TERCERO),
    )


def test_recuento_de_unidades_del_corpus(tercer_libro: IngestResult) -> None:
    assert tercer_libro.trace.counts.corpus_units == 741


def test_recuento_de_fragmentos(tercer_libro: IngestResult) -> None:
    assert len(tercer_libro.fragments) == 743


def test_lineas_de_numeros_de_pagina_excluidas(tercer_libro: IngestResult) -> None:
    assert tercer_libro.trace.counts.page_number_lines_excluded == 504


def test_pagina_anomala(tercer_libro: IngestResult) -> None:
    assert tercer_libro.trace.counts.paginas_anomalas == [565]


def test_rango_de_paginas_y_exclusion_del_indice(tercer_libro: IngestResult) -> None:
    fragments = tercer_libro.fragments
    assert min(fragment.pdf_page_start for fragment in fragments) == 30
    assert max(fragment.pdf_page_end for fragment in fragments) == 563
    assert all(fragment.pdf_page_end < 564 for fragment in fragments)


def test_mobiliario_no_inicia_fragmentos(tercer_libro: IngestResult) -> None:
    furniture_heading = re.compile(r"^(?:Chapter \d+|Index)(?:\s+\d{1,4})?$")

    for fragment in tercer_libro.fragments:
        first_non_empty = next(
            (line.strip() for line in fragment.content.splitlines() if line.strip()),
            "",
        )
        assert furniture_heading.match(first_non_empty) is None


def test_ultimo_fragmento_pertenece_a_share_your_thoughts(tercer_libro: IngestResult) -> None:
    assert tercer_libro.fragments[-1].section_path == ["Share your thoughts"]
