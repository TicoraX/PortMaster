import subprocess
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
