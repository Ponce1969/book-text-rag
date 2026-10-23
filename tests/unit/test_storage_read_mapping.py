"""Mapeo inverso fila -> `FragmentRead` (incremento 3).

Comprueba que la lectura no inventa valores: los enums se reconstruyen, los arreglos JSON canónicos se
decodifican y un `null` persistido se conserva `null` (`D-22` §5). Un contenido inválido **falla de
forma explícita**: no se tolera ni se sustituye.
"""

from __future__ import annotations

import pytest

from book_text_rag.adapters.storage import sqlite as sqlite_module
from book_text_rag.domain.models import AnchorLevel, BlockType
from book_text_rag.ports.storage import StoreError, StoreErrorCode

FILA = (
    7,
    "doc:abc123def456:7",
    '["Capítulo 1", "Sección 1.2"]',
    2,
    "prose",
    '["Figura 1.1"]',
    41,
    42,
    "contenido del fragmento",
    "a" * 64,
    "posicional",
)


def test_mapeo_completo_de_una_fila() -> None:
    leido = sqlite_module._fragmento_leido(FILA)
    assert leido.ordinal == 7
    assert leido.chunk_id == "doc:abc123def456:7"
    assert leido.section_path == ("Capítulo 1", "Sección 1.2")
    assert leido.level == 2
    assert leido.block_type is BlockType.PROSE
    assert leido.captions == ("Figura 1.1",)
    assert leido.pdf_page_start == 41
    assert leido.pdf_page_end == 42
    assert leido.content == "contenido del fragmento"
    assert leido.content_hash == "a" * 64
    assert leido.anchor_level is AnchorLevel.POSITIONAL


def test_null_se_conserva_null_y_los_arreglos_vacios() -> None:
    fila = (1, "c", "[]", 1, "table", "[]", None, None, "", "b" * 64, "pagina+tipografia")
    leido = sqlite_module._fragmento_leido(fila)
    assert leido.pdf_page_start is None
    assert leido.pdf_page_end is None
    assert leido.section_path == ()
    assert leido.captions == ()
    assert leido.content == ""
    assert leido.block_type is BlockType.TABLE
    assert leido.anchor_level is AnchorLevel.PAGE_TYPOGRAPHY


@pytest.mark.parametrize(
    ("indice", "valor", "columna"),
    [
        (2, "no es json", "section_path"),
        (5, '{"a": 1}', "captions"),
        (5, '["a", 3]', "captions"),
        (0, "siete", "ordinal"),
        (3, None, "level"),
    ],
)
def test_valores_invalidos_fallan_de_forma_explicita(indice: int, valor: object, columna: str) -> None:
    fila = list(FILA)
    fila[indice] = valor
    with pytest.raises(StoreError) as info:
        sqlite_module._fragmento_leido(tuple(fila))
    assert info.value.code is StoreErrorCode.ERROR_SQLITE
    assert info.value.details["columna"] == columna


@pytest.mark.parametrize(("indice", "valor"), [(4, "otro"), (10, "otro")])
def test_enum_desconocido_falla_de_forma_explicita(indice: int, valor: str) -> None:
    fila = list(FILA)
    fila[indice] = valor
    with pytest.raises(StoreError) as info:
        sqlite_module._fragmento_leido(tuple(fila))
    assert info.value.code is StoreErrorCode.ERROR_SQLITE
