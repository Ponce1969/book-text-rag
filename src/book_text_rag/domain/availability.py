"""Disponibilidad del almacén conforme a la política de `D-14`.

`D-14` fija cinco clases de causa, y solo la última **no** es degradación: **ausente**, **inaccesible**,
**incompatible**, **capacidad o extensión del motor ausente** y **disponible** («válido y vacío» es un
caso de disponible). Las cuatro primeras comparten el mismo efecto observable —`degraded`,
`dependencies` con `index`, ningún modo disponible— y difieren solo en el detalle que pertenece al
registro operativo, que este incremento **no** implementa.

El **resumen** que se publica es el que autoriza la decisión: `status`, `dependencies` y
`capabilities.available_modes`. La clase de causa **no** se publica como vocabulario de contrato.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

ESTADO_DISPONIBLE = "ok"
ESTADO_DEGRADADO = "degraded"

DEPENDENCIA_INDICE = "index"
MODO_LEXICO = "lexical"


class AvailabilityCause(StrEnum):
    """Las cinco clases de `D-14` ítem 3. Solo `DISPONIBLE` no es degradación."""

    AUSENTE = "ausente"
    INACCESIBLE = "inaccesible"
    INCOMPATIBLE = "incompatible"
    CAPACIDAD_AUSENTE = "capacidad_ausente"
    DISPONIBLE = "disponible"


@dataclass(frozen=True)
class Availability:
    """Resultado de la sonda: la causa, y la propiedad que decide el comportamiento observable."""

    cause: AvailabilityCause

    @property
    def disponible(self) -> bool:
        """`True` solo si el almacén es reconocible y utilizable para el modo `lexical`."""
        return self.cause is AvailabilityCause.DISPONIBLE


@dataclass(frozen=True)
class HealthSummary:
    """Resumen que publica `health`: los tres campos que `D-14` ítem 4 y `D-07` autorizan."""

    status: str
    dependencies: tuple[str, ...]
    available_modes: tuple[str, ...]

    @classmethod
    def desde(cls, availability: Availability) -> HealthSummary:
        """Proyecta la causa al resumen público, sin exponerla."""
        if availability.disponible:
            return cls(status=ESTADO_DISPONIBLE, dependencies=(), available_modes=(MODO_LEXICO,))
        return cls(status=ESTADO_DEGRADADO, dependencies=(DEPENDENCIA_INDICE,), available_modes=())
