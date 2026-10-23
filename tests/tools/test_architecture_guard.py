"""Pruebas del guardián de arquitectura y del hook de pre-commit.

Se demuestra que los controles **fallan** ante una violación real, no solo que pasan en un árbol sano:
arquitectura válida, importación prohibida, error de tipado y hook bloqueando el commit.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent.parent
GUARDIAN = RAIZ / "scripts" / "check_architecture.py"
HOOK = RAIZ / ".githooks" / "pre-commit"


def _entorno() -> dict[str, str]:
    """Entorno con salida UTF-8 forzada: la consola de Windows usa cp1252 y rompería la captura."""
    return {**os.environ, "PYTHONIOENCODING": "utf-8"}


def _arbol(tmp_path: Path, archivos: dict[str, str]) -> Path:
    """Crea una raíz de paquete temporal con los archivos indicados."""
    for ruta, contenido in archivos.items():
        destino = tmp_path / ruta
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(contenido, encoding="utf-8")
    return tmp_path


def _ejecutar_guardian(raiz: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(GUARDIAN), "--root", str(raiz)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=_entorno(),
    )


def test_la_arquitectura_real_respeta_la_direccion() -> None:
    resultado = subprocess.run(
        [sys.executable, str(GUARDIAN)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=RAIZ,
        env=_entorno(),
    )

    assert resultado.returncode == 0, resultado.stderr
    assert "arquitectura OK" in resultado.stdout


def test_no_queda_deuda_declarada_en_el_guardian() -> None:
    """La aplicación ya no importa adaptadores: el registro de excepciones está vacío."""
    sys.path.insert(0, str(RAIZ / "scripts"))
    try:
        import check_architecture
    finally:
        sys.path.pop(0)

    assert check_architecture.EXCEPCIONES == {}
    violaciones, _ = check_architecture.analizar(RAIZ / "src")
    assert violaciones == []


def test_un_import_prohibido_falla(tmp_path: Path) -> None:
    raiz = _arbol(
        tmp_path,
        {
            "book_text_rag/__init__.py": "",
            "book_text_rag/domain/__init__.py": "",
            "book_text_rag/domain/reglas.py": (
                "from book_text_rag.adapters.storage.sqlite import SqliteStore\n\n\n"
                "def usar() -> object:\n    return SqliteStore\n"
            ),
            "book_text_rag/adapters/__init__.py": "",
            "book_text_rag/adapters/storage/__init__.py": "",
            "book_text_rag/adapters/storage/sqlite.py": "class SqliteStore:\n    pass\n",
        },
    )

    resultado = _ejecutar_guardian(raiz)

    assert resultado.returncode == 1
    assert "domain/reglas.py:1" in resultado.stderr
    assert "«domain» no puede importar «adapters»" in resultado.stderr


def test_una_capa_intermedia_no_puede_importar_la_cli(tmp_path: Path) -> None:
    raiz = _arbol(
        tmp_path,
        {
            "book_text_rag/__init__.py": "",
            "book_text_rag/ports/__init__.py": "",
            "book_text_rag/ports/contrato.py": "from book_text_rag.cli import main\n",
            "book_text_rag/cli.py": "def main() -> int:\n    return 0\n",
        },
    )

    resultado = _ejecutar_guardian(raiz)

    assert resultado.returncode == 1
    assert "«ports» no puede importar «cli»" in resultado.stderr


def test_un_arbol_valido_pasa(tmp_path: Path) -> None:
    raiz = _arbol(
        tmp_path,
        {
            "book_text_rag/__init__.py": "",
            "book_text_rag/domain/__init__.py": "",
            "book_text_rag/domain/reglas.py": "VALOR = 1\n",
            "book_text_rag/ports/__init__.py": "",
            "book_text_rag/ports/contrato.py": "from book_text_rag.domain.reglas import VALOR\n",
            "book_text_rag/application/__init__.py": "",
            "book_text_rag/application/caso.py": "from book_text_rag.ports.contrato import VALOR\n",
            "book_text_rag/cli.py": "from book_text_rag.application.caso import VALOR\n",
        },
    )

    resultado = _ejecutar_guardian(raiz)

    assert resultado.returncode == 0, resultado.stderr
    assert "arquitectura OK" in resultado.stdout


def test_mypy_falla_ante_un_error_de_tipado(tmp_path: Path) -> None:
    """El control de tipado es real: un archivo mal tipado hace fallar a MyPy estricto."""
    archivo = tmp_path / "mal_tipado.py"
    archivo.write_text("def f() -> int:\n    return 'texto'\n", encoding="utf-8")

    resultado = subprocess.run(
        [sys.executable, "-m", "mypy", "--strict", "--no-incremental", str(archivo)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=_entorno(),
    )

    assert resultado.returncode != 0
    assert "Incompatible return value type" in resultado.stdout


def test_el_hook_bloquea_el_commit_cuando_un_control_falla(tmp_path: Path) -> None:
    """Se sustituye el intérprete por uno que falla: el hook debe abortar."""
    falso = tmp_path / "python_que_falla.sh"
    falso.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    falso.chmod(0o755)

    resultado = subprocess.run(
        ["sh", str(HOOK)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=RAIZ,
        env={**_entorno(), "BTRAG_PYTHON": str(falso)},
    )

    assert resultado.returncode != 0
    assert "[pre-commit] arquitectura hexagonal" in resultado.stdout


def test_el_hook_existe_y_es_versionado() -> None:
    contenido = HOOK.read_text(encoding="utf-8")

    assert "check_architecture.py" in contenido
    assert "-m ruff check ." in contenido
    assert "-m ruff format --check ." in contenido
    assert "-m mypy" in contenido
