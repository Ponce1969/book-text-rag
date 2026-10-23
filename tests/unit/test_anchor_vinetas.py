"""Viñetas fuera del anclaje: un ítem de lista nunca es encabezado.

Caso real (`libro_Agentic_Architectural_Patterns.pdf`, pág. 169): el recuadro de «Consequences» usa
negrita de 9,5 pt para los ítems y de 13 pt para el encabezado siguiente, así que la corrida de negrita
absorbía la viñeta y el bloque empezaba en el ítem → la alineación con el texto extraído fallaba.
"""

from __future__ import annotations

from book_text_rag.domain.anchor import (
    _size_only_runs,
    heading_block,
    lineas_de_vineta,
)
from book_text_rag.domain.models import Line

UMBRAL = 11.4


def _linea(texto: str, y0: float, tam: float, *, bold: bool) -> Line:
    return Line(text=texto, y0=y0, y1=y0 + tam, size=tam, font="Serif", bold=bold)


def test_excluye_el_glifo_y_su_texto_en_la_misma_linea() -> None:
    lineas = [_linea("\u25e6 Single point of failure: el flujo se detiene", 178.1, 9.5, bold=True)]

    assert lineas_de_vineta(lineas) == frozenset({id(lineas[0])})


def test_excluye_el_glifo_en_linea_propia_y_el_texto_alineado() -> None:
    """Disposición real de la pág. 169: el glifo es una línea aparte a menos de 1 pt del texto."""
    glifo = _linea("\u25e6 ", 177.6, 9.5, bold=False)
    texto = _linea("Single point of failure: el flujo se detiene", 178.1, 9.5, bold=True)
    otro = _linea("Implementation guidance", 192.0, 13.0, bold=True)

    afectadas = lineas_de_vineta([glifo, texto, otro])

    assert afectadas == frozenset({id(glifo), id(texto)})
    assert id(otro) not in afectadas


def test_no_excluye_un_encabezado_legitimo() -> None:
    encabezado = _linea("Implementation guidance", 192.0, 13.0, bold=True)
    cuerpo = _linea("When implementing a Supervisor Architecture…", 213.1, 9.5, bold=False)

    assert lineas_de_vineta([encabezado, cuerpo]) == frozenset()


def test_el_bloque_empieza_en_el_encabezado_y_no_en_la_vineta() -> None:
    glifo = _linea("\u25e6 ", 177.6, 9.5, bold=False)
    vinneta = _linea("Single point of failure: el flujo se detiene", 178.1, 9.5, bold=True)
    encabezado = _linea("Implementation guidance", 192.0, 13.0, bold=True)

    bloque, motivo = heading_block([glifo, vinneta, encabezado], "Implementation guidance", None)

    assert motivo == "texto_coincide"
    assert bloque is not None
    assert bloque[0].text == "Implementation guidance"


def test_el_ultimo_recurso_por_tamano_ignora_las_vinetas() -> None:
    glifo = _linea("\u2022 ", 100.0, 40.0, bold=False)
    item = _linea("Part 1", 100.5, 40.0, bold=False)
    legitimo = _linea("Part 1", 300.0, 48.0, bold=False)

    runs = _size_only_runs([glifo, item, legitimo], UMBRAL)

    assert [[linea.text for linea in run] for run in runs] == [["Part 1"]]
    assert runs[0][0] is legitimo
