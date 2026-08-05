"""Comandos del CLI. Servidores reales, igual que el resto del suite."""

import json
import sys
import textwrap
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from typer.testing import CliRunner

from portmaster import cli, registry

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


def test_doctor_sin_proyecto_no_revienta(tmp_path, monkeypatch):
    """Recien instalado, en una carpeta cualquiera, es el primer comando que
    alguien corre: no puede salir con ConfigError."""
    monkeypatch.chdir(tmp_path)
    resultado = runner.invoke(cli.app, ["doctor"])
    assert resultado.exit_code == 0
    assert "no es un proyecto conocido" in resultado.output


def test_doctor_delata_el_puerto_ocupado_y_dice_como_liberarlo(
    tmp_path, monkeypatch, servidor_http
):
    (tmp_path / "stack.yaml").write_text(
        f"services:\n  web:\n    command: python web\n    port: {servidor_http}\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    resultado = runner.invoke(cli.app, ["doctor"])
    assert f"portmaster free {servidor_http}" in resultado.output
    # Un puerto ocupado es aviso, no falla: `up` ofrece liberarlo.
    assert resultado.exit_code == 0


def test_doctor_falla_si_el_comando_no_esta_en_el_path(tmp_path, monkeypatch):
    (tmp_path / "stack.yaml").write_text(
        "services:\n  web:\n    command: noexistecomandoasi --dev\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)

    resultado = runner.invoke(cli.app, ["doctor"])
    assert resultado.exit_code == 1
    assert "noexistecomandoasi" in resultado.output


def test_doctor_falla_con_un_stack_roto(tmp_path, monkeypatch):
    (tmp_path / "stack.yaml").write_text("services:\n  web:\n    puerto: 3000\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    resultado = runner.invoke(cli.app, ["doctor"])
    assert resultado.exit_code == 1
    assert "stack.example.yaml" in resultado.output


def test_doctor_advierte_falta_de_dotenv(tmp_path, monkeypatch):
    (tmp_path / "stack.yaml").write_text(
        "services:\n  web:\n    command: python web\n", encoding="utf-8"
    )
    (tmp_path / ".env.example").write_text("FOO=bar\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    resultado = runner.invoke(cli.app, ["doctor"])
    assert "cp .env.example .env" in resultado.output
    assert resultado.exit_code == 0



def test_down_corre_los_stop_en_orden_inverso(tmp_path, monkeypatch):
    """Un stack de compose puro sobrevive a la terminal: `down` es la unica forma
    de bajarlo, y el orden importa igual que al arrancar."""
    marca = tmp_path / "orden.txt"
    escribir = "import sys; open(r'{f}', 'a').write('{q}\\n')"
    (tmp_path / "stack.yaml").write_text(
        textwrap.dedent(f"""
        services:
          db:
            command: echo db
            detached: true
            stop: {sys.executable} -c "{escribir.format(f=marca, q='db')}"
          api:
            command: echo api
            detached: true
            needs: [db]
            stop: {sys.executable} -c "{escribir.format(f=marca, q='api')}"
        """),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    resultado = runner.invoke(cli.app, ["down"])
    assert resultado.exit_code == 0
    assert marca.read_text(encoding="utf-8").split() == ["api", "db"]


def test_down_sin_ningun_stop_lo_dice_y_no_falla(tmp_path, monkeypatch):
    (tmp_path / "stack.yaml").write_text(
        "services:\n  web:\n    command: echo web\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)

    resultado = runner.invoke(cli.app, ["down"])
    assert resultado.exit_code == 0
    assert "Ctrl-C" in resultado.output


def test_down_con_un_stop_que_falla_sale_1(tmp_path, monkeypatch):
    (tmp_path / "stack.yaml").write_text(
        textwrap.dedent(f"""
        services:
          db:
            command: echo db
            detached: true
            stop: {sys.executable} -c "raise SystemExit(2)"
        """),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    assert runner.invoke(cli.app, ["down"]).exit_code == 1


def test_export_e_import_de_proyectos_cli(tmp_path, monkeypatch):
    root = tmp_path / "proyecto_exportable"
    root.mkdir()
    (root / "stack.yaml").write_text("services:\n  web:\n    command: python web\n", encoding="utf-8")
    registry.add(root)

    export_file = tmp_path / "backup.json"
    res_export_file = runner.invoke(cli.app, ["export", str(export_file)])
    assert res_export_file.exit_code == 0
    assert export_file.is_file()

    exported_paths = json.loads(export_file.read_text(encoding="utf-8"))
    assert str(root) in exported_paths

    pid = registry.project_id(root)
    registry.remove(pid)
    assert not any(p == root for p in registry.paths())

    res_import = runner.invoke(cli.app, ["import", str(export_file)])
    assert res_import.exit_code == 0
    assert any(p == root for p in registry.paths())



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
