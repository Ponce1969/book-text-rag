"""Re-medición explícita de la referencia de cola bajo **D-17** (corte por encabezado).

Uso:
    python -m tests.integration.measure_reference --write    # escribe la referencia
    python -m tests.integration.measure_reference            # verifica reproducibilidad

Registra, junto con las métricas, el **método**, la **configuración** y la **relación con la
referencia histórica M0** del Experimento 2 (corte por coincidencia textual). Las dos referencias no
se comparan por igualdad: miden procedimientos distintos sobre el mismo documento.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from book_text_rag.adapters.extraction.geometry import PyMuPdfGeometry  # noqa: E402
from book_text_rag.adapters.extraction.pdftotext import PdftotextExtractor  # noqa: E402
from book_text_rag.application.ingest_in_memory import ingest_in_memory  # noqa: E402
from book_text_rag.domain import anchor as A  # noqa: E402
from book_text_rag.domain.anchor import align_heading_index, anchor, calibrate  # noqa: E402
from book_text_rag.domain.fragmentation import build_units  # noqa: E402
from book_text_rag.domain.page_furniture import strip_page_number  # noqa: E402

PILOT = REPO_ROOT / "data" / "Ingeniería de IA - Chip Huyen (EN).pdf"
DOCUMENT_ID = "huyen-ai-engineering"
REFERENCE = Path(__file__).resolve().parent / "reference-d17.json"

WS = re.compile(r"\s+")


def _m0_index(lines: list[str], title: str) -> int:
    """Corte por coincidencia textual, tal como lo definió el Experimento 2 (norm y subcadena)."""
    wanted = WS.sub(" ", title).strip()
    for index, line in enumerate(lines):
        if wanted in WS.sub(" ", line).strip():
            return index
    return -1


def _cut_relacion(pdf: Path) -> dict[str, int | str]:
    """Cuenta las unidades donde el corte M0 y el corte D-17 caen en líneas distintas."""
    geometry = PyMuPdfGeometry(pdf)
    extractor = PdftotextExtractor(pdf)
    pages = [
        strip_page_number(page.split("\n"), number).lines for number, page in enumerate(extractor.pages(), start=1)
    ]
    units = build_units(geometry.toc())
    plan = calibrate(
        [(unit.title, unit.page, unit.y_dest) for unit in units if unit.y_dest and unit.y_dest > 0.5], geometry.lines
    )
    different = 0
    m0_words = 0
    current_page = 0
    min_index = 0
    for unit in units:
        key = f"{unit.page}|{unit.title}"
        use = plan.decisions.get(key, A.DestinationUse.UNUSABLE)
        y_effective = plan.corrected_y.get(key, unit.y_dest) if use is not A.DestinationUse.UNUSABLE else None
        _, _, block = anchor(geometry.lines(unit.page), unit.title, unit.page, y_effective, use, plan.record)
        if unit.page != current_page:
            current_page, min_index = unit.page, 0
        index = align_heading_index(pages[unit.page - 1], block, min_index)
        min_index = index + 1
        m0 = _m0_index(pages[unit.page - 1], unit.title)
        if m0 != index:
            different += 1
        if m0 >= 0:
            m0_words += sum(len(line.split()) for line in pages[unit.page - 1][:m0])
    return {
        "units_with_different_cut": different,
        "m0_tail_words_measured_now": m0_words,
        "note": (
            "M0 corta por coincidencia textual (Experimento 2); D-17 corta en la primera línea del bloque de "
            "encabezado. Las unidades con corte distinto explican la diferencia entre ambas referencias: es una "
            "diferencia de procedimiento, no un defecto del algoritmo."
        ),
    }


def measure() -> dict[str, object]:
    """Corre la unidad 1 sobre el piloto y devuelve la referencia bajo D-17."""
    result = ingest_in_memory(
        PILOT, DOCUMENT_ID, text_extractor=PdftotextExtractor(PILOT), geometry=PyMuPdfGeometry(PILOT)
    )
    counts = result.trace.counts
    return {
        "reference": "cola medida con el corte de D-17 (primera línea del bloque de encabezado)",
        "document": {
            "path": str(PILOT.relative_to(REPO_ROOT)).replace("\\", "/"),
            "document_id": DOCUMENT_ID,
            "document_version": result.trace.document_version,
        },
        "method": {
            "cut": "D-17: el fragmento arranca en la primera línea del bloque de encabezado",
            "tail": "líneas por encima de ese corte en la página declarada de la unidad",
            "calibration": result.trace.calibration.model_dump(),
            "anchoring_procedure": "anchoring/v1",
        },
        "configuration": {
            "extractor": result.trace.extractor,
            "geometry_tool": result.trace.geometry_tool,
            "manifest_canonical": result.trace.manifest_canonical,
            "chunking_config_version": result.trace.chunking_config_version,
        },
        "metrics": counts.model_dump(),
        "historical_m0_reference": {
            "procedure": "coincidencia textual M0 (Experimentos 2 y 3)",
            "tail_words_total": 14731,
            "tail_words_predecessor_same_page": 1777,
            "tail_blocks_with_caption": 30,
            "note": "se conserva intacta y no se compara por igualdad con la referencia D-17",
        },
        "relationship_m0_d17": _cut_relacion(PILOT),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="measure-reference", description="Referencia de cola bajo D-17")
    parser.add_argument("--write", action="store_true", help="escribe la referencia (por omisión sólo verifica)")
    args = parser.parse_args(argv)

    measured = measure()
    if args.write:
        REFERENCE.write_bytes(
            (json.dumps(measured, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
        )
        metrics = measured["metrics"]
        assert isinstance(metrics, dict)
        print(f"referencia escrita: {REFERENCE.name}")
        total = metrics["tail_words_total"]
        same_page = metrics["tail_words_predecessor_same_page"]
        caption_blocks = metrics["tail_blocks_with_caption"]
        print(f"  cola total = {total} | misma página = {same_page}")
        print(f"  bloques con rótulo en colas = {caption_blocks} | fragmentos = {metrics['fragments']}")
        relationship = measured["relationship_m0_d17"]
        assert isinstance(relationship, dict)
        print(f"  unidades con corte distinto entre M0 y D-17 = {relationship['units_with_different_cut']}")
        return 0

    if not REFERENCE.exists():
        print("no hay referencia guardada: ejecutá con --write", file=sys.stderr)
        return 2
    stored = json.loads(REFERENCE.read_text(encoding="utf-8"))
    if stored != measured:
        print("la medición NO reproduce la referencia guardada", file=sys.stderr)
        for key in ("metrics", "configuration", "method"):
            if stored.get(key) != measured.get(key):
                print(f"  difiere: {key}", file=sys.stderr)
        return 1
    print("reproducibilidad verificada: la medición coincide con la referencia guardada")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
