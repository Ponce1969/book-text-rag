"""Contrato de `get_document` (`D-07`, `D-13`) en el alcance mínimo decidido (B1, B2, B4).

Cubre los dos casos aceptados —cero y una versión—, la resolución de la versión omitida, los rechazos
(el `invalid_request` de B2 y el rechazo interno de N ≥ 2 versiones), la ausencia de fragmentos en la
respuesta y la lectura pura.
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import fields
from pathlib import Path

import pytest

from book_text_rag.adapters.storage.sqlite import SqliteStore
from book_text_rag.application.get_document import EstadoPorVersionNoDefinido, get_document
from book_text_rag.domain.identity import chunk_id, content_hash, index_version
from book_text_rag.ports.storage import (
    DocumentStatus,
    DocumentView,
    EstadoIngesta,
    StoreError,
    StoreErrorCode,
)

DOC = "doc"
V1 = "a" * 64
V2 = "b" * 64
TOKENIZER = "unicode61 remove_diacritics 2"

_COLUMNAS_CONSTRUCCION = (
    "document_id, document_version, extractor_nombre, extractor_version, extractor_config_efectiva, "
    "geometry_tool, manifiesto_canonico, chunking_config_version, calibracion_procedimiento, "
    "calibracion_entradas, calibracion_delta_pt, calibracion_dispersion_pt, calibracion_tolerancia_pt, "
    "calibracion_banda_pt, calibracion_umbral_tamano_pt, escala_entradas_corregidas, escala_factor, "
    "escala_residuo_max_pt, escala_destinos_inutilizables, recuento_unidades_corpus, "
    "recuento_ancladas_por_nivel, recuento_fragmentos, recuento_bloques_tabla, recuento_lineas_excluidas, "
    "recuento_anomalias_pagina, paginas_anomalas, tokenizer, sqlite_version, sqlite_vec_version"
)


def _huella(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def _laterales(ruta: Path) -> list[str]:
    return sorted(path.name for path in ruta.parent.glob(f"{ruta.name}-*"))


def _sembrar(
    ruta: Path,
    *,
    versiones: tuple[str, ...] = (V1,),
    estados: tuple[EstadoIngesta, ...] = (EstadoIngesta.COMPLETADA,),
    source_format: str | None = "pdf",
    page_count: int | None = 784,
    con_fuente: bool = True,
    con_construccion: bool = True,
) -> None:
    """Almacén válido con metadatos de fuente, referencias (una por estado) y versiones registradas."""
    SqliteStore(ruta).initialize()
    conexion = sqlite3.connect(ruta)
    try:
        if con_fuente:
            conexion.execute(
                "INSERT INTO fuente (document_id, source_format, page_count) VALUES (?, ?, ?)",
                (DOC, source_format, page_count),
            )
        for indice, estado in enumerate(estados):
            conexion.execute(
                "INSERT INTO referencia_fuente (document_id, alias, tipo_asignacion, fecha, estado_ingesta) "
                "VALUES (?, ?, ?, ?, ?)",
                (DOC, f"alias-{indice}", "deliberada", "2026-10-22", estado.value),
            )
        for version in versiones:
            contenido = "evidencia textual con procedencia verificable"
            conexion.execute(
                "INSERT INTO version_documento (document_id, document_version) VALUES (?, ?)", (DOC, version)
            )
            conexion.execute(
                "INSERT INTO fragmento (document_id, document_version, ordinal, chunk_id, section_path, level, "
                "block_type, captions, pdf_page_start, pdf_page_end, content, content_hash, anchor_level) "
                "VALUES (?, ?, 1, ?, '[]', 1, 'prose', '[]', 25, 25, ?, ?, 'posicional')",
                (DOC, version, chunk_id(DOC, version[:12], 1), contenido, content_hash(contenido)),
            )
            conexion.execute(
                "INSERT INTO fragmento_fts (document_id, document_version, ordinal, content) VALUES (?, ?, 1, ?)",
                (DOC, version, contenido),
            )
            if con_construccion:
                conexion.execute(
                    f"INSERT INTO construccion ({_COLUMNAS_CONSTRUCCION}) "
                    "VALUES (?, ?, 'pdftotext', '4.00', '-layout -enc UTF-8', 'PyMuPDF 1.26.7', '{}', "
                    "'chunking-v1', 'calibracion de prueba', 0, 0.0, 0.0, 0.0, 0.0, 0.0, 0, NULL, NULL, 0, "
                    "1, '{}', 1, 0, 0, 0, '[]', ?, ?, '0.1.9')",
                    (DOC, version, TOKENIZER, sqlite3.sqlite_version),
                )
        conexion.commit()
    finally:
        conexion.close()


def _valor_de_la_construccion(version: str) -> str:
    return index_version(
        document_version=version,
        extractor=("pdftotext", "4.00", "-layout -enc UTF-8"),
        chunking_config_version="chunking-v1",
        tokenizer=TOKENIZER,
        sqlite_version=sqlite3.sqlite_version,
        sqlite_vec_version="0.1.9",
        embeddings=(),
    )


def test_una_version_completada_proyecta_los_siete_campos(tmp_path: Path) -> None:
    ruta = tmp_path / "una.sqlite"
    _sembrar(ruta)

    vista = get_document(SqliteStore(ruta), DOC)

    assert vista == DocumentView(
        document_id=DOC,
        document_version=V1,
        title=None,
        source_format="pdf",
        page_count=784,
        index_version=_valor_de_la_construccion(V1),
        status=DocumentStatus.INDEXED,
    )


@pytest.mark.parametrize("estado", [EstadoIngesta.INCOMPLETA, EstadoIngesta.DECISION_REGISTRADA])
def test_una_version_no_completada_es_not_indexed(tmp_path: Path, estado: EstadoIngesta) -> None:
    ruta = tmp_path / "parcial.sqlite"
    _sembrar(ruta, estados=(estado,))

    vista = get_document(SqliteStore(ruta), DOC)

    assert vista.status is DocumentStatus.NOT_INDEXED
    assert vista.document_version == V1


def test_referencias_que_discrepan_no_se_presentan_como_indexed(tmp_path: Path) -> None:
    """Interpretación conservadora de `D-13`: `indexed` solo si **todos** los estados son «completada»."""
    ruta = tmp_path / "discrepan.sqlite"
    _sembrar(ruta, estados=(EstadoIngesta.COMPLETADA, EstadoIngesta.INCOMPLETA))

    assert get_document(SqliteStore(ruta), DOC).status is DocumentStatus.NOT_INDEXED


def test_cero_versiones_es_not_indexed_con_nulos_y_metadatos_de_fuente(tmp_path: Path) -> None:
    """B4: la ausencia de versiones no es `document_not_found`."""
    ruta = tmp_path / "sin_versiones.sqlite"
    _sembrar(ruta, versiones=())

    vista = get_document(SqliteStore(ruta), DOC)

    assert vista == DocumentView(
        document_id=DOC,
        document_version=None,
        title=None,
        source_format="pdf",
        page_count=784,
        index_version=None,
        status=DocumentStatus.NOT_INDEXED,
    )


def test_cero_versiones_sin_metadatos_declara_nulos(tmp_path: Path) -> None:
    ruta = tmp_path / "sin_metadatos.sqlite"
    _sembrar(ruta, versiones=(), source_format=None, page_count=None)

    vista = get_document(SqliteStore(ruta), DOC)

    assert (vista.source_format, vista.page_count, vista.document_version) == (None, None, None)


def test_documento_sin_referencia_es_document_not_found(tmp_path: Path) -> None:
    ruta = tmp_path / "sin_referencia.sqlite"
    _sembrar(ruta, versiones=(), con_fuente=True)
    conexion = sqlite3.connect(ruta)
    try:
        conexion.execute("DELETE FROM referencia_fuente")
        conexion.commit()
    finally:
        conexion.close()

    with pytest.raises(StoreError) as error:
        get_document(SqliteStore(ruta), DOC)

    assert error.value.code is StoreErrorCode.DOCUMENT_NOT_FOUND
    assert error.value.details["document_id"] == DOC


def test_version_explicita_no_registrada_es_document_not_found(tmp_path: Path) -> None:
    ruta = tmp_path / "otra_version.sqlite"
    _sembrar(ruta)

    with pytest.raises(StoreError) as error:
        get_document(SqliteStore(ruta), DOC, V2)

    assert error.value.code is StoreErrorCode.DOCUMENT_NOT_FOUND
    assert error.value.details["document_version"] == V2


def test_cero_versiones_con_version_explicita_es_document_not_found(tmp_path: Path) -> None:
    ruta = tmp_path / "cero_con_version.sqlite"
    _sembrar(ruta, versiones=())

    with pytest.raises(StoreError) as error:
        get_document(SqliteStore(ruta), DOC, V1)

    assert error.value.code is StoreErrorCode.DOCUMENT_NOT_FOUND


def test_dos_versiones_sin_parametro_es_invalid_request_con_field(tmp_path: Path) -> None:
    ruta = tmp_path / "dos_sin_parametro.sqlite"
    _sembrar(ruta, versiones=(V1, V2))

    with pytest.raises(StoreError) as error:
        get_document(SqliteStore(ruta), DOC)

    assert error.value.code is StoreErrorCode.INVALID_REQUEST
    assert error.value.details["field"] == "document_version"


def test_dos_versiones_con_version_explicita_se_rechaza_internamente(tmp_path: Path) -> None:
    """N ≥ 2 versiones: rechazo interno antes de construir la vista, sin código público ni `status`."""
    ruta = tmp_path / "dos_con_parametro.sqlite"
    _sembrar(ruta, versiones=(V1, V2))

    with pytest.raises(EstadoPorVersionNoDefinido) as error:
        get_document(SqliteStore(ruta), DOC, V1)

    assert not isinstance(error.value, StoreError)
    assert getattr(error.value, "code", None) is None
    assert "document_id='doc'" in str(error.value)


def test_almacen_no_disponible_es_index_unavailable(tmp_path: Path) -> None:
    ruta = tmp_path / "ausente.sqlite"

    with pytest.raises(StoreError) as error:
        get_document(SqliteStore(ruta), DOC)

    assert error.value.code is StoreErrorCode.INDEX_UNAVAILABLE
    assert not ruta.exists()


def test_una_version_sin_construccion_declara_index_version_nulo(tmp_path: Path) -> None:
    ruta = tmp_path / "sin_construccion.sqlite"
    _sembrar(ruta, con_construccion=False)

    vista = get_document(SqliteStore(ruta), DOC)

    assert vista.index_version is None
    assert vista.status is DocumentStatus.INDEXED


def test_la_respuesta_no_contiene_fragmentos_ni_identificadores_internos(tmp_path: Path) -> None:
    ruta = tmp_path / "forma.sqlite"
    _sembrar(ruta)

    vista = get_document(SqliteStore(ruta), DOC)

    assert tuple(campo.name for campo in fields(DocumentView)) == (
        "document_id",
        "document_version",
        "title",
        "source_format",
        "page_count",
        "index_version",
        "status",
    )
    assert not {"fragments", "content", "chunk_id", "ordinal", "rowid", "anchor_evidence"} & set(vars(vista))


def test_lectura_pura_sin_escritura_ni_laterales(tmp_path: Path) -> None:
    ruta = tmp_path / "pura.sqlite"
    _sembrar(ruta)
    antes = _huella(ruta)

    get_document(SqliteStore(ruta), DOC)
    get_document(SqliteStore(ruta), DOC, V1)

    assert _huella(ruta) == antes
    assert _laterales(ruta) == []
