"""Vectores de `index_version`: octetos escritos a mano y resumen independiente del cálculo probado.

El vector base se transcribió como literal conforme al orden de D-11 §4. Su resumen de referencia se obtuvo
aplicando SHA-256 directamente a esos octetos literales, nunca llamando a `index_version` para generarlo.
"""

from __future__ import annotations

import hashlib
import re

import pytest

from book_text_rag.domain.identity import _bytes_canonicos, index_version

_OCTETOS_VECTOR_SEIS = (
    b'{"document_version":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
    b'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","extractor":["pdftotext","4.00","-layout -enc UTF-8"],'
    b'"chunking_config_version":"chunking-v1","tokenizer":"unicode61 remove_diacritics 2",'
    b'"sqlite_version":"3.46.0","sqlite_vec_version":"0.1.6"}'
)

# Séptimo insumo (`D-11` §4.1): los mismos seis campos con `,"embeddings":[]` insertado antes de la llave
# de cierre. El literal se transcribió a mano y su resumen se obtuvo con `sha256sum` sobre esos octetos.
_OCTETOS_VECTOR = (
    b'{"document_version":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
    b'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","extractor":["pdftotext","4.00","-layout -enc UTF-8"],'
    b'"chunking_config_version":"chunking-v1","tokenizer":"unicode61 remove_diacritics 2",'
    b'"sqlite_version":"3.46.0","sqlite_vec_version":"0.1.6","embeddings":[]}'
)


def _argumentos_validos() -> dict[str, object]:
    return {
        "document_version": "a" * 64,
        "extractor": ("pdftotext", "4.00", "-layout -enc UTF-8"),
        "chunking_config_version": "chunking-v1",
        "tokenizer": "unicode61 remove_diacritics 2",
        "sqlite_version": "3.46.0",
        "sqlite_vec_version": "0.1.6",
        "embeddings": (),
    }


def test_index_version_es_determinista() -> None:
    argumentos = _argumentos_validos()
    assert index_version(**argumentos) == index_version(**argumentos)


def test_octetos_canonicos_coinciden_con_vector_literal_y_orden_de_claves() -> None:
    assert _bytes_canonicos(**_argumentos_validos()) == _OCTETOS_VECTOR


def test_index_version_coincide_con_vector_resumen_independiente() -> None:
    referencia = "889bb6da042a"
    assert index_version(**_argumentos_validos()) == referencia
    assert referencia == hashlib.sha256(_OCTETOS_VECTOR).hexdigest()[:12]


def test_los_seis_insumos_conservan_sus_octetos_con_el_septimo_insertado() -> None:
    """`D-11` §4.1, prueba de regresión exigida: comparación de **secuencias de bytes completas**."""
    assert _OCTETOS_VECTOR_SEIS[:-1] + b',"embeddings":[]}' == _OCTETOS_VECTOR
    assert _bytes_canonicos(**_argumentos_validos()) == _OCTETOS_VECTOR


def test_index_version_exige_el_septimo_insumo_sin_valor_por_defecto() -> None:
    """Omitir `embeddings` es un error de llamada: no hay sustituto implícito (`D-11` §4)."""
    argumentos = _argumentos_validos()
    del argumentos["embeddings"]

    with pytest.raises(TypeError):
        index_version(**argumentos)  # type: ignore[arg-type]


def test_septimo_insumo_admite_el_arreglo_vacio_en_tupla_y_en_lista() -> None:
    """Cero descriptores: `()` y `[]` son la misma construcción léxica y producen la misma etiqueta."""
    como_tupla = _argumentos_validos()
    como_tupla["embeddings"] = ()
    como_lista = _argumentos_validos()
    como_lista["embeddings"] = []

    assert index_version(**como_tupla) == index_version(**como_lista) == "889bb6da042a"


@pytest.mark.parametrize("valor", [None, "[]", b"[]", 7, {"provider": "x"}, ({"provider": "x"},)])
def test_septimo_insumo_fuera_de_la_gramatica_falla_sin_sustituto(valor: object) -> None:
    """Un descriptor o un valor no secuencial se rechazan: no se completa ni se inventa."""
    argumentos = _argumentos_validos()
    argumentos["embeddings"] = valor

    with pytest.raises(ValueError):
        index_version(**argumentos)


def test_index_version_tiene_formato_de_doce_hexadecimales_minusculos() -> None:
    assert re.fullmatch(r"[0-9a-f]{12}", index_version(**_argumentos_validos()))


_VECTOR_OCTETOS_ESPECIALES = (
    rb'{"document_version":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
    rb'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","extractor":["pd\"f","4.00\\path/","cfg'
    rb"\u0000\u0001\u0002\u0003\u0004\u0005\u0006\u0007\u0008\u0009\u000a\u000b\u000c\u000d\u000e\u000f"
    rb'\u0010\u0011\u0012\u0013\u0014\u0015\u0016\u0017\u0018\u0019\u001a\u001b\u001c\u001d\u001e\u001f"],'
    rb'"chunking_config_version":"chunking-v1","tokenizer":"unicode61 remove_diacritics 2",'
    rb'"sqlite_version":"3.46.0","sqlite_vec_version":"0.1.6","embeddings":[]}'
)


def test_octetos_canonicos_escapan_comillas_barras_y_todos_los_controles() -> None:
    argumentos = _argumentos_validos()
    argumentos["extractor"] = (
        'pd"f',
        "4.00\\path/",
        "cfg" + "".join(chr(codigo) for codigo in range(0x20)),
    )
    datos = _bytes_canonicos(**argumentos)

    assert datos == _VECTOR_OCTETOS_ESPECIALES
    assert b'pd\\"f' in datos
    assert b"4.00\\\\path/" in datos
    assert b"\\u0009" in datos
    assert b"\\u000a" in datos
    assert b"\\t" not in datos
    assert b"\\n" not in datos
    assert b"/" in datos
    assert b"\\/" not in datos


def test_octetos_canonicos_emiten_unicode_literal_en_utf8_sin_bom() -> None:
    argumentos = _argumentos_validos()
    argumentos["extractor"] = ("extracción", "versión—1", "configuración-á")
    datos = _bytes_canonicos(**argumentos)

    assert b"\xc3\xa1" in datos
    assert b"\xe2\x80\x94" in datos
    assert b"\\u00e1" not in datos
    assert b"\\u2014" not in datos
    assert not datos.startswith(b"\xef\xbb\xbf")
    assert datos.decode("utf-8")


def test_octetos_canonicos_emiten_astrales_literalmente_sin_pares_sustitutos() -> None:
    """M1: un carácter fuera del BMP (U+1F600) se emite literal en UTF-8, nunca como par sustituto."""
    argumentos = _argumentos_validos()
    argumentos["extractor"] = ("pdftotext", "4.00", "cfg" + chr(0x1F600))
    datos = _bytes_canonicos(**argumentos)

    assert b"\xf0\x9f\x98\x80" in datos
    assert b"\\ud83d" not in datos
    assert b"\\ude00" not in datos
    assert datos.decode("utf-8")


@pytest.mark.parametrize(
    ("campo", "indice"),
    [
        ("extractor", 0),
        ("extractor", 1),
        ("extractor", 2),
        ("chunking_config_version", None),
        ("tokenizer", None),
    ],
)
def test_index_version_equivale_para_texto_nfc_y_no_nfc(campo: str, indice: int | None) -> None:
    argumentos_no_nfc = _argumentos_validos()
    argumentos_nfc = _argumentos_validos()
    if indice is None:
        argumentos_no_nfc[campo] = "e\u0301"
        argumentos_nfc[campo] = "é"
    else:
        extractor_no_nfc = list(argumentos_no_nfc["extractor"])
        extractor_nfc = list(argumentos_nfc["extractor"])
        extractor_no_nfc[indice] = "e\u0301"
        extractor_nfc[indice] = "é"
        argumentos_no_nfc["extractor"] = extractor_no_nfc
        argumentos_nfc["extractor"] = extractor_nfc

    assert index_version(**argumentos_no_nfc) == index_version(**argumentos_nfc)


@pytest.mark.parametrize(
    ("campo", "valor"),
    [
        ("document_version", "b" * 64),
        ("extractor", ("pdftotext", "4.01", "-layout -enc UTF-8")),
        ("chunking_config_version", "chunking-v2"),
        ("tokenizer", "unicode61 remove_diacritics 1"),
        ("sqlite_version", "3.46.1"),
        ("sqlite_vec_version", "0.1.7"),
    ],
)
def test_index_version_cambia_al_modificar_cada_insumo(campo: str, valor: object) -> None:
    original = index_version(**_argumentos_validos())
    argumentos = _argumentos_validos()
    argumentos[campo] = valor

    assert index_version(**argumentos) != original


@pytest.mark.parametrize(
    ("campo", "valor", "mensaje"),
    [
        ("document_version", None, "document_version debe ser una cadena"),
        ("document_version", "", "document_version no puede ser una cadena vacía"),
        ("document_version", 7, "document_version debe ser una cadena"),
        ("extractor", None, "extractor debe ser una secuencia ordenada de exactamente tres cadenas"),
        ("extractor", "", "extractor debe ser una secuencia ordenada de exactamente tres cadenas"),
        ("extractor", 7, "extractor debe ser una secuencia ordenada de exactamente tres cadenas"),
        ("chunking_config_version", None, "chunking_config_version debe ser una cadena"),
        ("chunking_config_version", "", "chunking_config_version no puede ser una cadena vacía"),
        ("chunking_config_version", 7, "chunking_config_version debe ser una cadena"),
        ("tokenizer", None, "tokenizer debe ser una cadena"),
        ("tokenizer", "", "tokenizer no puede ser una cadena vacía"),
        ("tokenizer", [], "tokenizer debe ser una cadena"),
        ("sqlite_version", None, "sqlite_version debe ser una cadena"),
        ("sqlite_version", "", "sqlite_version no puede ser una cadena vacía"),
        ("sqlite_version", 7, "sqlite_version debe ser una cadena"),
        ("sqlite_vec_version", None, "sqlite_vec_version debe ser una cadena"),
        ("sqlite_vec_version", "", "sqlite_vec_version no puede ser una cadena vacía"),
        ("sqlite_vec_version", [], "sqlite_vec_version debe ser una cadena"),
        (
            "chunking_config_version",
            "\ud800",
            "chunking_config_version debe poder codificarse en UTF-8",
        ),
    ],
)
def test_index_version_rechaza_cada_valor_invalido(campo: str, valor: object, mensaje: str) -> None:
    argumentos = _argumentos_validos()
    argumentos[campo] = valor

    with pytest.raises(ValueError, match=f"^{re.escape(mensaje)}$"):
        index_version(**argumentos)


@pytest.mark.parametrize(
    "campo",
    [
        "document_version",
        "extractor",
        "chunking_config_version",
        "tokenizer",
        "sqlite_version",
        "sqlite_vec_version",
    ],
)
def test_index_version_falla_si_se_omite_cualquier_insumo(campo: str) -> None:
    argumentos = _argumentos_validos()
    del argumentos[campo]

    with pytest.raises(TypeError):
        index_version(**argumentos)


@pytest.mark.parametrize(
    "extractor",
    [
        ("pdftotext", "4.00"),
        ("pdftotext", "4.00", "configuración", "extra"),
        ("pdftotext", "", "configuración"),
        ("pdftotext", 4, "configuración"),
        "pdf",
        {"pdftotext", "4.00", "configuración"},
        b"abc",
        b"pdftotext",
    ],
)
def test_index_version_rechaza_formas_invalidas_de_extractor(extractor: object) -> None:
    argumentos = _argumentos_validos()
    argumentos["extractor"] = extractor

    with pytest.raises(ValueError, match="extractor"):
        index_version(**argumentos)


def test_index_version_acepta_cualquier_secuencia_ordenada_de_tres_cadenas() -> None:
    argumentos_lista = _argumentos_validos()
    argumentos_lista["extractor"] = ["pdftotext", "4.00", "-layout -enc UTF-8"]

    assert index_version(**argumentos_lista) == index_version(**_argumentos_validos())


def test_index_version_rechaza_llamada_posicional_con_los_seis_argumentos() -> None:
    """M2: la firma es keyword-only; una llamada posicional no puede omitir el nombre de ningún insumo."""
    with pytest.raises(TypeError):
        index_version(
            "a" * 64,
            ("pdftotext", "4.00", "-layout -enc UTF-8"),
            "chunking-v1",
            "unicode61 remove_diacritics 2",
            "3.46.0",
            "0.1.6",
        )


def test_index_version_rechaza_keyword_inesperado() -> None:
    """M2: un keyword inesperado es un error explícito, no un insumo ignorado en silencio."""
    argumentos = _argumentos_validos()
    argumentos["sobrante"] = "x"

    with pytest.raises(TypeError):
        index_version(**argumentos)
