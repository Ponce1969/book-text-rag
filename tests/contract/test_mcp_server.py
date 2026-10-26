"""Contrato del servicio MCP de solo lectura sobre Streamable HTTP (T1/T3/T4/T5: S1, S5, S7, S8).

Prueba la app real que compone `aplicacion_mcp` —el mismo camino que arranca `book-text-rag-mcp`—
a través del protocolo MCP completo (`initialize` → `notifications/initialized` → `tools/list` /
`tools/call`) con el transporte Streamable HTTP del SDK `mcp`. Cubre las tres herramientas, cada
límite rechazado de `D-07`, la barrera bearer, el timeout explícito, la no escritura del almacén y
la higiene de los registros (S8).

Los almacenes se siembran en `tmp_path` con el patrón de los tests de contrato existentes: nunca
el corpus real de `~/datos` ni almacenes de evaluación (`piloto*.sqlite`, `segundo*.sqlite`).
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import sqlite3
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx2
import pytest
from starlette.types import ASGIApp

from book_text_rag import cli
from book_text_rag.adapters.mcp import (
    ENV_ALMACEN,
    ENV_DIRECCION,
    ENV_PUERTO,
    ENV_TIMEOUT,
    ENV_TOKEN,
    ConfiguracionMcp,
    configurar_registro,
    desde_entorno,
)
from book_text_rag.adapters.mcp.auth import AutenticacionBearer
from book_text_rag.adapters.storage.sqlite import SqliteStore
from book_text_rag.cli import aplicacion_mcp
from book_text_rag.domain.identity import chunk_id, content_hash
from book_text_rag.ports.storage import EstadoIngesta

DOC = "libro"
VERSION = "d" * 64
TEXTO = "evidencia textual con procedencia verificable sobre recuperacion lexica"
TOKEN = "token-de-prueba-de-contrato"
DIRECCION = "127.0.0.1"
PUERTO = "8020"
BASE = f"http://{DIRECCION}:{PUERTO}"
_PROTOCOLO = "2025-06-18"
_ACEPTAR = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


# --- Semilla y utilidades (patrón de tests/contract/test_cli_consulta.py) ---------------------------


def _huella(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def _laterales(ruta: Path) -> list[str]:
    return sorted(path.name for path in ruta.parent.glob(f"{ruta.name}-*"))


def _sembrar(tmp_path: Path) -> Path:
    """Crea `tmp_path/mcp.sqlite` con un documento publicado de dos fragmentos consultables."""
    ruta = tmp_path / "mcp.sqlite"
    SqliteStore(ruta).initialize()
    conexion = sqlite3.connect(ruta)
    try:
        conexion.execute("INSERT INTO fuente (document_id, source_format, page_count) VALUES (?, 'pdf', 25)", (DOC,))
        conexion.execute(
            "INSERT INTO referencia_fuente (document_id, alias, tipo_asignacion, fecha, estado_ingesta) "
            "VALUES (?, 'alias', 'deliberada', '2026-10-24', ?)",
            (DOC, EstadoIngesta.COMPLETADA.value),
        )
        conexion.execute("INSERT INTO version_documento (document_id, document_version) VALUES (?, ?)", (DOC, VERSION))
        for ordinal in (1, 2):
            contenido = f"{TEXTO} (fragmento {ordinal})"
            conexion.execute(
                "INSERT INTO fragmento (document_id, document_version, ordinal, chunk_id, section_path, level, "
                "block_type, captions, pdf_page_start, pdf_page_end, content, content_hash, anchor_level) "
                "VALUES (?, ?, ?, ?, '[\"Capitulo\"]', 1, 'prose', '[]', ?, ?, ?, ?, 'posicional')",
                (
                    DOC,
                    VERSION,
                    ordinal,
                    chunk_id(DOC, VERSION[:12], ordinal),
                    ordinal,
                    ordinal,
                    contenido,
                    content_hash(contenido),
                ),
            )
            conexion.execute(
                "INSERT INTO fragmento_fts (document_id, document_version, ordinal, content) VALUES (?, ?, ?, ?)",
                (DOC, VERSION, ordinal, contenido),
            )
        conexion.commit()
    finally:
        conexion.close()
    return ruta


def _configuracion(almacen: Path, **extras: str) -> ConfiguracionMcp:
    """Configuración válida de prueba: dirección de loopback (permitida), token propio, sin eval."""
    return desde_entorno(
        {
            ENV_ALMACEN: str(almacen),
            ENV_DIRECCION: DIRECCION,
            ENV_PUERTO: PUERTO,
            ENV_TOKEN: TOKEN,
            **extras,
        }
    )


def _aplicacion(almacen: Path, **extras: str) -> ASGIApp:
    return aplicacion_mcp(_configuracion(almacen, **extras))


def _inicializacion() -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": 0,
        "method": "initialize",
        "params": {
            "protocolVersion": _PROTOCOLO,
            "capabilities": {},
            "clientInfo": {"name": "pruebas-contrato", "version": "0"},
        },
    }


def _mensaje_sse(texto: str) -> dict[str, Any]:
    """Extrae el mensaje JSON-RPC de la respuesta SSE de un POST (json_response=False, S1)."""
    for linea in texto.splitlines():
        if linea.startswith("data: "):
            dato = json.loads(linea.removeprefix("data: "))
            if isinstance(dato, dict) and ("result" in dato or "error" in dato):
                return dato
    raise AssertionError(f"la respuesta no contiene un mensaje JSON-RPC: {texto!r}")


class _Sesion:
    """Cliente MCP con sesión iniciada: `rpc` devuelve el mensaje de la respuesta."""

    def __init__(self, cliente: httpx2.AsyncClient, cabeceras: dict[str, str]) -> None:
        self._cliente = cliente
        self._cabeceras = cabeceras
        self._identificador = 0

    async def rpc(self, metodo: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._identificador += 1
        cuerpo: dict[str, Any] = {"jsonrpc": "2.0", "id": self._identificador, "method": metodo}
        if params is not None:
            cuerpo["params"] = params
        respuesta = await self._cliente.post("/mcp", json=cuerpo, headers=self._cabeceras)
        assert respuesta.status_code == 200, f"{respuesta.status_code}: {respuesta.text}"
        return _mensaje_sse(respuesta.text)

    async def listar(self) -> list[dict[str, Any]]:
        mensaje = await self.rpc("tools/list")
        return list(mensaje["result"]["tools"])

    async def llamar(self, nombre: str, argumentos: dict[str, Any]) -> tuple[bool, str]:
        """`(isError, texto)`: en éxito el texto es JSON de la herramienta; en rechazo, mensaje estático."""
        mensaje = await self.rpc("tools/call", {"name": nombre, "arguments": argumentos})
        resultado = mensaje["result"]
        return bool(resultado.get("isError")), str(resultado["content"][0]["text"])


@contextlib.asynccontextmanager
async def _servicio(app: ASGIApp) -> AsyncIterator[None]:
    """Ejecuta el lifespan real (session manager del SDK) bajo la barrera bearer."""
    interno = app.app if isinstance(app, AutenticacionBearer) else app
    async with interno.router.lifespan_context(interno):
        yield


@contextlib.asynccontextmanager
async def _cliente(app: ASGIApp, token: str | None = TOKEN) -> AsyncIterator[_Sesion]:
    """Servicio en marcha y sesión MCP inicializada con el bearer indicado (`None` = sin cabecera)."""
    async with (
        _servicio(app),
        httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url=BASE) as cliente,
    ):
        cabeceras = dict(_ACEPTAR)
        if token is not None:
            cabeceras["Authorization"] = f"Bearer {token}"
        respuesta = await cliente.post("/mcp", json=_inicializacion(), headers=cabeceras)
        assert respuesta.status_code == 200, f"{respuesta.status_code}: {respuesta.text}"
        cabeceras["mcp-session-id"] = respuesta.headers["mcp-session-id"]
        notificacion = await cliente.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            headers=cabeceras,
        )
        assert notificacion.status_code == 202, notificacion.text
        yield _Sesion(cliente, cabeceras)


# --- T5: la superficie de solo lectura -------------------------------------------------------------


def test_lista_exactamente_tres_herramientas_de_solo_lectura(tmp_path: Path) -> None:
    app = _aplicacion(_sembrar(tmp_path))

    async def caso() -> None:
        async with _cliente(app) as sesion:
            herramientas = await sesion.listar()
            assert sorted(herramienta["name"] for herramienta in herramientas) == [
                "get_document",
                "health",
                "search",
            ]
            for herramienta in herramientas:
                anotaciones = herramienta["annotations"]
                assert anotaciones["readOnlyHint"] is True
                assert anotaciones["destructiveHint"] is False
                assert anotaciones["openWorldHint"] is False
            esquema = next(h["inputSchema"] for h in herramientas if h["name"] == "search")
            assert set(esquema["properties"]) == {"query", "top_k", "mode", "document_ids"}
            assert esquema["required"] == ["query"]
            assert esquema["properties"]["top_k"]["default"] == 10
            assert esquema["properties"]["mode"]["default"] == "lexical"
            assert "filters" not in esquema["properties"]

    asyncio.run(caso())


# --- T1: las tres herramientas sobre los casos de uso existentes ----------------------------------


def test_search_devuelve_resultados_con_procedencia(tmp_path: Path) -> None:
    app = _aplicacion(_sembrar(tmp_path))

    async def caso() -> None:
        async with _cliente(app) as sesion:
            es_error, texto = await sesion.llamar("search", {"query": "procedencia"})

            assert es_error is False
            datos = json.loads(texto)
            assert datos["mode"] == "lexical"
            assert datos["index_version"] is None  # sin construcción persistida: genuinamente desconocido
            assert len(datos["resultados"]) == 2
            primero = datos["resultados"][0]
            assert primero["rank"] == 1
            assert primero["document_id"] == DOC
            assert primero["document_version"] == VERSION
            assert primero["chunk_id"] == f"{DOC}:{VERSION[:12]}:1"
            assert primero["section_path"] == ["Capitulo"]
            assert primero["pdf_page_start"] == 1
            assert primero["pdf_page_end"] == 1
            assert primero["content"].startswith(TEXTO)
            assert datos["resultados"][1]["rank"] == 2

    asyncio.run(caso())


def test_search_acepta_mode_lexical_y_filtra_por_document_ids(tmp_path: Path) -> None:
    app = _aplicacion(_sembrar(tmp_path))

    async def caso() -> None:
        async with _cliente(app) as sesion:
            es_error, texto = await sesion.llamar(
                "search", {"query": "procedencia", "mode": "lexical", "top_k": 1, "document_ids": [DOC]}
            )
            assert es_error is False
            assert len(json.loads(texto)["resultados"]) == 1

            es_error, texto = await sesion.llamar(
                "search", {"query": "procedencia", "document_ids": ["documento-ausente"]}
            )
            assert es_error is False
            assert json.loads(texto)["resultados"] == []

    asyncio.run(caso())


def test_search_valida_sin_coincidencias_es_respuesta_vacia_no_un_error(tmp_path: Path) -> None:
    app = _aplicacion(_sembrar(tmp_path))

    async def caso() -> None:
        async with _cliente(app) as sesion:
            es_error, texto = await sesion.llamar("search", {"query": "zurdo"})

            assert es_error is False
            assert json.loads(texto)["resultados"] == []

    asyncio.run(caso())


def test_get_document_devuelve_los_siete_campos(tmp_path: Path) -> None:
    app = _aplicacion(_sembrar(tmp_path))

    async def caso() -> None:
        async with _cliente(app) as sesion:
            es_error, texto = await sesion.llamar("get_document", {"document_id": DOC})

            assert es_error is False
            assert json.loads(texto) == {
                "document_id": DOC,
                "document_version": VERSION,
                "title": None,
                "source_format": "pdf",
                "page_count": 25,
                "index_version": None,
                "status": "indexed",
            }

    asyncio.run(caso())


def test_get_document_no_registrado_responde_document_not_found(tmp_path: Path) -> None:
    app = _aplicacion(_sembrar(tmp_path))

    async def caso() -> None:
        async with _cliente(app) as sesion:
            es_error, texto = await sesion.llamar("get_document", {"document_id": "no-existe"})

            assert es_error is True
            assert "document_not_found" in texto

    asyncio.run(caso())


def test_health_informa_ok_con_modos_disponibles(tmp_path: Path) -> None:
    app = _aplicacion(_sembrar(tmp_path))

    async def caso() -> None:
        async with _cliente(app) as sesion:
            es_error, texto = await sesion.llamar("health", {})

            assert es_error is False
            assert json.loads(texto) == {"status": "ok", "dependencies": [], "available_modes": ["lexical"]}

    asyncio.run(caso())


# --- T3: cada límite de D-07 rechazado en el borde -------------------------------------------------


def test_search_rechaza_consulta_vacia(tmp_path: Path) -> None:
    app = _aplicacion(_sembrar(tmp_path))

    async def caso() -> None:
        async with _cliente(app) as sesion:
            es_error, texto = await sesion.llamar("search", {"query": "   "})

            assert es_error is True
            assert "no puede estar vacía" in texto

    asyncio.run(caso())


def test_search_rechaza_consulta_de_1001_caracteres(tmp_path: Path) -> None:
    app = _aplicacion(_sembrar(tmp_path))
    consulta_larga = "q" * 1001

    async def caso() -> None:
        async with _cliente(app) as sesion:
            es_error, texto = await sesion.llamar("search", {"query": consulta_larga})

            assert es_error is True
            assert "1000 caracteres" in texto
            assert consulta_larga not in texto  # el valor rechazado no se refleja ni se registra

    asyncio.run(caso())


def test_search_rechaza_top_k_cero(tmp_path: Path) -> None:
    app = _aplicacion(_sembrar(tmp_path))

    async def caso() -> None:
        async with _cliente(app) as sesion:
            es_error, texto = await sesion.llamar("search", {"query": "procedencia", "top_k": 0})

            assert es_error is True
            assert "top_k" in texto

    asyncio.run(caso())


def test_search_rechaza_top_k_cincuenta_y_uno(tmp_path: Path) -> None:
    app = _aplicacion(_sembrar(tmp_path))

    async def caso() -> None:
        async with _cliente(app) as sesion:
            es_error, texto = await sesion.llamar("search", {"query": "procedencia", "top_k": 51})

            assert es_error is True
            assert "top_k" in texto

    asyncio.run(caso())


def test_search_rechaza_mode_vector_explicitamente(tmp_path: Path) -> None:
    app = _aplicacion(_sembrar(tmp_path))

    async def caso() -> None:
        async with _cliente(app) as sesion:
            es_error, texto = await sesion.llamar("search", {"query": "procedencia", "mode": "vector"})

            assert es_error is True
            assert "mode" in texto
            assert "lexical" in texto

    asyncio.run(caso())


def test_timeout_del_servidor_produce_error_explicito(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Un timeout es un error visible: jamás una respuesta vacía silenciosa (S7)."""
    almacen = _sembrar(tmp_path)

    def lenta(*args: Any, **kwargs: Any) -> dict[str, object]:
        time.sleep(0.3)
        return {}

    monkeypatch.setattr(cli, "search_lexical", lenta)
    app = _aplicacion(almacen, **{ENV_TIMEOUT: "0.05"})

    async def caso() -> None:
        async with _cliente(app) as sesion:
            es_error, texto = await sesion.llamar("search", {"query": "procedencia"})

            assert es_error is True
            assert "tiempo límite" in texto
            assert "0.05" in texto
            assert "resultados" not in texto

    asyncio.run(caso())


# --- T2: la barrera bearer en el borde HTTP --------------------------------------------------------


def test_peticion_sin_token_responde_401(tmp_path: Path) -> None:
    app = _aplicacion(_sembrar(tmp_path))

    async def caso() -> None:
        async with (
            _servicio(app),
            httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url=BASE) as cliente,
        ):
            respuesta = await cliente.post("/mcp", json=_inicializacion(), headers=dict(_ACEPTAR))

            assert respuesta.status_code == 401
            assert TOKEN not in respuesta.text
            assert respuesta.headers["www-authenticate"].startswith("Bearer")

    asyncio.run(caso())


def test_peticion_con_token_incorrecto_responde_401(tmp_path: Path) -> None:
    app = _aplicacion(_sembrar(tmp_path))

    async def caso() -> None:
        async with (
            _servicio(app),
            httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url=BASE) as cliente,
        ):
            cabeceras = {**_ACEPTAR, "Authorization": "Bearer token-erroneo"}
            respuesta = await cliente.post("/mcp", json=_inicializacion(), headers=cabeceras)

            assert respuesta.status_code == 401
            assert TOKEN not in respuesta.text

    asyncio.run(caso())


# --- T4: solo lectura y higiene de registros (S8) ---------------------------------------------------


def test_las_tres_herramientas_no_escriben_el_almacen(tmp_path: Path) -> None:
    almacen = _sembrar(tmp_path)
    antes = _huella(almacen)
    app = _aplicacion(almacen)

    async def caso() -> None:
        async with _cliente(app) as sesion:
            assert (await sesion.llamar("search", {"query": "procedencia"}))[0] is False
            assert (await sesion.llamar("get_document", {"document_id": DOC}))[0] is False
            assert (await sesion.llamar("health", {}))[0] is False

    asyncio.run(caso())

    assert _huella(almacen) == antes
    assert _laterales(almacen) == []


def test_logs_sin_consulta_contenido_token_ni_ruta(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """S8: los registros llevan solo metadatos; jamás texto crudo, contenido, secreto o ruta."""
    almacen = _sembrar(tmp_path)
    consulta_cruda = "procedencia verificable consulta cruda"
    app = _aplicacion(almacen)

    with caplog.at_level(logging.DEBUG):
        # Misma política de registro que aplica `main_mcp` al arrancar (S8).
        configurar_registro()

        async def caso() -> None:
            async with _cliente(app) as sesion:
                es_error, texto = await sesion.llamar("search", {"query": consulta_cruda})
                assert es_error is False
                assert TEXTO in json.loads(texto)["resultados"][0]["content"]

        asyncio.run(caso())

    registros = "\n".join(registro.getMessage() for registro in caplog.records)
    assert registros
    assert consulta_cruda not in registros
    assert TEXTO not in registros
    assert TOKEN not in registros
    assert str(almacen) not in registros
    assert str(almacen.parent) not in registros
