"""Contrato del `--page-count` de la ingesta: metadato declarado, no derivado.

El número de páginas de la fuente se **declara** en la CLI y se propaga tal cual hasta `fuente`.
La CLI no lo calcula del PDF ni del corpus: solo exige que sea un entero >= 1 cuando se declara.
Sin el parámetro, la ingesta no lo inventa (`None` ⇒ «no declarado»).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from book_text_rag.cli import _validar_page_count, main


def test_valor_explicito_se_acepta_tal_cual() -> None:
    assert _validar_page_count(784) == 784
    assert _validar_page_count(1) == 1


def test_ausencia_del_parametro_es_nulo() -> None:
    assert _validar_page_count(None) is None


@pytest.mark.parametrize("valor", [0, -1, -784])
def test_valores_no_positivos_son_error_de_uso(valor: int) -> None:
    with pytest.raises(ValueError, match=r"--page-count debe ser un entero >= 1"):
        _validar_page_count(valor)


def test_page_count_negativo_en_cli_es_uso_sin_inicializar_nada(tmp_path: Path) -> None:
    """Un `--page-count` inválido falla con código 2 antes de tocar el almacén."""
    ruta = tmp_path / "nulo.sqlite"

    assert (
        main(
            [
                "ingest",
                str(tmp_path / "fuente.pdf"),
                "--document-id",
                "doc",
                "--alias",
                "alias",
                "--fecha",
                "2026-10-18",
                "--store",
                str(ruta),
                "--page-count",
                "0",
            ]
        )
        == 2
    )
    assert not ruta.exists()
