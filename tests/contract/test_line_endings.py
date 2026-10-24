"""Fin de línea normalizado en la extracción: el contenido no depende del sistema operativo.

`pdftotext` escribe el fin de línea de su plataforma (CRLF en Windows, LF en Linux). Sin normalizar,
el mismo PDF con el mismo extractor produce `content_hash` distintos según la máquina, y el campo de
integridad deja de ser comparable. El contenido lógico (`D-11` §3) no depende del SO.
"""

from __future__ import annotations

from book_text_rag.adapters.extraction.pdftotext import decode_output
from book_text_rag.domain.identity import content_hash


def test_crlf_de_windows_se_normaliza_a_lf() -> None:
    assert decode_output(b"linea uno\r\nlinea dos\r\n") == "linea uno\nlinea dos\n"


def test_cr_solo_tambien_pasa_a_lf() -> None:
    assert decode_output(b"viejo mac\rlinea") == "viejo mac\nlinea"


def test_texto_sin_retorno_no_se_toca() -> None:
    texto = b"linea uno\nlinea dos\n"
    assert decode_output(texto) == texto.decode("utf-8")


def test_la_normalizacion_solo_cambia_el_fin_de_linea() -> None:
    """Se conservan acentos, espacios internos y orden: únicamente cambia `\\r\\n` por `\\n`."""
    assert decode_output("ñandú\r\n  sangría interna".encode()) == "ñandú\n  sangría interna"


def test_el_mismo_corpus_produce_el_mismo_hash_en_cualquier_plataforma() -> None:
    """Lo que Windows y Linux emiten para el mismo PDF acaba en el mismo `content_hash`."""
    texto = "Part I. Foundations\nof Graph-Based Systems\ncuerpo del fragmento\n"

    windows = decode_output(texto.replace("\n", "\r\n").encode("utf-8"))
    linux = decode_output(texto.encode("utf-8"))

    assert windows == linux == texto
    assert content_hash(windows) == content_hash(linux)


def test_los_invisibles_de_composicion_se_descartan() -> None:
    """U+200B y U+2060 los coloca el extractor, no el autor: no entran en el contenido lógico."""
    assert decode_output("pala\u200bbra\u2060 unida".encode()) == "palabra unida"


def test_el_orden_plataforma_dependiente_de_los_invisibles_no_cambia_el_hash() -> None:
    """Caso real del ordinal 58: mismas marcas en otra posición, mismo contenido lógico."""
    en_windows = decode_output("a\u200bb cd\u2060 e".encode("utf-8"))
    en_linux = decode_output("ab\u2060 c\u200bd e".encode("utf-8"))

    assert en_windows == en_linux == "ab cd e"
    assert content_hash(en_windows) == content_hash(en_linux)
