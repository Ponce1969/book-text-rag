"""Contrato de la secuencia T1/T2/T3 de `D-25`, con un escritor falso.

Comprueba el **orden** de las transacciones y la política de reintento cuando T2 falla, sin tocar el
motor ni ejecutar la extracción.
"""

from __future__ import annotations

import pytest

from book_text_rag.application.ingest_persistent import persist_unit
from book_text_rag.domain.models import CalibrationRecord, Counts, IngestTrace
from book_text_rag.ports.storage import StoreError, StoreErrorCode, UnitWrite, WriteOutcome

ESTADO_COMPLETADA = "ingesta completada e índice disponible para consulta"
ESTADO_DECISION = "decisión de identidad registrada"


def _unidad(document_id: str = "doc", alias: str = "pilot") -> UnitWrite:
    return UnitWrite(
        document_id=document_id,
        alias=alias,
        fecha="2026-10-17",
        fragments=(),
        trace=IngestTrace(
            document_version="a" * 64,
            extractor=["pdftotext", "4.00", "-layout -enc UTF-8"],
            geometry_tool="PyMuPDF 1.26.7",
            manifest_canonical="{}",
            chunking_config_version="0123456789ab",
            calibration=CalibrationRecord(
                procedure="anchoring/v1",
                entries=116,
                delta_pt=72.118,
                dispersion_pt=0.75,
                tolerance_pt=2.0,
                top_band_pt=200.0,
                heading_min_size_pt=18.403,
            ),
            counts=Counts(
                corpus_units=0,
                anchored_by_level={},
                fragments=0,
                table_blocks=0,
                page_number_lines_excluded=0,
                page_number_anomalies=0,
            ),
        ),
    )


class EscritorFalso:
    """Escritor de prueba: registra el orden de las llamadas y el estado de la referencia."""

    def __init__(self, *, fallar_en_t2: bool = False) -> None:
        self.llamadas: list[str] = []
        self.estado = "sin referencia"
        self._fallar_en_t2 = fallar_en_t2

    def register_reference(self, unit: UnitWrite) -> None:
        self.llamadas.append("T1")
        if self.estado == "sin referencia":
            self.estado = ESTADO_DECISION

    def mark_incomplete(self, document_id: str, alias: str) -> None:
        self.llamadas.append("T2")
        if self._fallar_en_t2:
            self._fallar_en_t2 = False
            raise StoreError(StoreErrorCode.ERROR_SQLITE, "fallo inyectado en T2")
        self.estado = "ingesta incompleta"

    def write_unit(self, unit: UnitWrite) -> WriteOutcome:
        self.llamadas.append("T3")
        self.estado = ESTADO_COMPLETADA
        return WriteOutcome(fragmentos_escritos=len(unit.fragments))


def test_secuencia_t1_t2_t3_en_orden() -> None:
    escritor = EscritorFalso()
    resultado = persist_unit(_unidad(), store=escritor)
    assert escritor.llamadas == ["T1", "T2", "T3"]
    assert escritor.estado == ESTADO_COMPLETADA
    assert resultado.fragmentos_escritos == 0


def test_fallo_en_t2_y_reintento_que_vuelve_a_intentar_t2_antes_de_t3() -> None:
    escritor = EscritorFalso(fallar_en_t2=True)
    with pytest.raises(StoreError) as info:
        persist_unit(_unidad(), store=escritor)
    assert info.value.code is StoreErrorCode.ERROR_SQLITE
    assert escritor.llamadas == ["T1", "T2"]
    assert escritor.estado == ESTADO_DECISION

    persist_unit(_unidad(), store=escritor)
    assert escritor.llamadas == ["T1", "T2", "T1", "T2", "T3"]
    assert escritor.estado == ESTADO_COMPLETADA
