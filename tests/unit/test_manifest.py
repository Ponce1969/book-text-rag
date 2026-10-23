"""Manifiesto v2: quince campos, orden, valores y serialización canónica (D-10, D-11 §4, D-19 §3)."""

from __future__ import annotations

import hashlib
import unicodedata

import pytest

from book_text_rag.domain.manifest import (
    MANIFEST_SCHEMA,
    Manifest,
    canonical_manifest,
    chunking_config_version,
    default_manifest,
    validate_manifest,
)
from book_text_rag.domain.models import ErrorCode, IngestError

EXPECTED_KEYS = [
    "schema",
    "segmentation_unit",
    "heading_start",
    "split_boundary",
    "parent_own_text",
    "table_blocks",
    "excluded_regions",
    "overlap_scope",
    "count_unit",
    "max_words",
    "overlap_words",
    "content_end",
    "page_furniture",
    "anchoring_procedure",
    "geometry_tool",
]


def test_manifiesto_tiene_quince_campos_en_orden() -> None:
    manifest = default_manifest("PyMuPDF 1.26.7")
    assert [name for name, _ in manifest.as_ordered_pairs()] == EXPECTED_KEYS
    assert len(EXPECTED_KEYS) == 15
    assert manifest.schema_ == MANIFEST_SCHEMA == "chunking_config/v3"


def test_bytes_canonicos_exactos() -> None:
    manifest = default_manifest("PyMuPDF 0.0.0-fake")
    expected = (
        '{"schema":"chunking_config/v3","segmentation_unit":"hierarchy_leaf","heading_start":true,'
        '"split_boundary":"paragraph_within_unit","parent_own_text":"own_fragment","table_blocks":"atomic",'
        '"excluded_regions":["front_matter","back_matter","index"],"overlap_scope":"same_unit",'
        '"count_unit":"words","max_words":1500,"overlap_words":0,"content_end":"next_heading",'
        '"page_furniture":"excluded","anchoring_procedure":"anchoring/v1",'
        '"geometry_tool":"PyMuPDF 0.0.0-fake"}'
    )
    canonical = canonical_manifest(manifest)
    assert canonical == expected
    assert not canonical.endswith("\n")
    assert " " not in canonical.replace("PyMuPDF 0.0.0-fake", "")


def test_reglas_de_escape_y_nfc() -> None:
    base = default_manifest("x")
    tricky = base.model_copy(update={"geometry_tool": 'T"X\\Y\t\u0001 n\u0303/ñ'})
    canonical = canonical_manifest(tricky)
    assert '\\"' in canonical
    assert "\\\\" in canonical
    assert "\\u0009" in canonical
    assert "\\u0001" in canonical
    assert "\t" not in canonical
    assert unicodedata.normalize("NFC", "ñ") in canonical
    assert "n\u0303" not in canonical
    assert "/" in canonical and "\\/" not in canonical


def test_huella_truncada_es_sha256() -> None:
    manifest = default_manifest("PyMuPDF 1.26.7")
    canonical = canonical_manifest(manifest)
    expected = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]
    assert chunking_config_version(manifest) == expected
    assert len(expected) == 12


@pytest.mark.parametrize(
    ("field", "value"),
    [("count_unit", "chars"), ("content_end", "page_end"), ("geometry_tool", " ")],
)
def test_manifiesto_invalido_es_rechazado(field: str, value: str) -> None:
    manifest: Manifest = default_manifest("PyMuPDF 1.26.7").model_copy(update={field: value})
    with pytest.raises(IngestError) as error:
        validate_manifest(manifest)
    assert error.value.code is ErrorCode.CONFIG_INVALID


def test_max_words_no_positivo_es_rechazado() -> None:
    manifest: Manifest = default_manifest("PyMuPDF 1.26.7").model_copy(update={"max_words": 0})
    with pytest.raises(IngestError) as error:
        validate_manifest(manifest)
    assert error.value.code is ErrorCode.CONFIG_INVALID
