"""Anclaje del encabezado, calibración documental y alineación con el texto (D-17 §2-§5, D-20 §4).

El anclaje se **decide** con tipografía y geometría (la herramienta autorizada para outline,
tipografía y coordenadas) y se **alinea** con el texto del extractor aprobado: la decisión del
corte es geométrica; la alineación sólo ubica esa misma línea en el flujo de texto de D-19.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Callable, Sequence
from statistics import median

from book_text_rag.domain.models import (
    AnchorEvidence,
    AnchorLevel,
    CalibrationPlan,
    CalibrationRecord,
    DestinationUse,
    ErrorCode,
    IngestError,
    Line,
)

BOLD_MARKER = "Bold"
MAX_BLOCK_LINES = 4
MAX_BLOCK_CHARS = 300
MIN_TOLERANCE_PT = 2.0
TOLERANCE_FACTOR = 1.5
TOP_BAND_PT = 200.0
SIZE_FACTOR = 0.95
MIN_CALIBRATION_ENTRIES = 20
MAX_DISPERSION_PT = 3.0
PREFIX_WORDS = 4
_USABLE_Y = 0.5
CORE_WINDOW_PT = 2.0
MIN_CORE_FRACTION = 2.0 / 3.0
MAX_DESTINATION_OFFSET_PT = 120.0
MIN_PREFIX_WORDS = 4
SCALE_RESIDUAL_PT = 1.0

_WS = re.compile(r"\s+")
_SOFT_HYPHEN = "\u00ad"
_ORDINAL = re.compile(r"^(?:chapter|cap[ií]tulo)\s+\d+[.:]?\s*", re.IGNORECASE)
_NUMERIC_ORDINAL = re.compile(r"^\d+[.:]?\s*")
_PART_WORD_PREFIX = re.compile(r"^part\s+([ivxlcdm]+|\d+)\s*[.:\-\u2013\u2014]\s*", re.IGNORECASE)
_PART_BARE_PREFIX = re.compile(r"^([IVXLCDM]{1,7}|\d{1,2})\s*[.:]\s+")
_PART_SUFFIX = re.compile(r"\s*\(\s*(?:part\s+)?([ivxlcdm]+|\d+)\s*\)\s*$", re.IGNORECASE)
_CANONICAL_ROMAN = re.compile(r"^M{0,3}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})$")
_ROMAN_VALUES = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
_MAX_BARE_PART = 20
_MAX_DECLARED_PART = 99


def norm(text: str) -> str:
    """Colapsa espacios, une guiones de corte y elimina el guion suave (D-17 §2.3)."""
    cleaned = text.replace(_SOFT_HYPHEN, "")
    cleaned = re.sub(r"-\s*\n\s*", "", cleaned)
    cleaned = cleaned.replace("-\n", "").replace("\n", " ")
    return _WS.sub(" ", cleaned).strip()


def _roman_value(numeral: str) -> int | None:
    """Valor de un numeral romano canónico; `None` si la forma no es canónica."""
    if not _CANONICAL_ROMAN.match(numeral):
        return None
    total = 0
    previous = 0
    for char in reversed(numeral):
        current = _ROMAN_VALUES[char]
        total += -current if current < previous else current
        previous = max(previous, current)
    return total


def _part_number(token: str, maximum: int) -> int | None:
    """Número de parte admitido: dígitos o romano canónico dentro del rango declarado."""
    if token.isdigit():
        value = int(token)
        return value if 1 <= value <= maximum else None
    roman = _roman_value(token.upper())
    if roman is None or not 1 <= roman <= maximum:
        return None
    return roman


def _declared_part(text: str) -> tuple[int | None, str]:
    """Separa una marca de parte declarada del resto del texto (D-17 §2.3).

    Solo reconoce las formas declaradas: `Part <n>.` o `<ROMANO>.` al inicio y `(Part <n>)` o
    `(<n>)` al final. No toca marcas en el medio, romanos no canónicos ni valores fuera de rango.
    Si el texto declara dos marcas contradictorias, no se normaliza.
    """
    value = norm(text)
    parts: list[int] = []
    match = _PART_WORD_PREFIX.match(value)
    if match is not None:
        part_word = _part_number(match.group(1), _MAX_DECLARED_PART)
        if part_word is not None:
            parts.append(part_word)
            value = value[match.end() :].strip()
    else:
        match = _PART_BARE_PREFIX.match(value)
        if match is not None:
            part_bare = _part_number(match.group(1), _MAX_BARE_PART)
            if part_bare is not None:
                parts.append(part_bare)
                value = value[match.end() :].strip()
    match = _PART_SUFFIX.search(value)
    if match is not None:
        part_suffix = _part_number(match.group(1), _MAX_DECLARED_PART)
        if part_suffix is not None:
            parts.append(part_suffix)
            value = value[: match.start()].strip()
    if len(set(parts)) > 1:
        return None, norm(text)
    return (parts[0] if parts else None), value


def core_title(title: str) -> str:
    """Título sin su forma ordinal, para comparar `N.` con `Chapter N.` (D-17 §2.3)."""
    value = norm(title)
    value = _ORDINAL.sub("", value)
    return _NUMERIC_ORDINAL.sub("", value).strip()


def _canonical_heading(text: str) -> tuple[int | None, str]:
    """Marca de parte y contenido restante, en la forma canónica de comparación."""
    part, rest = _declared_part(text)
    return part, core_title(rest)


def _variants(text: str) -> set[str]:
    base = norm(text).lower()
    return {
        base,
        base.replace("- ", ""),
        base.replace("-", ""),
        base.replace("-", " "),
        base.replace("- ", "-"),
    }


def covers(block_text: str, title: str) -> bool:
    """Cobertura del título: el bloque contiene el título, o sus primeras 4 palabras (D-17 §2.2).

    Las variantes editoriales declaradas en D-17 §2.3 se resuelven en ambos lados: marca de parte
    (`Part I.` / `I.` / `(Part I)`) y guion de corte. Si ambos lados declaran número de parte, deben
    coincidir; si no, no hay emparejamiento.
    """
    block_part, block_core = _canonical_heading(block_text)
    title_part, title_core = _canonical_heading(title)
    if block_part is not None and title_part is not None and block_part != title_part:
        return False
    core = title_core.lower()
    if not core:
        return False
    prefix = " ".join(core.split()[:PREFIX_WORDS])
    for variant in _variants(block_core):
        if core in variant:
            return True
        if prefix and prefix in variant:
            return True
    return False


def _strong_heading_match(block_text: str, title: str) -> bool:
    """Igualdad canónica o prefijo palabra a palabra con al menos `MIN_PREFIX_WORDS` palabras.

    La marca de parte debe coincidir cuando ambos lados la declaran. Un prefijo de cuatro palabras
    que diverge después no se acepta, y el prefijo debe terminar en un límite de palabra.
    """
    title_part, title_core = _canonical_heading(title)
    block_part, block_core = _canonical_heading(block_text)
    if title_part is not None and block_part is not None and title_part != block_part:
        return False
    izquierda = title_core.casefold()
    derecha = block_core.casefold()
    if not izquierda or not derecha:
        return False
    if izquierda == derecha:
        return True
    corto, largo = (izquierda, derecha) if len(izquierda.split()) <= len(derecha.split()) else (derecha, izquierda)
    if len(corto.split()) < MIN_PREFIX_WORDS or not largo.startswith(corto):
        return False
    return largo[len(corto) : len(corto) + 1].isspace()


def _local_window_block(
    candidates: Sequence[list[Line]],
    title: str,
    declared_y_dest: float | None,
    previous_y0: float | None,
) -> list[Line] | None:
    """Candidato único de la ventana local para un destino inutilizable (Incremento C).

    Exige `y0 <= y_dest`, `y_dest - y0 <= MAX_DESTINATION_OFFSET_PT` y, cuando existe una unidad
    anterior anclada en la misma página, orden estricto `y0 > previous_y0`. Cualquier ambigüedad
    o incumplimiento devuelve `None`: no se elige un bloque "más probable".
    """
    if declared_y_dest is None:
        return None
    validos: list[list[Line]] = []
    for block in candidates:
        if not _strong_heading_match(" ".join(line.text for line in block), title):
            continue
        y0 = block[0].y0
        if y0 > declared_y_dest:
            continue
        if declared_y_dest - y0 > MAX_DESTINATION_OFFSET_PT:
            continue
        if previous_y0 is not None and y0 <= previous_y0:
            continue
        validos.append(block)
    return validos[0] if len(validos) == 1 else None


def bold_runs(lines: Sequence[Line]) -> list[list[Line]]:
    """Runs maximales de líneas consecutivas en negrita (adyacencia vertical, D-17 §2.1)."""
    runs: list[list[Line]] = []
    current: list[Line] = []
    for line in lines:
        if line.bold:
            if current and (line.y0 - current[-1].y0) <= 1.7 * current[-1].size:
                current.append(line)
            else:
                if current:
                    runs.append(current)
                current = [line]
        elif current:
            runs.append(current)
            current = []
    if current:
        runs.append(current)
    return runs


def _block_lines(run: Sequence[Line], title: str) -> list[Line]:
    """Acumula el run hasta cubrir el título, con los topes de 4 líneas y 300 caracteres (D-17 §2.1)."""
    accumulated: list[Line] = []
    text = ""
    for line in run[:MAX_BLOCK_LINES]:
        accumulated.append(line)
        text = f"{text} {line.text}".strip()
        if len(text) > MAX_BLOCK_CHARS:
            return []
        if covers(text, title):
            return accumulated
    return []


def heading_block(lines: Sequence[Line], title: str, size_min: float | None) -> tuple[list[Line] | None, str]:
    """Bloque de encabezado que cubre el título.

    Devuelve `(bloque, "texto_coincide")` si lo encuentra; `(primer_bloque, "texto_no_coincide")`
    si hay bloques pero ninguno cubre el título; `(None, "sin_bloque")` si no hay ninguno.
    """
    fallback: list[Line] | None = None
    for run in bold_runs(lines):
        if size_min is not None and max(line.size for line in run) < size_min:
            continue
        if fallback is None:
            fallback = run
        block = _block_lines(run, title)
        if block:
            return block, "texto_coincide"
    if fallback is not None:
        return fallback, "texto_no_coincide"
    return None, "sin_bloque"


def body_size(lines: Sequence[Line]) -> float:
    """Tamaño de cuerpo modal de la página, ponderado por caracteres (líneas no negritas).

    Es el discriminador robusto: D-17 §4.1 deriva el umbral de los bloques de calibración, y el
    artefacto de escala del capítulo 3 reduce encabezado y cuerpo por el **mismo** factor
    (19,37/15 = 1,29 y 16,9/13,06 = 1,29), así que la razón encabezado/cuerpo se conserva aunque el
    tamaño absoluto no.
    """
    counts: dict[float, int] = {}
    for line in lines:
        if not line.bold:
            counts[line.size] = counts.get(line.size, 0) + len(line.text)
    if not counts:
        return 0.0
    return max(counts.items(), key=lambda item: item[1])[0]


def size_threshold(lines: Sequence[Line], calibration: CalibrationRecord) -> float:
    """Umbral de tamaño vigente para una página: razón x cuerpo, con el absoluto como respaldo."""
    body = body_size(lines)
    if body > 0 and calibration.heading_min_ratio > 0:
        return body * calibration.heading_min_ratio
    return calibration.heading_min_size_pt


def candidate_blocks(lines: Sequence[Line], title: str, size_min: float | None) -> list[list[Line]]:
    """Todos los bloques en negrita (con tamaño suficiente) que cubren el título (D-17 §2).

    El desempate entre varios candidatos es de D-17 §2.4: por nivel, el de `y` más próximo al
    destino. Devolverlos todos permite aplicarlo tanto al anclaje como a la calibración.
    """
    found: list[list[Line]] = []
    for run in bold_runs(lines):
        if size_min is not None and max(line.size for line in run) < size_min:
            continue
        block = _block_lines(run, title)
        if block:
            found.append(block)
    return found


def _key(page: int, title: str) -> str:
    """Clave de una entrada del outline para las decisiones de calibración."""
    return f"{page}|{title}"


def calibrate(
    entries: Sequence[tuple[str, int, float]],
    lines_for_page: Callable[[int], Sequence[Line]],
) -> CalibrationPlan:
    """Calibración documental determinista con detección del artefacto de escala (D-17 §4).

    (1) Por cada entrada con destino utilizable se elige el bloque **más próximo al destino**
    (D-17 §2.4) y se mide `Δ = y0 - y_dest`. (2) La calibración se acepta por la **moda dominante**
    (ventana declarada de ±2 pt alrededor de la mediana, con al menos 20 entradas y dos tercios del
    total, y dispersión propia ≤ 3 pt). (3) Las entradas fuera de la moda se contrastan contra un
    **factor de escala único** —artefacto de conversión del PDF—: si ese factor las explica con
    residuo ≤ 1 pt, se corrigen y se **registran** como anomalía del outline; si no, su destino queda
    inutilizable y la unidad se ancla por página y tipografía. Nada se compensa en silencio.
    """
    usable = [(title, page, y_dest) for title, page, y_dest in entries if y_dest > _USABLE_Y]
    if not usable:
        raise IngestError(ErrorCode.OUTLINE_UNAVAILABLE, "no hay entradas de outline con destino utilizable")

    measured: dict[str, tuple[float, float, float, float]] = {}
    ratios: dict[str, float] = {}
    for title, page, y_dest in usable:
        lines = lines_for_page(page)
        candidates = candidate_blocks(lines, title, size_min=None)
        if not candidates:
            continue
        chosen = min(candidates, key=lambda block: abs(block[0].y0 - y_dest))
        measured[_key(page, title)] = (
            chosen[0].y0 - y_dest,
            chosen[0].y0,
            y_dest,
            max(line.size for line in chosen),
        )
        body = body_size(lines)
        if body > 0:
            ratios[_key(page, title)] = max(line.size for line in chosen) / body

    if len(measured) < MIN_CALIBRATION_ENTRIES:
        raise IngestError(
            ErrorCode.CALIBRATION_FAILED,
            "entradas de calibración insuficientes",
            entradas=len(measured),
            minimo=MIN_CALIBRATION_ENTRIES,
        )

    mode = float(median([value[0] for value in measured.values()]))
    core = {key for key, value in measured.items() if abs(value[0] - mode) <= CORE_WINDOW_PT}
    required = max(MIN_CALIBRATION_ENTRIES, math.ceil(MIN_CORE_FRACTION * len(measured)))
    if len(core) < required:
        raise IngestError(
            ErrorCode.CALIBRATION_FAILED,
            "la moda de la calibración no alcanza el mínimo exigido",
            nucleo=len(core),
            exigido=required,
            total=len(measured),
        )

    core_deltas = [measured[key][0] for key in core]
    dispersion = float(max(core_deltas) - min(core_deltas))
    if dispersion > MAX_DISPERSION_PT:
        raise IngestError(
            ErrorCode.CALIBRATION_FAILED,
            "dispersión de la calibración fuera de umbral",
            dispersion_pt=round(dispersion, 3),
            tope_pt=MAX_DISPERSION_PT,
        )

    decisions = {key: DestinationUse.VALID for key in core}
    corrected: dict[str, float] = {}
    factor: float | None = None
    residual: float | None = None
    outliers = [key for key in measured if key not in core]
    if outliers:
        bases = [measured[key][1] - mode for key in outliers]
        if all(base > 0 for base in bases):
            candidate = float(median([measured[key][2] / base for key, base in zip(outliers, bases, strict=True)]))
            residuals = [abs(base * candidate - measured[key][2]) for key, base in zip(outliers, bases, strict=True)]
            if candidate > 0 and max(residuals) <= SCALE_RESIDUAL_PT:
                factor = round(candidate, 6)
                residual = round(max(residuals), 3)
                for key in outliers:
                    decisions[key] = DestinationUse.SCALE_CORRECTED
                    corrected[key] = round(measured[key][2] / candidate, 3)
        for key in outliers:
            if decisions.get(key) is not DestinationUse.SCALE_CORRECTED:
                decisions[key] = DestinationUse.UNUSABLE

    record = CalibrationRecord(
        procedure="anchoring/v1",
        entries=len(core),
        delta_pt=round(mode, 3),
        dispersion_pt=round(dispersion, 3),
        tolerance_pt=round(max(MIN_TOLERANCE_PT, TOLERANCE_FACTOR * dispersion), 3),
        top_band_pt=TOP_BAND_PT,
        heading_min_size_pt=round(SIZE_FACTOR * min(measured[key][3] for key in core), 3),
        heading_min_ratio=round(SIZE_FACTOR * min(ratios[key] for key in core if key in ratios), 3)
        if any(key in ratios for key in core)
        else 0.0,
        outline_scale_anomalies=len(corrected),
        outline_scale_factor=factor,
        outline_scale_residual_max_pt=residual,
        destinations_unusable=sum(1 for use in decisions.values() if use is DestinationUse.UNUSABLE),
    )
    return CalibrationPlan(record=record, decisions=decisions, corrected_y=corrected)


def _exact_heading_blocks(lines: Sequence[Line], title: str, size_min: float) -> list[list[Line]]:
    """Bloques que igualan canónicamente el título; sin la regla de prefijo (fallback de página)."""
    title_part, title_core = _canonical_heading(title)
    core = title_core.casefold()
    if not core:
        return []
    found: list[list[Line]] = []
    for block in candidate_blocks(lines, title, size_min):
        block_part, block_core = _canonical_heading(" ".join(line.text for line in block))
        if block_core.casefold() != core:
            continue
        if title_part is not None and block_part is not None and title_part != block_part:
            continue
        found.append(block)
    return found


def _anchor_on_next_page(
    lines: Sequence[Line] | None,
    title: str,
    page: int | None,
    size_min: float,
    calibration: CalibrationRecord,
) -> tuple[tuple[AnchorEvidence, AnchorLevel, list[Line]] | None, int]:
    """Fallback declarado: encabezado exacto y único en la página siguiente (Incremento B)."""
    if lines is None or page is None:
        return None, 0
    blocks = _exact_heading_blocks(lines, title, size_min)
    if len(blocks) != 1:
        return None, len(blocks)
    block = blocks[0]
    if block[0].y0 > calibration.top_band_pt:
        return None, len(blocks)
    evidence = AnchorEvidence(
        page=page,
        y0=round(block[0].y0, 3),
        y_dest=None,
        destination_use=DestinationUse.UNUSABLE,
    )
    return (evidence, AnchorLevel.PAGE_TYPOGRAPHY, block), len(blocks)


def anchor(
    lines: Sequence[Line],
    title: str,
    page: int,
    y_dest: float | None,
    destination_use: DestinationUse,
    calibration: CalibrationRecord,
    *,
    next_page: int | None = None,
    next_lines: Sequence[Line] | None = None,
    declared_y_dest: float | None = None,
    previous_y0: float | None = None,
) -> tuple[AnchorEvidence, AnchorLevel, list[Line]]:
    """Ancla la unidad y devuelve `(evidencia, nivel, bloque)`; falla si no puede (D-17 §5).

    El bloque se devuelve para poder alinear su primera línea con el texto del extractor aprobado.
    Si la página declarada no tiene candidato, se admite el fallback declarado de **una** página:
    encabezado canónicamente exacto, único y dentro de la banda superior (Incremento B). Si el
    destino es inutilizable y el candidato queda fuera de la banda, se admite la ventana local
    estricta del Incremento C.
    """
    threshold = size_threshold(lines, calibration)
    candidates: list[tuple[list[Line], float]] = [
        (block, block[0].y0) for block in candidate_blocks(lines, title, threshold)
    ]

    if not candidates:
        fallback, exact_count = _anchor_on_next_page(next_lines, title, next_page, threshold, calibration)
        if fallback is not None:
            return fallback
        if next_page is None:
            raise IngestError(
                ErrorCode.UNIT_NOT_ANCHORED,
                "ningún bloque de encabezado cubre el título en la página declarada",
                pagina=page,
                titulo=title,
            )
        raise IngestError(
            ErrorCode.UNIT_NOT_ANCHORED,
            "ningún bloque de encabezado cubre el título en la página declarada",
            pagina=page,
            titulo=title,
            pagina_siguiente=next_page,
            candidatos_siguiente=exact_count,
        )

    usable_dest = y_dest if (y_dest is not None and y_dest > _USABLE_Y) else None
    if usable_dest is not None:
        chosen = min(candidates, key=lambda item: abs(item[1] - usable_dest))
        y0 = chosen[1]
        deviation = abs((y0 - usable_dest) - calibration.delta_pt)
        if deviation > calibration.tolerance_pt:
            raise IngestError(
                ErrorCode.UNIT_NOT_ANCHORED,
                "el bloque de encabezado no coincide con la posición calibrada",
                pagina=page,
                titulo=title,
                desvio_pt=round(deviation, 3),
                tolerancia_pt=calibration.tolerance_pt,
            )
        evidence = AnchorEvidence(page=page, y0=round(y0, 3), y_dest=usable_dest, destination_use=destination_use)
        return evidence, AnchorLevel.POSITIONAL, chosen[0]

    top = min(candidates, key=lambda item: item[1])
    if top[1] > calibration.top_band_pt:
        if destination_use is DestinationUse.UNUSABLE:
            window_block = _local_window_block([block for block, _ in candidates], title, declared_y_dest, previous_y0)
            if window_block is not None:
                evidence = AnchorEvidence(
                    page=page,
                    y0=round(window_block[0].y0, 3),
                    y_dest=None,
                    destination_use=DestinationUse.UNUSABLE,
                )
                return evidence, AnchorLevel.PAGE_TYPOGRAPHY, window_block
        raise IngestError(
            ErrorCode.UNIT_NOT_ANCHORED,
            "el bloque de encabezado queda fuera de la banda superior",
            pagina=page,
            titulo=title,
            y0=round(top[1], 3),
        )
    evidence = AnchorEvidence(page=page, y0=round(top[1], 3), y_dest=None, destination_use=destination_use)
    return evidence, AnchorLevel.PAGE_TYPOGRAPHY, top[0]


def _comparable(line_text: str) -> str:
    return _WS.sub(" ", unicodedata.normalize("NFC", line_text)).strip().lower()


def align_heading_index(text_lines: Sequence[str], block: Sequence[Line], min_index: int = 0) -> int:
    """Ubica la primera línea del bloque en el flujo de texto del extractor (D-19).

    La decisión del corte es geométrica (D-17); esta alineación sólo la traduce al texto extraído.
    `min_index` impone monotonía de orden de lectura: el encabezado de una unidad nunca puede quedar
    antes del de su predecesora. Se elige el primer candidato en o después de `min_index`; si el
    texto del encabezado no aparece en la página, la unidad queda sin anclar (nunca corte silencioso).
    """
    head = _comparable(block[0].text)
    candidates = [index for index, line in enumerate(text_lines) if index >= min_index and _comparable(line) == head]
    if not candidates:
        prefix = " ".join(head.split()[:PREFIX_WORDS])
        if prefix:
            candidates = [
                index
                for index, line in enumerate(text_lines)
                if index >= min_index and _comparable(line).startswith(prefix)
            ]
    if not candidates:
        raise IngestError(
            ErrorCode.UNIT_NOT_ANCHORED,
            "no se pudo alinear el encabezado con el texto extraído",
            linea=block[0].text,
        )
    return candidates[0]
