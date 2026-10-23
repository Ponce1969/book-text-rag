"""Exclusión del apartado `Index` y del material posterior (`D-10` pto. iv).

El apartado se identifica por su **título canónico exacto** en el outline, no por palabras contenidas,
y el cuerpo del libro termina donde empieza su encabezado: el último tramo se recorta ahí para que el
material excluido no quede absorbido por la unidad anterior.
"""

from __future__ import annotations

import pytest

from book_text_rag.domain.fragmentation import (
    AnchoredUnit,
    build_units,
    corpus_end_marker,
    excluded_section,
    unit_spans,
)
from book_text_rag.domain.models import ErrorCode, IngestError, OutlineUnit, TocEntry, UnitKind

TOC = [
    TocEntry(level=1, title="Preface", page=8),
    TocEntry(level=1, title="Indexing: Organizing for Speed", page=255),
    TocEntry(level=3, title="Indexing: Organizing for Speed", page=255),
    TocEntry(level=1, title="1. Introducción", page=25),
    TocEntry(level=1, title="Epílogo", page=716),
    TocEntry(level=1, title="Index", page=717),
    TocEntry(level=1, title="About the Author", page=776),
]


def test_apartado_excluido_es_el_index_de_nivel_uno() -> None:
    """`Indexing: Organizing for Speed` no coincide: la comparación es de título canónico completo."""
    entry = excluded_section(TOC)

    assert entry is not None
    assert entry.title == "Index"
    assert entry.page == 717


def test_libro_sin_index_no_excluye_nada() -> None:
    """Sin apartado `Index` en el outline no hay exclusión: la regla no inventa un corte."""
    assert excluded_section([TocEntry(level=1, title="Capítulo", page=25)]) is None


def test_unidades_anteriores_se_conservan_y_el_index_no_entra() -> None:
    """El cuerpo conserva sus unidades; el `Index` y lo posterior no producen unidades."""
    units = build_units(TOC)

    assert [unit.title for unit in units] == [
        "Indexing: Organizing for Speed",
        "Indexing: Organizing for Speed",
        "1. Introducción",
        "Epílogo",
    ]


def test_marcador_de_fin_localiza_el_encabezado_en_su_pagina() -> None:
    """El límite es la **línea** del encabezado, no el final de la página que lo contiene."""
    lineas = _paginas(717, {717: ["Index", "1", "16-bit floating point (FP16) models", "43"]})

    assert corpus_end_marker(TOC, lineas) == (717, 0)


def test_marcador_no_encontrado_falla_de_forma_explicita() -> None:
    """Si el encabezado no está en su página, la corrida falla: no se corta en otro punto."""
    lineas = _paginas(717, {717: ["indice alfabetico", "1", "43"]})

    with pytest.raises(IngestError) as info:
        corpus_end_marker(TOC, lineas)

    assert info.value.code is ErrorCode.OUTLINE_UNAVAILABLE
    assert info.value.details["pagina"] == 717


def _paginas(total: int, contenido: dict[int, list[str]]) -> list[list[str]]:
    """Páginas 1..`total` con su contenido; las que no se nombran quedan vacías."""
    paginas: list[list[str]] = [[] for _ in range(total)]
    for numero, lineas in contenido.items():
        paginas[numero - 1] = list(lineas)
    return paginas


def _unidad(ordinal: int, titulo: str, pagina: int) -> OutlineUnit:
    return OutlineUnit(
        title=titulo,
        level=1,
        page=pagina,
        section_path=[titulo],
        kind=UnitKind.LEAF,
        ordinal=ordinal,
    )


def test_el_ultimo_tramo_no_absorbe_el_index() -> None:
    """Sin el recorte, la última unidad del cuerpo llegaría hasta el final de la página del Index."""
    toc = [
        TocEntry(level=1, title="1. Introducción", page=25),
        TocEntry(level=1, title="Epílogo", page=290),
        TocEntry(level=1, title="Index", page=300),
    ]
    ancladas = [
        AnchoredUnit(unit=_unidad(1, "1. Introducción", 25), text_index=0, page=25),
        AnchoredUnit(unit=_unidad(2, "Epílogo", 290), text_index=3, page=290),
    ]
    lineas = _paginas(300, {290: ["Epílogo", "texto", "final"], 300: ["Index", "1", "43"]})

    sin_recorte = unit_spans(toc, ancladas, lineas)
    con_recorte = unit_spans(toc, ancladas, lineas, corpus_end=(300, 0))

    assert (sin_recorte[-1].end_page, sin_recorte[-1].end_index) == (300, 3)
    assert (con_recorte[-1].end_page, con_recorte[-1].end_index) == (300, 0)


def test_sin_index_el_tramo_final_no_cambia() -> None:
    """Sin apartado excluido el recorte no se aplica: el corpus termina donde ya terminaba."""
    toc = [TocEntry(level=1, title="1. Introducción", page=25), TocEntry(level=1, title="Epílogo", page=30)]
    ancladas = [AnchoredUnit(unit=_unidad(1, "Epílogo", 30), text_index=0, page=30)]
    lineas = _paginas(30, {30: ["Epílogo", "texto"]})

    assert corpus_end_marker(toc, lineas) is None
    spans = unit_spans(toc, ancladas, lineas, corpus_end=None)

    assert (spans[-1].end_page, spans[-1].end_index) == (30, 2)
