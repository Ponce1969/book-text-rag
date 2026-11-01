"""Barrera bearer del servicio MCP (T2: S3), delante del transporte Streamable HTTP.

Compara `Authorization: Bearer <token>` contra el secreto de la configuración con igualdad
**exacta** (`hmac.compare_digest`, en bytes, sin normalizar): cualquier cabecera ausente, con otro
esquema o con otro token recibe `401` **antes** de que el transporte cree sesión alguna. El token
nunca se registra, no aparece en la respuesta y solo vive en memoria de este proceso: el secreto es
propio e independiente de cualquier otro servicio (S3).

Se implementa aquí como middleware ASGI en lugar de usar `token_verifier` del SDK, porque esa vía
exige `AuthSettings` con un `issuer_url` OAuth que este servicio no tiene (no expone descubrimiento
ni flujo de autorización); inventar un issuer añadiría superficie falsa. El transporte y el
protocolo MCP siguen siendo los del SDK oficial `mcp` (S1).
"""

from __future__ import annotations

import hmac
import logging

from starlette.types import ASGIApp, Receive, Scope, Send

_ESQUEMA_BEARER = b"bearer"
_CUERPO_401 = b'{"error": "unauthorized"}'

# Motivos internos del rechazo. Se registran como metadato y **no** cambian la decisión: los cuatro
# rechazan. Solo hacen legible un 401 que, sin ellos, es indistinguible de un token incorrecto.
SIN_CABECERA = "sin_cabecera"
BEARER_VACIO = "bearer_vacio"
ESQUEMA_INCORRECTO = "esquema_incorrecto"
TOKEN_NO_COINCIDE = "token_no_coincide"

logger = logging.getLogger(__name__)


class AutenticacionBearer:
    """Middleware ASGI: exige el bearer exacto en toda petición HTTP; `lifespan` y `websocket` pasan.

    No hay ruta pública sin barrera: el `401` se emite para cualquier método y camino, y la
    respuesta no distingue token ausente de token erróneo (sin oráculo) ni revela el esperado.
    El motivo del rechazo se registra como metadato de diagnóstico: nunca la cabecera, ni el token
    recibido, ni el esperado.
    """

    def __init__(self, app: ASGIApp, token: str) -> None:
        self.app = app
        self._token = token.encode()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        motivo = self._motivo_rechazo(scope)
        if motivo is not None:
            logger.info("autenticacion_rechazada motivo=%s", motivo)
            await send(
                {
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(_CUERPO_401)).encode()),
                        (b"www-authenticate", b'Bearer realm="book-text-rag-mcp"'),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": _CUERPO_401})
            return
        await self.app(scope, receive, send)

    def _motivo_rechazo(self, scope: Scope) -> str | None:
        """`None` solo con `Bearer <token>` exacto (esquema sin distinción de mayúsculas, RFC 6750).

        Clasifica el rechazo para el registro. La comparación y el conjunto de peticiones aceptadas
        son los mismos que antes: esquema `bearer`, separador presente e igualdad exacta del token.
        """
        cabecera = next((valor for nombre, valor in scope.get("headers", ()) if nombre == b"authorization"), None)
        if cabecera is None:
            return SIN_CABECERA
        esquema, separador, credenciales = cabecera.partition(b" ")
        if esquema.lower() != _ESQUEMA_BEARER:
            return ESQUEMA_INCORRECTO
        if not separador or not credenciales.strip():
            return BEARER_VACIO
        return None if hmac.compare_digest(credenciales, self._token) else TOKEN_NO_COINCIDE
