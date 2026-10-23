"""Contrato de la atribución de `index_version` en `search` y `show` (decisión F; `M7`/`CD-01`).

Regla adoptada: el valor se emite solo si la respuesta corresponde a **un único** par
`(document_id, document_version)` con **exactamente una** construcción y todos sus insumos válidos; en
cualquier otro caso —resultados vacíos, varias versiones o varias construcciones— se emite `null`.
`index_version` se **recalcula** desde la traza persistida: no se persiste ni se añade esquema.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
from pathlib import Path

from book_text_rag.adapters.storage.sqlite import SCHEMA_VERSION, SqliteStore
from book_text_rag.cli import main
from book_text_rag.domain.identity import chunk_id, content_hash, index_version

DOC = "doc"
V1 = "a" * 64
V2 = "b" * 64
TOKENIZER = "unicode61 remove_diacritics 2"
PATRON = re.compile(r"^index_version: (?P<valor>[0-9a-f]{12}|null)$")

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
    construcciones_por_version: int = 1,
    tokenizer: str = TOKENIZER,
) -> None:
    """Almacén válido con una fuente, N versiones, un fragmento por versión y N construcciones por versión."""
    SqliteStore(ruta).initialize()
    conexion = sqlite3.connect(ruta)
    try:
        conexion.execute(
            "INSERT INTO fuente (document_id, source_format, page_count) VALUES (?, ?, ?)", (DOC, "pdf", 2)
        )
        conexion.execute(
            "INSERT INTO referencia_fuente (document_id, alias, tipo_asignacion, fecha, estado_ingesta) "
            "VALUES (?, ?, ?, ?, ?)",
            (DOC, "alias", "deliberada", "2026-10-22", "ingesta completada e índice disponible para consulta"),
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
            for _ in range(construcciones_por_version):
                conexion.execute(
                    f"INSERT INTO construccion ({_COLUMNAS_CONSTRUCCION}) "
                    "VALUES (?, ?, 'pdftotext', '4.00', '-layout -enc UTF-8', 'PyMuPDF 1.26.7', '{}', "
                    "'chunking-v1', 'calibracion de prueba', 0, 0.0, 0.0, 0.0, 0.0, 0.0, 0, NULL, NULL, 0, "
                    "1, '{}', 1, 0, 0, 0, '[]', ?, ?, '0.1.9')",
                    (DOC, version, tokenizer, sqlite3.sqlite_version),
                )
        conexion.commit()
    finally:
        conexion.close()


def _identidad(salida: str) -> str:
    """Extrae el valor declarado en la línea `index_version:` y comprueba su forma."""
    linea = next(linea for linea in salida.splitlines() if linea.startswith("index_version:"))
    coincidencia = PATRON.match(linea)
    assert coincidencia is not None, linea
    return coincidencia.group("valor")


def _valor_esperado(version: str = V1, tokenizer: str = TOKENIZER) -> str:
    return index_version(
        document_version=version,
        extractor=("pdftotext", "4.00", "-layout -enc UTF-8"),
        chunking_config_version="chunking-v1",
        tokenizer=tokenizer,
        sqlite_version=sqlite3.sqlite_version,
        sqlite_vec_version="0.1.9",
        embeddings=(),
    )


def test_una_construccion_recalcula_el_valor_de_forma_determinista(tmp_path: Path) -> None:
    ruta = tmp_path / "una.sqlite"
    _sembrar(ruta)
    antes = _huella(ruta)

    assert SqliteStore(ruta).index_version_for(DOC, V1) == _valor_esperado()
    assert SqliteStore(ruta).index_version_for(DOC, V1) == SqliteStore(ruta).index_version_for(DOC, V1)
    assert re.fullmatch(r"[0-9a-f]{12}", _valor_esperado())
    assert _huella(ruta) == antes
    assert _laterales(ruta) == []


def test_index_version_no_se_persiste_ni_cambia_el_esquema(tmp_path: Path) -> None:
    ruta = tmp_path / "esquema.sqlite"
    _sembrar(ruta)
    conexion = sqlite3.connect(f"{ruta.as_uri()}?mode=ro", uri=True)
    try:
        assert conexion.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        columnas = [
            fila[1]
            for tabla in ("fragmento", "construccion", "version_documento", "fuente")
            for fila in conexion.execute(f"PRAGMA table_info({tabla})")
        ]
    finally:
        conexion.close()
    assert "index_version" not in columnas


def test_search_emite_el_valor_con_una_sola_construccion(tmp_path: Path, capsys) -> None:
    ruta = tmp_path / "una.sqlite"
    _sembrar(ruta)

    assert main(["search", "procedencia", "--store", str(ruta)]) == 0

    salida = capsys.readouterr().out
    assert _identidad(salida) == _valor_esperado()
    assert "resultados: 1" in salida
    assert "rank: 1" in salida


def test_search_con_dos_versiones_emite_null_y_conserva_el_ranking(tmp_path: Path, capsys) -> None:
    ruta = tmp_path / "dos.sqlite"
    _sembrar(ruta, versiones=(V1, V2))

    assert main(["search", "procedencia", "--store", str(ruta)]) == 0

    salida = capsys.readouterr().out
    assert _identidad(salida) == "null"
    assert "resultados: 2" in salida
    assert "rank: 1" in salida
    assert "rank: 2" in salida
    assert f"document_version: {V1}" in salida
    assert f"document_version: {V2}" in salida


def test_indice_valido_y_vacio_emite_null(tmp_path: Path, capsys) -> None:
    ruta = tmp_path / "vacio.sqlite"
    SqliteStore(ruta).initialize()

    assert main(["search", "procedencia", "--store", str(ruta)]) == 0

    salida = capsys.readouterr().out
    assert _identidad(salida) == "null"
    assert "resultados: 0" in salida


def test_insumo_invalido_emite_null_sin_sustituto(tmp_path: Path, capsys) -> None:
    ruta = tmp_path / "invalido.sqlite"
    _sembrar(ruta, tokenizer="")
    assert SqliteStore(ruta).index_version_for(DOC, V1) is None

    assert main(["search", "procedencia", "--store", str(ruta)]) == 0

    assert _identidad(capsys.readouterr().out) == "null"


def test_dos_construcciones_para_la_misma_version_emiten_null(tmp_path: Path, capsys) -> None:
    ruta = tmp_path / "dos_construcciones.sqlite"
    _sembrar(ruta, construcciones_por_version=2)
    assert SqliteStore(ruta).index_version_for(DOC, V1) is None

    assert main(["search", "procedencia", "--store", str(ruta)]) == 0

    assert _identidad(capsys.readouterr().out) == "null"


def test_show_emite_el_valor_con_una_construccion(tmp_path: Path, capsys) -> None:
    ruta = tmp_path / "ficha.sqlite"
    _sembrar(ruta)

    assert main(["show", "--store", str(ruta), "--document-id", DOC, "--document-version", V1]) == 0

    salida = capsys.readouterr().out
    assert _identidad(salida) == _valor_esperado()
    assert "fragmentos: 1" in salida


def test_show_emite_null_con_dos_construcciones(tmp_path: Path, capsys) -> None:
    ruta = tmp_path / "ficha_dos.sqlite"
    _sembrar(ruta, construcciones_por_version=2)

    assert main(["show", "--store", str(ruta), "--document-id", DOC, "--document-version", V1]) == 0

    assert _identidad(capsys.readouterr().out) == "null"
