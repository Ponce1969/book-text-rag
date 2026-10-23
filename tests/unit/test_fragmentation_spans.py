"""Corte de tramos en `_content_lines` (Incremento D).

Los límites de `UnitSpan` son índices absolutos de línea dentro de su página. En un tramo de una
sola página, el corte final no puede aplicarse sobre la lista ya recortada por el índice inicial.
"""

from __future__ import annotations

from book_text_rag.domain.fragmentation import UnitSpan, _content_lines
from book_text_rag.domain.models import OutlineUnit, UnitKind


def _span(start_page: int, start_index: int, end_page: int, end_index: int) -> UnitSpan:
    unit = OutlineUnit(
        title="Unit",
        level=1,
        page=start_page,
        section_path=["Unit"],
        kind=UnitKind.LEAF,
        ordinal=1,
    )
    return UnitSpan(
        unit=unit,
        start_page=start_page,
        start_index=start_index,
        end_page=end_page,
        end_index=end_index,
    )


def _page(count: int) -> list[str]:
    return [f"L{index}" for index in range(count)]


def test_misma_pagina_con_indice_inicial_no_nulo_respeta_el_limite_absoluto() -> None:
    span = _span(1, 7, 1, 22)
    result = _content_lines(span, [_page(30)])
    assert [line for _, line in result] == [f"L{index}" for index in range(7, 22)]


def test_misma_pagina_desde_cero() -> None:
    span = _span(1, 0, 1, 5)
    result = _content_lines(span, [_page(10)])
    assert [line for _, line in result] == [f"L{index}" for index in range(5)]


def test_varias_paginas_con_indices_en_los_extremos() -> None:
    span = _span(1, 2, 3, 4)
    result = _content_lines(span, [_page(6), _page(6), _page(6)])
    assert result == [
        (1, "L2"),
        (1, "L3"),
        (1, "L4"),
        (1, "L5"),
        (2, "L0"),
        (2, "L1"),
        (2, "L2"),
        (2, "L3"),
        (2, "L4"),
        (2, "L5"),
        (3, "L0"),
        (3, "L1"),
        (3, "L2"),
        (3, "L3"),
    ]


def test_tramo_vacio_en_la_misma_pagina() -> None:
    span = _span(1, 5, 1, 5)
    assert _content_lines(span, [_page(10)]) == []


def test_tramo_de_una_sola_linea_en_la_misma_pagina() -> None:
    span = _span(1, 5, 1, 6)
    assert _content_lines(span, [_page(10)]) == [(1, "L5")]
