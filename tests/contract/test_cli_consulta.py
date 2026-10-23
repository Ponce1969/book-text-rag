"""Contrato de las salidas compactas de la CLI: `search --brief`, `show --fragments` y `show --orden`.

Las salidas actuales se conservan cuando las opciones no se activan; estas pruebas fijan el formato nuevo,
los límites, los errores de uso y la lectura pura.
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from book_text_rag.adapters.storage.sqlite import SqliteStore
from book_text_rag.cli import main
from book_text_rag.domain.identity import chunk_id, content_hash
from book_text_rag.ports.storage import EstadoIngesta

DOC = "libro"
VERSION = "d" * 64
TEXTO = "evidencia textual con procedencia verificable sobre recuperacion lexica"


def _huella(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def _laterales(ruta: Path) -> list[str]:
    return sorted(path.name for path in ruta.parent.glob(f"{ruta.name}-*"))


def _sembrar(ruta: Path, *, fragmentos: int = 2) -> None:
    """Documento publicado con `fragmentos` fragmentos consultables."""
    SqliteStore(ruta).initialize()
    conexion = sqlite3.connect(ruta)
    try:
        conexion.execute("INSERT INTO fuente (document_id, source_format, page_count) VALUES (?, 'pdf', 25)", (DOC,))
        conexion.execute(
            "INSERT INTO referencia_fuente (document_id, alias, tipo_asignacion, fecha, estado_ingesta) "
            "VALUES (?, 'alias', 'deliberada', '2026-10-22', ?)",
            (DOC, EstadoIngesta.COMPLETADA.value),
        )
        conexion.execute("INSERT INTO version_documento (document_id, document_version) VALUES (?, ?)", (DOC, VERSION))
        for ordinal in range(1, fragmentos + 1):
            contenido = f"{TEXTO} (fragmento {ordinal})"
            conexion.execute(
                "INSERT INTO fragmento (document_id, document_version, ordinal, chunk_id, section_path, level, "
                "block_type, captions, pdf_page_start, pdf_page_end, content, content_hash, anchor_level) "
                "VALUES (?, ?, ?, ?, '[\"Capitulo\"]', 1, 'prose', '[]', ?, ?, ?, ?, 'posicional')",
                (
                    DOC,
                    VERSION,
                    ordinal,
                    chunk_id(DOC, VERSION[:12], ordinal),
                    ordinal,
                    ordinal,
                    contenido,
                    content_hash(contenido),
                ),
            )
            conexion.execute(
                "INSERT INTO fragmento_fts (document_id, document_version, ordinal, content) VALUES (?, ?, ?, ?)",
                (DOC, VERSION, ordinal, contenido),
            )
        conexion.commit()
    finally:
        conexion.close()


def _almacen(tmp_path: Path, *, fragmentos: int = 2) -> Path:
    ruta = tmp_path / "consulta.sqlite"
    _sembrar(ruta, fragmentos=fragmentos)
    return ruta


def test_search_brief_emite_una_linea_por_resultado_sin_contenido(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ruta = _almacen(tmp_path, fragmentos=3)
    antes = _huella(ruta)

    assert main(["search", "procedencia", "--store", str(ruta), "--top-k", "3", "--brief"]) == 0

    lineas = capsys.readouterr().out.splitlines()
    assert lineas[:4] == ["consulta: procedencia", "modo: lexical", "index_version: null", "resultados: 3"]
    assert len(lineas) == 7, lineas
    for posicion, linea in enumerate(lineas[4:], start=1):
        assert linea.startswith(f"[{posicion}] score=")
        assert f"document_id={DOC}" in linea
        assert f"chunk_id={DOC}:{VERSION[:12]}:{posicion}" in linea
        assert "paginas=" in linea
        assert "seccion=Capitulo" in linea
        assert TEXTO not in linea
    assert _huella(ruta) == antes
    assert _laterales(ruta) == []


def test_search_sin_brief_conserva_la_salida_completa(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ruta = _almacen(tmp_path, fragmentos=1)

    assert main(["search", "procedencia", "--store", str(ruta)]) == 0

    lineas = capsys.readouterr().out.splitlines()
    assert lineas[:4] == ["consulta: procedencia", "modo: lexical", "index_version: null", "resultados: 1"]
    assert lineas[4:6] == ["", "[1]"]
    assert any(linea.startswith("rank: ") for linea in lineas)
    assert any(linea.startswith("score: ") for linea in lineas)
    assert "content:" in lineas
    assert any(TEXTO in linea for linea in lineas)


def test_show_fragments_lista_por_defecto_veinte(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ruta = _almacen(tmp_path, fragmentos=25)

    assert main(["show", "--store", str(ruta), "--document-id", DOC, "--document-version", VERSION, "--fragments"]) == 0

    lineas = capsys.readouterr().out.splitlines()
    assert "fragmentos: 25" in lineas
    assert "listado: 20 de 25" in lineas
    assert sum(1 for linea in lineas if " | " in linea and "chunk_id" not in linea) == 20
    assert "  … 5 fragmentos más; use --all o --limit N" in lineas


def test_show_fragments_all_lista_todos(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ruta = _almacen(tmp_path, fragmentos=25)

    assert (
        main(
            ["show", "--store", str(ruta), "--document-id", DOC, "--document-version", VERSION, "--fragments", "--all"]
        )
        == 0
    )

    lineas = capsys.readouterr().out.splitlines()
    assert "listado: 25 de 25" in lineas
    assert sum(1 for linea in lineas if " | " in linea and "chunk_id" not in linea) == 25
    assert not any("fragmentos más" in linea for linea in lineas)


def test_show_fragments_limit_controla_el_corte(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ruta = _almacen(tmp_path, fragmentos=10)

    assert (
        main(
            [
                "show",
                "--store",
                str(ruta),
                "--document-id",
                DOC,
                "--document-version",
                VERSION,
                "--fragments",
                "--limit",
                "3",
            ]
        )
        == 0
    )

    lineas = capsys.readouterr().out.splitlines()
    assert "listado: 3 de 10" in lineas
    assert sum(1 for linea in lineas if " | " in linea and "chunk_id" not in linea) == 3


def test_show_orden_inspecciona_un_fragmento_con_su_contenido(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ruta = _almacen(tmp_path, fragmentos=5)

    assert (
        main(["show", "--store", str(ruta), "--document-id", DOC, "--document-version", VERSION, "--orden", "3"]) == 0
    )

    lineas = capsys.readouterr().out.splitlines()
    assert "fragmento 3:" in lineas
    assert f"chunk_id: {DOC}:{VERSION[:12]}:3" in lineas
    assert "anchor_level: posicional" in lineas
    assert "content:" in lineas
    assert f"{TEXTO} (fragmento 3)" in lineas


def test_show_sin_opciones_conserva_la_ficha_actual(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ruta = _almacen(tmp_path, fragmentos=5)

    assert main(["show", "--store", str(ruta), "--document-id", DOC, "--document-version", VERSION]) == 0

    lineas = capsys.readouterr().out.splitlines()
    assert lineas[0] == f"document_id: {DOC}"
    assert "fragmentos: 5" in lineas
    assert "listado:" not in lineas
    assert "fragmento 3:" not in lineas


@pytest.mark.parametrize(
    ("extra", "mensaje"),
    [
        (["--limit", "0"], "--limit debe ser un entero >= 1"),
        (["--orden", "0"], "--orden debe ser un ordinal >= 1"),
        (["--orden", "99"], "la versión no tiene un fragmento con ordinal 99"),
    ],
)
def test_limites_y_ordinales_invalidos_son_errores_de_uso(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], extra: list[str], mensaje: str
) -> None:
    ruta = _almacen(tmp_path, fragmentos=3)
    argumentos = ["show", "--store", str(ruta), "--document-id", DOC, "--document-version", VERSION, *extra]
    if "--ordinal" not in extra and "--orden" not in extra and "--limit" in extra:
        argumentos.append("--fragments")

    assert main(argumentos) == 2
    assert mensaje in capsys.readouterr().err


def test_las_salidas_compactas_no_escriben(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ruta = _almacen(tmp_path, fragmentos=25)
    antes = _huella(ruta)

    assert main(["search", "procedencia", "--store", str(ruta), "--brief"]) == 0
    assert main(["show", "--store", str(ruta), "--document-id", DOC, "--document-version", VERSION, "--fragments"]) == 0
    assert (
        main(["show", "--store", str(ruta), "--document-id", DOC, "--document-version", VERSION, "--orden", "1"]) == 0
    )

    capsys.readouterr()
    assert _huella(ruta) == antes
    assert _laterales(ruta) == []


def test_brief_permite_encadenar_show_orden(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Ciclo completo: la línea breve trae los tres datos que `show` necesita para bajar al fragmento."""
    ruta = _almacen(tmp_path, fragmentos=3)

    assert main(["search", "procedencia", "--store", str(ruta), "--top-k", "1", "--brief"]) == 0
    linea = capsys.readouterr().out.splitlines()[-1]
    document_id = next(parte.split("=", 1)[1] for parte in linea.split() if parte.startswith("document_id="))
    version_corta = next(parte.split("=", 1)[1] for parte in linea.split() if parte.startswith("version="))

    assert (
        main(
            [
                "show",
                "--store",
                str(ruta),
                "--document-id",
                document_id,
                "--document-version",
                version_corta,
                "--orden",
                "1",
            ]
        )
        == 0
    )

    salida = capsys.readouterr().out
    assert f"document_version: {VERSION}" in salida
    assert "fragmento 1:" in salida
    assert f"{TEXTO} (fragmento 1)" in salida


def test_show_resuelve_un_prefijo_unico(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ruta = _almacen(tmp_path, fragmentos=2)

    assert main(["show", "--store", str(ruta), "--document-id", DOC, "--document-version", VERSION[:12]]) == 0

    lineas = capsys.readouterr().out.splitlines()
    assert f"document_version: {VERSION}" in lineas
    assert "fragmentos: 2" in lineas


def test_show_rechaza_un_prefijo_ambiguo_sin_elegir(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ruta = _almacen(tmp_path, fragmentos=1)
    otra = "dd" + "e" * 62  # comparte el prefijo «dd» con VERSION («dddd…»)
    conexion = sqlite3.connect(ruta)
    try:
        conexion.execute("INSERT INTO version_documento (document_id, document_version) VALUES (?, ?)", (DOC, otra))
        conexion.commit()
    finally:
        conexion.close()

    assert main(["show", "--store", str(ruta), "--document-id", DOC, "--document-version", "dd"]) == 2

    error = capsys.readouterr().err
    assert "error [uso]" in error
    assert "coincide con 2 versiones" in error
    assert VERSION in error and otra in error


def test_show_conserva_version_no_encontrada_para_un_prefijo_inexistente(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ruta = _almacen(tmp_path, fragmentos=1)

    assert main(["show", "--store", str(ruta), "--document-id", DOC, "--document-version", "f" * 12]) == 2

    assert "error [version_no_encontrada]" in capsys.readouterr().err


def test_show_rechaza_una_version_vacia(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ruta = _almacen(tmp_path, fragmentos=1)

    assert main(["show", "--store", str(ruta), "--document-id", DOC, "--document-version", ""]) == 2

    assert "--document-version no puede estar vacía" in capsys.readouterr().err
