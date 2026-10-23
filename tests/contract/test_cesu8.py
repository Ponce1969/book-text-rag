"""Reparación CESU-8 del decodificador del extractor (excepción aprobada de `D-19` §1.2).

Algunos PDF traen caracteres astrales como dos surrogates UTF-8 (CESU-8) en lugar de la secuencia
UTF-8 de cuatro bytes. Se recomponen en el carácter real; un surrogate suelto sigue siendo `decode_error`.
"""

from __future__ import annotations

import pytest

from book_text_rag.adapters.extraction.pdftotext import decode_output
from book_text_rag.domain.models import ErrorCode, IngestError

# Bytes reales de `libro_Agentic_Architectural_Patterns.pdf`, posición 61225: U+1F9E0 en CESU-8.
CESU8_CEREBRO = b"\xed\xa0\xbe\xed\xb7\xa0"
CEREBRO = "\U0001f9e0"


def test_recompone_el_par_cesu8_real_del_libro_que_fallaba() -> None:
    assert decode_output(CESU8_CEREBRO + b" THOUGHT from the log") == CEREBRO + " THOUGHT from the log"


def test_acepta_el_astral_codificado_en_utf8_normal() -> None:
    esperado = CEREBRO + " texto"
    assert decode_output(esperado.encode("utf-8")) == esperado


def test_rechaza_un_surrogate_alto_no_emparejado() -> None:
    with pytest.raises(IngestError) as error:
        decode_output(b"\xed\xa0\xbe suelto")

    assert error.value.code is ErrorCode.DECODE_ERROR
    assert "surrogate alto" in error.value.message


def test_rechaza_un_surrogate_bajo_no_emparejado() -> None:
    with pytest.raises(IngestError) as error:
        decode_output(b"\xed\xb7\xa0 suelto")

    assert error.value.code is ErrorCode.DECODE_ERROR
    assert "surrogate bajo" in error.value.message


def test_rechaza_un_alto_seguido_de_otro_alto() -> None:
    with pytest.raises(IngestError) as error:
        decode_output(CESU8_CEREBRO[:3] + CESU8_CEREBRO[:3])

    assert error.value.code is ErrorCode.DECODE_ERROR


def test_no_altera_el_texto_utf8_valido() -> None:
    """Sin surrogates, el resultado es idéntico a la decodificación estricta de siempre."""
    texto = "Acentos: \u00e1\u00e9\u00ed\u00f3\u00fa \u00f1; comillas \u201cy\u201d.\n"
    datos = texto.encode("utf-8")

    assert decode_output(datos) == datos.decode("utf-8", errors="strict")


def test_conserva_el_rechazo_de_bytes_invalidos_y_de_bom() -> None:
    with pytest.raises(IngestError) as invalido:
        decode_output(b"texto \xff\xfe invalido")
    assert invalido.value.code is ErrorCode.DECODE_ERROR

    with pytest.raises(IngestError) as bom:
        decode_output("\ufeffcontenido".encode())
    assert bom.value.code is ErrorCode.DECODE_ERROR
