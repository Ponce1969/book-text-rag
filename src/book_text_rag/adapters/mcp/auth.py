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

from starlette.types import ASGIApp, Receive, Scope, Send

_ESQUEMA_BEARER = b"bearer"
_CUERPO_401 = b'{"error": "unauthorized"}'


class AutenticacionBearer:
    """Middleware ASGI: exige el bearer exacto en toda petición HTTP; `lifespan` y `websocket` pasan.

    No hay ruta pública sin barrera: el `401` se emite para cualquier método y camino, y la
    respuesta no distingue token ausente de token erróneo (sin oráculo) ni revela el esperado.
    """

    def __init__(self, app: ASGIApp, token: str) -> None:
        self.app = app
        self._token = token.encode()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        if not self._autorizado(scope):
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

    def _autorizado(self, scope: Scope) -> bool:
        """`True` solo con `Bearer <token>` exacto (esquema sin distinción de mayúsculas, RFC 6750)."""
        cabecera = next((valor for nombre, valor in scope.get("headers", ()) if nombre == b"authorization"), b"")
        esquema, separador, credenciales = cabecera.partition(b" ")
        if not separador or esquema.lower() != _ESQUEMA_BEARER:
            return False
        return hmac.compare_digest(credenciales, self._token)
