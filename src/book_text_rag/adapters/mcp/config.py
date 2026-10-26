"""Configuración por entorno del servicio MCP, con arranque fail-closed (T2/T3: S2, S3, S7).

El servicio MCP no acepta argumentos de línea de comandos: todo llega por variables de entorno
**independientes de cualquier otro servicio** (S3):

- `BOOK_TEXT_RAG_MCP_STORE` — ruta del almacén SQLite (obligatoria).
- `BOOK_TEXT_RAG_MCP_BIND_ADDRESS` — dirección de enlace (obligatoria; `0.0.0.0` y `::` están
  prohibidos: el servicio debe enlazar solo una dirección concreta, la de la interfaz Tailscale, S2).
- `BOOK_TEXT_RAG_MCP_PORT` — puerto TCP (8020 por defecto, S4).
- `BOOK_TEXT_RAG_MCP_TOKEN` — bearer propio e independiente (obligatorio y no vacío, S3).
- `BOOK_TEXT_RAG_MCP_QUERY_TIMEOUT_SECONDS` — timeout de consulta (5 s por defecto, S7).

Cualquier requisito incumplido produce `ConfiguracionInvalida` y el proceso **no arranca**: el fallo
es cerrado, no hay valor por defecto para lo obligatorio. Los mensajes de error nombran la variable
y el problema, y **nunca** incluyen el valor del token.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

ENV_ALMACEN = "BOOK_TEXT_RAG_MCP_STORE"
ENV_DIRECCION = "BOOK_TEXT_RAG_MCP_BIND_ADDRESS"
ENV_PUERTO = "BOOK_TEXT_RAG_MCP_PORT"
ENV_TOKEN = "BOOK_TEXT_RAG_MCP_TOKEN"
ENV_TIMEOUT = "BOOK_TEXT_RAG_MCP_QUERY_TIMEOUT_SECONDS"

PUERTO_DEFECTO = 8020
"""Puerto objetivo del servicio (`S4`); comprobado libre el 2026-10-24."""

TIMEOUT_DEFECTO_SEGUNDOS = 5.0
"""Timeout de consulta por defecto (`S7`): configurable por entorno, no es constante universal."""

DIRECCIONES_PROHIBIDAS = frozenset({"0.0.0.0", "::"})
"""Enlaces comodín que publicarían el servicio fuera de la interfaz prevista (`S2`)."""


class ConfiguracionInvalida(Exception):
    """Configuración obligatoria ausente o insegura: el servicio no arranca. Nunca lleva secretos."""


@dataclass(frozen=True)
class ConfiguracionMcp:
    """Valores ya validados con los que arranca el servicio MCP."""

    almacen: Path
    direccion: str
    puerto: int
    token: str
    timeout_consulta: float


def _obligatorio(entorno: Mapping[str, str], variable: str, detalle: str) -> str:
    """Lee una variable obligatoria; ausente o vacía ⇒ `ConfiguracionInvalida` (fallo cerrado)."""
    valor = entorno.get(variable, "")
    if not valor.strip():
        raise ConfiguracionInvalida(f"falta {variable}: {detalle}; el servicio no arranca sin ella")
    return valor


def _puerto(entorno: Mapping[str, str]) -> int:
    """Puerto del entorno o el defecto de `S4`; solo un entero 1..65535."""
    crudo = entorno.get(ENV_PUERTO, "").strip() or str(PUERTO_DEFECTO)
    try:
        puerto = int(crudo)
    except ValueError:
        raise ConfiguracionInvalida(f"{ENV_PUERTO} debe ser un entero entre 1 y 65535, no {crudo!r}") from None
    if not 1 <= puerto <= 65535:
        raise ConfiguracionInvalida(f"{ENV_PUERTO} debe estar entre 1 y 65535, no {puerto}")
    return puerto


def _timeout(entorno: Mapping[str, str]) -> float:
    """Timeout de consulta del entorno o 5 s (`S7`); solo un número finito estrictamente positivo."""
    crudo = entorno.get(ENV_TIMEOUT, "").strip() or str(TIMEOUT_DEFECTO_SEGUNDOS)
    try:
        segundos = float(crudo)
    except ValueError:
        raise ConfiguracionInvalida(f"{ENV_TIMEOUT} debe ser un número de segundos > 0, no {crudo!r}") from None
    if not math.isfinite(segundos) or segundos <= 0:
        raise ConfiguracionInvalida(f"{ENV_TIMEOUT} debe ser un número finito > 0, no {crudo!r}")
    return segundos


def desde_entorno(entorno: Mapping[str, str]) -> ConfiguracionMcp:
    """Valida el entorno y devuelve la configuración, o rechaza el arranque con `ConfiguracionInvalida`.

    El token solo se exige no vacío (`strip()` detecta el vacío); el valor se conserva **sin**
    recortar, porque la comparación en el borde HTTP es exacta.
    """
    almacen = _obligatorio(entorno, ENV_ALMACEN, "la ruta del almacén SQLite de solo lectura")
    direccion = _obligatorio(
        entorno, ENV_DIRECCION, "la dirección de enlace (la de la interfaz Tailscale; no se admite 0.0.0.0 ni ::)"
    ).strip()
    if direccion in DIRECCIONES_PROHIBIDAS:
        raise ConfiguracionInvalida(
            f"{ENV_DIRECCION}={direccion} está prohibido: el servicio solo puede enlazar una dirección concreta (S2)"
        )
    token = _obligatorio(entorno, ENV_TOKEN, "el bearer propio de este servicio (S3)")
    return ConfiguracionMcp(
        almacen=Path(almacen),
        direccion=direccion,
        puerto=_puerto(entorno),
        token=token,
        timeout_consulta=_timeout(entorno),
    )
