"""Guardián de la dirección de dependencias de la arquitectura hexagonal.

Capas reales del proyecto (`src/book_text_rag/`) y lo que cada una puede importar:

    domain       ←  nada del proyecto: reglas puras, sin puertos ni adaptadores
    ports        ←  domain
    adapters     ←  domain, ports
    application  ←  domain, ports
    cli          ←  domain, ports, application, adapters  (raíz de composición)

Una violación es cualquier import que apunte a una capa no permitida. Se analiza el árbol de imports
con `ast`, sin ejecutar el código. `EXCEPCIONES` registra deuda **concreta** —un archivo y un módulo
exactos, no una capa entera—; cualquier otra violación falla.

Uso:
    python scripts/check_architecture.py            # analiza src/book_text_rag
    python scripts/check_architecture.py --root DIR # analiza DIR/book_text_rag (para pruebas)
"""

from __future__ import annotations

import argparse
import ast
import sys
from dataclasses import dataclass
from pathlib import Path

PAQUETE = "book_text_rag"

PERMITIDAS: dict[str, frozenset[str]] = {
    "domain": frozenset(),
    "ports": frozenset({"domain"}),
    "adapters": frozenset({"domain", "ports"}),
    "application": frozenset({"domain", "ports"}),
    "cli": frozenset({"domain", "ports", "application", "adapters"}),
}

EXCEPCIONES: dict[tuple[str, str], str] = {}
"""Sin excepciones: la aplicación no importa adaptadores. Si aparece una violación, es un fallo."""

"""Deuda aceptada, con archivo y módulo **exactos**. Cualquier otra violación es un fallo."""


@dataclass(frozen=True)
class Violacion:
    archivo: str
    linea: int
    capa: str
    modulo: str
    capa_destino: str

    def __str__(self) -> str:
        permitidas = ", ".join(sorted(PERMITIDAS[self.capa])) or "ninguna"
        return (
            f"{self.archivo}:{self.linea}: «{self.capa}» no puede importar «{self.capa_destino}» "
            f"({self.modulo}); permitidas: {permitidas}"
        )


def _capa_de(modulo: str) -> str | None:
    """Primera capa del proyecto a la que apunta un módulo (`book_text_rag.<capa>...`)."""
    partes = modulo.split(".")
    if len(partes) < 2 or partes[0] != PAQUETE:
        return None
    candidata = partes[1]
    return candidata if candidata in PERMITIDAS else None


def _modulos_importados(arbol: ast.AST) -> list[tuple[int, str]]:
    """Pares `(línea, módulo)` de todos los imports, incluidos los que están dentro de funciones."""
    encontrados: list[tuple[int, str]] = []
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Import):
            for alias in nodo.names:
                encontrados.append((nodo.lineno, alias.name))
        elif isinstance(nodo, ast.ImportFrom):
            if nodo.module is not None:
                encontrados.append((nodo.lineno, nodo.module))
            elif nodo.level == 0:
                continue
        elif isinstance(nodo, ast.ImportFrom) is False:
            continue
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.ImportFrom) and nodo.module == PAQUETE:
            for alias in nodo.names:
                encontrados.append((nodo.lineno, f"{PAQUETE}.{alias.name}"))
    return encontrados


def analizar(raiz: Path) -> tuple[list[Violacion], int]:
    """Devuelve las violaciones encontradas y cuántos imports del proyecto se revisaron."""
    paquete = raiz / PAQUETE
    violaciones: list[Violacion] = []
    revisados = 0
    for archivo in sorted(paquete.rglob("*.py")):
        relativo = archivo.relative_to(paquete).as_posix()
        capa = relativo.split("/")[0].removesuffix(".py")
        if capa not in PERMITIDAS:
            continue  # archivos de la raíz del paquete (__init__.py) no pertenecen a una capa
        arbol = ast.parse(archivo.read_text(encoding="utf-8"), filename=str(archivo))
        for linea, modulo in _modulos_importados(arbol):
            destino = _capa_de(modulo)
            if destino is None or destino == capa:
                continue
            revisados += 1
            if destino in PERMITIDAS[capa]:
                continue
            if any(
                relativo == archivo_exceto and modulo.startswith(modulo_exceto)
                for archivo_exceto, modulo_exceto in EXCEPCIONES
            ):
                continue
            violaciones.append(Violacion(relativo, linea, capa, modulo, destino))
    return violaciones, revisados


def main(argv: list[str] | None = None) -> int:
    """Devuelve 0 si la arquitectura respeta la dirección; 1 si hay violaciones."""
    parser = argparse.ArgumentParser(description="Verifica la dirección de dependencias entre capas.")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "src",
        help="directorio que contiene el paquete (por defecto src)",
    )
    argumentos = parser.parse_args(argv)
    violaciones, revisados = analizar(argumentos.root)
    if violaciones:
        print(f"arquitectura: {len(violaciones)} violación(es) de dirección de dependencias", file=sys.stderr)
        for violacion in violaciones:
            print(f"  {violacion}", file=sys.stderr)
        return 1
    print(f"arquitectura OK: {revisados} imports entre capas respetan la dirección")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
