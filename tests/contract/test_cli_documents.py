"""Contrato de `documents`: catálogo de solo lectura del almacén (sin fragmentos ni contenido).

Cubre la enumeración completa, la regla conservadora de `consultable` (`D-13`), el almacén válido y vacío,
el almacén no disponible, el orden determinista, la ausencia de contenido y la lectura pura.
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from book_text_rag.adapters.storage.sqlite import SqliteStore
from book_text_rag.application.search_lexical import search_lexical
from book_text_rag.cli import main
from book_text_rag.domain.identity import chunk_id, content_hash
from book_text_rag.ports.storage import EstadoIngesta

DOC_A = "alfa"
DOC_B = "beta"
V_A = "a" * 64
V_B = "b" * 64
TEXTO = "evidencia textual con procedencia verificable sobre recuperacion lexica"


def _huella(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def _laterales(ruta: Path) -> list[str]:
    return sorted(path.name for path in ruta.parent.glob(f"{ruta.name}-*"))


def _almacen(tmp_path: Path) -> Path:
    ruta = tmp_path / "catalogo.sqlite"
    SqliteStore(ruta).initialize()
    return ruta


def _sembrar(
    ruta: Path,
    *,
    document_id: str,
    version: str,
    estados: tuple[EstadoIngesta, ...] = (EstadoIngesta.COMPLETADA,),
    source_format: str | None = "pdf",
    page_count: int | None = 784,
) -> None:
    """Registra un documento con una referencia por estado y una versión con un fragmento."""
    conexion = sqlite3.connect(ruta)
    try:
        conexion.execute(
            "INSERT INTO fuente (document_id, source_format, page_count) VALUES (?, ?, ?)",
            (document_id, source_format, page_count),
        )
        for indice, estado in enumerate(estados):
            conexion.execute(
                "INSERT INTO referencia_fuente (document_id, alias, tipo_asignacion, fecha, estado_ingesta) "
                "VALUES (?, ?, 'deliberada', '2026-10-22', ?)",
                (document_id, f"{document_id}-alias" if indice == 0 else f"{document_id}-alias-{indice}", estado.value),
            )
        conexion.execute(
            "INSERT INTO version_documento (document_id, document_version) VALUES (?, ?)", (document_id, version)
        )
        conexion.execute(
            "INSERT INTO fragmento (document_id, document_version, ordinal, chunk_id, section_path, level, "
            "block_type, captions, pdf_page_start, pdf_page_end, content, content_hash, anchor_level) "
            "VALUES (?, ?, 1, ?, '[]', 1, 'prose', '[]', 5, 5, ?, ?, 'posicional')",
            (document_id, version, chunk_id(document_id, version[:12], 1), TEXTO, content_hash(TEXTO)),
        )
        conexion.execute(
            "INSERT INTO fragmento_fts (document_id, document_version, ordinal, content) VALUES (?, ?, 1, ?)",
            (document_id, version, TEXTO),
        )
        conexion.commit()
    finally:
        conexion.close()


def test_enumera_todos_los_documentos_con_sus_datos(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ruta = _almacen(tmp_path)
    _sembrar(ruta, document_id=DOC_A, version=V_A)

    assert main(["documents", "--store", str(ruta)]) == 0

    assert capsys.readouterr().out.splitlines() == [
        "documentos: 1",
        "",
        "[1]",
        f"document_id: {DOC_A}",
        "source_format: pdf",
        "page_count: 784",
        "referencias: 1",
        f"  alias: {DOC_A}-alias | estado: ingesta completada e índice disponible para consulta",
        "versiones: 1",
        f"  - {V_A}",
        "consultable: sí",
    ]


def test_metadatos_ausentes_se_declaran_sin_inventar(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ruta = _almacen(tmp_path)
    _sembrar(ruta, document_id=DOC_A, version=V_A, source_format=None, page_count=None)

    assert main(["documents", "--store", str(ruta)]) == 0

    salida = capsys.readouterr().out
    assert "source_format: (no declarado)" in salida
    assert "page_count: (no declarado)" in salida


def test_varios_documentos_en_orden_determinista(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ruta = _almacen(tmp_path)
    _sembrar(ruta, document_id=DOC_B, version=V_B)
    _sembrar(ruta, document_id=DOC_A, version=V_A)

    assert main(["documents", "--store", str(ruta)]) == 0

    salida = capsys.readouterr().out
    assert [linea for linea in salida.splitlines() if linea.startswith("document_id: ")] == [
        f"document_id: {DOC_A}",
        f"document_id: {DOC_B}",
    ]


def test_aliases_ordenados_dentro_del_documento(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ruta = _almacen(tmp_path)
    conexion = sqlite3.connect(ruta)
    try:
        conexion.execute("INSERT INTO fuente (document_id) VALUES (?)", (DOC_A,))
        for alias in ("zeta", "alfa"):
            conexion.execute(
                "INSERT INTO referencia_fuente (document_id, alias, tipo_asignacion, fecha, estado_ingesta) "
                "VALUES (?, ?, 'deliberada', '2026-10-22', ?)",
                (DOC_A, alias, EstadoIngesta.COMPLETADA.value),
            )
        conexion.commit()
    finally:
        conexion.close()

    assert main(["documents", "--store", str(ruta)]) == 0

    aliases = [linea for linea in capsys.readouterr().out.splitlines() if linea.strip().startswith("alias: ")]
    assert [linea.split("|")[0].strip().removeprefix("alias: ") for linea in aliases] == ["alfa", "zeta"]


@pytest.mark.parametrize("estado", [EstadoIngesta.INCOMPLETA, EstadoIngesta.DECISION_REGISTRADA])
def test_consultable_es_no_cuando_falta_completar(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], estado: EstadoIngesta
) -> None:
    ruta = _almacen(tmp_path)
    _sembrar(ruta, document_id=DOC_A, version=V_A, estados=(estado,))

    assert main(["documents", "--store", str(ruta)]) == 0

    assert "consultable: no" in capsys.readouterr().out
    assert search_lexical(SqliteStore(ruta), query="procedencia") == ()


def test_consultable_es_no_con_referencias_discrepantes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ruta = _almacen(tmp_path)
    _sembrar(ruta, document_id=DOC_A, version=V_A, estados=(EstadoIngesta.COMPLETADA, EstadoIngesta.INCOMPLETA))

    assert main(["documents", "--store", str(ruta)]) == 0

    salida = capsys.readouterr().out
    assert "referencias: 2" in salida
    assert "consultable: no" in salida


def test_consultable_es_no_sin_referencias(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ruta = _almacen(tmp_path)
    _sembrar(ruta, document_id=DOC_A, version=V_A, estados=())

    assert main(["documents", "--store", str(ruta)]) == 0

    salida = capsys.readouterr().out
    assert "(sin referencias)" in salida
    assert "consultable: no" in salida


def test_consultable_coincide_con_lo_que_devuelve_search(tmp_path: Path) -> None:
    """El indicador es del documento y refleja exactamente la regla que aplica `search`."""
    ruta = _almacen(tmp_path)
    _sembrar(ruta, document_id=DOC_A, version=V_A)
    _sembrar(ruta, document_id=DOC_B, version=V_B, estados=(EstadoIngesta.INCOMPLETA,))

    documentos = SqliteStore(ruta).list_documents()
    devueltos = {resultado.document_id for resultado in search_lexical(SqliteStore(ruta), query="procedencia")}

    assert {d.document_id: d.consultable for d in documentos} == {DOC_A: True, DOC_B: False}
    assert devueltos == {d.document_id for d in documentos if d.consultable}


def test_almacen_valido_y_vacio_devuelve_cero_documentos(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ruta = _almacen(tmp_path)

    assert main(["documents", "--store", str(ruta)]) == 0

    assert capsys.readouterr().out.splitlines() == ["documentos: 0"]


def test_almacen_no_disponible_conserva_index_unavailable(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ruta = tmp_path / "ausente.sqlite"

    assert main(["documents", "--store", str(ruta)]) == 2

    assert "error [index_unavailable]" in capsys.readouterr().err
    assert not ruta.exists()


def test_no_muestra_fragmentos_contenido_ni_rutas(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ruta = _almacen(tmp_path)
    _sembrar(ruta, document_id=DOC_A, version=V_A)

    assert main(["documents", "--store", str(ruta)]) == 0

    salida = capsys.readouterr().out
    assert TEXTO not in salida
    assert "content:" not in salida
    assert "chunk_id" not in salida
    assert str(ruta) not in salida
    assert "fragmentos" not in salida


def test_listado_es_solo_lectura(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ruta = _almacen(tmp_path)
    _sembrar(ruta, document_id=DOC_A, version=V_A)
    antes = _huella(ruta)

    assert main(["documents", "--store", str(ruta)]) == 0

    capsys.readouterr()
    assert _huella(ruta) == antes
    assert _laterales(ruta) == []
