"""Contrato de arranque del servicio MCP: configuración fail-closed por entorno (T2: S2, S3, S7).

Fija que el proceso **no arranca** sin dirección de enlace, con enlaces comodín (`0.0.0.0`, `::`)
o sin token bearer propio, y que el token nunca aparece en los mensajes de error. Usa solo
`desde_entorno` con diccionarios en memoria y `main_mcp` con el entorno de la prueba: no abre
puerto, no toca almacén alguno y no usa el corpus real ni almacenes de evaluación.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from book_text_rag.adapters.mcp import (
    ENV_ALMACEN,
    ENV_DIRECCION,
    ENV_PUERTO,
    ENV_TIMEOUT,
    ENV_TOKEN,
    PUERTO_DEFECTO,
    TIMEOUT_DEFECTO_SEGUNDOS,
    ConfiguracionInvalida,
    desde_entorno,
)
from book_text_rag.cli import main_mcp

DIRECCION = "100.106.85.109"
TOKEN = "secreto-de-prueba-de-contrato"


def _entorno(tmp_path: Path, **extras: str) -> dict[str, str]:
    """Entorno válido base (dirección Tailscale ficticia y token de prueba) con sobrescrituras."""
    return {
        ENV_ALMACEN: str(tmp_path / "almacen.sqlite"),
        ENV_DIRECCION: DIRECCION,
        ENV_TOKEN: TOKEN,
        **extras,
    }


def test_valores_por_defecto_de_puerto_y_timeout(tmp_path: Path) -> None:
    configuracion = desde_entorno(_entorno(tmp_path))

    assert configuracion.puerto == PUERTO_DEFECTO == 8020
    assert configuracion.timeout_consulta == TIMEOUT_DEFECTO_SEGUNDOS == 5.0
    assert configuracion.direccion == DIRECCION
    assert configuracion.token == TOKEN
    assert configuracion.almacen == tmp_path / "almacen.sqlite"


def test_direccion_de_enlace_ausente_impide_arrancar(tmp_path: Path) -> None:
    entorno = _entorno(tmp_path)
    del entorno[ENV_DIRECCION]

    with pytest.raises(ConfiguracionInvalida, match=ENV_DIRECCION):
        desde_entorno(entorno)


def test_direccion_0_0_0_0_es_rechazada(tmp_path: Path) -> None:
    with pytest.raises(ConfiguracionInvalida, match="prohibido"):
        desde_entorno(_entorno(tmp_path, **{ENV_DIRECCION: "0.0.0.0"}))


def test_direccion_comodin_ipv6_es_rechazada(tmp_path: Path) -> None:
    with pytest.raises(ConfiguracionInvalida, match="prohibido"):
        desde_entorno(_entorno(tmp_path, **{ENV_DIRECCION: "::"}))


@pytest.mark.parametrize("token", ["", "   "], ids=["vacio", "solo_espacios"])
def test_token_ausente_o_vacio_impide_arrancar(tmp_path: Path, token: str) -> None:
    with pytest.raises(ConfiguracionInvalida, match=ENV_TOKEN):
        desde_entorno(_entorno(tmp_path, **{ENV_TOKEN: token}))


def test_token_ausente_del_entorno_impide_arrancar(tmp_path: Path) -> None:
    entorno = _entorno(tmp_path)
    del entorno[ENV_TOKEN]

    with pytest.raises(ConfiguracionInvalida, match=ENV_TOKEN):
        desde_entorno(entorno)


@pytest.mark.parametrize("crudo", ["abc", "0", "-1", "nan", "inf"], ids=["texto", "cero", "negativo", "nan", "inf"])
def test_timeout_invalido_o_no_positivo_es_rechazado(tmp_path: Path, crudo: str) -> None:
    with pytest.raises(ConfiguracionInvalida, match=ENV_TIMEOUT):
        desde_entorno(_entorno(tmp_path, **{ENV_TIMEOUT: crudo}))


@pytest.mark.parametrize("crudo", ["ochenta", "0", "65536"], ids=["texto", "cero", "fuera_de_rango"])
def test_puerto_invalido_es_rechazado(tmp_path: Path, crudo: str) -> None:
    with pytest.raises(ConfiguracionInvalida, match=ENV_PUERTO):
        desde_entorno(_entorno(tmp_path, **{ENV_PUERTO: crudo}))


def test_almacen_ausente_impide_arrancar(tmp_path: Path) -> None:
    entorno = _entorno(tmp_path)
    del entorno[ENV_ALMACEN]

    with pytest.raises(ConfiguracionInvalida, match=ENV_ALMACEN):
        desde_entorno(entorno)


def test_mensajes_de_configuracion_nunca_incluyen_el_token(tmp_path: Path) -> None:
    secreto = "valor-secreto-que-no-debe-filtrarse"
    casos = (
        {ENV_DIRECCION: "0.0.0.0"},
        {ENV_DIRECCION: "::"},
        {ENV_TIMEOUT: "nada"},
        {ENV_PUERTO: "ochenta"},
    )
    for extras in casos:
        with pytest.raises(ConfiguracionInvalida) as captura:
            desde_entorno(_entorno(tmp_path, **{ENV_TOKEN: secreto, **extras}))
        assert secreto not in str(captura.value)


def _aislar_entorno(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Entorno completo de prueba para `main_mcp`, sin heredar nada del proceso."""
    monkeypatch.setenv(ENV_ALMACEN, str(tmp_path / "almacen.sqlite"))
    monkeypatch.setenv(ENV_DIRECCION, DIRECCION)
    monkeypatch.setenv(ENV_TOKEN, TOKEN)


def test_main_mcp_sin_direccion_no_arranca(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _aislar_entorno(monkeypatch, tmp_path)
    monkeypatch.delenv(ENV_DIRECCION, raising=False)

    assert main_mcp() == 2

    error = capsys.readouterr().err
    assert "error [configuración]" in error
    assert ENV_DIRECCION in error


def test_main_mcp_con_0_0_0_0_no_arranca(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _aislar_entorno(monkeypatch, tmp_path)
    monkeypatch.setenv(ENV_DIRECCION, "0.0.0.0")

    assert main_mcp() == 2

    error = capsys.readouterr().err
    assert "0.0.0.0" in error
    assert ENV_DIRECCION in error


def test_main_mcp_sin_token_no_arranca(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _aislar_entorno(monkeypatch, tmp_path)
    monkeypatch.delenv(ENV_TOKEN, raising=False)

    assert main_mcp() == 2

    error = capsys.readouterr().err
    assert "error [configuración]" in error
    assert ENV_TOKEN in error
    assert TOKEN not in error
