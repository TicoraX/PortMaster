import os
import subprocess
import sys
import time
from unittest.mock import MagicMock

import pytest

from portmaster import tunnel
from portmaster.tunnel import TunnelError


def test_provider_regex_extraction():
    _, cf_extract = tunnel._provider_config("cloudflared", 3000)
    assert cf_extract("INF +--------------------------------------------------------------------------------------------+") is None
    assert cf_extract("INF |  Your quick Tunnel has been created! Visit it at (it may take some time to be reachable):  |") is None
    assert cf_extract("INF |  https://my-temp-tunnel-123.trycloudflare.com                                             |") == "https://my-temp-tunnel-123.trycloudflare.com"

    _, ngrok_extract = tunnel._provider_config("ngrok", 8080)
    assert ngrok_extract("t=2026-08-14 msg=\"started tunnel\" url=https://abc-123.ngrok-free.app") == "https://abc-123.ngrok-free.app"

    _, lt_extract = tunnel._provider_config("lt", 5173)
    assert lt_extract("your url is: https://sweet-lion-42.loca.lt") == "https://sweet-lion-42.loca.lt"


def test_start_tunnel_proveedor_desconocido():
    with pytest.raises(TunnelError, match="proveedor desconocido"):
        tunnel.start_tunnel(3000, provider="invalido")


def test_start_tunnel_proveedor_no_instalado(monkeypatch):
    monkeypatch.setattr(tunnel.shutil, "which", lambda x: None)
    with pytest.raises(TunnelError, match="no se encontro ningun cliente de tuneles"):
        tunnel.start_tunnel(3000)


def test_tunnel_stop():
    mock_proc = MagicMock(spec=subprocess.Popen)
    mock_proc.poll.return_value = None
    mock_proc.wait.return_value = 0

    tun = tunnel.Tunnel(provider="cloudflared", port=3000, url="https://test.trycloudflare.com", proc=mock_proc)
    tun.stop()
    mock_proc.terminate.assert_called_once()


# El pipeline de start_tunnel: Popen, el hilo lector, el Event y el timeout. Las
# regex ya estan cubiertas arriba una por una; lo que no ejercitaba nadie es todo
# lo que pasa alrededor, que es donde vive el unico bug que puede colgar el
# comando. Un binario falso en el PATH lo recorre entero, sin red ni cuentas.
#
# Las muestras estan reconstruidas del formato documentado de cada cliente, no
# copiadas de una corrida real. Prueban que el codigo hace lo correcto con la
# salida que creemos que sale; que sea la que realmente sale hoy solo lo dice
# correr el binario de verdad.

MUESTRAS = {
    "cloudflared": (
        ["2026-08-15T21:00:00Z INF +------------------------------------+",
         "2026-08-15T21:00:00Z INF |  Your quick Tunnel has been created! |",
         "2026-08-15T21:00:00Z INF |  https://tired-fish-run-fast.trycloudflare.com |",
         "2026-08-15T21:00:00Z INF +------------------------------------+"],
        "https://tired-fish-run-fast.trycloudflare.com",
    ),
    "ngrok": (
        ['t=2026-08-15T21:00:00+0000 lvl=info msg="started tunnel" obj=tunnels '
         "name=command_line addr=http://localhost:3000 url=https://1a2b-3c4d.ngrok-free.app"],
        "https://1a2b-3c4d.ngrok-free.app",
    ),
    "lt": (["your url is: https://tidy-moon-42.loca.lt"], "https://tidy-moon-42.loca.lt"),
    "tailscale": (
        ["Available on the internet:", "https://mi-maquina.tailnet-1234.ts.net/"],
        "https://mi-maquina.tailnet-1234.ts.net/",
    ),
}


@pytest.fixture
def proveedor_falso(tmp_path, monkeypatch):
    """Pone en el PATH un binario con el nombre de un proveedor.

    Un `.bat` en Windows y un script con shebang en el resto, los dos delegando
    en este mismo interprete: es la unica forma de que `shell=True` lo encuentre
    igual en las tres plataformas del CI.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ.get("PATH", ""))

    def crear(nombre, lineas, vivo=True):
        impl = tmp_path / f"{nombre}_impl.py"
        cuerpo = "import time\n" + "".join(f"print({linea!r}, flush=True)\n" for linea in lineas)
        impl.write_text(cuerpo + ("time.sleep(30)\n" if vivo else ""), encoding="utf-8")
        if os.name == "nt":
            shim = bin_dir / f"{nombre}.bat"
            shim.write_text(f'@echo off\r\n"{sys.executable}" "{impl}" %*\r\n', encoding="utf-8")
        else:
            shim = bin_dir / nombre
            shim.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{impl}" "$@"\n', encoding="utf-8")
            shim.chmod(0o755)
        return shim

    return crear


@pytest.mark.parametrize("nombre", sorted(MUESTRAS))
def test_start_tunnel_saca_la_url_de_la_salida_del_cliente(proveedor_falso, nombre):
    lineas, esperada = MUESTRAS[nombre]
    proveedor_falso(nombre, lineas)

    tun = tunnel.start_tunnel(3000, provider=nombre, timeout=20)
    try:
        assert tun.url == esperada
        assert tun.provider == nombre
        assert tun.port == 3000
        assert tun.proc.poll() is None, "el cliente tiene que seguir vivo"
    finally:
        tun.stop()
    assert tun.proc.poll() is not None, "stop no cerro el proceso"


def test_detect_providers_ve_lo_que_hay_en_el_path(proveedor_falso):
    proveedor_falso("lt", ["nada"])
    assert "lt" in tunnel.detect_providers()


def test_start_tunnel_sin_url_en_la_salida_corta_y_no_deja_el_proceso_vivo(proveedor_falso):
    """El caso de un cliente que arranca y nunca publica nada.

    Lo que importa no es solo el error: es que el proceso quede muerto. Un
    cliente de tuneles que sobrevive al fallo puede terminar publicando el
    puerto igual, y ahi nadie sabe que existe.
    """
    proveedor_falso("cloudflared", ["INF arrancando", "INF conectando"])

    with pytest.raises(TunnelError, match="no se pudo obtener la URL"):
        tunnel.start_tunnel(3000, provider="cloudflared", timeout=2)


def test_start_tunnel_no_espera_a_un_cliente_que_ya_murio(proveedor_falso):
    """`ngrok` sin autenticar imprime el error y se va en menos de un segundo.

    Esperar el timeout entero ahi es tiempo regalado: el proceso esta muerto y
    la URL no va a aparecer nunca. Con 15s por defecto, `portmaster share`
    parecia colgado antes de dar un error que ya se sabia.
    """
    proveedor_falso("ngrok", ["ERR authentication failed"], vivo=False)

    inicio = time.monotonic()
    with pytest.raises(TunnelError):
        tunnel.start_tunnel(3000, provider="ngrok", timeout=10)
    tardo = time.monotonic() - inicio

    assert tardo < 5, f"espero {tardo:.1f}s a un proceso que ya estaba muerto"
