"""Contrato físico del almacén: tablas, claves, restricciones, índices y pragmas (CA-3…CA-11).

Lee el esquema realmente creado en un almacén temporal y lo compara con el diseño aprobado. **No**
persiste datos del pipeline y no toca ninguna base existente.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from book_text_rag.adapters.storage.sqlite import (
    INDICES_ESPERADOS,
    PREFIJO_SOMBRA_FTS,
    SCHEMA_VERSION,
    TABLAS_ESPERADAS,
    SqliteStore,
)

COLUMNAS_PROHIBIDAS = (
    "title",
    "word_count",
    "document_version_short",
    "anchor_evidence",
    "revision_codigo",
    "index_version",
)
VERSION_HEX = "a" * 64
HASH_HEX = "b" * 64


@contextmanager
def _abrir(ruta: Path) -> Iterator[sqlite3.Connection]:
    conexion = sqlite3.connect(ruta)
    try:
        yield conexion
    finally:
        conexion.close()


@pytest.fixture
def almacen(tmp_path: Path) -> Path:
    ruta = tmp_path / "almacen.sqlite"
    SqliteStore(ruta).initialize()
    return ruta


def _nombres(conexion: sqlite3.Connection, tipo: str) -> set[str]:
    filas = conexion.execute("SELECT name FROM sqlite_master WHERE type = ?", (tipo,)).fetchall()
    return {str(fila[0]) for fila in filas}


def test_ca3_tablas_exactas_del_esquema(almacen: Path) -> None:
    with _abrir(almacen) as conexion:
        tablas = _nombres(conexion, "table")
    ajenas = {t for t in tablas if t not in TABLAS_ESPERADAS and not t.startswith(PREFIJO_SOMBRA_FTS)}
    assert tablas >= TABLAS_ESPERADAS
    assert ajenas == set()


def test_ca4_clave_primaria_de_fragmento_y_unicidad_de_chunk_id(almacen: Path) -> None:
    with _abrir(almacen) as conexion:
        columnas = {str(fila[1]): int(fila[5]) for fila in conexion.execute("PRAGMA table_info('fragmento')")}
        indices = [(str(fila[1]), int(fila[2])) for fila in conexion.execute("PRAGMA index_list('fragmento')")]
        unicos = [nombre for nombre, unico in indices if unico]
        unicos_por_columna = {
            frozenset(str(fila[2]) for fila in conexion.execute(f"PRAGMA index_info('{nombre}')")) for nombre in unicos
        }
    assert {columna for columna, pk in columnas.items() if pk} == {
        "document_id",
        "document_version",
        "ordinal",
    }
    assert frozenset({"chunk_id"}) in unicos_por_columna


def test_ca5_sin_unicidad_global_sobre_document_version(almacen: Path) -> None:
    """`D-5`: **ninguna** restricción única sobre `document_version` sola.

    El `sqlite_autoindex` del PK compuesto (`document_id`, `document_version`) **no** es una unicidad
    global sobre `document_version` y no infringe la decisión.
    """
    with _abrir(almacen) as conexion:
        indices = [(str(fila[1]), int(fila[2])) for fila in conexion.execute("PRAGMA index_list('version_documento')")]
        unicos_por_columna = {
            frozenset(str(fila[2]) for fila in conexion.execute(f"PRAGMA index_info('{nombre}')"))
            for nombre, unico in indices
            if unico
        }
    assert frozenset({"document_version"}) not in unicos_por_columna
    assert frozenset({"document_id", "document_version"}) in unicos_por_columna
    assert "idx_version_documento_document_version" in {nombre for nombre, unico in indices if not unico}


def test_ca5_indices_nombrados_presentes(almacen: Path) -> None:
    with _abrir(almacen) as conexion:
        indices = _nombres(conexion, "index")
    assert indices >= INDICES_ESPERADOS


def test_ca6_columnas_prohibidas_ausentes(almacen: Path) -> None:
    presentes: set[str] = set()
    with _abrir(almacen) as conexion:
        tablas = _nombres(conexion, "table")
        for tabla in sorted(tablas):
            if tabla.startswith(PREFIJO_SOMBRA_FTS):
                continue
            presentes |= {str(fila[1]) for fila in conexion.execute(f"PRAGMA table_info('{tabla}')")}
    assert presentes & set(COLUMNAS_PROHIBIDAS) == set()


def test_ca7_anclaje_cache_separada_y_con_fk_hacia_fragmento(almacen: Path) -> None:
    with _abrir(almacen) as conexion:
        tablas = _nombres(conexion, "table")
        fks_cache = {
            (str(fila[2]), str(fila[3]), str(fila[4]))
            for fila in conexion.execute("PRAGMA foreign_key_list('anclaje_cache')")
        }
        fks_fragmento = {
            (str(fila[2]), str(fila[3]), str(fila[4]))
            for fila in conexion.execute("PRAGMA foreign_key_list('fragmento')")
        }
    assert "anclaje_cache" in tablas
    assert fks_cache == {
        ("fragmento", "document_id", "document_id"),
        ("fragmento", "document_version", "document_version"),
        ("fragmento", "ordinal", "ordinal"),
    }
    assert all(destino != "anclaje_cache" for destino, _, _ in fks_fragmento)


def test_ca8_checks_de_enum_se_cumplen(almacen: Path) -> None:
    with _abrir(almacen) as conexion:
        conexion.execute("PRAGMA foreign_keys = ON")
        conexion.execute("INSERT INTO fuente (document_id) VALUES ('doc')")
        for estado in (
            "decisión de identidad registrada",
            "ingesta incompleta",
            "ingesta completada e índice disponible para consulta",
        ):
            conexion.execute(
                "INSERT INTO referencia_fuente (document_id, alias, tipo_asignacion, fecha, estado_ingesta) "
                "VALUES ('doc', ?, 'deliberada', '2026-10-17', ?)",
                (estado, estado),
            )
        with pytest.raises(sqlite3.IntegrityError):
            conexion.execute(
                "INSERT INTO referencia_fuente (document_id, alias, tipo_asignacion, fecha, estado_ingesta) "
                "VALUES ('doc', 'x', 'deliberada', '2026-10-17', 'token_inventado')"
            )
        conexion.execute(
            "INSERT INTO version_documento (document_id, document_version) VALUES ('doc', ?)", (VERSION_HEX,)
        )
        with pytest.raises(sqlite3.IntegrityError):
            conexion.execute(
                "INSERT INTO version_documento (document_id, document_version) VALUES ('doc', 'NO-ES-HEX')"
            )


def test_ca8_fk_y_enum_de_fragmento_se_hacen_cumplir(almacen: Path) -> None:
    columnas = (
        "document_id, document_version, ordinal, chunk_id, section_path, level, block_type, "
        "captions, pdf_page_start, pdf_page_end, content, content_hash, anchor_level"
    )
    valida = (
        "doc",
        VERSION_HEX,
        1,
        "doc:aaaaaaaaaaaa:1",
        "[]",
        1,
        "prose",
        "[]",
        None,
        None,
        "c",
        HASH_HEX,
        "posicional",
    )
    invalido_block = (
        "doc",
        VERSION_HEX,
        2,
        "doc:aaaaaaaaaaaa:2",
        "[]",
        1,
        "otro",
        "[]",
        None,
        None,
        "c",
        HASH_HEX,
        "posicional",
    )
    invalido_anchor = (
        "doc",
        VERSION_HEX,
        3,
        "doc:aaaaaaaaaaaa:3",
        "[]",
        1,
        "prose",
        "[]",
        None,
        None,
        "c",
        HASH_HEX,
        "otro",
    )
    sin_version = (
        "otro",
        VERSION_HEX,
        1,
        "otro:aaaaaaaaaaaa:1",
        "[]",
        1,
        "prose",
        "[]",
        None,
        None,
        "c",
        HASH_HEX,
        "posicional",
    )
    with _abrir(almacen) as conexion:
        conexion.execute("PRAGMA foreign_keys = ON")
        conexion.execute("INSERT INTO fuente (document_id) VALUES ('doc')")
        conexion.execute(
            "INSERT INTO version_documento (document_id, document_version) VALUES ('doc', ?)", (VERSION_HEX,)
        )
        conexion.execute(f"INSERT INTO fragmento ({columnas}) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", valida)
        for fila in (invalido_block, invalido_anchor, sin_version):
            with pytest.raises(sqlite3.IntegrityError):
                conexion.execute(f"INSERT INTO fragmento ({columnas}) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", fila)


def test_ca9_fts5_declarada_con_su_tokenizer(almacen: Path) -> None:
    with _abrir(almacen) as conexion:
        fila = conexion.execute("SELECT sql FROM sqlite_master WHERE name = 'fragmento_fts'").fetchone()
    assert fila is not None
    sql = str(fila[0])
    assert "fts5" in sql.lower()
    assert "unicode61 remove_diacritics 2" in sql


def test_ca10_sin_pragmas_de_durabilidad(tmp_path: Path) -> None:
    referencia = tmp_path / "referencia.sqlite"
    with _abrir(referencia) as conexion:
        conexion.execute("CREATE TABLE x (a INTEGER)")
        esperado = (
            str(conexion.execute("PRAGMA journal_mode").fetchone()[0]),
            int(conexion.execute("PRAGMA synchronous").fetchone()[0]),
        )
    ruta = tmp_path / "almacen.sqlite"
    assert SqliteStore(ruta).initialize() is not None
    with _abrir(ruta) as conexion:
        obtenido = (
            str(conexion.execute("PRAGMA journal_mode").fetchone()[0]),
            int(conexion.execute("PRAGMA synchronous").fetchone()[0]),
        )
    assert obtenido == esperado


def test_ca15_el_marcador_coincide_con_la_version_del_esquema(almacen: Path) -> None:
    with _abrir(almacen) as conexion:
        version = int(conexion.execute("PRAGMA user_version").fetchone()[0])
    assert version == SCHEMA_VERSION


COLUMNAS_CONSTRUCCION = (
    "document_id, document_version, extractor_nombre, extractor_version, extractor_config_efectiva, "
    "geometry_tool, manifiesto_canonico, chunking_config_version, calibracion_procedimiento, "
    "calibracion_entradas, calibracion_delta_pt, calibracion_dispersion_pt, calibracion_tolerancia_pt, "
    "calibracion_banda_pt, calibracion_umbral_tamano_pt, escala_entradas_corregidas, "
    "escala_destinos_inutilizables, recuento_unidades_corpus, recuento_ancladas_por_nivel, "
    "recuento_fragmentos, recuento_bloques_tabla, recuento_lineas_excluidas, recuento_anomalias_pagina, "
    "paginas_anomalas, tokenizer, sqlite_version, sqlite_vec_version"
)


def _insertar_construccion(conexion: sqlite3.Connection, recuento: int, paginas: str) -> None:
    """Inserta una fila de `construccion` con valores fijos y las dos columnas de `D-23` parametrizadas."""
    valores: tuple[object, ...] = (
        "doc",
        VERSION_HEX,
        "pdftotext",
        "4.00",
        "-layout -enc UTF-8",
        "PyMuPDF 1.26.7",
        "{}",
        "0123456789ab",
        "anchoring/v1",
        116,
        72.118,
        0.75,
        2.0,
        200.0,
        18.403,
        17,
        0,
        166,
        '{"pagina+tipografia":33,"posicional":133}',
        583,
        209,
        692,
        recuento,
        paginas,
        "unicode61 remove_diacritics 2",
        "3.50.4",
        "0.1.9",
    )
    marcadores = ", ".join("?" * len(valores))
    conexion.execute(f"INSERT INTO construccion ({COLUMNAS_CONSTRUCCION}) VALUES ({marcadores})", valores)


def _preparar_construccion(conexion: sqlite3.Connection) -> None:
    conexion.execute("PRAGMA foreign_keys = ON")
    conexion.execute("INSERT INTO fuente (document_id) VALUES ('doc')")
    conexion.execute("INSERT INTO version_documento (document_id, document_version) VALUES ('doc', ?)", (VERSION_HEX,))


def test_d23_columnas_de_anomalias_con_tipo_y_obligatoriedad(almacen: Path) -> None:
    with _abrir(almacen) as conexion:
        columnas = {
            str(fila[1]): (str(fila[2]).upper(), int(fila[3]))
            for fila in conexion.execute("PRAGMA table_info('construccion')")
        }
    assert columnas["recuento_anomalias_pagina"] == ("INTEGER", 1)
    assert columnas["paginas_anomalas"] == ("TEXT", 1)


def test_d23_cero_anomalias_se_persiste_como_cero_y_arreglo_vacio(almacen: Path) -> None:
    with _abrir(almacen) as conexion:
        _preparar_construccion(conexion)
        _insertar_construccion(conexion, 0, "[]")
        fila = conexion.execute("SELECT recuento_anomalias_pagina, paginas_anomalas FROM construccion").fetchone()
    assert fila is not None
    assert int(fila[0]) == 0
    assert str(fila[1]) == "[]"


def test_d23_paginas_anomalas_ordenadas_se_persisten(almacen: Path) -> None:
    with _abrir(almacen) as conexion:
        _preparar_construccion(conexion)
        _insertar_construccion(conexion, 2, "[184,229]")
        fila = conexion.execute("SELECT recuento_anomalias_pagina, paginas_anomalas FROM construccion").fetchone()
    assert fila is not None
    assert int(fila[0]) == 2
    assert str(fila[1]) == "[184,229]"


def test_d23_discrepancia_entre_recuento_y_arreglo_se_rechaza(almacen: Path) -> None:
    with _abrir(almacen) as conexion:
        _preparar_construccion(conexion)
        with pytest.raises(sqlite3.IntegrityError):
            _insertar_construccion(conexion, 2, "[184]")


def test_d23_arreglo_que_no_es_arreglo_se_rechaza(almacen: Path) -> None:
    with _abrir(almacen) as conexion:
        _preparar_construccion(conexion)
        with pytest.raises(sqlite3.IntegrityError):
            _insertar_construccion(conexion, 0, "{}")


def test_d23_json_malformado_se_rechaza(almacen: Path) -> None:
    with _abrir(almacen) as conexion:
        _preparar_construccion(conexion)
        with pytest.raises(sqlite3.DatabaseError):
            _insertar_construccion(conexion, 0, "[")
