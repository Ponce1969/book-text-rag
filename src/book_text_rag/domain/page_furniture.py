"""Exclusión del mobiliario de página (D-18 §3, D-20 §I5).

Regla: se excluye del contenido la **última línea de texto** de una página cuando, ya recortada,
satisface `^\\d{1,4}$` y su valor es `pdf_page - 1` (la numeración impresa equivale a `pdf_page - 1`
según D-01). Si la última línea es un número **distinto**, se **conserva** y se registra como
anomalía: nunca se descarta en silencio.
"""

from __future__ import annotations

import re

from pydantic import BaseModel

_PAGE_NUMBER = re.compile(r"^\d{1,4}$")


class PageFurnitureResult(BaseModel):
    """Resultado de aplicar la regla de mobiliario a una página."""

    lines: list[str]
    excluded: bool = False
    excluded_value: int | None = None
    anomaly: bool = False


def strip_page_number(lines: list[str], pdf_page: int) -> PageFurnitureResult:
    """Devuelve las líneas sin el número impreso de página, y si hubo exclusión o anomalía."""
    last = -1
    for index in range(len(lines) - 1, -1, -1):
        if lines[index].strip():
            last = index
            break
    if last < 0:
        return PageFurnitureResult(lines=list(lines))

    candidate = lines[last].strip()
    if not _PAGE_NUMBER.match(candidate):
        return PageFurnitureResult(lines=list(lines))

    value = int(candidate)
    expected = pdf_page - 1
    if value == expected:
        return PageFurnitureResult(
            lines=[*lines[:last], *lines[last + 1 :]],
            excluded=True,
            excluded_value=value,
        )
    return PageFurnitureResult(lines=list(lines), anomaly=True, excluded_value=value)
