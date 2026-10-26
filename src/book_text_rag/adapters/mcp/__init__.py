"""Adaptador MCP de solo lectura: servidor Streamable HTTP con `search`, `get_document` y `health`.

Esta es la **única** capa del proyecto que importa el SDK de MCP (S10). La configuración llega
fail-closed por entorno (`config`), la barrera bearer protege el transporte (`auth`) y el servidor
expone las tres herramientas de `D-07` sobre los casos de uso que la raíz de composición le entrega
(`server`). Ningún módulo de aplicación o dominio conoce este paquete.
"""

from __future__ import annotations

from book_text_rag.adapters.mcp.auth import AutenticacionBearer
from book_text_rag.adapters.mcp.config import (
    ENV_ALMACEN,
    ENV_DIRECCION,
    ENV_PUERTO,
    ENV_TIMEOUT,
    ENV_TOKEN,
    PUERTO_DEFECTO,
    TIMEOUT_DEFECTO_SEGUNDOS,
    ConfiguracionInvalida,
    ConfiguracionMcp,
    desde_entorno,
)
from book_text_rag.adapters.mcp.server import (
    MODO_SOPORTADO,
    configurar_registro,
    construir_aplicacion,
    construir_servidor,
)

__all__ = [
    "ENV_ALMACEN",
    "ENV_DIRECCION",
    "ENV_PUERTO",
    "ENV_TIMEOUT",
    "ENV_TOKEN",
    "MODO_SOPORTADO",
    "PUERTO_DEFECTO",
    "TIMEOUT_DEFECTO_SEGUNDOS",
    "AutenticacionBearer",
    "ConfiguracionInvalida",
    "ConfiguracionMcp",
    "configurar_registro",
    "construir_aplicacion",
    "construir_servidor",
    "desde_entorno",
]
