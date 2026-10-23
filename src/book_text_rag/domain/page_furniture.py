"""Exclusión del mobiliario de página (D-18 §3, D-20 §I5).

Dos reglas, ambas deterministas y verificables por separado.

1. **Número al pie (D-18 §3.1, sin cambios).** Se excluye la **última línea de texto** de una página
   cuando, ya recortada, satisface `^\\d{1,4}$` y su valor es `pdf_page - 1`. Si el número es
   **distinto**, la línea se **conserva** y la página se registra como anomalía: nunca se descarta en
   silencio.

2. **Cabecera corrida (libros cuya numeración impresa no es `pdf_page - 1`).** Se excluye la
   **primera línea de texto** de una página cuando esa línea está compuesta **exactamente** por los
   textos de una banda de cabecera ya validada. La banda se valida con evidencia geométrica y
   aritmética, nunca por palabras:

   - el **primer renglón** de la página, en la misma coordenada `y0` (±1 pt) de forma repetida;
   - su texto es un número que forma una **secuencia de ±1 con la página** durante al menos tres
     páginas consecutivas: un desplazamiento constante entre la página física y la impresa;
   - la banda reúne todas las líneas de la página que comparten ese `y0`, es decir el rótulo
     corrido y el número impreso.

   Sin secuencia demostrada no hay banda, y sin banda no se excluye nada. Si la página tiene banda
   pero su primera línea de texto no está compuesta exactamente por los textos de la banda, la línea
   se **conserva** y la página se registra como anomalía.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from pydantic import BaseModel, Field

from book_text_rag.domain.anchor import norm
from book_text_rag.domain.models import Line

_PAGE_NUMBER = re.compile(r"^\d{1,4}$")

HEADER_SEQUENCE_MIN_PAGES = 3
BAND_TOLERANCE_PT = 1.0


class PageFurnitureResult(BaseModel):
    """Resultado de aplicar una regla de mobiliario a una página."""

    lines: list[str]
    excluded: bool = False
    excluded_value: int | None = None
    anomaly: bool = False


class HeaderBand(BaseModel):
    """Banda de cabecera validada: `y0` compartido, textos que la componen y número impreso."""

    y0: float
    texts: list[str]
    printed: int


class HeaderFurniture(BaseModel):
    """Bandas de cabecera validadas por página (1-based)."""

    bands: dict[int, HeaderBand] = Field(default_factory=dict)


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


def _top_row(lines: Sequence[Line]) -> list[Line]:
    """Renglón superior de la página: las líneas que comparten la menor `y0` (± tolerancia)."""
    tops = [line for line in lines if line.text.strip()]
    if not tops:
        return []
    first_y = min(line.y0 for line in tops)
    return [line for line in tops if line.y0 - first_y <= BAND_TOLERANCE_PT]


def _printed_numbers(geometry: Mapping[int, Sequence[Line]]) -> dict[int, tuple[float, int]]:
    """Páginas cuyo renglón superior contiene un número impreso, con su `y0` y su valor.

    El número puede ir antes o después del rótulo corrido según la página sea par o impar: se busca
    **en todo el renglón**, no en la primera línea.
    """
    found: dict[int, tuple[float, int]] = {}
    for page in sorted(geometry):
        row = _top_row(geometry[page])
        for line in row:
            text = line.text.strip()
            if _PAGE_NUMBER.match(text):
                found[page] = (min(item.y0 for item in row), int(text))
                break
    return found


def detect_header_furniture(geometry: Mapping[int, Sequence[Line]]) -> HeaderFurniture:
    """Bandas de cabecera validadas por secuencia aritmética y repetición de `y0` (`D-18` §3).

    La evidencia es doble: el valor numérico crece **exactamente** 1 por página y la coordenada `y0`
    se mantiene. Una corrida de menos de tres páginas consecutivas no basta y no produce banda.
    """
    candidates = _printed_numbers(geometry)
    pages = sorted(candidates)
    validated: dict[int, tuple[float, int]] = {}

    run: list[int] = []
    for page in pages:
        if run:
            previous = run[-1]
            prev_y0, prev_value = candidates[previous]
            y0, value = candidates[page]
            if page == previous + 1 and value == prev_value + 1 and abs(y0 - prev_y0) <= BAND_TOLERANCE_PT:
                run.append(page)
                continue
            if len(run) >= HEADER_SEQUENCE_MIN_PAGES:
                validated.update({item: candidates[item] for item in run})
        run = [page]
    if len(run) >= HEADER_SEQUENCE_MIN_PAGES:
        validated.update({item: candidates[item] for item in run})

    bands: dict[int, HeaderBand] = {}
    for page, (y0, printed) in validated.items():
        texts = [line.text.strip() for line in geometry[page] if abs(line.y0 - y0) <= BAND_TOLERANCE_PT]
        bands[page] = HeaderBand(y0=y0, texts=[text for text in texts if text], printed=printed)
    return HeaderFurniture(bands=bands)


def _tokens(text: str) -> list[str]:
    """Palabras normalizadas, sin depender del relleno de alineación del extractor."""
    return norm(text).split()


def _band_runs(tokens: list[str], band_texts: list[str]) -> list[tuple[int, int]] | None:
    """Posiciones de cada texto de la banda dentro de la línea, o `None` si no son únicas.

    Cada texto de la banda debe aparecer **una sola vez** como corrida contigua de palabras. Si
    aparece más de una vez, no hay forma de saber cuál es el mobiliario y se devuelve `None`.
    """
    spans: list[tuple[int, int]] = []
    for text in band_texts:
        wanted = _tokens(text)
        size = len(wanted)
        hits = [i for i in range(len(tokens) - size + 1) if tokens[i : i + size] == wanted]
        if len(hits) != 1:
            return None
        spans.append((hits[0], hits[0] + size))
    return sorted(spans)


def strip_header_line(lines: list[str], pdf_page: int, furniture: HeaderFurniture) -> PageFurnitureResult:
    """Excluye el mobiliario de la cabecera de la primera línea de texto de la página.

    Tres desenlaces, todos explícitos:

    1. la línea está compuesta **solo** por la banda -> se elimina;
    2. la línea **contiene** cada texto de la banda exactamente una vez, junto a contenido del
       cuerpo -> se quitan solo esas palabras y el resto se conserva;
    3. cualquier otra cosa -> la línea se **conserva íntegra** y la página se registra como anomalía.
    """
    band = furniture.bands.get(pdf_page)
    if band is None:
        return PageFurnitureResult(lines=list(lines))

    first = -1
    for index, line in enumerate(lines):
        if line.strip():
            first = index
            break
    if first < 0:
        return PageFurnitureResult(lines=list(lines), anomaly=True)

    tokens = _tokens(lines[first])
    band_texts = [text for text in band.texts if text.strip()]
    expected = sorted(token for text in band_texts for token in _tokens(text))
    if sorted(tokens) == expected:
        return PageFurnitureResult(
            lines=[*lines[:first], *lines[first + 1 :]],
            excluded=True,
            excluded_value=band.printed,
        )

    spans = _band_runs(tokens, band_texts)
    if spans is None:
        return PageFurnitureResult(lines=list(lines), anomaly=True, excluded_value=band.printed)
    eliminados = {position for start, end in spans for position in range(start, end)}
    resto = [token for position, token in enumerate(tokens) if position not in eliminados]
    if not resto:
        return PageFurnitureResult(
            lines=[*lines[:first], *lines[first + 1 :]],
            excluded=True,
            excluded_value=band.printed,
        )
    return PageFurnitureResult(
        lines=[*lines[:first], " ".join(resto), *lines[first + 1 :]],
        excluded=True,
        excluded_value=band.printed,
    )
