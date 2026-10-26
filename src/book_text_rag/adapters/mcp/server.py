"""Servidor MCP de solo lectura sobre Streamable HTTP (T1/T3/T4: S1, S5, S7, S8).

Registra **exactamente** tres herramientas —`search`, `get_document` y `health`— todas anotadas de
solo lectura; no existe ingesta, reconstrucción ni superficie administrativa alguna (S5). Las
herramientas delegan en llamadas que la raíz de composición (`cli.py`) fija a los casos de uso
existentes: este módulo **no** importa la capa de aplicación ni conoce el almacén, de modo que la
dirección de dependencias (adaptadores → dominio/puertos) permanece intacta y el guardián de
arquitectura sigue en verde sin excepciones nuevas (S10). El SDK de MCP solo se importa en
`adapters/`, nunca en aplicación ni dominio (S10).

Borde de `D-07` (T3): `mode` solo admite `lexical` y cualquier otro valor se rechaza **explícitamente**
antes de tocar los casos de uso; `query`, `top_k` y `document_ids` se validan en la aplicación que
llamamos, con mensajes estáticos. Toda llamada corre en un hilo con timeout configurable (5 s por
defecto, S7) y un timeout es un **error explícito**, nunca una respuesta vacía silenciosa.

Registro (S8): solo metadatos —nombre de herramienta, duración, resultado, código de error—; jamás
texto de consulta, contenido recuperado, token ni rutas. Los mensajes de rechazo que el SDK registra
son estáticos, y cualquier excepción no prevista se informa sin volcar su detalle (que podría
contener una ruta) ni su traza al cliente.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from functools import partial

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from starlette.types import ASGIApp

from book_text_rag.adapters.mcp.auth import AutenticacionBearer
from book_text_rag.adapters.mcp.config import ConfiguracionMcp
from book_text_rag.ports.storage import StoreError

logger = logging.getLogger(__name__)

MODO_SOPORTADO = "lexical"
"""Único modo admitido en el MVP (`S7`/`D-07`); `mode` es un parámetro con valor por defecto."""


def configurar_registro() -> None:
    """Fija la política de registro del servicio (S8): nivel de servicio y sin trazas de transporte.

    `sse_starlette` vuelca los trozos SSE **crudos** a nivel DEBUG —con el contenido recuperado
    dentro de la traza—; se le fija `WARNING` para que ni un ajuste global de nivel ponga texto de
    consulta ni contenido en los registros. El resto de los registradores queda en INFO con la
    salida por defecto, donde todos los mensajes del servicio y del SDK son metadatos estáticos.
    """
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    logging.getLogger("sse_starlette").setLevel(logging.WARNING)


type Llamada = Callable[..., dict[str, object]]
"""Caso de uso ya compuesto por la raíz: recibe los argumentos de la herramienta y responde JSON."""

type LlamadaNula = Callable[[], dict[str, object]]


def _anotaciones_solo_lectura() -> ToolAnnotations:
    """Las cuatro pistas en valor explícito: sin ellas `destructive_hint` implica `True` por defecto."""
    return ToolAnnotations(
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    )


async def _ejecutar(nombre: str, llamada: LlamadaNula, timeout_consulta: float) -> dict[str, object]:
    """Ejecuta un caso de uso en un hilo con timeout y traduce el fallo a `ToolError` sin secretos.

    El orden de las ramas importa: `TimeoutError` y `ValueError` son subclases de `Exception`, y
    cualquier excepción no prevista se reduce a un mensaje genérico para que el detalle —que puede
    contener rutas o texto del almacén— no llegue ni al cliente ni al registro (S8).
    """
    inicio = time.monotonic()
    try:
        resultado = await asyncio.wait_for(asyncio.to_thread(llamada), timeout=timeout_consulta)
    except TimeoutError:
        logger.info("herramienta=%s resultado=timeout limite_s=%.3f", nombre, timeout_consulta)
        raise ToolError(f"la operación '{nombre}' superó el tiempo límite de {timeout_consulta:g} segundos") from None
    except StoreError as error:
        # `error.message` es estático en todo el camino de lectura; el detalle (puede llevar la ruta)
        # no se propaga ni se registra.
        logger.info("herramienta=%s resultado=error codigo=%s", nombre, error.code.value)
        raise ToolError(f"{error.code.value}: {error.message}") from error
    except ValueError as error:
        # Validaciones de `D-07` en la aplicación: mensajes estáticos, sin el valor rechazado.
        logger.info("herramienta=%s resultado=rechazo", nombre)
        raise ToolError(str(error)) from error
    except ToolError:
        raise
    except Exception as error:
        logger.warning("herramienta=%s resultado=fallo_inesperado tipo=%s", nombre, type(error).__name__)
        raise ToolError(f"error interno no previsto en la operación '{nombre}'") from None
    duracion_ms = int((time.monotonic() - inicio) * 1000)
    logger.info("herramienta=%s resultado=ok duracion_ms=%d", nombre, duracion_ms)
    return resultado


def construir_servidor(
    *,
    buscar: Llamada,
    obtener_documento: Llamada,
    estado: Llamada,
    timeout_consulta: float,
) -> MCPServer:
    """Crea el `MCPServer` con las tres herramientas ligadas a los casos de uso dados."""
    servidor = MCPServer(
        name="book-text-rag-mcp",
        description="Recuperación de evidencia textual de solo lectura (search, get_document, health).",
        instructions=(
            "Servicio de solo lectura: no expone ingesta, reconstrucción ni operación administrativa. "
            "Admite únicamente el modo lexical (D-07)."
        ),
    )

    @servidor.tool(
        name="search",
        description=(
            "Consulta léxica BM25 de solo lectura sobre el índice del corpus; devuelve resultados con "
            "procedencia (document_id, chunk_id, secciones y páginas). Acepta solo mode=lexical (D-07)."
        ),
        annotations=_anotaciones_solo_lectura(),
    )
    async def herramienta_search(
        query: str,
        top_k: int = 10,
        mode: str = MODO_SOPORTADO,
        document_ids: list[str] | None = None,
    ) -> dict[str, object]:
        if mode != MODO_SOPORTADO:
            raise ToolError(f"mode solo admite '{MODO_SOPORTADO}' en este servicio (D-07)")
        identificadores = None if document_ids is None else tuple(document_ids)
        return await _ejecutar(
            "search",
            partial(buscar, query=query, top_k=top_k, document_ids=identificadores),
            timeout_consulta,
        )

    @servidor.tool(
        name="get_document",
        description=(
            "Ficha pública de un documento (siete campos de D-07): identificador, versión resuelta, "
            "origen, formato, páginas, identidad del índice y estado. Sin fragmentos ni contenido."
        ),
        annotations=_anotaciones_solo_lectura(),
    )
    async def herramienta_get_document(document_id: str, document_version: str | None = None) -> dict[str, object]:
        return await _ejecutar(
            "get_document",
            partial(obtener_documento, document_id, document_version),
            timeout_consulta,
        )

    @servidor.tool(
        name="health",
        description=(
            "Disponibilidad del almacén (D-14): status, dependencies y available_modes. "
            "Solo lectura: no crea, no escribe y no repara."
        ),
        annotations=_anotaciones_solo_lectura(),
    )
    async def herramienta_health() -> dict[str, object]:
        return await _ejecutar("health", estado, timeout_consulta)

    return servidor


def construir_aplicacion(servidor: MCPServer, configuracion: ConfiguracionMcp) -> ASGIApp:
    """App ASGI de Streamable HTTP con Host acotado a la dirección configurada y bearer al frente.

    `TransportSecuritySettings` acota la cabecera `Host` a la dirección de enlace (y su forma con
    puerto), de modo que también a nivel HTTP el servicio responde solo en esa interfaz (S2); la
    barrera `AutenticacionBearer` rechaza con `401` antes de que el transporte vea la petición (S3).
    """
    seguridad = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[configuracion.direccion, f"{configuracion.direccion}:*"],
        allowed_origins=[
            f"{esquema}://{host}"
            for esquema in ("http", "https")
            for host in (configuracion.direccion, f"{configuracion.direccion}:*")
        ],
    )
    app = servidor.streamable_http_app(
        transport_security=seguridad,
        host=configuracion.direccion,
    )
    return AutenticacionBearer(app, configuracion.token)
