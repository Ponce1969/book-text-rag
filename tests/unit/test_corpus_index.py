"""Fronteras del corpus derivadas del outline (`D-05` pto. 1 y 6, `D-10` pto. iv).

El cuerpo empieza donde empieza la numeración de los apartados —`1. Título` en el piloto, `I. Título`
en GraphRAG, `1` solo en el tercer libro— y termina donde empieza el `Index`. No hay constantes por
libro: cuando el outline no declara esa estructura, la corrida falla de forma explícita y el llamador
puede fijar las fronteras a mano.
"""

from __future__ import annotations

import pytest

from book_text_rag.domain.fragmentation import (
    AnchoredUnit,
    body_start,
    build_units,
    corpus_end_marker,
    excluded_section,
    unit_spans,
)
from book_text_rag.domain.models import ErrorCode, IngestError, OutlineUnit, TocEntry, UnitKind

TOC = [
    TocEntry(level=1, title="Preface", page=8),
    TocEntry(level=2, title="Who Should Read This Book", page=9),
    TocEntry(level=1, title="Indexing: Organizing for Speed", page=255),
    TocEntry(level=3, title="Indexing: Organizing for Speed", page=255),
    TocEntry(level=1, title="1. Introducción", page=25),
    TocEntry(level=1, title="Epílogo", page=716),
    TocEntry(level=1, title="Index", page=717),
    TocEntry(level=1, title="About the Author", page=776),
]


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


@pytest.mark.parametrize(
    ("titulo", "pagina", "esperado"),
    [
        ("1. Introduction to Building AI Applications", 25, 25),
        ("I. Foundations of Graph-Based Agentic Systems", 25, 25),
        ("1", 40, 40),
    ],
)
def test_inicio_del_cuerpo_segun_la_convencion_del_libro(titulo: str, pagina: int, esperado: int) -> None:
    """Las tres convenciones medidas abren el cuerpo: `1.`, `I.` y `1` solo."""
    toc = [
        TocEntry(level=1, title="Preface", page=3),
        TocEntry(level=1, title="Table of Contents", page=5),
        TocEntry(level=1, title=titulo, page=pagina),
    ]

    assert body_start(toc).page == esperado


def test_rotulo_de_parte_no_abre_el_cuerpo() -> None:
    """`Part 1` es la portadilla de una parte, no la numeración del cuerpo: no adelanta la frontera."""
    toc = [
        TocEntry(level=1, title="Preface", page=30),
        TocEntry(level=1, title="Part 1", page=38),
        TocEntry(level=1, title="1", page=40),
    ]

    assert body_start(toc).page == 40


def test_sin_apartado_numerado_falla_de_forma_explicita() -> None:
    """Sin numeración en el nivel 1 no hay frontera derivable: se detiene y se informa."""
    toc = [TocEntry(level=1, title="Preface", page=3), TocEntry(level=2, title="1. Capítulo", page=9)]

    with pytest.raises(IngestError) as info:
        body_start(toc)

    assert info.value.code is ErrorCode.OUTLINE_UNAVAILABLE


def test_primer_apartado_que_no_empieza_en_uno_es_ambiguo() -> None:
    """Si el primer numerado no es el 1, el outline no permite fijar la frontera con seguridad."""
    toc = [TocEntry(level=1, title="2. Segundo capítulo", page=40)]

    with pytest.raises(IngestError) as info:
        body_start(toc)

    assert info.value.code is ErrorCode.OUTLINE_UNAVAILABLE
    assert info.value.details["numero"] == 2


def test_dos_candidatos_en_la_misma_pagina_son_ambiguos() -> None:
    """Dos apartados numerados que compiten por la misma página de inicio no deciden el cuerpo."""
    toc = [
        TocEntry(level=1, title="I. Parte", page=25),
        TocEntry(level=1, title="1. Capítulo", page=25),
    ]

    with pytest.raises(IngestError) as info:
        body_start(toc)

    assert info.value.code is ErrorCode.OUTLINE_UNAVAILABLE
    assert info.value.details["pagina"] == 25


def test_apartado_excluido_es_el_index_de_nivel_uno() -> None:
    """`Indexing: Organizing for Speed` no coincide: la comparación es de título canónico completo."""
    entry = excluded_section(TOC)

    assert entry is not None
    assert entry.title == "Index"
    assert entry.page == 717


def test_libro_sin_index_no_tiene_apartado_excluido() -> None:
    """Sin apartado `Index` en el outline la regla no inventa un corte."""
    assert excluded_section([TocEntry(level=1, title="1. Capítulo", page=25)]) is None


def test_unidades_anteriores_se_conservan_y_el_index_no_entra() -> None:
    """El cuerpo conserva sus unidades; el front matter y el `Index` no producen unidades."""
    units = build_units(TOC, start_page=25)

    assert [unit.title for unit in units] == [
        "Indexing: Organizing for Speed",
        "Indexing: Organizing for Speed",
        "1. Introducción",
        "Epílogo",
    ]


def test_front_matter_queda_fuera_del_corpus() -> None:
    """Las entradas anteriores a la frontera —prefacio, índice analítico del frente— no son unidades."""
    toc = [
        TocEntry(level=1, title="Preface", page=30),
        TocEntry(level=1, title="Who this book is for", page=31),
        TocEntry(level=1, title="Part 1", page=38),
        TocEntry(level=1, title="1", page=40),
        TocEntry(level=2, title="1.1 Detalle", page=41),
        TocEntry(level=1, title="Index", page=564),
    ]

    units = build_units(toc, start_page=body_start(toc).page)

    assert [unit.title for unit in units] == ["1", "1.1 Detalle"]


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


def test_libro_sin_index_exige_fronteras_explicitas() -> None:
    """Sin `Index` no hay fin derivable: se falla en vez de suponer una constante."""
    toc = [TocEntry(level=1, title="1. Capítulo", page=25)]
    lineas = _paginas(40, {})

    with pytest.raises(IngestError) as info:
        corpus_end_marker(toc, lineas)

    assert info.value.code is ErrorCode.OUTLINE_UNAVAILABLE


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


def test_fronteras_explicitas_acotan_el_ultimo_tramo() -> None:
    """Con límites explícitos, el cuerpo termina donde el llamador declara, no en el fin del archivo."""
    toc = [TocEntry(level=1, title="1. Introducción", page=25), TocEntry(level=1, title="Epílogo", page=30)]
    ancladas = [AnchoredUnit(unit=_unidad(1, "Epílogo", 30), text_index=0, page=30)]
    lineas = _paginas(40, {30: ["Epílogo", "texto"], 31: ["material ajeno al cuerpo"]})

    spans = unit_spans(toc, ancladas, lineas, corpus_end=(31, 0))

    assert (spans[-1].end_page, spans[-1].end_index) == (31, 0)
