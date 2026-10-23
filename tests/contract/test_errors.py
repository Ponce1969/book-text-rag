"""Los ocho códigos de error del camino de ingesta (D-20 §5) y la ausencia de salida parcial."""

from __future__ import annotations

from pathlib import Path

import pytest

from book_text_rag.adapters.extraction.pdftotext import PdftotextExtractor, decode_output
from book_text_rag.application.ingest_in_memory import ingest_in_memory
from book_text_rag.domain.manifest import default_manifest
from book_text_rag.domain.models import ErrorCode, IngestError
from tests.conftest import DocumentBuilder, FakeGeometry, FakeTextExtractor


def _dummy_pdf(tmp_path: Path, payload: bytes = b"no soy un PDF") -> Path:
    path = tmp_path / "fuente.pdf"
    path.write_bytes(payload)
    return path


def _document(units: int = 22) -> tuple[FakeTextExtractor, FakeGeometry]:
    builder = DocumentBuilder()
    builder.add_unit(25, "Alpha", [["alpha body"]])
    for page in range(26, 25 + units):
        builder.add_unit(page, f"Filler {page}", [["filler text"]])
    return builder.build(25 + units + 4)


def test_source_unreadable(tmp_path: Path) -> None:
    with pytest.raises(IngestError) as error:
        ingest_in_memory(tmp_path / "no-existe.pdf", "doc")
    assert error.value.code is ErrorCode.SOURCE_UNREADABLE


def test_extractor_unavailable(tmp_path: Path) -> None:
    pdf = _dummy_pdf(tmp_path)
    extractor = PdftotextExtractor(pdf, binary=Path("binario-inexistente"))
    _text, geometry = _document()
    with pytest.raises(IngestError) as error:
        ingest_in_memory(pdf, "doc", text_extractor=extractor, geometry=geometry)
    assert error.value.code is ErrorCode.EXTRACTOR_UNAVAILABLE


def test_extraction_failed(tmp_path: Path) -> None:
    pdf = _dummy_pdf(tmp_path, b"contenido que no es un PDF valido")
    with pytest.raises(IngestError) as error:
        PdftotextExtractor(pdf).pages()
    assert error.value.code in {ErrorCode.EXTRACTION_FAILED, ErrorCode.SOURCE_UNREADABLE}


def test_decode_error_con_bytes_invalidos() -> None:
    with pytest.raises(IngestError) as error:
        decode_output(b"texto \xff\xfe invalido")
    assert error.value.code is ErrorCode.DECODE_ERROR


def test_decode_error_con_bom() -> None:
    with pytest.raises(IngestError) as error:
        decode_output("\ufeffcontenido".encode())
    assert error.value.code is ErrorCode.DECODE_ERROR


def test_outline_unavailable(tmp_path: Path) -> None:
    text, _ = _document()
    geometry = FakeGeometry(toc_entries=[], page_lines={})
    with pytest.raises(IngestError) as error:
        ingest_in_memory(_dummy_pdf(tmp_path), "doc", text_extractor=text, geometry=geometry)
    assert error.value.code is ErrorCode.OUTLINE_UNAVAILABLE


def test_calibration_failed_por_pocas_entradas(tmp_path: Path) -> None:
    builder = DocumentBuilder()
    builder.add_unit(25, "Alpha", [["alpha body"]])
    builder.add_unit(26, "Beta", [["beta body"]])
    text, geometry = builder.build(30)
    with pytest.raises(IngestError) as error:
        ingest_in_memory(_dummy_pdf(tmp_path), "doc", text_extractor=text, geometry=geometry)
    assert error.value.code is ErrorCode.CALIBRATION_FAILED
    assert error.value.details["minimo"] == 20


def test_calibration_failed_por_dispersion(tmp_path: Path) -> None:
    text, geometry = _document()
    for index, entry in enumerate(geometry.toc_entries):
        if entry.page >= 25 and index % 2 == 0:
            geometry.toc_entries[index] = entry.model_copy(update={"y_dest": (entry.y_dest or 0.0) + 8.0})
    with pytest.raises(IngestError) as error:
        ingest_in_memory(_dummy_pdf(tmp_path), "doc", text_extractor=text, geometry=geometry)
    assert error.value.code is ErrorCode.CALIBRATION_FAILED
    assert {"dispersion_pt", "nucleo", "entradas"} & set(error.value.details)


def test_unit_not_anchored(tmp_path: Path) -> None:
    text, geometry = _document()
    lines = geometry.page_lines[46]
    geometry.page_lines[46] = [
        line.model_copy(update={"bold": False, "size": 12.0}) if line.bold else line for line in lines
    ]
    with pytest.raises(IngestError) as error:
        ingest_in_memory(_dummy_pdf(tmp_path), "doc", text_extractor=text, geometry=geometry)
    assert error.value.code is ErrorCode.UNIT_NOT_ANCHORED
    assert error.value.details["titulo"] == "Filler 46"


def test_config_invalid(tmp_path: Path) -> None:
    text, geometry = _document()
    manifest = default_manifest(geometry.tool()).model_copy(update={"max_words": 0})
    with pytest.raises(IngestError) as error:
        ingest_in_memory(_dummy_pdf(tmp_path), "doc", text_extractor=text, geometry=geometry, manifest=manifest)
    assert error.value.code is ErrorCode.CONFIG_INVALID


def test_document_id_vacio(tmp_path: Path) -> None:
    with pytest.raises(IngestError) as error:
        ingest_in_memory(_dummy_pdf(tmp_path), "   ")
    assert error.value.code is ErrorCode.CONFIG_INVALID


def test_sin_resultados_parciales(tmp_path: Path) -> None:
    """Un fallo en la última unidad no deja fragmentos observables: la corrida no devuelve nada."""
    text, geometry = _document()
    lines = geometry.page_lines[46]
    geometry.page_lines[46] = [
        line.model_copy(update={"bold": False, "size": 12.0}) if line.bold else line for line in lines
    ]
    resultado = None
    with pytest.raises(IngestError):
        resultado = ingest_in_memory(_dummy_pdf(tmp_path), "doc", text_extractor=text, geometry=geometry)
    assert resultado is None

    text_ok, geometry_ok = _document()
    assert ingest_in_memory(_dummy_pdf(tmp_path), "doc", text_extractor=text_ok, geometry=geometry_ok).fragments
