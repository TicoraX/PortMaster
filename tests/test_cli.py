"""Comandos del CLI. Servidores reales, igual que el resto del suite."""

import textwrap
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from typer.testing import CliRunner

from portmaster import cli

runner = CliRunner()


@pytest.fixture
def servidor_http(free_ports):
    """Un servidor HTTP de verdad, para distinguirlo de un socket pelado."""
    (port,) = free_ports(1)
    server = HTTPServer(("127.0.0.1", port), BaseHTTPRequestHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield port
    server.shutdown()


@pytest.fixture
def abierto(monkeypatch):
    """Lo que se hubiera abierto en el navegador."""
    urls = []
    monkeypatch.setattr(webbrowser, "open", lambda url: urls.append(url) or True)
    return urls


def test_open_elige_el_puerto_que_contesta_http(
    tmp_path, monkeypatch, free_ports, servidor_http, abierto
):
    """El primer servicio del stack es una base de datos: no es lo que se abre."""
    (mudo,) = free_ports(1)
    (tmp_path / "stack.yaml").write_text(
        textwrap.dedent(f"""
        services:
          db:
            command: echo db
            port: {mudo}
          web:
            command: echo web
            port: {servidor_http}
            needs: [db]
        """),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    resultado = runner.invoke(cli.app, ["open"])
    assert resultado.exit_code == 0
    assert abierto == [f"http://localhost:{servidor_http}"]


def test_open_con_puerto_explicito(tmp_path, monkeypatch, servidor_http, abierto):
    monkeypatch.chdir(tmp_path)
    resultado = runner.invoke(cli.app, ["open", str(servidor_http)])
    assert resultado.exit_code == 0
    assert abierto == [f"http://localhost:{servidor_http}"]


def test_open_sin_nada_arriba_no_abre_nada(tmp_path, monkeypatch, free_ports, abierto):
    (mudo,) = free_ports(1)
    (tmp_path / "stack.yaml").write_text(
        f"services:\n  web:\n    command: echo web\n    port: {mudo}\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    resultado = runner.invoke(cli.app, ["open"])
    assert resultado.exit_code == 1
    assert abierto == []
