"""Anclaje de un encabezado fuera de la banda superior con evidencia suficiente.

Caso real (`libro_Agentic_Architectural_Patterns.pdf`, pág. 434): «Context» aparece a media página,
después de una tabla. La regla exige coincidencia textual exacta, candidato único, orden estricto
respecto de la unidad anterior y tamaño de encabezado; cualquier ambigüedad falla.
"""

from __future__ import annotations

from book_text_rag.domain.anchor import _block_lines, _ordered_exact_block
from book_text_rag.domain.models import Line


def _linea(texto: str, y0: float, tam: float, *, bold: bool = True) -> Line:
    return Line(text=texto, y0=y0, y1=y0 + tam, size=tam, font="Serif", bold=bold)


def test_ancla_el_caso_real_de_la_pagina_434() -> None:
    """Bloque único, exacto y por debajo de la unidad anterior de la misma página."""
    bloque = [_linea("Context", 272.8, 14.0)]

    assert _ordered_exact_block([bloque], "Context", previous_y0=53.48) is bloque


def test_no_ancla_con_dos_candidatos_iguales() -> None:
    primero = [_linea("Context", 272.8, 14.0)]
    segundo = [_linea("Context", 400.0, 14.0)]

    assert _ordered_exact_block([primero, segundo], "Context", previous_y0=53.48) is None


def test_no_ancla_si_el_texto_no_coincide_exactamente() -> None:
    bloque = [_linea("Context and consequences", 272.8, 14.0)]

    assert _ordered_exact_block([bloque], "Context", previous_y0=53.48) is None


def test_no_ancla_si_el_bloque_no_esta_despues_de_la_unidad_anterior() -> None:
    bloque = [_linea("Context", 60.0, 14.0)]

    assert _ordered_exact_block([bloque], "Context", previous_y0=120.0) is None


def test_no_ancla_sin_unidad_anterior_no_hay_orden_demostrable() -> None:
    bloque = [_linea("Context", 272.8, 14.0)]

    assert _ordered_exact_block([bloque], "Context", previous_y0=None) is None


def test_el_bloque_empieza_en_la_linea_de_tamano_de_encabezado() -> None:
    """Una corrida de negrita puede arrastrar la última línea del párrafo anterior."""
    corrida = [
        _linea("investment (ROI).", 257.0, 9.5),
        _linea("Context", 272.8, 14.0),
    ]

    bloque = _block_lines(corrida, "Context", size_min=12.35)

    assert bloque is not None
    assert [linea.text for linea in bloque] == ["Context"]
    assert bloque[0].y0 == 272.8


def test_sin_linea_de_encabezado_no_hay_bloque() -> None:
    corrida = [_linea("solo cuerpo", 100.0, 9.5), _linea("mas cuerpo", 112.0, 9.5)]

    assert _block_lines(corrida, "Context", size_min=12.35) == []
