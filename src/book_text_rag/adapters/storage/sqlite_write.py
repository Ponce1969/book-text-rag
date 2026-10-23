"""Persistencia del almacén: T1/T2/T3 (`D-25`) y sus auxiliares de escritura.

Separado de `sqlite.py` (incrementos B1 y B2 de la división por responsabilidades): aquí vive la
secuencia de escritura —T1 registra la referencia, T2 deja durable «ingesta incompleta», T3 persiste la
unidad en una transacción y fija «ingesta completada»— con sus funciones de inserción, la **reconstrucción
del índice derivado** (operación explícita de mantenimiento, no de lectura) y los auxiliares que solo
esta mitad usa. El camino de lectura, la verificación y la búsqueda siguen en `sqlite.py`.

**Este módulo no es el único que abre conexiones de escritura:** la aplicación del `DDL` (`_crear`)
permanece en `sqlite.py` y usa `_abrir_escritura`. Esa es la única limitación que queda declarada de la
división.

Las transacciones conservan los límites de `D-25`: T1, T2 y T3 abren **cada una** su conexión
(`isolation_level=None`) y T3 envuelve sus escrituras en `BEGIN IMMEDIATE` con `ROLLBACK` protegido.
"""

from __future__ import annotations

import contextlib
import importlib.metadata
import json
import sqlite3
import unicodedata
from pathlib import Path

from book_text_rag.adapters.storage.sqlite_schema import (
    SCHEMA_VERSION,
    SQLITE_VEC_PIN,
    TIPO_ASIGNACION_DELIBERADA,
    TOKENIZER_FTS,
    _abrir_escritura,
    _abrir_lectura_valida,
    _consultar,
    _entero,
    _referencias,
    _version_registrada,
)
from book_text_rag.domain.identity import chunk_id, content_hash, document_version_short
from book_text_rag.domain.models import FragmentRecord
from book_text_rag.ports.storage import (
    EstadoIngesta,
    RebuildOutcome,
    StoreError,
    StoreErrorCode,
    UnitWrite,
    WriteOutcome,
)


def json_canonico(valor: object) -> str:
    """Serialización canónica acordada: JSON compacto, sin escapar no-ASCII y con claves ordenadas."""
    return json.dumps(valor, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _nfc(texto: str) -> str:
    """Normalización NFC **al persistir** para los campos de texto no-contenido (`D-6`)."""
    return unicodedata.normalize("NFC", texto)


def _sqlite_vec_version() -> tuple[str, bool]:
    """Valor del pin y si se pudo **verificar** contra la distribución instalada (`D-24`).

    Distribución ausente ⇒ se usa el pin y se **declara** que la versión efectiva no se verificó.
    Distribución presente con otra versión ⇒ **fallo explícito**. El código `version_no_coincide` está
    registrado por `D-24` pero **no implementado**; hasta entonces la discrepancia usa `error_sqlite`.
    """
    try:
        instalada = importlib.metadata.version("sqlite-vec")
    except importlib.metadata.PackageNotFoundError:
        return SQLITE_VEC_PIN, False
    if instalada != SQLITE_VEC_PIN:
        raise StoreError(
            StoreErrorCode.ERROR_SQLITE,
            "la versión instalada de `sqlite-vec` no coincide con el pin de `D-02`",
            instalada=instalada,
            pin=SQLITE_VEC_PIN,
        )
    return SQLITE_VEC_PIN, True


def _verificar_unidad(unit: UnitWrite) -> None:
    """Contrasta `content_hash` y `chunk_id` de cada fragmento antes de escribir (`D-22` §2 y §9)."""
    version_corta = document_version_short(unit.trace.document_version)
    for fragmento in unit.fragments:
        if content_hash(fragmento.content) != fragmento.content_hash:
            raise StoreError(
                StoreErrorCode.CONTENIDO_DIVERGENTE,
                "el `content_hash` del fragmento no coincide con su contenido",
                ordinal=fragmento.ordinal,
            )
        esperado = chunk_id(unit.document_id, version_corta, fragmento.ordinal)
        if esperado != fragmento.chunk_id:
            raise StoreError(
                StoreErrorCode.CONTENIDO_DIVERGENTE,
                "el `chunk_id` del fragmento no es reconstruible",
                ordinal=fragmento.ordinal,
                esperado=esperado,
                obtenido=fragmento.chunk_id,
            )


def _t1_registrar_referencia(ruta: Path, unit: UnitWrite) -> None:
    """**T1:** registra la fuente y la referencia **sin** degradar un estado previo."""
    conexion = _abrir_escritura(ruta)
    try:
        conexion.execute("PRAGMA foreign_keys = ON")
        conexion.execute(
            "INSERT OR IGNORE INTO fuente (document_id, source_format, page_count) VALUES (?, ?, ?)",
            (unit.document_id, unit.source_format, unit.page_count),
        )
        conexion.execute(
            "INSERT OR IGNORE INTO referencia_fuente "
            "(document_id, alias, tipo_asignacion, fecha, estado_ingesta) VALUES (?, ?, ?, ?, ?)",
            (
                unit.document_id,
                unit.alias,
                TIPO_ASIGNACION_DELIBERADA,
                unit.fecha,
                EstadoIngesta.DECISION_REGISTRADA.value,
            ),
        )
    except sqlite3.Error as error:
        raise StoreError(StoreErrorCode.ERROR_SQLITE, "T1 falló al registrar la referencia", ruta=str(ruta)) from error
    finally:
        conexion.close()


def _t2_marcar_incompleta(ruta: Path, document_id: str, alias: str) -> None:
    """**T2:** deja durable «ingesta incompleta» antes de T3. Exige la referencia de `D-25` §1."""
    conexion = _abrir_escritura(ruta)
    try:
        cursor = conexion.execute(
            "UPDATE referencia_fuente SET estado_ingesta = ? WHERE document_id = ? AND alias = ?",
            (EstadoIngesta.INCOMPLETA.value, document_id, alias),
        )
        if cursor.rowcount == 0:
            raise StoreError(
                StoreErrorCode.REFERENCIA_AUSENTE,
                "T2: la referencia de fuente no existe",
                document_id=document_id,
                alias=alias,
            )
    except sqlite3.Error as error:
        raise StoreError(StoreErrorCode.ERROR_SQLITE, "T2 falló al marcar la ingesta", ruta=str(ruta)) from error
    finally:
        conexion.close()


def _insertar_fragmento(conexion: sqlite3.Connection, unit: UnitWrite, fragmento: FragmentRecord) -> None:
    conexion.execute(
        "INSERT INTO fragmento (document_id, document_version, ordinal, chunk_id, section_path, level, "
        "block_type, captions, pdf_page_start, pdf_page_end, content, content_hash, anchor_level) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            unit.document_id,
            unit.trace.document_version,
            fragmento.ordinal,
            fragmento.chunk_id,
            json_canonico([_nfc(elemento) for elemento in fragmento.section_path]),
            fragmento.level,
            fragmento.block_type.value,
            json_canonico([_nfc(elemento) for elemento in fragmento.captions]),
            fragmento.pdf_page_start,
            fragmento.pdf_page_end,
            fragmento.content,
            fragmento.content_hash,
            fragmento.anchor_level.value,
        ),
    )


def _insertar_anclaje(conexion: sqlite3.Connection, unit: UnitWrite, fragmento: FragmentRecord) -> None:
    evidencia = fragmento.anchor_evidence
    conexion.execute(
        "INSERT INTO anclaje_cache (document_id, document_version, ordinal, page, y0, y_dest, destination_use) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            unit.document_id,
            unit.trace.document_version,
            fragmento.ordinal,
            evidencia.page,
            evidencia.y0,
            evidencia.y_dest,
            evidencia.destination_use.value,
        ),
    )


def _insertar_fts(conexion: sqlite3.Connection, unit: UnitWrite, fragmento: FragmentRecord) -> None:
    conexion.execute(
        "INSERT INTO fragmento_fts (document_id, document_version, ordinal, content) VALUES (?, ?, ?, ?)",
        (unit.document_id, unit.trace.document_version, fragmento.ordinal, fragmento.content),
    )


def _insertar_construccion(conexion: sqlite3.Connection, unit: UnitWrite, sqlite_vec_version: str) -> None:
    """Una fila de `construccion` por operación aceptada (**D-1**/**D-25**); sin `index_version`."""
    calibracion = unit.trace.calibration
    counts = unit.trace.counts
    conexion.execute(
        "INSERT INTO construccion ("
        "document_id, document_version, extractor_nombre, extractor_version, extractor_config_efectiva, "
        "geometry_tool, manifiesto_canonico, chunking_config_version, calibracion_procedimiento, "
        "calibracion_entradas, calibracion_delta_pt, calibracion_dispersion_pt, calibracion_tolerancia_pt, "
        "calibracion_banda_pt, calibracion_umbral_tamano_pt, escala_entradas_corregidas, escala_factor, "
        "escala_residuo_max_pt, escala_destinos_inutilizables, recuento_unidades_corpus, "
        "recuento_ancladas_por_nivel, recuento_fragmentos, recuento_bloques_tabla, recuento_lineas_excluidas, "
        "recuento_anomalias_pagina, paginas_anomalas, tokenizer, sqlite_version, sqlite_vec_version) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            unit.document_id,
            unit.trace.document_version,
            unit.trace.extractor[0],
            unit.trace.extractor[1],
            unit.trace.extractor[2],
            unit.trace.geometry_tool,
            unit.trace.manifest_canonical,
            unit.trace.chunking_config_version,
            calibracion.procedure,
            calibracion.entries,
            calibracion.delta_pt,
            calibracion.dispersion_pt,
            calibracion.tolerance_pt,
            calibracion.top_band_pt,
            calibracion.heading_min_size_pt,
            calibracion.outline_scale_anomalies,
            calibracion.outline_scale_factor,
            calibracion.outline_scale_residual_max_pt,
            calibracion.destinations_unusable,
            counts.corpus_units,
            json_canonico(counts.anchored_by_level),
            counts.fragments,
            counts.table_blocks,
            counts.page_number_lines_excluded,
            counts.page_number_anomalies,
            json_canonico(counts.paginas_anomalas),
            TOKENIZER_FTS,
            sqlite3.sqlite_version,
            sqlite_vec_version,
        ),
    )


def _t3_escribir_unidad(ruta: Path, unit: UnitWrite) -> WriteOutcome:
    """**T3:** versión, fragmentos, caché, traza y FTS5 en **una** transacción, y estado completado.

    Exige la referencia de `D-25` §1: sin ella no hay a quién marcar «ingesta completada».
    """
    _verificar_unidad(unit)
    version = unit.trace.document_version
    pin, verificado = _sqlite_vec_version()
    escritos = 0
    conexion = _abrir_escritura(ruta)
    try:
        conexion.execute("PRAGMA foreign_keys = ON")
        conexion.execute("BEGIN IMMEDIATE")
        try:
            # Precondición de `D-25` §1, verificada DENTRO de la transacción: así el hecho se informa
            # igual exista o no la fila de `fuente` (antes, sin `fuente`, la FK daba `error_sqlite`).
            if (
                conexion.execute(
                    "SELECT 1 FROM referencia_fuente WHERE document_id = ? AND alias = ?",
                    (unit.document_id, unit.alias),
                ).fetchone()
                is None
            ):
                raise StoreError(
                    StoreErrorCode.REFERENCIA_AUSENTE,
                    "T3: la referencia de fuente no existe",
                    document_id=unit.document_id,
                    alias=unit.alias,
                )
            conexion.execute(
                "INSERT OR IGNORE INTO version_documento (document_id, document_version) VALUES (?, ?)",
                (unit.document_id, version),
            )
            previos = {
                int(fila[0]): str(fila[1])
                for fila in conexion.execute(
                    "SELECT ordinal, content_hash FROM fragmento WHERE document_id = ? AND document_version = ?",
                    (unit.document_id, version),
                )
            }
            for fragmento in unit.fragments:
                previo = previos.get(fragmento.ordinal)
                if previo is not None:
                    if previo != fragmento.content_hash:
                        raise StoreError(
                            StoreErrorCode.CONTENIDO_DIVERGENTE,
                            "el contenido persistido difiere del entrante para el mismo ordinal",
                            ordinal=fragmento.ordinal,
                            persistido=previo,
                            entrante=fragmento.content_hash,
                        )
                    continue
                _insertar_fragmento(conexion, unit, fragmento)
                _insertar_anclaje(conexion, unit, fragmento)
                escritos += 1
            conexion.execute(
                "DELETE FROM fragmento_fts WHERE document_id = ? AND document_version = ?",
                (unit.document_id, version),
            )
            for fragmento in unit.fragments:
                _insertar_fts(conexion, unit, fragmento)
            _insertar_construccion(conexion, unit, pin)
            cursor = conexion.execute(
                "UPDATE referencia_fuente SET estado_ingesta = ? WHERE document_id = ? AND alias = ?",
                (EstadoIngesta.COMPLETADA.value, unit.document_id, unit.alias),
            )
            if cursor.rowcount == 0:
                raise StoreError(
                    StoreErrorCode.REFERENCIA_AUSENTE,
                    "T3: la referencia de fuente no existe",
                    document_id=unit.document_id,
                    alias=unit.alias,
                )
        except Exception:
            with contextlib.suppress(sqlite3.Error):
                conexion.execute("ROLLBACK")
            raise
        conexion.execute("COMMIT")
    except StoreError:
        raise
    except sqlite3.OperationalError as error:
        raise StoreError(StoreErrorCode.ERROR_SQLITE, "T3 falló al escribir la unidad", ruta=str(ruta)) from error
    except sqlite3.DatabaseError as error:
        raise StoreError(
            StoreErrorCode.ERROR_SQLITE, "el motor rechazó la escritura de la unidad", ruta=str(ruta)
        ) from error
    finally:
        conexion.close()
    return WriteOutcome(
        fragmentos_escritos=escritos,
        fragmentos_existentes=len(unit.fragments) - escritos,
        sqlite_vec_verificado=verificado,
    )


# --- Incremento 3-b: reconstrucción del índice léxico derivado -------------------------------------
#
# Operación de **mantenimiento**, no de lectura: escribe **solo** `fragmento_fts`, desde la autoridad
# (`fragmento`), en una transacción. No toca la autoridad, no cambia el estado de ingesta, no publica
# generaciones y **no** calcula `index_version`: el criterio de `D-22` §11 se cumple aquí en su mitad
# observable («mismos resultados»), **no** en la de «misma `index_version`».


def _exigir_destino_vigente(conexion: sqlite3.Connection, ruta: Path) -> None:
    """Re-comprueba la versión del esquema **dentro** de la transacción.

    No es una primitiva de bloqueo: la validación sin escritura la hace `_abrir_lectura_valida` antes de
    abrir para escritura, y esto sólo evita escribir si el destino cambió en el intervalo (`M-08` sigue
    sin mecanismo de exclusión).
    """
    fila = conexion.execute("PRAGMA user_version").fetchone()
    version = None if fila is None else int(fila[0])
    if version != SCHEMA_VERSION:
        raise StoreError(
            StoreErrorCode.INCOMPATIBLE,
            "el destino no es un almacén de la versión vigente",
            ruta=str(ruta),
            user_version=version,
            version_esperada=SCHEMA_VERSION,
        )


def _exigir_version_utilizable(conexion: sqlite3.Connection, document_id: str, document_version: str) -> None:
    """Precondiciones del contrato, **antes** de escribir: referencia presente y versión registrada."""
    if not _referencias(conexion, document_id):
        raise StoreError(
            StoreErrorCode.REFERENCIA_AUSENTE,
            "el documento no tiene referencia registrada",
            document_id=document_id,
        )
    if not _version_registrada(conexion, document_id, document_version):
        raise StoreError(
            StoreErrorCode.VERSION_NO_ENCONTRADA,
            "la versión no está registrada",
            document_id=document_id,
            document_version=document_version,
        )


def _derivadas_de(conexion: sqlite3.Connection, document_id: str, document_version: str) -> int:
    """Número de filas del índice derivado de la versión."""
    filas = _consultar(
        conexion,
        "SELECT count(*) FROM fragmento_fts WHERE document_id = ? AND document_version = ?",
        (document_id, document_version),
        "el motor falló al contar el índice derivado",
    )
    return _entero(filas[0][0], "count")


def _autoridad_para_reconstruir(
    conexion: sqlite3.Connection, document_id: str, document_version: str
) -> tuple[tuple[int, str], ...]:
    """Lo **único** que la reconstrucción toma de la autoridad: ordinal y contenido, en orden."""
    filas = _consultar(
        conexion,
        "SELECT ordinal, content FROM fragmento WHERE document_id = ? AND document_version = ? ORDER BY ordinal",
        (document_id, document_version),
        "el motor falló al leer la autoridad para reconstruir",
    )
    return tuple((_entero(fila[0], "ordinal"), str(fila[1])) for fila in filas)


def _insertar_fila_derivada(
    conexion: sqlite3.Connection, document_id: str, document_version: str, ordinal: int, content: str
) -> None:
    """Inserta **una** fila del índice derivado. Aislada para poder inyectar un fallo a mitad."""
    conexion.execute(
        "INSERT INTO fragmento_fts (document_id, document_version, ordinal, content) VALUES (?, ?, ?, ?)",
        (document_id, document_version, ordinal, content),
    )


def _reconstruir_indice_lexico(ruta: Path, document_id: str, document_version: str) -> RebuildOutcome:
    """Reconstruye el índice léxico derivado de **una** versión desde la autoridad (`D-02` pt. 3; `D-22` §5).

    Explícito, atómico e idempotente. La validación previa es de **solo lectura**: un destino inexistente
    o ajeno se rechaza **sin escribir**. Dentro de la transacción, un fallo revierte el `DELETE` y las
    inserciones, de modo que el índice previo queda **exactamente como estaba**, aunque ya estuviera dañado.
    """
    _abrir_lectura_valida(ruta).close()
    conexion = _abrir_escritura(ruta)
    try:
        conexion.execute("BEGIN IMMEDIATE")
        try:
            _exigir_destino_vigente(conexion, ruta)
            _exigir_version_utilizable(conexion, document_id, document_version)
            previas = _derivadas_de(conexion, document_id, document_version)
            autoridad = _autoridad_para_reconstruir(conexion, document_id, document_version)
            conexion.execute(
                "DELETE FROM fragmento_fts WHERE document_id = ? AND document_version = ?",
                (document_id, document_version),
            )
            for ordinal, content in autoridad:
                _insertar_fila_derivada(conexion, document_id, document_version, ordinal, content)
        except Exception:
            with contextlib.suppress(sqlite3.Error):
                conexion.execute("ROLLBACK")
            raise
        conexion.execute("COMMIT")
    except StoreError:
        raise
    except sqlite3.OperationalError as error:
        raise StoreError(
            StoreErrorCode.ERROR_SQLITE, "la reconstrucción falló al escribir el índice", ruta=str(ruta)
        ) from error
    except sqlite3.DatabaseError as error:
        raise StoreError(
            StoreErrorCode.ERROR_SQLITE, "el motor rechazó la reconstrucción del índice", ruta=str(ruta)
        ) from error
    finally:
        conexion.close()
    return RebuildOutcome(
        document_id=document_id,
        document_version=document_version,
        filas_previas=previas,
        filas_reconstruidas=len(autoridad),
    )
