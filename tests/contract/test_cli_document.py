"""Contrato del verbo `document`: ficha pública de un documento (`D-07`, siete campos).

La CLI expone el caso de uso ya probado en aplicación: resolución de la versión omitida (B2),
cero versiones (B4), prefijo único de versión, errores con su código y lectura pura.
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
V1 = "a" * 64
V2 = "b" * 64
TEXTO = "evidencia textual con procedencia verificable sobre recuperacion lexica"


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
) -> None:
    """Documento publicado con referencias (una por estado) y versiones registradas."""
    SqliteStore(ruta).initialize()
    conexion = sqlite3.connect(ruta)
    try:
        conexion.execute(
            "INSERT INTO fuente (document_id, source_format, page_count) VALUES (?, ?, ?)",
            (DOC, source_format, page_count),
        )
        for indice, estado in enumerate(estados):
            conexion.execute(
                "INSERT INTO referencia_fuente (document_id, alias, tipo_asignacion, fecha, estado_ingesta) "
                "VALUES (?, ?, 'deliberada', '2026-10-22', ?)",
                (DOC, f"alias-{indice}", estado.value),
            )
        for version in versiones:
            conexion.execute(
                "INSERT INTO version_documento (document_id, document_version) VALUES (?, ?)", (DOC, version)
            )
            conexion.execute(
                "INSERT INTO fragmento (document_id, document_version, ordinal, chunk_id, section_path, level, "
                "block_type, captions, pdf_page_start, pdf_page_end, content, content_hash, anchor_level) "
                "VALUES (?, ?, 1, ?, '[]', 1, 'prose', '[]', 5, 5, ?, ?, 'posicional')",
                (DOC, version, chunk_id(DOC, version[:12], 1), TEXTO, content_hash(TEXTO)),
            )
            conexion.execute(
                "INSERT INTO fragmento_fts (document_id, document_version, ordinal, content) VALUES (?, ?, 1, ?)",
                (DOC, version, TEXTO),
            )
        conexion.commit()
    finally:
        conexion.close()


def test_una_version_resuelta_sin_parametro_proyecta_los_siete_campos(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ruta = tmp_path / "uno.sqlite"
    _sembrar(ruta)

    assert main(["document", "--store", str(ruta), "--document-id", DOC]) == 0

    assert capsys.readouterr().out.splitlines() == [
        f"document_id: {DOC}",
        f"document_version: {V1}",
        "title: (no declarado)",
        "source_format: pdf",
        "page_count: 784",
        "index_version: (no calculado)",
        "status: indexed",
    ]


def test_version_explicita_completa_se_proyecta(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ruta = tmp_path / "explicita.sqlite"
    _sembrar(ruta)

    assert main(["document", "--store", str(ruta), "--document-id", DOC, "--document-version", V1]) == 0

    salida = capsys.readouterr().out
    assert f"document_version: {V1}" in salida.splitlines()
    assert "status: indexed" in salida.splitlines()


def test_prefijo_unico_resuelve_la_version(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ruta = tmp_path / "prefijo.sqlite"
    _sembrar(ruta)

    assert main(["document", "--store", str(ruta), "--document-id", DOC, "--document-version", V1[:12]]) == 0

    assert f"document_version: {V1}" in capsys.readouterr().out.splitlines()


def test_prefijo_ambiguo_es_error_de_uso_con_candidatos(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ruta = tmp_path / "ambiguo.sqlite"
    _sembrar(ruta, versiones=("ab" + "0" * 62, "ab" + "1" * 62))

    assert main(["document", "--store", str(ruta), "--document-id", DOC, "--document-version", "ab"]) == 2

    error = capsys.readouterr().err
    assert error.startswith("error [uso]: el prefijo")
    assert "ab" + "0" * 62 in error and "ab" + "1" * 62 in error


def test_dos_versiones_sin_parametro_exige_document_version(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ruta = tmp_path / "dos.sqlite"
    _sembrar(ruta, versiones=(V1, V2))

    assert main(["document", "--store", str(ruta), "--document-id", DOC]) == 2

    assert "error [invalid_request]" in capsys.readouterr().err


def test_dos_versiones_con_version_explicita_no_inventa_respuesta(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """N ≥ 2 versiones: el estado por versión requiere CD-02/M-14; la CLI no construye ficha."""
    ruta = tmp_path / "dos_explicita.sqlite"
    _sembrar(ruta, versiones=(V1, V2))

    assert main(["document", "--store", str(ruta), "--document-id", DOC, "--document-version", V1]) == 2

    error = capsys.readouterr().err
    assert error.startswith("sin respuesta: ")
    assert "CD-02/M-14" in error
    assert capsys.readouterr().out == ""


def test_cero_versiones_es_not_indexed_con_nulos(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ruta = tmp_path / "cero.sqlite"
    _sembrar(ruta, versiones=())

    assert main(["document", "--store", str(ruta), "--document-id", DOC]) == 0

    assert capsys.readouterr().out.splitlines() == [
        f"document_id: {DOC}",
        "document_version: (sin versiones)",
        "title: (no declarado)",
        "source_format: pdf",
        "page_count: 784",
        "index_version: (no calculado)",
        "status: not_indexed",
    ]


def test_estado_no_completado_es_not_indexed(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ruta = tmp_path / "parcial.sqlite"
    _sembrar(ruta, estados=(EstadoIngesta.INCOMPLETA,))

    assert main(["document", "--store", str(ruta), "--document-id", DOC]) == 0

    assert "status: not_indexed" in capsys.readouterr().out.splitlines()


def test_metadatos_ausentes_se_declaran_sin_inventar(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ruta = tmp_path / "metadatos.sqlite"
    _sembrar(ruta, source_format=None, page_count=None)

    assert main(["document", "--store", str(ruta), "--document-id", DOC]) == 0

    salida = capsys.readouterr().out
    assert "source_format: (no declarado)" in salida
    assert "page_count: (no declarado)" in salida


def test_documento_no_registrado_conserva_document_not_found(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ruta = tmp_path / "otro.sqlite"
    _sembrar(ruta)

    assert main(["document", "--store", str(ruta), "--document-id", "desconocido"]) == 2

    assert "error [document_not_found]" in capsys.readouterr().err


def test_version_no_registrada_conserva_version_no_encontrada(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ruta = tmp_path / "inexistente.sqlite"
    _sembrar(ruta)

    assert main(["document", "--store", str(ruta), "--document-id", DOC, "--document-version", V2]) == 2

    assert "error [version_no_encontrada]" in capsys.readouterr().err


def test_almacen_no_disponible_conserva_index_unavailable(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ruta = tmp_path / "ausente.sqlite"

    assert main(["document", "--store", str(ruta), "--document-id", DOC]) == 2

    assert "error [index_unavailable]" in capsys.readouterr().err
    assert not ruta.exists()


def test_no_muestra_fragmentos_contenido_ni_rutas(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ruta = tmp_path / "forma.sqlite"
    _sembrar(ruta)

    assert main(["document", "--store", str(ruta), "--document-id", DOC]) == 0

    salida = capsys.readouterr().out
    assert TEXTO not in salida
    assert "content:" not in salida
    assert "chunk_id" not in salida
    assert str(ruta) not in salida
    assert "fragmentos" not in salida


def test_lectura_pura_sin_escritura_ni_laterales(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ruta = tmp_path / "pura.sqlite"
    _sembrar(ruta)
    antes = _huella(ruta)

    assert main(["document", "--store", str(ruta), "--document-id", DOC]) == 0
    assert main(["document", "--store", str(ruta), "--document-id", DOC, "--document-version", V1]) == 0

    capsys.readouterr()
    assert _huella(ruta) == antes
    assert _laterales(ruta) == []
