"""Mobiliario de cabecera corrida: el caso real del tercer libro y sus negativos (`D-18` §3).

La banda se valida por **secuencia aritmética + repetición de `y0`**, nunca por palabras: por eso los
negativos incluyen valores que no avanzan de uno en uno, corridas demasiado cortas y coordenadas que
cambian. Cuando la evidencia no alcanza, no hay banda y el texto se conserva.
"""

from __future__ import annotations

import pytest

from book_text_rag.domain.models import Line
from book_text_rag.domain.page_furniture import (
    HeaderBand,
    HeaderFurniture,
    detect_header_furniture,
    strip_header_line,
    strip_page_number,
)


def _linea(texto: str, y0: float) -> Line:
    return Line(text=texto, y0=y0, y1=y0 + 9.0, size=8.5, font="Arial", bold=False)


def _pagina(textos: list[str], y0: float = 26.108) -> list[Line]:
    """Renglón superior con sus textos y un cuerpo por debajo."""
    fila = [_linea(texto, y0) for texto in textos]
    return [*fila, _linea("cuerpo del texto", y0 + 20.0)]


def test_secuencia_de_cabecera_valida_la_banda() -> None:
    """Tres páginas consecutivas con el número en el renglón superior y `y0` estable forman banda."""
    geometria = {
        565: _pagina(["Index", "528"]),
        566: _pagina(["529", "Index"]),
        567: _pagina(["Index", "530"]),
    }

    furniture = detect_header_furniture(geometria)

    assert set(furniture.bands) == {565, 566, 567}
    assert furniture.bands[565].printed == 528
    assert sorted(furniture.bands[565].texts) == ["528", "Index"]
    assert furniture.bands[565].y0 == pytest.approx(26.108)


def test_corrida_de_dos_paginas_no_alcanza() -> None:
    """Dos páginas con secuencia no son evidencia suficiente: no hay banda ni exclusión."""
    geometria = {10: _pagina(["8", "Chapter 1"]), 11: _pagina(["9", "Chapter 1"])}

    furniture = detect_header_furniture(geometria)

    assert furniture.bands == {}
    resultado = strip_header_line(["8   Chapter 1", "cuerpo"], 10, furniture)
    assert resultado.lines == ["8   Chapter 1", "cuerpo"]
    assert resultado.excluded is False
    assert resultado.anomaly is False


def test_valores_que_no_avanzan_de_uno_en_uno_no_forman_banda() -> None:
    """Una progresión de +2 no es numeración de página: se conserva el texto."""
    geometria = {p: _pagina([str(200 + 2 * (p - 10)), "Chapter 5"]) for p in (10, 11, 12, 13)}

    assert detect_header_furniture(geometria).bands == {}


def test_cambio_de_y0_rompe_la_secuencia() -> None:
    """Si la coordenada del renglón superior cambia, la serie no se sostiene."""
    geometria = {
        10: _pagina(["40", "Chapter 2"], y0=26.0),
        11: _pagina(["41", "Chapter 2"], y0=26.0),
        12: _pagina(["42", "Chapter 2"], y0=40.0),
    }

    assert detect_header_furniture(geometria).bands == {}


def test_linea_compuesta_solo_por_la_banda_se_elimina() -> None:
    """Caso real de la página 565: `Index` y su número impreso, nada más."""
    furniture = HeaderFurniture(bands={565: HeaderBand(y0=26.108, texts=["Index", "528"], printed=528)})

    resultado = strip_header_line(["Index                       528\r", "", "consequences   128"], 565, furniture)

    assert resultado.lines == ["", "consequences   128"]
    assert resultado.excluded is True
    assert resultado.excluded_value == 528
    assert resultado.anomaly is False


def test_encabezado_fusionado_con_el_cuerpo_conserva_el_cuerpo() -> None:
    """Caso real de la página 119: `-layout` pega el renglón de cabecera con la tabla siguiente."""
    furniture = HeaderFurniture(bands={119: HeaderBand(y0=26.108, texts=["Chapter 3", "82"], printed=82)})

    resultado = strip_header_line(["Chapter 3            FFT            82\r", "", "tabla"], 119, furniture)

    assert resultado.lines == ["FFT", "", "tabla"]
    assert resultado.excluded is True
    assert resultado.anomaly is False


def test_texto_de_la_banda_repetido_conserva_la_linea_completa() -> None:
    """Si un texto de la banda aparece dos veces, no se puede distinguir el mobiliario: se conserva."""
    furniture = HeaderFurniture(bands={20: HeaderBand(y0=26.108, texts=["Index", "49"], printed=49)})
    original = ["Index 49 Index 49", "cuerpo"]

    resultado = strip_header_line(original, 20, furniture)

    assert resultado.lines == original
    assert resultado.excluded is False
    assert resultado.anomaly is True


def test_primera_linea_ajena_a_la_banda_se_conserva_y_se_registra() -> None:
    """Con banda validada, una primera línea que no la contiene no se toca: se anota la anomalía."""
    furniture = HeaderFurniture(bands={30: HeaderBand(y0=26.108, texts=["Index", "59"], printed=59)})
    original = ["contenido distinto", "Index   59"]

    resultado = strip_header_line(original, 30, furniture)

    assert resultado.lines == original
    assert resultado.excluded is False
    assert resultado.anomaly is True


def test_pagina_sin_banda_queda_intacta() -> None:
    """Sin banda validada no hay exclusión: la regla no actúa sobre contenido legítimo."""
    furniture = HeaderFurniture()

    resultado = strip_header_line(["50  Resultados del experimento"], 7, furniture)

    assert resultado.lines == ["50  Resultados del experimento"]
    assert resultado.excluded is False
    assert resultado.anomaly is False


def test_regla_de_pie_de_d18_sigue_intacta() -> None:
    """La regla de `D-18` §3.1 no cambia: último renglón numérico igual a `pdf_page - 1`."""
    assert strip_page_number(["cuerpo", "41"], 42).lines == ["cuerpo"]
    conservado = strip_page_number(["cuerpo", "40"], 42)
    assert conservado.lines == ["cuerpo", "40"]
    assert conservado.anomaly is True
