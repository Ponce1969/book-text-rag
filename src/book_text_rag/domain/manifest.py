"""Manifiesto declarativo y su serialización canónica (D-10, D-11 §4, D-19 §3, D-20 §2.4).

La lista de campos y sus valores adoptados provienen de D-10 (once campos) más las tres reglas
incorporadas por D-19 §3 (`content_end`, `page_furniture`, `anchoring_procedure`) y el campo
`geometry_tool` decidido por el propietario al autorizar la segunda herramienta. La versión de
esquema queda en una única constante (`MANIFEST_SCHEMA`) porque la enmienda documental de D-10 que
la fija como quince campos está preparada aparte, sin aplicar.
"""

from __future__ import annotations

import hashlib
import unicodedata

from pydantic import BaseModel

from book_text_rag.domain.models import ErrorCode, IngestError

MANIFEST_SCHEMA = "chunking_config/v3"
ANCHORING_PROCEDURE = "anchoring/v1"
"""Las fronteras del corpus **no** se fijan aquí: se derivan del outline de cada libro (`body_start`
para el inicio y el apartado `Index` para el fin, `D-10` pto. iv). Las antiguas constantes del piloto
(`25` y `716`, de `D-01`) dejaron de usarse como límites universales."""

_STR_VALUE_FIELDS = (
    "segmentation_unit",
    "split_boundary",
    "parent_own_text",
    "table_blocks",
    "overlap_scope",
    "count_unit",
    "content_end",
    "page_furniture",
    "anchoring_procedure",
)

ADOPTED_STR_VALUES: dict[str, str] = {
    "segmentation_unit": "hierarchy_leaf",
    "split_boundary": "paragraph_within_unit",
    "parent_own_text": "own_fragment",
    "table_blocks": "atomic",
    "overlap_scope": "same_unit",
    "count_unit": "words",
    "content_end": "next_heading",
    "page_furniture": "excluded",
    "anchoring_procedure": ANCHORING_PROCEDURE,
}


class Manifest(BaseModel):
    """Manifiesto declarativo: enuncia qué reglas se aplicaron (D-10; quince campos)."""

    schema_: str
    segmentation_unit: str
    heading_start: bool
    split_boundary: str
    parent_own_text: str
    table_blocks: str
    excluded_regions: list[str]
    overlap_scope: str
    count_unit: str
    max_words: int
    overlap_words: int
    content_end: str
    page_furniture: str
    anchoring_procedure: str
    geometry_tool: str

    def as_ordered_pairs(self) -> list[tuple[str, object]]:
        """Pares en el orden declarado por D-10 más el campo nuevo al final."""
        return [
            ("schema", self.schema_),
            ("segmentation_unit", self.segmentation_unit),
            ("heading_start", self.heading_start),
            ("split_boundary", self.split_boundary),
            ("parent_own_text", self.parent_own_text),
            ("table_blocks", self.table_blocks),
            ("excluded_regions", list(self.excluded_regions)),
            ("overlap_scope", self.overlap_scope),
            ("count_unit", self.count_unit),
            ("max_words", self.max_words),
            ("overlap_words", self.overlap_words),
            ("content_end", self.content_end),
            ("page_furniture", self.page_furniture),
            ("anchoring_procedure", self.anchoring_procedure),
            ("geometry_tool", self.geometry_tool),
        ]


def default_manifest(geometry_tool: str) -> Manifest:
    """Manifiesto con los valores adoptados en D-10/D-19 §3 y la herramienta de geometría efectiva."""
    return Manifest(
        schema_=MANIFEST_SCHEMA,
        segmentation_unit=ADOPTED_STR_VALUES["segmentation_unit"],
        heading_start=True,
        split_boundary=ADOPTED_STR_VALUES["split_boundary"],
        parent_own_text=ADOPTED_STR_VALUES["parent_own_text"],
        table_blocks=ADOPTED_STR_VALUES["table_blocks"],
        excluded_regions=["front_matter", "back_matter", "index"],
        overlap_scope=ADOPTED_STR_VALUES["overlap_scope"],
        count_unit=ADOPTED_STR_VALUES["count_unit"],
        max_words=1500,
        overlap_words=0,
        content_end=ADOPTED_STR_VALUES["content_end"],
        page_furniture=ADOPTED_STR_VALUES["page_furniture"],
        anchoring_procedure=ADOPTED_STR_VALUES["anchoring_procedure"],
        geometry_tool=geometry_tool,
    )


def validate_manifest(manifest: Manifest) -> None:
    """Rechaza un manifiesto incompleto o con valores fuera del conjunto adoptado (D-20 §5)."""
    if manifest.schema_ != MANIFEST_SCHEMA:
        raise IngestError(
            ErrorCode.CONFIG_INVALID,
            "el esquema del manifiesto no es el vigente",
            schema=manifest.schema_,
            esperado=MANIFEST_SCHEMA,
        )
    for field in _STR_VALUE_FIELDS:
        got = getattr(manifest, field)
        expected = ADOPTED_STR_VALUES[field]
        if got != expected:
            raise IngestError(
                ErrorCode.CONFIG_INVALID,
                "valor de manifiesto fuera del conjunto adoptado",
                campo=field,
                valor=got,
                esperado=expected,
            )
    if list(manifest.excluded_regions) != ["front_matter", "back_matter", "index"]:
        raise IngestError(
            ErrorCode.CONFIG_INVALID,
            "regiones excluidas fuera del conjunto adoptado",
            valor=list(manifest.excluded_regions),
        )
    if manifest.overlap_words != 0:
        raise IngestError(ErrorCode.CONFIG_INVALID, "overlap_words debe ser 0", valor=manifest.overlap_words)
    if manifest.max_words <= 0:
        raise IngestError(ErrorCode.CONFIG_INVALID, "max_words debe ser positivo", valor=manifest.max_words)
    if not manifest.heading_start:
        raise IngestError(ErrorCode.CONFIG_INVALID, "heading_start debe ser true", valor=manifest.heading_start)
    if not manifest.geometry_tool.strip():
        raise IngestError(ErrorCode.CONFIG_INVALID, "geometry_tool no puede estar vacío")


def _emit_str(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value)
    out: list[str] = ['"']
    for char in normalized:
        code = ord(char)
        if char == '"':
            out.append('\\"')
        elif char == "\\":
            out.append("\\\\")
        elif code < 0x20:
            out.append(f"\\u{code:04x}")
        else:
            out.append(char)
    out.append('"')
    return "".join(out)


def _emit(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return _emit_str(value)
    if isinstance(value, list):
        return "[" + ",".join(_emit(item) for item in value) + "]"
    raise TypeError(f"tipo no serializable en el manifiesto: {type(value)!r}")


def canonical_manifest(manifest: Manifest) -> str:
    """Bytes canónicos del manifiesto (D-10 «Serialización canónica» + D-11 §4)."""
    items = ",".join(f"{_emit_str(name)}:{_emit(value)}" for name, value in manifest.as_ordered_pairs())
    return "{" + items + "}"


def chunking_config_version(manifest: Manifest) -> str:
    """Huella del manifiesto: SHA-256 hex minúsculas truncada a 12 caracteres (D-10 «Algoritmo»)."""
    digest = hashlib.sha256(canonical_manifest(manifest).encode("utf-8")).hexdigest()
    return digest[:12]
