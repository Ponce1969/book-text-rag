"""Caso de uso de la unidad 1: extraer → anclar → fragmentar, todo en memoria (D-20 §1-§3).

No persiste nada y no calcula `index_version` (D-20 §3.3). Cualquier fallo del camino de ingesta
detiene la corrida **antes** de producir salida: no hay resultados parciales.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from book_text_rag.domain.anchor import align_heading_index, anchor, calibrate
from book_text_rag.domain.fragmentation import (
    AnchoredUnit,
    FragmentDraft,
    build_units,
    counts_of,
    fragment_span,
    successor_page,
    tail_metrics,
    unit_spans,
)
from book_text_rag.domain.identity import chunk_id, content_hash, document_version, document_version_short
from book_text_rag.domain.manifest import (
    CORPUS_END,
    Manifest,
    canonical_manifest,
    chunking_config_version,
    default_manifest,
)
from book_text_rag.domain.models import (
    AnchorEvidence,
    AnchorLevel,
    DestinationUse,
    ErrorCode,
    FragmentRecord,
    IngestError,
    IngestResult,
    IngestTrace,
    Line,
)
from book_text_rag.domain.page_furniture import strip_page_number
from book_text_rag.ports.extraction import GeometryProvider, TextExtractor

USABLE_Y = 0.5


def _clean_pages(pages: list[str]) -> tuple[list[list[str]], int, list[int]]:
    """Excluye el mobiliario de página y registra exclusiones y **páginas** con anomalía (`D-23`)."""
    cleaned: list[list[str]] = []
    excluded = 0
    anomalas: list[int] = []
    for number, page_text in enumerate(pages, start=1):
        result = strip_page_number(page_text.split("\n"), number)
        cleaned.append(result.lines)
        if 25 <= number <= 716:
            if result.excluded:
                excluded += 1
            if result.anomaly:
                anomalas.append(number)
    return cleaned, excluded, anomalas


def ingest_in_memory(
    pdf_path: Path,
    document_id: str,
    *,
    text_extractor: TextExtractor | None = None,
    geometry: GeometryProvider | None = None,
    manifest: Manifest | None = None,
    temporal_mark: str | None = None,
) -> IngestResult:
    """Produce los fragmentos y la traza de la unidad 1 para una fuente y una configuración.

    `document_id` es un parámetro explícito: el catálogo de fuentes de D-13 es persistencia y queda
    fuera de esta unidad.
    """
    if not document_id.strip():
        raise IngestError(ErrorCode.CONFIG_INVALID, "document_id vacío")

    if not pdf_path.exists():
        raise IngestError(ErrorCode.SOURCE_UNREADABLE, "la fuente no existe", ruta=str(pdf_path))
    try:
        pdf_bytes = pdf_path.read_bytes()
    except OSError as error:
        raise IngestError(ErrorCode.SOURCE_UNREADABLE, "la fuente no puede leerse", ruta=str(pdf_path)) from error

    from book_text_rag.adapters.extraction.geometry import PyMuPdfGeometry
    from book_text_rag.adapters.extraction.pdftotext import PdftotextExtractor

    extractor: TextExtractor = text_extractor if text_extractor is not None else PdftotextExtractor(pdf_path)
    geometry_provider: GeometryProvider = geometry if geometry is not None else PyMuPdfGeometry(pdf_path)

    active_manifest = manifest if manifest is not None else default_manifest(geometry_provider.tool())
    from book_text_rag.domain.manifest import validate_manifest

    validate_manifest(active_manifest)

    pages = extractor.pages()
    if not pages:
        raise IngestError(ErrorCode.EXTRACTION_FAILED, "el extractor no devolvió páginas")
    clean_pages, excluded_lines, anomalas = _clean_pages(pages)

    toc = geometry_provider.toc()
    if not toc:
        raise IngestError(ErrorCode.OUTLINE_UNAVAILABLE, "el documento no tiene marcadores utilizables")
    units = build_units(toc)
    if not units:
        raise IngestError(ErrorCode.OUTLINE_UNAVAILABLE, "el corpus no tiene unidades")

    calibration_entries = [
        (unit.title, unit.page, unit.y_dest) for unit in units if unit.y_dest is not None and unit.y_dest > USABLE_Y
    ]
    plan = calibrate(calibration_entries, geometry_provider.lines)
    calibration = plan.record

    anchored: list[AnchoredUnit] = []
    anchors: dict[int, tuple[AnchorEvidence, AnchorLevel]] = {}
    min_index = 0
    current_page = 0
    previous_page: int | None = None
    previous_y0: float | None = None
    for unit in units:
        key = f"{unit.page}|{unit.title}"
        destination_use = plan.decisions.get(key, DestinationUse.UNUSABLE)
        y_effective: float | None = None
        if destination_use is not DestinationUse.UNUSABLE:
            y_effective = plan.corrected_y.get(key, unit.y_dest)
        next_page: int | None = None
        next_lines: Sequence[Line] | None = None
        candidate_page = unit.page + 1
        if (
            candidate_page <= CORPUS_END
            and candidate_page <= len(clean_pages)
            and candidate_page < successor_page(toc, unit)
        ):
            next_page = candidate_page
            next_lines = geometry_provider.lines(candidate_page)
        previous_same_page = previous_y0 if previous_page == unit.page else None
        evidence, level, block = anchor(
            geometry_provider.lines(unit.page),
            unit.title,
            unit.page,
            y_effective,
            destination_use,
            calibration,
            next_page=next_page,
            next_lines=next_lines,
            declared_y_dest=unit.y_dest,
            previous_y0=previous_same_page,
        )
        real_page = evidence.page
        if real_page != current_page:
            current_page = real_page
            min_index = 0
        text_index = align_heading_index(clean_pages[real_page - 1], block, min_index)
        min_index = text_index + 1
        anchored.append(AnchoredUnit(unit=unit, text_index=text_index, page=real_page))
        anchors[unit.ordinal] = (evidence, level)
        previous_page = real_page
        previous_y0 = evidence.y0

    spans = unit_spans(toc, anchored, clean_pages)
    version = document_version(pdf_bytes)
    short = document_version_short(version)

    fragments: list[FragmentRecord] = []
    drafts: list[FragmentDraft] = []
    for span in spans:
        evidence, level = anchors[span.unit.ordinal]
        for draft in fragment_span(span, clean_pages, active_manifest):
            drafts.append(draft)
            ordinal = len(fragments) + 1
            fragments.append(
                FragmentRecord(
                    document_id=document_id,
                    document_version=version,
                    document_version_short=short,
                    chunk_id=chunk_id(document_id, short, ordinal),
                    ordinal=ordinal,
                    section_path=draft.section_path,
                    level=draft.level,
                    block_type=draft.block_type,
                    captions=draft.captions,
                    pdf_page_start=draft.pdf_page_start,
                    pdf_page_end=draft.pdf_page_end,
                    content=draft.content,
                    word_count=draft.word_count,
                    content_hash=content_hash(draft.content),
                    anchor_level=level,
                    anchor_evidence=evidence,
                )
            )

    levels = Counter(level.value for _, level in anchors.values())
    tails = tail_metrics(anchored, clean_pages)
    counts = counts_of(units, dict(levels), drafts, excluded_lines, anomalas, tails)

    name, tool_version, flags = extractor.effective_config()
    trace = IngestTrace(
        document_version=version,
        extractor=[name, tool_version, flags],
        geometry_tool=geometry_provider.tool(),
        manifest_canonical=canonical_manifest(active_manifest),
        chunking_config_version=chunking_config_version(active_manifest),
        calibration=calibration,
        counts=counts,
        temporal_mark=temporal_mark,
    )
    return IngestResult(fragments=fragments, trace=trace)
