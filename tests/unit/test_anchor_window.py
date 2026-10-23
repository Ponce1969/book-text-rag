"""Ventana local para destinos inutilizables por debajo de la banda superior (Incremento C).

Solo aplica cuando el destino es `UNUSABLE`, no hay candidato en la banda y existe una única
coincidencia fuerte: igualdad canónica o prefijo palabra a palabra de al menos cuatro palabras,
con `y0 <= y_dest`, distancia máxima de 120 pt y orden estricto respecto de la unidad anterior
anclada en la misma página.
"""

from __future__ import annotations

import pytest

from book_text_rag.domain.anchor import _local_window_block, _strong_heading_match
from book_text_rag.domain.models import Line


def _block(text: str, y0: float) -> list[Line]:
    return [Line(text=text, y0=y0, y1=y0 + 14.5, size=14.5, font="Fake-Bold", bold=True)]


@pytest.mark.parametrize(
    ("title", "block"),
    [
        ("Agents as Tools: A Powerful Pattern", "Agents as Tools: A Powerful Pattern"),
        (
            "The Prompt Bloat Crisis: When More Tools Mean Less Intelligence",
            "The Prompt Bloat Crisis: When More Tools Mean",
        ),
        ("Alpha Beta Gamma Delta", "Alpha Beta Gamma Delta Epsilon"),
        ("Summary", "Summary"),
    ],
)
def test_relacion_fuerte_acepta(title: str, block: str) -> None:
    assert _strong_heading_match(block, title)


@pytest.mark.parametrize(
    ("title", "block"),
    [
        ("Alpha Beta Gamma Delta One", "Alpha Beta Gamma Delta Two"),
        ("The Trust Problem: When Tools Game the System", "The Trust Problem: When Tools Game Everything"),
        ("Alpha Beta Gamma Delta", "Alpha Beta Gamma Deltas"),
        ("Summary", "Summary of the Chapter"),
        ("I. Foundations of Graph-Based Systems", "Part II. Foundations of Graph-Based Systems"),
        (
            "The Prompt Bloat Crisis: When More Tools Mean Less Intelligence",
            "The Prompt Bloat Crisis: When More Tools Cause Chaos",
        ),
    ],
)
def test_relacion_fuerte_rechaza_divergencias(title: str, block: str) -> None:
    assert not _strong_heading_match(block, title)


def test_ventana_limites_y_orden() -> None:
    title = "Agents as Tools: A Powerful Pattern"
    bloque = _block(title, 386.3)

    assert _local_window_block([bloque], title, 386.3, None) is bloque
    assert _local_window_block([bloque], title, 506.3, None) is bloque
    assert _local_window_block([bloque], title, 506.31, None) is None
    assert _local_window_block([bloque], title, 386.29, None) is None
    assert _local_window_block([bloque], title, 437.25, None) is bloque

    assert _local_window_block([bloque], title, 437.25, 386.3) is None
    assert _local_window_block([bloque], title, 437.25, 400.0) is None
    assert _local_window_block([bloque], title, 437.25, 72.0) is bloque


def test_ventana_ambiguedad_y_divergencia() -> None:
    title = "Agents as Tools: A Powerful Pattern"
    primero = _block(title, 386.3)
    segundo = _block(title, 400.0)
    assert _local_window_block([primero, segundo], title, 437.25, None) is None

    divergente = _block("Agents as Tools: A Very Different Pattern", 386.3)
    assert _local_window_block([divergente], title, 437.25, None) is None


def test_ventana_sin_destino_declarado_no_aplica() -> None:
    bloque = _block("Alpha Beta Gamma Delta", 386.3)
    assert _local_window_block([bloque], "Alpha Beta Gamma Delta", None, None) is None
