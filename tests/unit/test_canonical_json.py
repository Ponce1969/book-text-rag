"""Serialización canónica y normalización NFC al persistir (`D-6`, `D-23`, `D-25`)."""

from __future__ import annotations

import unicodedata

from book_text_rag.adapters.storage.sqlite import _nfc, json_canonico


def test_json_canonico_es_compacto_y_ordena_claves() -> None:
    assert json_canonico({"b": 2, "a": 1}) == '{"a":1,"b":2}'
    assert json_canonico({"posicional": 133, "pagina+tipografia": 33}) == ('{"pagina+tipografia":33,"posicional":133}')


def test_json_canonico_de_arreglos_y_vacio() -> None:
    assert json_canonico([184, 229]) == "[184,229]"
    assert json_canonico([]) == "[]"


def test_json_canonico_no_escapa_no_ascii() -> None:
    assert json_canonico(["capítulo"]) == '["capítulo"]'
    assert "\\u" not in json_canonico(["capítulo"])


def test_nfc_normaliza_texto_descompuesto() -> None:
    descompuesto = "capi\u0301tulo"
    assert descompuesto != unicodedata.normalize("NFC", descompuesto)
    assert _nfc(descompuesto) == "capítulo"
    assert json_canonico([_nfc(descompuesto)]) == '["capítulo"]'
