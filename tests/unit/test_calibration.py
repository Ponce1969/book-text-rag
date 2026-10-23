"""Calibración documental: moda dominante y artefacto de escala del outline (decisión B del propietario).

El capítulo 3 del piloto trae los destinos del outline en un espacio de coordenadas escalado
(k ≈ 1,1475). La calibración debe detectarlo, corregirlo y **registrarlo**, nunca compensarlo en
silencio; y cuando no hay un factor único que lo explique, el destino queda inutilizable y la unidad
se ancla por página y tipografía (D-17 §3).
"""

from __future__ import annotations

from pathlib import Path

from book_text_rag.application.ingest_in_memory import ingest_in_memory
from book_text_rag.domain.models import AnchorLevel, DestinationUse, IngestResult
from tests.conftest import DocumentBuilder, FakeGeometry, FakeTextExtractor

SCALED_UNITS = (30, 31, 32)
SCALE = 1.1475


def _document(units: int = 30) -> tuple[FakeTextExtractor, FakeGeometry, list[int]]:
    builder = DocumentBuilder()
    pages = list(range(25, 25 + units))
    for page in pages:
        builder.add_unit(page, f"Unit{page}", [["some body text"]])
    return *builder.build(25 + units + 2), pages


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


def _mutate_destinations(geometry: FakeGeometry, pages: list[int], factor: float) -> None:
    for index, entry in enumerate(geometry.toc_entries):
        if entry.page in pages and entry.y_dest is not None:
            geometry.toc_entries[index] = entry.model_copy(update={"y_dest": entry.y_dest * factor})


def test_artefacto_de_escala_se_detecta_corrige_y_registra(tmp_path: Path) -> None:
    text, geometry, pages = _document()
    _mutate_destinations(geometry, [pages[-1], pages[-2], pages[-3]], SCALE)

    result = _run(tmp_path, text, geometry)
    calibration = result.trace.calibration

    assert calibration.outline_scale_anomalies == 3
    assert calibration.outline_scale_factor is not None
    assert abs(calibration.outline_scale_factor - SCALE) < 0.002
    assert calibration.outline_scale_residual_max_pt is not None
    assert calibration.outline_scale_residual_max_pt <= 1.0
    assert calibration.destinations_unusable == 0

    scaled_titles = {f"Unit{pages[-1]}", f"Unit{pages[-2]}", f"Unit{pages[-3]}"}
    scaled = [fragment for fragment in result.fragments if fragment.section_path[-1] in scaled_titles]
    assert scaled
    for fragment in scaled:
        assert fragment.anchor_evidence.destination_use is DestinationUse.SCALE_CORRECTED
        assert fragment.anchor_level is AnchorLevel.POSITIONAL

    untouched = [fragment for fragment in result.fragments if fragment.section_path[-1] not in scaled_titles]
    assert untouched and all(f.anchor_evidence.destination_use is DestinationUse.VALID for f in untouched)


def test_sin_factor_unico_el_destino_queda_inutilizable_y_ancla_por_pagina(tmp_path: Path) -> None:
    text, geometry, pages = _document()
    for page, y_dest in zip((pages[-1], pages[-2], pages[-3]), (1.0, 400.0, 20.0), strict=True):
        for index, entry in enumerate(geometry.toc_entries):
            if entry.page == page:
                geometry.toc_entries[index] = entry.model_copy(update={"y_dest": y_dest})

    result = _run(tmp_path, text, geometry)
    calibration = result.trace.calibration

    assert calibration.outline_scale_anomalies == 0
    assert calibration.destinations_unusable == 3

    affected = {
        f"Unit{pages[-1]}",
        f"Unit{pages[-2]}",
        f"Unit{pages[-3]}",
    }
    fragments = [fragment for fragment in result.fragments if fragment.section_path[-1] in affected]
    assert fragments
    for fragment in fragments:
        assert fragment.anchor_evidence.destination_use is DestinationUse.UNUSABLE
        assert fragment.anchor_level is AnchorLevel.PAGE_TYPOGRAPHY
        assert fragment.anchor_evidence.y_dest is None


def test_moda_dominante_insuficiente_rechaza_la_calibracion(tmp_path: Path) -> None:
    text, geometry, pages = _document(units=22)
    for index, entry in enumerate(geometry.toc_entries):
        if entry.page in pages and index % 2 == 0 and entry.y_dest is not None:
            geometry.toc_entries[index] = entry.model_copy(update={"y_dest": entry.y_dest - 8.0})

    import pytest

    from book_text_rag.domain.models import ErrorCode, IngestError

    with pytest.raises(IngestError) as error:
        _run(tmp_path, text, geometry)
    assert error.value.code is ErrorCode.CALIBRATION_FAILED
