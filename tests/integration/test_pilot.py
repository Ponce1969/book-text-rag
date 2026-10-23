"""Corrida real sobre el PDF piloto: cifras estructurales y comparación de referencias.

Hay **dos referencias de cola** y no se comparan por igualdad, porque miden procedimientos distintos
sobre el mismo documento:

- `reference-d17.json`: referencia **vigente**, medida con el corte de **D-17** (primera línea del
  bloque de encabezado), con su método, su configuración y su reproducibilidad verificada.
- **Referencia histórica M0** (Experimentos 2 y 3), obtenida con corte por **coincidencia textual**.
  Se conserva intacta, identificada como método distinto: la diferencia entre ambas es
  **metodológica** (unidades donde el corte cae en otra línea) y no un defecto del algoritmo.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from book_text_rag.adapters.extraction.geometry import PyMuPdfGeometry
from book_text_rag.adapters.extraction.pdftotext import PdftotextExtractor
from book_text_rag.application.ingest_in_memory import ingest_in_memory
from book_text_rag.domain.identity import content_hash
from book_text_rag.domain.models import BlockType, IngestResult

REPO_ROOT = Path(__file__).resolve().parents[2]
PILOT = REPO_ROOT / "data" / "Ingeniería de IA - Chip Huyen (EN).pdf"
DOCUMENT_ID = "huyen-ai-engineering"
EXPECTED_DOCUMENT_VERSION = "0cd2fc8424e5220940663026edd7e3d4261ed67945d80008b352e7c5ded8fbb0"

EXPECTED_UNITS = 166
EXPECTED_POSITIONAL = 133
EXPECTED_PAGE_TYPOGRAPHY = 33
EXPECTED_EXCLUDED_PAGE_NUMBERS = 692
EXPECTED_TAIL_CAPTION_BLOCKS = 30
EXPECTED_CALIBRATION_ENTRIES = 116
EXPECTED_SCALE_ANOMALIES = 17
EXPECTED_SCALE_FACTOR = 1.148827

# Referencia histórica M0 (Experimentos 2 y 3): corte por coincidencia textual. No se re-mide ni se altera.
HISTORICAL_M0 = {
    "procedure": "coincidencia textual M0 (Experimentos 2 y 3)",
    "tail_words_total": 14731,
    "tail_words_predecessor_same_page": 1777,
    "tail_blocks_with_caption": 30,
}

REFERENCE_D17_PATH = Path(__file__).resolve().parent / "reference-d17.json"

pytestmark = pytest.mark.skipif(not PILOT.exists(), reason="falta el PDF piloto en data/")


@pytest.fixture(scope="module")
def pilot() -> IngestResult:
    return ingest_in_memory(
        PILOT, DOCUMENT_ID, text_extractor=PdftotextExtractor(PILOT), geometry=PyMuPdfGeometry(PILOT)
    )


def test_document_version_del_piloto(pilot: IngestResult) -> None:
    assert pilot.trace.document_version == EXPECTED_DOCUMENT_VERSION
    assert pilot.fragments[0].document_version == EXPECTED_DOCUMENT_VERSION


def test_cifras_estructurales(pilot: IngestResult) -> None:
    counts = pilot.trace.counts
    calibration = pilot.trace.calibration

    assert counts.corpus_units == EXPECTED_UNITS
    assert counts.anchored_by_level.get("posicional") == EXPECTED_POSITIONAL
    assert counts.anchored_by_level.get("pagina+tipografia") == EXPECTED_PAGE_TYPOGRAPHY
    assert sum(counts.anchored_by_level.values()) == EXPECTED_UNITS
    assert counts.page_number_lines_excluded == EXPECTED_EXCLUDED_PAGE_NUMBERS
    assert counts.page_number_anomalies == 0
    assert counts.fragments > 0

    assert calibration.entries == EXPECTED_CALIBRATION_ENTRIES
    assert calibration.dispersion_pt <= 3.0
    assert calibration.tolerance_pt == 2.0
    assert calibration.outline_scale_anomalies == EXPECTED_SCALE_ANOMALIES
    assert calibration.outline_scale_factor is not None
    assert abs(calibration.outline_scale_factor - EXPECTED_SCALE_FACTOR) < 0.001
    assert calibration.outline_scale_residual_max_pt is not None
    assert calibration.outline_scale_residual_max_pt <= 1.0
    assert calibration.destinations_unusable == 0


def test_bloques_con_rotulo_en_las_colas(pilot: IngestResult) -> None:
    """La cifra de 30 bloques con rótulo se reproduce con la misma definición del Experimento 2."""
    assert pilot.trace.counts.tail_blocks_with_caption == EXPECTED_TAIL_CAPTION_BLOCKS


def test_invariantes_del_piloto(pilot: IngestResult) -> None:
    fragments = pilot.fragments

    # I8 - ordinales contiguos y chunk_id reconstruible.
    assert [fragment.ordinal for fragment in fragments] == list(range(1, len(fragments) + 1))
    for fragment in fragments:
        assert fragment.chunk_id == f"{DOCUMENT_ID}:{fragment.document_version_short}:{fragment.ordinal}"

    # I9 - content_hash recomputable.
    for fragment in fragments:
        assert fragment.content_hash == content_hash(fragment.content)

    # I7 - sólo los bloques de tabla pueden superar el tope.
    for fragment in fragments:
        if fragment.word_count > 1500:
            assert fragment.block_type is BlockType.TABLE

    # I5 - ninguna línea del contenido es un número de página del rango del fragmento.
    for fragment in fragments:
        start = fragment.pdf_page_start or 0
        end = fragment.pdf_page_end or 0
        expected = {str(page - 1) for page in range(start, end + 1)}
        for line in fragment.content.splitlines():
            assert not (line.strip() in expected and line.strip().isdigit())

    # I2 - todo fragmento de prosa de una unidad arranca en el encabezado de esa unidad: la cabecera
    # del primer fragmento de prosa contiene el título (tolerante a título envuelto y a la forma ordinal).
    from book_text_rag.domain.anchor import core_title, norm

    first_by_path: dict[tuple[str, ...], str] = {}
    for fragment in fragments:
        if fragment.block_type is BlockType.PROSE:
            first_by_path.setdefault(tuple(fragment.section_path), "\n".join(fragment.content.splitlines()[:3]))
    assert first_by_path
    for path, head in first_by_path.items():
        assert core_title(path[-1]).lower() in norm(head).lower()

    # Todo fragmento pertenece a una unidad del corpus y el corpus entero produce fragmentos.
    paths = {tuple(fragment.section_path) for fragment in fragments}
    assert len(paths) == EXPECTED_UNITS

    # I3 (estructural) - los rangos de página no retroceden entre fragmentos consecutivos.
    starts = [fragment.pdf_page_start or 0 for fragment in fragments]
    assert starts == sorted(starts)
    assert all(fragment.pdf_page_start is not None and fragment.pdf_page_start >= 25 for fragment in fragments)
    assert all(fragment.pdf_page_end is not None and fragment.pdf_page_end <= 716 for fragment in fragments)

    # Todo fragmento declara cómo usó el destino del outline (registro de la anomalía de escala).
    assert {fragment.anchor_evidence.destination_use.value for fragment in fragments} <= {
        "valid",
        "scale_corrected",
        "unusable",
    }


def test_referencia_d17_se_reproduce(pilot: IngestResult) -> None:
    """La referencia vigente se reproduce con el **mismo procedimiento y la misma configuración**."""
    reference = json.loads(REFERENCE_D17_PATH.read_text(encoding="utf-8"))
    metrics = reference["metrics"]
    configuration = reference["configuration"]
    counts = pilot.trace.counts

    assert counts.corpus_units == metrics["corpus_units"]
    assert counts.fragments == metrics["fragments"]
    assert counts.table_blocks == metrics["table_blocks"]
    assert counts.tail_words_total == metrics["tail_words_total"]
    assert counts.tail_words_predecessor_same_page == metrics["tail_words_predecessor_same_page"]
    assert counts.tail_blocks_with_caption == metrics["tail_blocks_with_caption"]
    assert counts.page_number_lines_excluded == metrics["page_number_lines_excluded"]
    assert counts.page_number_anomalies == metrics["page_number_anomalies"]

    # Misma configuración: si cambia el extractor, la herramienta de geometría o la huella de
    # fragmentación, la comparación deja de ser válida y esta prueba falla.
    assert configuration["chunking_config_version"] == pilot.trace.chunking_config_version
    assert configuration["extractor"] == pilot.trace.extractor
    assert configuration["geometry_tool"] == pilot.trace.geometry_tool
    assert configuration["manifest_canonical"] == pilot.trace.manifest_canonical
    assert reference["document"]["document_version"] == pilot.trace.document_version
    assert reference["method"]["calibration"] == pilot.trace.calibration.model_dump()


def test_comparacion_historica_m0_identificada(pilot: IngestResult) -> None:
    """La referencia histórica M0 se conserva identificada como método distinto (no se compara por igualdad)."""
    reference = json.loads(REFERENCE_D17_PATH.read_text(encoding="utf-8"))
    historical = reference["historical_m0_reference"]
    counts = pilot.trace.counts

    assert historical["procedure"] == HISTORICAL_M0["procedure"]
    assert historical["tail_words_total"] == HISTORICAL_M0["tail_words_total"]
    assert historical["tail_words_predecessor_same_page"] == HISTORICAL_M0["tail_words_predecessor_same_page"]

    # La diferencia es metodológica: queda documentada con las unidades cuyo corte cambia, y no se
    # interpreta como defecto. El recuento de bloques con rótulo no depende del corte y coincide.
    relationship = reference["relationship_m0_d17"]
    assert relationship["units_with_different_cut"] > 0
    assert counts.tail_words_total != historical["tail_words_total"]
    assert historical["tail_blocks_with_caption"] == counts.tail_blocks_with_caption
    assert relationship["m0_tail_words_measured_now"] > 0
