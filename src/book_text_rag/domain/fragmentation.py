"""Fragmentación estructural en memoria (D-05 ptos. 1-8, D-18 §2-§4, D-20 §4).

El contenido de una unidad va **desde la primera línea de su bloque de encabezado hasta la primera
línea del bloque de encabezado de su sucesora** (D-18 §2.1): la cola previa queda, por construcción,
dentro del predecesor y se incluye **una sola vez** (D-18 §2.2). Se corta por párrafo dentro de la
unidad, con el tope `max_words` como umbral de desborde; los bloques de tabla son **atómicos** y se
emiten como fragmentos propios etiquetados (D-05 pto. 5).
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from pydantic import BaseModel

from book_text_rag.domain.manifest import CORPUS_END, CORPUS_START, Manifest
from book_text_rag.domain.models import BlockType, Counts, OutlineUnit, TocEntry, UnitKind

CAPTION_RE = re.compile(r"^(?:Figure|Table)\s+\d+-\d+\.", re.MULTILINE)


class UnitSpan(BaseModel):
    """Tramo de texto de una unidad: página e índice de línea del encabezado, y su fin exclusivo."""

    unit: OutlineUnit
    start_page: int
    start_index: int
    end_page: int
    end_index: int


class AnchoredUnit(BaseModel):
    """Unidad ya anclada: índice de texto del encabezado y página real donde se encontró."""

    unit: OutlineUnit
    text_index: int
    page: int


class FragmentDraft(BaseModel):
    """Borrador de fragmento antes de agregarle identidad y hashes (D-20 §3.1)."""

    section_path: list[str]
    level: int
    block_type: BlockType
    captions: list[str]
    pdf_page_start: int
    pdf_page_end: int
    content: str
    word_count: int


def is_table_block(block: Sequence[str]) -> bool:
    """Un bloque es de tabla cuando su primera línea es un rótulo `Figure|Table N-M.` (D-05 pto. 5)."""
    for line in block:
        if line.strip():
            return bool(CAPTION_RE.match(line.strip()))
    return False


def caption_lines(block: Sequence[str]) -> list[str]:
    """Líneas de rótulo del bloque (habitualmente una), para etiquetar el fragmento de tabla."""
    captions: list[str] = []
    for line in block:
        if CAPTION_RE.match(line.strip()):
            captions.append(line.strip())
        elif captions:
            break
    return captions


def blocks_of(lines: Sequence[str]) -> list[list[str]]:
    """Bloques separados por línea en blanco (D-05 «hallazgos»: bloques = párrafos/estructuras)."""
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if line.strip():
            current.append(line)
        elif current:
            blocks.append(current)
            current = []
    if current:
        blocks.append(current)
    return blocks


def build_units(toc: Sequence[TocEntry]) -> list[OutlineUnit]:
    """Unidades del corpus a partir del outline (D-05 pto. 1; corpus = páginas 25-716 de D-01).

    La hoja más profunda disponible es la unidad; una entrada con hijos aporta su texto propio como
    fragmento propio (`parent_own`, D-05 pto. 4).
    """
    units: list[OutlineUnit] = []
    stack: list[TocEntry] = []
    for index, entry in enumerate(toc):
        stack = [item for item in stack if item.level < entry.level]
        path = [item.title for item in stack] + [entry.title]
        stack.append(entry)
        if entry.page < CORPUS_START or entry.page > CORPUS_END:
            continue
        has_child = index + 1 < len(toc) and toc[index + 1].level > entry.level
        units.append(
            OutlineUnit(
                title=entry.title,
                level=entry.level,
                page=entry.page,
                section_path=path,
                kind=UnitKind.PARENT_OWN if has_child else UnitKind.LEAF,
                ordinal=len(units) + 1,
                y_dest=entry.y_dest,
            )
        )
    return units


def successor_page(toc: Sequence[TocEntry], unit: OutlineUnit) -> int:
    """Página de la sucesora en el outline (D-18 §2.1): la próxima entrada del libro tras la unidad."""
    for index, entry in enumerate(toc):
        if entry.page == unit.page and entry.title == unit.title:
            nexts = [item for item in toc[index + 1 :] if item.page >= entry.page]
            if nexts:
                return nexts[0].page
            return CORPUS_END
    return CORPUS_END


def unit_spans(
    toc: Sequence[TocEntry],
    anchored: Sequence[AnchoredUnit],
    lines_per_page: Sequence[Sequence[str]],
) -> list[UnitSpan]:
    """Tramos de contenido por unidad, acotados al corpus (nunca más allá de la página 716)."""
    spans: list[UnitSpan] = []
    for position, item in enumerate(anchored):
        unit = item.unit
        if position + 1 < len(anchored):
            following = anchored[position + 1]
            end_page = following.page
            end_index = following.text_index
        else:
            end_page = min(successor_page(toc, unit), CORPUS_END)
            end_index = len(lines_per_page[end_page - 1]) if end_page <= len(lines_per_page) else 0
        if end_page > CORPUS_END or end_page > len(lines_per_page):
            end_page = min(CORPUS_END, len(lines_per_page))
            end_index = len(lines_per_page[end_page - 1])
        if end_page == item.page and end_index < item.text_index:
            raise AssertionError("el fin de la unidad precede a su encabezado")
        spans.append(
            UnitSpan(
                unit=unit,
                start_page=item.page,
                start_index=item.text_index,
                end_page=end_page,
                end_index=end_index,
            )
        )
    return spans


def _content_lines(span: UnitSpan, lines_per_page: Sequence[Sequence[str]]) -> list[tuple[int, str]]:
    """Líneas del tramo con los límites absolutos de cada página (Incremento D).

    `start_index` y `end_index` son índices absolutos de su página. En un tramo de una sola página
    se aplican en un solo corte; en varias páginas, el inicio solo afecta a la primera y el fin solo
    a la última.
    """
    collected: list[tuple[int, str]] = []
    for page in range(span.start_page, span.end_page + 1):
        lines = list(lines_per_page[page - 1])
        start = span.start_index if page == span.start_page else 0
        end = span.end_index if page == span.end_page else len(lines)
        collected.extend((page, line) for line in lines[start:end])
    return collected


def blocks_with_pages(
    collected: Sequence[tuple[int, str]],
) -> list[tuple[list[tuple[int, str]], int, int]]:
    """Bloques (párrafos) de un tramo, con la página inicial y final de cada bloque."""
    blocks: list[tuple[list[tuple[int, str]], int, int]] = []
    current: list[tuple[int, str]] = []
    for page, line in collected:
        if line.strip():
            current.append((page, line))
        elif current:
            blocks.append((current, current[0][0], current[-1][0]))
            current = []
    if current:
        blocks.append((current, current[0][0], current[-1][0]))
    return blocks


def fragment_span(
    span: UnitSpan,
    lines_per_page: Sequence[Sequence[str]],
    manifest: Manifest,
) -> list[FragmentDraft]:
    """Fragmenta el tramo de una unidad: prosa acumulada por bloques y tablas atómicas propias."""
    collected = _content_lines(span, lines_per_page)
    fragments: list[FragmentDraft] = []
    buffer: list[tuple[int, str]] = []

    def flush() -> None:
        if not buffer:
            return
        content = "\n".join(line for _, line in buffer).strip("\n")
        if content.strip():
            fragments.append(
                FragmentDraft(
                    section_path=list(span.unit.section_path),
                    level=span.unit.level,
                    block_type=BlockType.PROSE,
                    captions=[],
                    pdf_page_start=buffer[0][0],
                    pdf_page_end=buffer[-1][0],
                    content=content,
                    word_count=len(content.split()),
                )
            )
        buffer.clear()

    for rows, page_start, page_end in blocks_with_pages(collected):
        lines = [line for _, line in rows]
        words = sum(len(line.split()) for line in lines)
        if is_table_block(lines):
            flush()
            content = "\n".join(lines).strip("\n")
            fragments.append(
                FragmentDraft(
                    section_path=list(span.unit.section_path),
                    level=span.unit.level,
                    block_type=BlockType.TABLE,
                    captions=caption_lines(lines),
                    pdf_page_start=page_start,
                    pdf_page_end=page_end,
                    content=content,
                    word_count=len(content.split()),
                )
            )
            continue
        buffered_words = sum(len(line.split()) for _, line in buffer)
        if buffer and buffered_words + words > manifest.max_words:
            flush()
        buffer.extend(rows)
    flush()
    return fragments


def tail_metrics(
    anchored: Sequence[AnchoredUnit],
    lines_per_page: Sequence[Sequence[str]],
) -> tuple[int, int, int, int]:
    """Métricas de la cola previa (D-18 §2.2 y §5; D-20 §7.3).

    Devuelve `(palabras_totales_en_colas, palabras_en_colas_cuyo_predecesor_arranca_en_la_misma_pagina,
    unidades_con_cola, bloques_con_rotulo_en_colas)`. La cola de una unidad son las líneas por encima
    de su encabezado en su **página real de anclaje**; el recuento de bloques con rótulo usa la misma
    definición que los Experimentos 2 y 3, para que la cifra sea comparable.
    """
    total = 0
    same_page = 0
    with_tail = 0
    caption_blocks = 0
    for position, item in enumerate(anchored):
        above = lines_per_page[item.page - 1][: item.text_index]
        words = sum(len(line.split()) for line in above)
        caption_blocks += sum(1 for block in blocks_of(above) if is_table_block(block))
        if words <= 0:
            continue
        with_tail += 1
        total += words
        if position > 0 and anchored[position - 1].page == item.page:
            same_page += words
    return total, same_page, with_tail, caption_blocks


def counts_of(
    units: Sequence[OutlineUnit],
    anchored_by_level: dict[str, int],
    fragments: Sequence[FragmentDraft],
    excluded_lines: int,
    paginas_anomalas: Sequence[int],
    tails: tuple[int, int, int, int],
) -> Counts:
    """Recuentos de la traza (D-20 §3.2) más las dos métricas de cola que exige D-20 §7.3.

    El recuento de anomalías se **deriva** de la lista de páginas (`D-23`): así el recuento y el arreglo
    no pueden divergir al construir la traza.
    """
    return Counts(
        corpus_units=len(units),
        anchored_by_level=dict(anchored_by_level),
        fragments=len(fragments),
        table_blocks=sum(1 for fragment in fragments if fragment.block_type is BlockType.TABLE),
        page_number_lines_excluded=excluded_lines,
        page_number_anomalies=len(paginas_anomalas),
        paginas_anomalas=list(paginas_anomalas),
        tail_words_total=tails[0],
        tail_words_predecessor_same_page=tails[1],
        tail_blocks_with_caption=tails[3],
    )
