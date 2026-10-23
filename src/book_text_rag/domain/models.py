"""Modelos de la unidad 1 en memoria (contrato D-20 §3 y §5).

Todos los campos provienen de D-20 §3.1 (registro de fragmento), §3.2 (traza de ingesta) y §5
(los ocho códigos de error del camino de ingesta).
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ErrorCode(StrEnum):
    """Códigos internos del camino de ingesta (D-20 §5). No son el enum público de D-07."""

    SOURCE_UNREADABLE = "source_unreadable"
    EXTRACTOR_UNAVAILABLE = "extractor_unavailable"
    EXTRACTION_FAILED = "extraction_failed"
    DECODE_ERROR = "decode_error"
    OUTLINE_UNAVAILABLE = "outline_unavailable"
    CALIBRATION_FAILED = "calibration_failed"
    UNIT_NOT_ANCHORED = "unit_not_anchored"
    CONFIG_INVALID = "config_invalid"


class IngestError(Exception):
    """Error explícito del camino de ingesta: detiene la corrida y no produce salida parcial."""

    def __init__(self, code: ErrorCode, message: str, **details: object) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details: dict[str, object] = dict(details)

    def __str__(self) -> str:
        return f"{self.code.value}: {self.message}"


class AnchorLevel(StrEnum):
    """Niveles de evidencia del anclaje (D-17 §3)."""

    POSITIONAL = "posicional"
    PAGE_TYPOGRAPHY = "pagina+tipografia"


class DestinationUse(StrEnum):
    """Uso del destino del outline en el anclaje, registrado por unidad (decisión B del propietario).

    `VALID` = el destino entra tal cual; `SCALE_CORRECTED` = el destino venía en un espacio de
    coordenadas escalado (anomalía del outline) y se corrigió con un factor declarado;
    `UNUSABLE` = el destino no se usa y la unidad se ancla por página y tipografía (D-17 §3).
    """

    VALID = "valid"
    SCALE_CORRECTED = "scale_corrected"
    UNUSABLE = "unusable"


class BlockType(StrEnum):
    """Tipo de bloque del fragmento (D-05 pto. 5 y pto. 8; nombres internos confirmados)."""

    PROSE = "prose"
    TABLE = "table"


class UnitKind(StrEnum):
    """Naturaleza de la entrada del corpus (D-05 ptos. 1 y 4)."""

    LEAF = "leaf"
    PARENT_OWN = "parent_own"


class Line(BaseModel):
    """Línea de la página con su tipografía y su coordenada vertical (herramienta de geometría)."""

    model_config = ConfigDict(frozen=True)

    text: str
    y0: float
    y1: float
    size: float
    font: str
    bold: bool


class TocEntry(BaseModel):
    """Entrada del outline: nivel, título, página física 1-based y coordenada del destino si existe."""

    model_config = ConfigDict(frozen=True)

    level: int
    title: str
    page: int
    y_dest: float | None = None


class OutlineUnit(BaseModel):
    """Unidad del corpus derivada del outline (D-05 pto. 1: hoja más profunda disponible)."""

    title: str
    level: int
    page: int
    section_path: list[str]
    kind: UnitKind
    ordinal: int
    y_dest: float | None = None


class AnchorEvidence(BaseModel):
    """Evidencia del anclaje registrada por unidad (D-20 §3.1 y D-17 §6.1)."""

    page: int
    y0: float | None = None
    y_dest: float | None = None
    destination_use: DestinationUse = DestinationUse.VALID


class FragmentRecord(BaseModel):
    """Registro de fragmento (D-20 §3.1)."""

    document_id: str
    document_version: str
    document_version_short: str
    chunk_id: str
    ordinal: int
    section_path: list[str]
    level: int
    block_type: BlockType
    captions: list[str] = Field(default_factory=list)
    pdf_page_start: int | None = None
    pdf_page_end: int | None = None
    content: str
    word_count: int
    content_hash: str
    anchor_level: AnchorLevel
    anchor_evidence: AnchorEvidence


class CalibrationRecord(BaseModel):
    """Calibración documental del anclaje (D-17 §4.3 y §4.5; D-20 §3.2).

    Los campos `outline_scale_*` y `destinations_unusable` registran el artefacto de escala detectado
    y las entradas cuyo destino no se usa (decisión B del propietario): nunca se compensa en silencio.
    """

    procedure: str
    entries: int
    delta_pt: float
    dispersion_pt: float
    tolerance_pt: float
    top_band_pt: float
    heading_min_size_pt: float
    heading_min_ratio: float = 0.0
    outline_scale_anomalies: int = 0
    outline_scale_factor: float | None = None
    outline_scale_residual_max_pt: float | None = None
    destinations_unusable: int = 0


class CalibrationPlan(BaseModel):
    """Calibración más la decisión de uso del destino de cada entrada del outline."""

    record: CalibrationRecord
    decisions: dict[str, DestinationUse] = Field(default_factory=dict)
    corrected_y: dict[str, float] = Field(default_factory=dict)


class Counts(BaseModel):
    """Recuentos de la ingesta (D-20 §3.2).

    `tail_words_total` y `tail_words_predecessor_same_page` se agregan `[P]` porque D-20 §7.3 los
    exige como criterio de comparación del piloto: son métricas de verificación, no del contrato de
    fragmento.
    """

    corpus_units: int
    anchored_by_level: dict[str, int]
    fragments: int
    table_blocks: int
    page_number_lines_excluded: int
    page_number_anomalies: int
    paginas_anomalas: list[int] = Field(default_factory=list)
    tail_words_total: int = 0
    tail_words_predecessor_same_page: int = 0
    tail_blocks_with_caption: int = 0


class IngestTrace(BaseModel):
    """Traza de ingesta (D-20 §3.2). `temporal_mark` queda fuera de la comparación (D-20 §6)."""

    document_version: str
    extractor: list[str]
    geometry_tool: str
    manifest_canonical: str
    chunking_config_version: str
    calibration: CalibrationRecord
    counts: Counts
    temporal_mark: str | None = None


class IngestResult(BaseModel):
    """Salida de la unidad: fragmentos en orden de lectura y traza (D-20 §3)."""

    fragments: list[FragmentRecord]
    trace: IngestTrace
