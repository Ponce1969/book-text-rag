"""Contrato de la CLI administrativa: inicialización, ingesta persistente y verificación."""

from __future__ import annotations

import hashlib
import re
import sqlite3
from pathlib import Path

import pytest

from book_text_rag import cli
from book_text_rag.adapters.storage.sqlite import SCHEMA_VERSION, SqliteStore
from book_text_rag.cli import main
from book_text_rag.domain.identity import chunk_id, content_hash
from book_text_rag.domain.models import ErrorCode, IngestError
from book_text_rag.ports.storage import NO_VERIFICADO

DOCUMENT_ID = "doc"
VERSION = "a" * 64

_INDEX_VERSION = re.compile(r"^index_version: (?:[0-9a-f]{12}|null)$", re.MULTILINE)


def _huella(ruta: Path) -> str:
    """Huella del archivo para comprobar que una operación de lectura no escribió."""
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def _laterales(ruta: Path) -> list[str]:
    """Nombres de archivos laterales de SQLite asociados al almacén."""
    return sorted(path.name for path in ruta.parent.glob(f"{ruta.name}-*"))


def _sembrar_almacen(ruta: Path) -> None:
    """Inicializa y siembra dos fragmentos con todos sus derivados usando sqlite3."""
    SqliteStore(ruta).initialize()
    conexion = sqlite3.connect(ruta)
    try:
        conexion.execute(
            "INSERT INTO fuente (document_id, source_format, page_count) VALUES (?, ?, ?)",
            (DOCUMENT_ID, "pdf", 2),
        )
        conexion.execute(
            "INSERT INTO referencia_fuente "
            "(document_id, alias, tipo_asignacion, fecha, estado_ingesta) VALUES (?, ?, ?, ?, ?)",
            (
                DOCUMENT_ID,
                "alias",
                "deliberada",
                "2026-10-18",
                "ingesta completada e índice disponible para consulta",
            ),
        )
        conexion.execute(
            "INSERT INTO version_documento (document_id, document_version) VALUES (?, ?)",
            (DOCUMENT_ID, VERSION),
        )
        for ordinal in (1, 2):
            contenido = f"contenido de prueba {ordinal}"
            conexion.execute(
                "INSERT INTO fragmento (document_id, document_version, ordinal, chunk_id, section_path, level, "
                "block_type, captions, pdf_page_start, pdf_page_end, content, content_hash, anchor_level) "
                "VALUES (?, ?, ?, ?, '[]', 1, 'prose', '[]', ?, ?, ?, ?, 'posicional')",
                (
                    DOCUMENT_ID,
                    VERSION,
                    ordinal,
                    chunk_id(DOCUMENT_ID, VERSION[:12], ordinal),
                    ordinal,
                    ordinal,
                    contenido,
                    content_hash(contenido),
                ),
            )
            conexion.execute(
                "INSERT INTO fragmento_fts (document_id, document_version, ordinal, content) VALUES (?, ?, ?, ?)",
                (DOCUMENT_ID, VERSION, ordinal, contenido),
            )
        conexion.execute(
            "INSERT INTO construccion ("
            "document_id, document_version, extractor_nombre, extractor_version, extractor_config_efectiva, "
            "geometry_tool, manifiesto_canonico, chunking_config_version, calibracion_procedimiento, "
            "calibracion_entradas, calibracion_delta_pt, calibracion_dispersion_pt, calibracion_tolerancia_pt, "
            "calibracion_banda_pt, calibracion_umbral_tamano_pt, escala_entradas_corregidas, escala_factor, "
            "escala_residuo_max_pt, escala_destinos_inutilizables, recuento_unidades_corpus, "
            "recuento_ancladas_por_nivel, recuento_fragmentos, recuento_bloques_tabla, "
            "recuento_lineas_excluidas, recuento_anomalias_pagina, paginas_anomalas, tokenizer, "
            "sqlite_version, sqlite_vec_version) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                DOCUMENT_ID,
                VERSION,
                "extractor",
                "1",
                "{}",
                "geometría de prueba",
                "{}",
                "prueba",
                "calibración de prueba",
                0,
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                0,
                None,
                None,
                0,
                2,
                "{}",
                2,
                0,
                0,
                0,
                "[]",
                "unicode61 remove_diacritics 2",
                sqlite3.sqlite_version,
                "0.1.9",
            ),
        )
        conexion.commit()
    finally:
        conexion.close()


def _contar(ruta: Path, tabla: str) -> int:
    """Cuenta filas en una tabla conocida del esquema de pruebas."""
    conexion = sqlite3.connect(ruta)
    try:
        fila = conexion.execute(f"SELECT count(*) FROM {tabla}").fetchone()
    finally:
        conexion.close()
    assert fila is not None
    return int(fila[0])


def _version_esquema(ruta: Path) -> int:
    """`user_version` del almacén: la reconstrucción no cambia el esquema."""
    conexion = sqlite3.connect(f"{ruta.as_uri()}?mode=ro", uri=True)
    try:
        fila = conexion.execute("PRAGMA user_version").fetchone()
    finally:
        conexion.close()
    assert fila is not None
    return int(fila[0])


def _chunk_ids(salida: str) -> list[str]:
    """Identificadores de fragmento que proyecta `search`, en el orden de la respuesta."""
    return [linea.removeprefix("chunk_id: ") for linea in salida.splitlines() if linea.startswith("chunk_id: ")]


def _derivado(ruta: Path) -> tuple[tuple[object, ...], ...]:
    """Contenido lógico del índice derivado, en orden de ordinal."""
    conexion = sqlite3.connect(f"{ruta.as_uri()}?mode=ro", uri=True)
    try:
        filas = conexion.execute(
            "SELECT document_id, document_version, ordinal, content FROM fragmento_fts ORDER BY ordinal"
        ).fetchall()
    finally:
        conexion.close()
    return tuple(tuple(fila) for fila in filas)


def _huella_tablas(ruta: Path, tablas: tuple[str, ...]) -> str:
    """Huella del contenido lógico de las tablas indicadas (la reconstrucción no las toca)."""
    conexion = sqlite3.connect(f"{ruta.as_uri()}?mode=ro", uri=True)
    try:
        volcado = tuple(
            (
                tabla,
                tuple(sorted((tuple(fila) for fila in conexion.execute(f"SELECT * FROM {tabla}")), key=repr)),
            )
            for tabla in tablas
        )
    finally:
        conexion.close()
    return hashlib.sha256(repr(volcado).encode("utf-8")).hexdigest()


AUTORIDAD = ("fuente", "referencia_fuente", "version_documento", "fragmento", "construccion", "anclaje_cache")


def test_ayuda_lista_los_seis_comandos_y_documenta_los_codigos(capsys: pytest.CaptureFixture[str]) -> None:
    """La ayuda raíz y la ayuda de cada comando declaran los códigos de salida."""
    ayudas = (
        (
            ["--help"],
            ("init", "ingest", "verify", "search", "show", "rebuild", "Códigos de salida", "0", "1", "2"),
            ("auditoría ejecutada", "error operativo o de uso"),
        ),
        (
            ["init", "--help"],
            ("Códigos de salida", "0", "1", "2"),
            ("auditoría ejecutada", "error operativo o de uso"),
        ),
        (
            ["ingest", "--help"],
            ("Códigos de salida", "0", "1", "2"),
            ("auditoría ejecutada", "error operativo o de uso"),
        ),
        (
            ["verify", "--help"],
            ("Códigos de salida", "0", "1", "2"),
            ("auditoría ejecutada", "error operativo o de uso"),
        ),
        (
            ["search", "--help"],
            ("Códigos de salida", "0", "2", "--top-k", "--document-id", "1000"),
            ("no devuelve resultados", "error operativo o de uso"),
        ),
        (
            ["show", "--help"],
            ("Códigos de salida", "0", "2", "--document-version"),
            ("error operativo o de uso",),
        ),
        (
            ["rebuild", "--help"],
            ("Códigos de salida", "0", "2", "--document-id", "--document-version"),
            ("error operativo o de uso",),
        ),
    )
    for argumentos, esperados, diagnosticos in ayudas:
        with pytest.raises(SystemExit) as salida:
            main(argumentos)
        assert salida.value.code == 0
        ayuda = capsys.readouterr().out
        assert ayuda.startswith("Uso: ")
        assert "usage:" not in ayuda
        assert all(texto in ayuda for texto in esperados)
        assert all(texto in ayuda for texto in diagnosticos)
        assert "mostrar esta ayuda y salir" in ayuda
        assert "show this help message and exit" not in ayuda


def test_inicializacion_crea_y_luego_reconoce_el_almacen_inicializado(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ruta = tmp_path / "almacen.sqlite"

    assert main(["init", "--store", str(ruta)]) == 0
    primera = capsys.readouterr().out
    assert "creado" in primera
    assert str(ruta) in primera
    assert SqliteStore(ruta).is_initialized() is True

    assert main(["init", "--store", str(ruta)]) == 0
    segunda = capsys.readouterr().out
    assert "ya_inicializado" in segunda
    assert SqliteStore(ruta).is_initialized() is True


@pytest.mark.parametrize("tipo", ["tabla_ajena", "version_ajena"])
def test_inicializacion_rechaza_un_almacen_ajeno_sin_modificarlo(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], tipo: str
) -> None:
    ruta = tmp_path / f"ajeno_{tipo}.sqlite"
    conexion = sqlite3.connect(ruta)
    try:
        if tipo == "tabla_ajena":
            conexion.execute("CREATE TABLE ajena (valor TEXT)")
        else:
            conexion.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
        conexion.commit()
    finally:
        conexion.close()
    antes = _huella(ruta)

    assert main(["init", "--store", str(ruta)]) == 2
    diagnostico = capsys.readouterr().err
    assert "incompatible" in diagnostico
    assert "user_version" in diagnostico
    assert _huella(ruta) == antes
    assert _laterales(ruta) == []


def test_ingesta_exige_store_y_no_inicia_ningun_camino_sin_el(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pdf = tmp_path / "no_debe_leerse.pdf"
    with pytest.raises(SystemExit) as salida:
        main(
            [
                "ingest",
                str(pdf),
                "--document-id",
                DOCUMENT_ID,
                "--alias",
                "alias",
                "--fecha",
                "2026-10-18",
            ]
        )
    assert salida.value.code == 2
    diagnostico = capsys.readouterr().err
    assert "error [uso]" in diagnostico
    assert "faltan argumentos requeridos: --store" in diagnostico
    assert not pdf.exists()
    assert tuple(tmp_path.iterdir()) == ()


def test_fallo_de_extraccion_informa_codigo_y_detalles_sin_escaparse(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    ruta = tmp_path / "almacen.sqlite"
    SqliteStore(ruta).initialize()

    def fallar(*args: object, **kwargs: object) -> None:
        raise IngestError(ErrorCode.EXTRACTION_FAILED, "fallo de prueba", origen="pdf")

    monkeypatch.setattr(cli, "ingest_persistent", fallar)
    assert (
        main(
            [
                "ingest",
                str(tmp_path / "fuente.pdf"),
                "--document-id",
                DOCUMENT_ID,
                "--alias",
                "alias",
                "--fecha",
                "2026-10-18",
                "--store",
                str(ruta),
            ]
        )
        == 2
    )
    diagnostico = capsys.readouterr().err
    assert "error [extraction_failed]: fallo de prueba" in diagnostico
    assert "origen: pdf" in diagnostico


def test_verificacion_correcta_es_de_solo_lectura_y_muestra_siete_indicadores(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ruta = tmp_path / "sano.sqlite"
    _sembrar_almacen(ruta)
    antes = _huella(ruta)

    assert main(["verify", "--store", str(ruta), "--document-id", DOCUMENT_ID, "--document-version", VERSION]) == 0
    salida = capsys.readouterr().out
    for indicador in (
        "ordinales_ok: True",
        "content_hash_ok: True",
        "chunk_id_ok: True",
        "fts5_ok: True",
        "estado_ok: True",
        "traza_presente: True",
        "fuente_presente: True",
        "ok: True",
        f"no_verificado: {NO_VERIFICADO}",
    ):
        assert indicador in salida
    assert _huella(ruta) == antes
    assert _laterales(ruta) == []


def test_verificacion_danada_devuelve_uno_y_muestra_el_indicador_falso(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ruta = tmp_path / "danado.sqlite"
    _sembrar_almacen(ruta)
    conexion = sqlite3.connect(ruta)
    try:
        conexion.execute("DELETE FROM fragmento_fts WHERE document_id = ? AND ordinal = 2", (DOCUMENT_ID,))
        conexion.commit()
    finally:
        conexion.close()

    assert main(["verify", "--store", str(ruta), "--document-id", DOCUMENT_ID, "--document-version", VERSION]) == 1
    salida = capsys.readouterr().out
    assert "fts5_ok: False" in salida
    assert "ok: False" in salida


@pytest.mark.parametrize(
    ("document_id", "version", "codigo"),
    [
        (DOCUMENT_ID, "b" * 64, "version_no_encontrada"),
        ("desconocido", VERSION, "referencia_ausente"),
    ],
)
def test_verificacion_inexistente_informa_el_codigo_sin_modificar_el_almacen(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    document_id: str,
    version: str,
    codigo: str,
) -> None:
    ruta = tmp_path / "versiones.sqlite"
    _sembrar_almacen(ruta)
    antes = _huella(ruta)

    assert main(["verify", "--store", str(ruta), "--document-id", document_id, "--document-version", version]) == 2
    diagnostico = capsys.readouterr().err
    assert codigo in diagnostico
    assert document_id in diagnostico
    assert _huella(ruta) == antes
    assert _laterales(ruta) == []


def test_busqueda_muestra_campos_orden_y_estado_de_index_version(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`search` proyecta los nueve campos, declara el estado de `index_version` y no escribe."""
    ruta = tmp_path / "consulta.sqlite"
    _sembrar_almacen(ruta)
    antes = _huella(ruta)

    assert main(["search", "contenido", "--store", str(ruta)]) == 0
    salida = capsys.readouterr().out
    assert "consulta: contenido" in salida
    assert "modo: lexical" in salida
    assert _INDEX_VERSION.search(salida) is not None
    assert "index_version: null" not in salida
    assert "resultados: 2" in salida
    assert "[1]" in salida
    assert "[2]" in salida
    assert "rank: 1" in salida
    assert "rank: 2" in salida
    assert "score: " in salida
    assert f"document_id: {DOCUMENT_ID}" in salida
    assert f"document_version: {VERSION}" in salida
    assert f"chunk_id: {DOCUMENT_ID}:{VERSION[:12]}:1" in salida
    assert "section_path: (sin secciones)" in salida
    assert "paginas: 1" in salida
    assert "paginas: 2" in salida
    assert "content:\ncontenido de prueba 1" in salida
    assert "content:\ncontenido de prueba 2" in salida
    assert _huella(ruta) == antes
    assert _laterales(ruta) == []


def test_busqueda_es_determinista_y_respeta_top_k_y_filtros(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Dos ejecuciones idénticas producen la misma salida; `top_k` y los filtros acotan sin reordenar."""
    ruta = tmp_path / "consulta.sqlite"
    _sembrar_almacen(ruta)

    assert main(["search", "contenido", "--store", str(ruta)]) == 0
    primera = capsys.readouterr().out
    assert main(["search", "contenido", "--store", str(ruta)]) == 0
    assert capsys.readouterr().out == primera

    assert main(["search", "contenido", "--store", str(ruta), "--top-k", "1"]) == 0
    assert "resultados: 1" in capsys.readouterr().out

    assert main(["search", "contenido", "--store", str(ruta), "--document-id", DOCUMENT_ID]) == 0
    assert "resultados: 2" in capsys.readouterr().out

    assert main(["search", "contenido", "--store", str(ruta), "--document-id", "desconocido"]) == 0
    assert "resultados: 0" in capsys.readouterr().out


def test_busqueda_sin_coincidencias_es_exito_y_solo_lectura(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Sin coincidencias: cero resultados, código 0 y almacén intacto."""
    ruta = tmp_path / "consulta.sqlite"
    _sembrar_almacen(ruta)
    antes = _huella(ruta)

    assert main(["search", "inexistente", "--store", str(ruta)]) == 0
    salida = capsys.readouterr().out
    assert "resultados: 0" in salida
    assert "index_version: null" in salida
    assert _huella(ruta) == antes
    assert _laterales(ruta) == []


@pytest.mark.parametrize(
    ("consulta", "extra", "detalle"),
    [
        ("", [], "vacía"),
        ("x" * 1001, [], "1000"),
        ("contenido", ["--top-k", "0"], "top_k"),
        ("contenido", ["--top-k", "51"], "top_k"),
    ],
)
def test_busqueda_rechaza_entradas_invalidas_con_codigo_dos(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    consulta: str,
    extra: list[str],
    detalle: str,
) -> None:
    """Consulta vacía o larga y `top_k` fuera de rango fallan con diagnóstico de uso y sin escribir."""
    ruta = tmp_path / "consulta.sqlite"
    _sembrar_almacen(ruta)
    antes = _huella(ruta)

    assert main(["search", consulta, "--store", str(ruta), *extra]) == 2
    diagnostico = capsys.readouterr().err
    assert diagnostico.startswith("error [uso]: ")
    assert detalle in diagnostico
    assert _huella(ruta) == antes
    assert _laterales(ruta) == []


def test_busqueda_rechaza_almacen_inexistente_sin_crearlo(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Un destino ausente se informa como `index_unavailable` (`D-14`) sin crearlo ni inicializarlo."""
    ruta = tmp_path / "falta.sqlite"

    assert main(["search", "contenido", "--store", str(ruta)]) == 2
    diagnostico = capsys.readouterr().err
    assert "index_unavailable" in diagnostico
    assert not ruta.exists()


def test_ficha_de_version_muestra_metadatos_estados_y_fragmentos(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`show` informa la autoridad de la versión y no escribe."""
    ruta = tmp_path / "ficha.sqlite"
    _sembrar_almacen(ruta)
    antes = _huella(ruta)

    assert main(["show", "--store", str(ruta), "--document-id", DOCUMENT_ID, "--document-version", VERSION]) == 0
    salida = capsys.readouterr().out
    assert f"document_id: {DOCUMENT_ID}" in salida
    assert f"document_version: {VERSION}" in salida
    assert _INDEX_VERSION.search(salida) is not None
    assert "index_version: null" not in salida
    assert "estados: ingesta completada e índice disponible para consulta" in salida
    assert "source_format: pdf" in salida
    assert "page_count: 2" in salida
    assert "fragmentos: 2" in salida
    assert _huella(ruta) == antes
    assert _laterales(ruta) == []


@pytest.mark.parametrize(
    ("document_id", "version", "codigo"),
    [
        (DOCUMENT_ID, "b" * 64, "version_no_encontrada"),
        ("desconocido", VERSION, "referencia_ausente"),
    ],
)
def test_ficha_de_version_inexistente_informa_el_codigo_sin_modificar_el_almacen(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    document_id: str,
    version: str,
    codigo: str,
) -> None:
    """Una versión o un documento desconocidos fallan con código 2 sin alterar el almacén."""
    ruta = tmp_path / "ficha.sqlite"
    _sembrar_almacen(ruta)
    antes = _huella(ruta)

    assert main(["show", "--store", str(ruta), "--document-id", document_id, "--document-version", version]) == 2
    diagnostico = capsys.readouterr().err
    assert codigo in diagnostico
    assert _huella(ruta) == antes
    assert _laterales(ruta) == []


def test_ficha_rechaza_almacen_inexistente_sin_crearlo(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """`show` sobre un destino ausente informa `index_unavailable` (`D-14`) y no crea el archivo."""
    ruta = tmp_path / "falta.sqlite"

    assert main(["show", "--store", str(ruta), "--document-id", DOCUMENT_ID, "--document-version", VERSION]) == 2
    diagnostico = capsys.readouterr().err
    assert "index_unavailable" in diagnostico
    assert not ruta.exists()


def test_busqueda_con_puntuacion_de_fts5_no_falla(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Un guion en la consulta se sanea y la búsqueda termina con éxito, sin error del motor."""
    ruta = tmp_path / "consulta.sqlite"
    _sembrar_almacen(ruta)
    antes = _huella(ruta)

    assert main(["search", "TF-IDF", "--store", str(ruta)]) == 0
    salida = capsys.readouterr().out
    assert "resultados: " in salida
    assert _INDEX_VERSION.search(salida) is not None
    assert _huella(ruta) == antes
    assert _laterales(ruta) == []


def test_busqueda_sin_tokens_alfanumericos_devuelve_dos(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Una consulta solo de puntuación es una entrada inválida y no consulta el almacén."""
    ruta = tmp_path / "consulta.sqlite"
    _sembrar_almacen(ruta)
    antes = _huella(ruta)

    assert main(["search", "???", "--store", str(ruta)]) == 2
    diagnostico = capsys.readouterr().err
    assert diagnostico.startswith("error [uso]: ")
    assert "no contiene tokens alfanuméricos utilizables" in diagnostico
    assert _huella(ruta) == antes
    assert _laterales(ruta) == []


def test_reconstruccion_repara_el_indice_y_conserva_los_resultados(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`verify` falla tras el daño, `rebuild` lo repara y `search` recupera los mismos fragmentos."""
    ruta = tmp_path / "reparar.sqlite"
    _sembrar_almacen(ruta)

    assert main(["search", "contenido", "--store", str(ruta)]) == 0
    linea_base = _chunk_ids(capsys.readouterr().out)
    assert linea_base == [f"{DOCUMENT_ID}:{VERSION[:12]}:1", f"{DOCUMENT_ID}:{VERSION[:12]}:2"]

    conexion = sqlite3.connect(ruta)
    try:
        conexion.execute(
            "DELETE FROM fragmento_fts WHERE document_id = ? AND document_version = ? AND ordinal = 1",
            (DOCUMENT_ID, VERSION),
        )
        conexion.commit()
    finally:
        conexion.close()

    assert main(["verify", "--store", str(ruta), "--document-id", DOCUMENT_ID, "--document-version", VERSION]) == 1
    assert "fts5_ok: False" in capsys.readouterr().out

    assert main(["rebuild", "--store", str(ruta), "--document-id", DOCUMENT_ID, "--document-version", VERSION]) == 0
    salida = capsys.readouterr().out
    assert "filas_previas: 1" in salida
    assert "filas_reconstruidas: 2" in salida

    assert main(["verify", "--store", str(ruta), "--document-id", DOCUMENT_ID, "--document-version", VERSION]) == 0
    verificacion = capsys.readouterr().out
    assert "fts5_ok: True" in verificacion
    assert "ok: True" in verificacion

    assert main(["search", "contenido", "--store", str(ruta)]) == 0
    assert _chunk_ids(capsys.readouterr().out) == linea_base
    assert _laterales(ruta) == []


def test_reconstruccion_es_idempotente_y_no_toca_la_autoridad(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Dos reconstrucciones conservan el índice lógico, los conteos y la autoridad persistida."""
    ruta = tmp_path / "idempotente.sqlite"
    _sembrar_almacen(ruta)
    autoridad = _huella_tablas(ruta, AUTORIDAD)
    derivado = _derivado(ruta)
    fragmentos = _contar(ruta, "fragmento")
    referencia = _contar(ruta, "referencia_fuente")
    version_esquema = _version_esquema(ruta)

    assert main(["rebuild", "--store", str(ruta), "--document-id", DOCUMENT_ID, "--document-version", VERSION]) == 0
    primera = capsys.readouterr().out
    assert "filas_previas: 2" in primera
    assert "filas_reconstruidas: 2" in primera
    assert "index_version" not in primera

    assert main(["rebuild", "--store", str(ruta), "--document-id", DOCUMENT_ID, "--document-version", VERSION]) == 0
    segunda = capsys.readouterr().out
    assert "filas_previas: 2" in segunda
    assert "filas_reconstruidas: 2" in segunda

    assert _derivado(ruta) == derivado
    assert _huella_tablas(ruta, AUTORIDAD) == autoridad
    assert _contar(ruta, "fragmento") == fragmentos
    assert _contar(ruta, "referencia_fuente") == referencia
    assert _version_esquema(ruta) == version_esquema == SCHEMA_VERSION
    assert _laterales(ruta) == []


@pytest.mark.parametrize(
    ("document_id", "version", "codigo"),
    [
        ("desconocido", VERSION, "referencia_ausente"),
        (DOCUMENT_ID, "b" * 64, "version_no_encontrada"),
    ],
)
def test_reconstruccion_inexistente_informa_el_codigo_sin_modificar_el_almacen(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    document_id: str,
    version: str,
    codigo: str,
) -> None:
    """Una referencia o una versión desconocidas fallan con código 2 sin alterar el almacén."""
    ruta = tmp_path / "rechazos.sqlite"
    _sembrar_almacen(ruta)
    antes = _huella(ruta)

    assert main(["rebuild", "--store", str(ruta), "--document-id", document_id, "--document-version", version]) == 2
    diagnostico = capsys.readouterr().err
    assert codigo in diagnostico
    assert _huella(ruta) == antes
    assert _laterales(ruta) == []


def test_reconstruccion_rechaza_almacen_ausente_sin_crearlo(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Un destino ausente se informa sin crearlo ni inicializarlo."""
    ruta = tmp_path / "falta.sqlite"

    assert main(["rebuild", "--store", str(ruta), "--document-id", DOCUMENT_ID, "--document-version", VERSION]) == 2
    diagnostico = capsys.readouterr().err
    assert "no_es_base" in diagnostico
    assert not ruta.exists()
    assert _laterales(ruta) == []
