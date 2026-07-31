"""Procesos reales. Un orquestador probado con mocks no prueba nada."""

import io
import sys
import textwrap
import time

import psutil
import pytest
from rich.console import Console

from portmaster import config, runner

# Servidor minimo que anuncia su arranque y se queda escuchando.
SERVER = (
    "import socket, time; "
    "s = socket.socket(); s.bind(('127.0.0.1', {port})); s.listen(); "
    "print('SERVIDOR ARRIBA', flush=True); "
    "time.sleep(120)"
)


def stack_from(tmp_path, body):
    path = tmp_path / "stack.yaml"
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return config.load(path)


def make_runner(stack, timeout=20.0):
    return runner.Runner(stack, console=Console(file=io.StringIO()), timeout=timeout)


def test_arranca_en_orden_y_espera_el_puerto(tmp_path, free_ports):
    a, b = free_ports(2)
    stack = stack_from(
        tmp_path,
        f"""
        services:
          uno:
            command: {sys.executable} -c "{SERVER.format(port=a)}"
            port: {a}
          dos:
            command: {sys.executable} -c "{SERVER.format(port=b)}"
            port: {b}
            needs: [uno]
        """,
    )
    engine = make_runner(stack)
    try:
        engine.up()
        assert [p.service.name for p in engine.procs] == ["uno", "dos"]
        assert all(p.ready for p in engine.procs)
    finally:
        engine.down()


def test_down_apaga_el_arbol_y_libera_el_puerto(tmp_path, free_ports):
    (port,) = free_ports(1)
    stack = stack_from(
        tmp_path,
        f"""
        services:
          srv:
            command: {sys.executable} -c "{SERVER.format(port=port)}"
            port: {port}
        """,
    )
    engine = make_runner(stack)
    engine.up()
    hijos = psutil.Process(engine.procs[0].popen.pid).children(recursive=True)

    engine.down()

    deadline = time.time() + 10
    while time.time() < deadline and not runner.ports.is_free(port):
        time.sleep(0.1)
    assert runner.ports.is_free(port)
    assert all(not h.is_running() for h in hijos)


def test_ready_por_log(tmp_path):
    stack = stack_from(
        tmp_path,
        f"""
        services:
          srv:
            command: {sys.executable} -c "print('LISTO PARA RECIBIR', flush=True); import time; time.sleep(120)"
            ready: "log:LISTO PARA RECIBIR"
        """,
    )
    engine = make_runner(stack)
    try:
        engine.up()
        assert engine.procs[0].ready
    finally:
        engine.down()


def test_detached_exitoso(tmp_path):
    stack = stack_from(
        tmp_path,
        f"""
        services:
          setup:
            command: {sys.executable} -c "print('hecho')"
            detached: true
        """,
    )
    engine = make_runner(stack)
    engine.up()
    assert engine.procs[0].ready


HTTP_SERVER = (
    "from http.server import HTTPServer, BaseHTTPRequestHandler; "
    "HTTPServer(('127.0.0.1', {port}), BaseHTTPRequestHandler).serve_forever()"
)


def test_un_puerto_que_habla_http_se_puede_abrir(tmp_path, free_ports):
    (port,) = free_ports(1)
    stack = stack_from(
        tmp_path,
        f"""
        services:
          web:
            command: {sys.executable} -c "{HTTP_SERVER.format(port=port)}"
            port: {port}
        """,
    )
    engine = make_runner(stack)
    try:
        engine.up()
        # BaseHTTPRequestHandler contesta 501 a un GET: no sirve nada, pero es
        # HTTP, que es justo lo que distingue a un frontend de una base de datos.
        assert engine.procs[0].http is True
    finally:
        engine.down()


def test_un_socket_pelado_no_se_ofrece_para_abrir(tmp_path, free_ports):
    (port,) = free_ports(1)
    stack = stack_from(
        tmp_path,
        f"""
        services:
          db:
            command: {sys.executable} -c "{SERVER.format(port=port)}"
            port: {port}
        """,
    )
    engine = make_runner(stack)
    try:
        engine.up()
        assert engine.procs[0].ready, "esta listo igual, solo que no es abrible"
        assert engine.procs[0].http is False
    finally:
        engine.down()


def test_el_comando_de_apagado_corre_al_bajar(tmp_path):
    """Un detached deja algo vivo fuera de nuestro arbol: matar al hijo no
    alcanza, tiene que correr su propio comando de apagado."""
    marca = tmp_path / "apagado.txt"
    stack = stack_from(
        tmp_path,
        f"""
        services:
          contenedores:
            command: {sys.executable} -c "print('arriba')"
            detached: true
            stop: {sys.executable} -c "open(r'{marca}', 'w').write('bajado')"
        """,
    )

    engine = make_runner(stack)
    engine.up()
    assert not marca.exists(), "el apagado no corre al arrancar"

    engine.down()
    assert marca.read_text(encoding="utf-8") == "bajado"


def test_un_apagado_que_falla_no_revienta(tmp_path):
    stack = stack_from(
        tmp_path,
        f"""
        services:
          contenedores:
            command: {sys.executable} -c "print('arriba')"
            detached: true
            stop: {sys.executable} -c "raise SystemExit(2)"
        """,
    )
    engine = make_runner(stack)
    engine.up()
    engine.down()  # no propaga: apagar es lo ultimo que se hace


def test_el_error_dice_la_causa_no_solo_el_codigo(tmp_path):
    stack = stack_from(
        tmp_path,
        f"""
        services:
          contenedores:
            command: {sys.executable} -c "print('no encuentro el daemon'); raise SystemExit(1)"
            detached: true
        """,
    )
    engine = make_runner(stack)
    with pytest.raises(runner.StartupError, match="no encuentro el daemon"):
        engine.up()


def test_los_avisos_no_tapan_la_causa(tmp_path):
    """compose escupe un level=warning por cada variable sin definir, despues del
    error de verdad. La ultima linea a secas seria el aviso."""
    salida = (
        "print('la causa real'); "
        "print('time=x level=warning msg=\\\"variable sin definir\\\"'); "
        "raise SystemExit(1)"
    )
    stack = stack_from(
        tmp_path,
        f"""
        services:
          contenedores:
            command: {sys.executable} -c "{salida}"
            detached: true
        """,
    )
    engine = make_runner(stack)
    with pytest.raises(runner.StartupError, match="la causa real"):
        engine.up()


def test_detached_que_falla_aborta(tmp_path):
    stack = stack_from(
        tmp_path,
        f"""
        services:
          setup:
            command: {sys.executable} -c "raise SystemExit(3)"
            detached: true
        """,
    )
    engine = make_runner(stack)
    with pytest.raises(runner.StartupError, match="codigo 3"):
        engine.up()


def test_servicio_que_muere_antes_de_estar_listo(tmp_path, free_ports):
    (port,) = free_ports(1)
    stack = stack_from(
        tmp_path,
        f"""
        services:
          srv:
            command: {sys.executable} -c "raise SystemExit(1)"
            port: {port}
        """,
    )
    engine = make_runner(stack)
    with pytest.raises(runner.StartupError, match="antes de estar listo"):
        engine.up()


def test_timeout_de_healthcheck(tmp_path, free_ports):
    (port,) = free_ports(1)
    stack = stack_from(
        tmp_path,
        f"""
        services:
          srv:
            command: {sys.executable} -c "import time; time.sleep(120)"
            port: {port}
        """,
    )
    engine = make_runner(stack, timeout=2.0)
    with pytest.raises(runner.StartupError, match="no estuvo listo"):
        engine.up()


def test_un_fallo_apaga_lo_ya_levantado(tmp_path, free_ports):
    a, b = free_ports(2)
    stack = stack_from(
        tmp_path,
        f"""
        services:
          bueno:
            command: {sys.executable} -c "{SERVER.format(port=a)}"
            port: {a}
          malo:
            command: {sys.executable} -c "raise SystemExit(1)"
            port: {b}
            needs: [bueno]
        """,
    )
    engine = make_runner(stack, timeout=5.0)
    with pytest.raises(runner.StartupError):
        engine.up()

    deadline = time.time() + 10
    while time.time() < deadline and not runner.ports.is_free(a):
        time.sleep(0.1)
    assert runner.ports.is_free(a), "el servicio bueno quedo huerfano"


def test_env_llega_al_proceso(tmp_path):
    stack = stack_from(
        tmp_path,
        f"""
        services:
          srv:
            command: {sys.executable} -c "import os; print('VALOR=' + os.environ['SALUDO'])"
            detached: true
            env:
              SALUDO: hola
        """,
    )
    salida = io.StringIO()
    engine = runner.Runner(stack, console=Console(file=salida), timeout=20.0)
    engine.up()
    assert "VALOR=hola" in salida.getvalue()


def test_terminate_tree_pid_inexistente():
    # PID 999999 no deberia lanzar psutil.NoSuchProcess
    runner._terminate_tree(999999)
