"""Persistencia transaccional de la unidad 1 del piloto (`D-25`).

Ejecuta la secuencia **T1 → T2 → T3** sobre un `StoreWriter`:

- **T1** registra o confirma la referencia **sin** degradar su estado previo.
- **T2** deja durable «ingesta incompleta» antes de escribir la unidad.
- **T3** persiste la unidad de forma atómica y fija «ingesta completada».

Un **reintento** vuelve a pasar por T1 (que no degrada) y por T2 antes de T3: eso es exactamente lo que
`D-25` exige cuando T2 había fallado.

**No** publica generaciones, **no** expone un modelo de lectura, **no** calcula `index_version`
(`D-22` §3.3) y **no** resuelve `P-1b`, `P-2`, `P-3/CD-05` ni ningún otro pendiente.
"""

from __future__ import annotations

from pathlib import Path

from book_text_rag.application.ingest_in_memory import ingest_in_memory
from book_text_rag.domain.manifest import Manifest
from book_text_rag.domain.models import IngestResult
from book_text_rag.ports.extraction import GeometryProvider, TextExtractor
from book_text_rag.ports.storage import StoreWriter, UnitWrite, WriteOutcome


def persist_unit(unit: UnitWrite, *, store: StoreWriter) -> WriteOutcome:
    """Secuencia **T1 → T2 → T3** sobre la unidad ya construida (`D-25`).

    Un reintento vuelve a pasar por T1 (que no degrada el estado) y por T2 antes de T3.
    """
    store.register_reference(unit)  # T1
    store.mark_incomplete(unit.document_id, unit.alias)  # T2
    return store.write_unit(unit)  # T3


def ingest_persistent(
    pdf_path: Path,
    document_id: str,
    alias: str,
    *,
    fecha: str,
    store: StoreWriter,
    source_format: str | None = None,
    page_count: int | None = None,
    text_extractor: TextExtractor | None = None,
    geometry: GeometryProvider | None = None,
    manifest: Manifest | None = None,
) -> tuple[IngestResult, WriteOutcome]:
    """Produce la unidad en memoria y la persiste con la secuencia T1/T2/T3 de `D-25`."""
    resultado = ingest_in_memory(
        pdf_path,
        document_id,
        text_extractor=text_extractor,
        geometry=geometry,
        manifest=manifest,
    )
    unit = UnitWrite(
        document_id=document_id,
        alias=alias,
        fecha=fecha,
        fragments=tuple(resultado.fragments),
        trace=resultado.trace,
        source_format=source_format,
        page_count=page_count,
    )
    return resultado, persist_unit(unit, store=store)
