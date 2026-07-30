"""Sockets y procesos reales, sin mocks: es justo lo que hay que verificar."""

import os
import socket
import subprocess
import sys
import time

import psutil
import pytest

from portmaster import ports


@pytest.fixture
def listener():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    sock.listen()
    yield sock, sock.getsockname()[1]
    sock.close()


@pytest.fixture
def child():
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    yield proc
    if proc.poll() is None:
        proc.kill()
        proc.wait()


def test_scan_identifica_el_listener_propio(listener):
    _, port = listener
    status = ports.scan(port)
    assert status.free is False
    assert status.pid == os.getpid()
    assert status.create_time is not None


def test_scan_puerto_libre(listener):
    sock, port = listener
    sock.close()
    status = ports.scan(port)
    assert status.free is True
    assert status.pid is None


def test_next_free_salta_el_ocupado(listener):
    _, port = listener
    assert ports.next_free(port) != port


def test_puerto_fuera_de_rango():
    for value in (0, 65536, -1):
        with pytest.raises(ValueError):
            ports.scan(value)


def test_kill_rechaza_el_proceso_propio():
    with pytest.raises(ports.KillRefused):
        ports.kill(os.getpid())


def test_kill_rechaza_pids_protegidos():
    with pytest.raises(ports.KillRefused):
        ports.kill(0)


def test_kill_rechaza_un_ancestro():
    parent = psutil.Process().parent()
    if parent is None:
        pytest.skip("sin proceso padre visible")
    with pytest.raises(ports.KillRefused):
        ports.kill(parent.pid)


def test_kill_rechaza_pid_reciclado(child):
    with pytest.raises(ports.KillRefused):
        ports.kill(child.pid, create_time=1.0)
    assert child.poll() is None


def test_kill_cierra_el_proceso(child):
    ports.kill(child.pid)
    assert child.poll() is not None


def test_kill_libera_el_puerto():
    code = (
        "import socket, time; "
        "s = socket.socket(); s.bind(('127.0.0.1', 0)); s.listen(); "
        "print(s.getsockname()[1], flush=True); time.sleep(60)"
    )
    proc = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
    try:
        port = int(proc.stdout.readline().strip())
        status = ports.scan(port)
        # En Windows el python.exe del venv relanza el interprete como hijo,
        # asi que el listener puede ser un descendiente y no el PID de Popen.
        launcher = psutil.Process(proc.pid)
        assert status.pid in {proc.pid} | {c.pid for c in launcher.children(recursive=True)}

        ports.kill(status.pid, status.create_time)
        deadline = time.time() + 5
        while time.time() < deadline and not ports.is_free(port):
            time.sleep(0.1)
        assert ports.is_free(port)
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait()
