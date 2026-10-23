"""Anclaje de último recurso por **tamaño** (encabezados no negros y títulos numéricos).

Algunos libros componen los títulos de parte a gran tamaño **sin negrita** y numeran los capítulos con
un «1» suelto. El camino ordinario exige negrita, así que estas unidades fallaban con
`unit_not_anchored`. El último recurso solo se evalúa cuando **no** hubo ningún candidato: no puede
alterar un anclaje que ya funcionaba.
"""

from __future__ import annotations

import pytest

from book_text_rag.domain.anchor import (
    _last_resort_size_only,
    _size_only_exact_blocks,
    _size_only_runs,
)
from book_text_rag.domain.models import AnchorLevel, Line

UMBRAL = 11.4


def _linea(texto: str, y0: float, tam: float, *, bold: bool = False) -> Line:
    return Line(text=texto, y0=y0, y1=y0 + tam, size=tam, font="Serif", bold=bold)


def test_agrupa_lineas_consecutivas_del_mismo_tamano_sin_exigir_negrita() -> None:
    lineas = [
        _linea("Part 1", 71.3, 48.0),
        _linea("Foundations and Core", 166.3, 36.0),
        _linea("Agent Concepts", 209.6, 36.0),
        _linea("cuerpo del texto", 294.5, 9.5),
    ]

    runs = _size_only_runs(lineas, UMBRAL)

    assert [[linea.text for linea in run] for run in runs] == [
        ["Part 1"],
        ["Foundations and Core", "Agent Concepts"],
    ]


def test_las_lineas_bajo_el_umbral_no_forman_bloques() -> None:
    lineas = [_linea("texto normal", 100.0, 9.5), _linea("mas texto", 112.0, 9.5)]

    assert _size_only_runs(lineas, UMBRAL) == []


def test_el_titulo_de_parte_no_negro_se_encuentra() -> None:
    lineas = [_linea("Part 1", 71.3, 48.0), _linea("Foundations and Core", 166.3, 36.0)]

    bloques = _size_only_exact_blocks(lineas, "Part 1", UMBRAL)

    assert len(bloques) == 1
    assert [linea.text for linea in bloques[0]] == ["Part 1"]


def test_el_titulo_partido_en_dos_lineas_se_encuentra() -> None:
    lineas = [
        _linea("Part 1", 71.3, 48.0),
        _linea("Foundations and Core", 166.3, 36.0),
        _linea("Agent Concepts", 209.6, 36.0),
    ]

    bloques = _size_only_exact_blocks(lineas, "Foundations and Core Agent Concepts", UMBRAL)

    assert len(bloques) == 1
    assert len(bloques[0]) == 2


def test_un_titulo_solo_numerico_requiere_igualdad_textual() -> None:
    lineas = [_linea("1", 43.8, 75.0), _linea("GenAI in the Enterprise:", 147.3, 27.0)]

    assert len(_size_only_exact_blocks(lineas, "1", UMBRAL)) == 1
    assert _size_only_exact_blocks(lineas, "2", UMBRAL) == []


def test_dos_bloques_iguales_no_eligen_ninguno() -> None:
    lineas = [_linea("Part 1", 71.3, 48.0), _linea("Part 1", 200.0, 48.0)]

    assert len(_size_only_exact_blocks(lineas, "Part 1", UMBRAL)) == 2
    assert _last_resort_size_only(lineas, "Part 1", UMBRAL, page=38) is None


def test_el_ultimo_recurso_ancla_con_nivel_de_pagina_y_tipografia() -> None:
    lineas = [_linea("Part 1", 71.3, 48.0)]

    resultado = _last_resort_size_only(lineas, "Part 1", UMBRAL, page=38)

    assert resultado is not None
    evidencia, nivel, bloque = resultado
    assert nivel is AnchorLevel.PAGE_TYPOGRAPHY
    assert evidencia.page == 38
    assert evidencia.y0 == pytest.approx(71.3)
    assert evidencia.y_dest is None
    assert [linea.text for linea in bloque] == ["Part 1"]
