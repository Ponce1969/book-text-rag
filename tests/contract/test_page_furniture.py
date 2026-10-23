"""Exclusión del mobiliario de página y sus anomalías (D-18 §3, D-20 §I5)."""

from __future__ import annotations

from pathlib import Path

from book_text_rag.application.ingest_in_memory import ingest_in_memory
from book_text_rag.domain.page_furniture import strip_page_number
from tests.conftest import DocumentBuilder


def test_se_excluye_el_numero_impreso() -> None:
    result = strip_page_number(["texto", "cuerpo", "24"], 25)
    assert result.lines == ["texto", "cuerpo"]
    assert result.excluded is True
    assert result.excluded_value == 24
    assert result.anomaly is False


def test_numero_distinto_se_conserva_y_se_registra_como_anomalia() -> None:
    result = strip_page_number(["texto", "999"], 25)
    assert result.lines == ["texto", "999"]
    assert result.excluded is False
    assert result.anomaly is True
    assert result.excluded_value == 999


def test_pagina_sin_numero_al_final() -> None:
    result = strip_page_number(["texto", "fin de la página"], 25)
    assert result.lines == ["texto", "fin de la página"]
    assert result.excluded is False
    assert result.anomaly is False


def test_la_anomalia_aparece_en_la_traza_y_el_texto_se_conserva(tmp_path: Path) -> None:
    builder = DocumentBuilder()
    builder.add_unit(25, "Alpha", [["alpha body"]])
    for page in range(26, 46):
        builder.add_unit(page, f"Filler {page}", [["filler text"]])
    text, geometry = builder.build(50)

    # La página 30 termina con un número que no es pdf_page - 1: se conserva y se registra.
    lines = text.pages_list[29].split("\n")
    text.pages_list[29] = "\n".join([*lines[:-1], "999"])

    pdf = tmp_path / "sintetico.pdf"
    pdf.write_bytes(b"bytes sinteticos")
    result = ingest_in_memory(pdf, "sintetico", text_extractor=text, geometry=geometry)

    assert result.trace.counts.page_number_anomalies == 1
    assert result.trace.counts.page_number_lines_excluded == 20
    assert any("999" in fragment.content.split() for fragment in result.fragments)


def test_todas_las_exclusiones_del_corpus_se_cuentan(tmp_path: Path) -> None:
    builder = DocumentBuilder()
    for page in range(25, 47):
        builder.add_unit(page, f"Unit {page}", [["body text"]])
    text, geometry = builder.build(50)
    pdf = tmp_path / "sintetico.pdf"
    pdf.write_bytes(b"bytes sinteticos")
    result = ingest_in_memory(pdf, "sintetico", text_extractor=text, geometry=geometry)
    assert result.trace.counts.page_number_lines_excluded == 22
    assert result.trace.counts.page_number_anomalies == 0
    for fragment in result.fragments:
        for line in fragment.content.splitlines():
            assert line.strip() not in {str(page - 1) for page in range(25, 47)}
