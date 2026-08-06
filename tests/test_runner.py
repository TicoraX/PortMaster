"""Procesos reales. Un orquestador probado con mocks no prueba nada."""

import io
import socket
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


def test_un_puerto_que_habla_http_se_puede_abrir(tmp_path, free_ports):
    (port,) = free_ports(1)
    stack = stack_from(
        tmp_path,
        f"""
        services:
          web:
            command: {sys.executable} -m http.server {port} --bind 127.0.0.1
            port: {port}
        """,
    )
    engine = make_runner(stack)
    try:
        engine.up()
        # Aunque la raiz no sirva nada util, sigue siendo HTTP y se puede abrir.
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


def test_reiniciar_un_servicio_no_toca_al_resto(tmp_path, free_ports):
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
        intacto = engine.procs[0].popen.pid
        viejo = engine.procs[1].popen.pid

        engine.restart("dos")

        assert engine.procs[1].popen.pid != viejo, "no se reinicio"
        assert engine.procs[1].ready
        assert engine.procs[0].popen.pid == intacto, "el otro servicio se movio"
        assert [p.service.name for p in engine.procs] == ["uno", "dos"], "cambio el orden"
        assert not psutil.pid_exists(viejo) or not psutil.Process(viejo).is_running()
    finally:
        engine.down()


def test_reiniciar_algo_que_no_esta(tmp_path):
    stack = stack_from(
        tmp_path,
        f"""
        services:
          srv:
            command: {sys.executable} -c "print('hola')"
            detached: true
        """,
    )
    engine = make_runner(stack)
    engine.up()
    with pytest.raises(runner.StartupError, match="no esta corriendo"):
        engine.restart("fantasma")


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


def test_clean_error_message_docker_daemon():
    raw = 'error during connect: Get "http://%2F%2F.%2Fpipe%2Fdocker_engine/v1.24/containers/json": open //./pipe/docker_engine: The system cannot find the file specified.'
    assert runner.clean_error_message(raw) == "Docker no está en ejecución (abrí Docker Desktop)"


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


def test_el_timeout_avisa_si_abrio_otro_puerto(tmp_path, free_ports):
    """El caso vite: declaras 5177, el proceso se corre a 5178 y no falla."""
    declarado, real = free_ports(2)
    stack = stack_from(
        tmp_path,
        f"""
        services:
          srv:
            command: {sys.executable} -c "{SERVER.format(port=real)}"
            port: {declarado}
        """,
    )
    engine = make_runner(stack, timeout=2.0)
    with pytest.raises(runner.StartupError, match=f"pero abrio {real}"):
        engine.up()


def test_el_timeout_avisa_quien_tiene_el_puerto(tmp_path, free_ports):
    """El puerto declarado lo tiene un intruso y el servicio nunca abre nada."""
    (declarado,) = free_ports(1)
    intruso = socket.socket()
    intruso.bind(("127.0.0.1", declarado))
    intruso.listen()
    try:
        stack = stack_from(
            tmp_path,
            f"""
            services:
              srv:
                command: {sys.executable} -c "import time; time.sleep(120)"
                port: {declarado}
                ready: "log:NUNCA APARECE"
            """,
        )
        engine = make_runner(stack, timeout=2.0)
        with pytest.raises(runner.StartupError, match="ya lo tenia"):
            engine.up()
    finally:
        intruso.close()


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


LENTO = (
    "import socket, time; "
    "time.sleep(2); "
    "s = socket.socket(); s.bind(('127.0.0.1', {port})); s.listen(); "
    "time.sleep(120)"
)


def test_los_servicios_sin_dependencias_arrancan_juntos(tmp_path, free_ports):
    """Solapamiento, no duracion total: medir segundos es intermitente en tres
    sistemas operativos, y lo que importa es que los intervalos se pisen."""
    a, b, c = free_ports(3)
    stack = stack_from(
        tmp_path,
        f"""
        services:
          uno:
            command: {sys.executable} -c "{LENTO.format(port=a)}"
            port: {a}
          dos:
            command: {sys.executable} -c "{LENTO.format(port=b)}"
            port: {b}
          tres:
            command: {sys.executable} -c "{LENTO.format(port=c)}"
            port: {c}
            needs: [uno, dos]
        """,
    )
    engine = make_runner(stack)
    # Cada nivel contra si mismo, no contra un numero de segundos: el arranque
    # del interprete pesa distinto en cada sistema operativo y un umbral fijo se
    # vuelve intermitente en CI. `tres` arranca solo y da la unidad de medida.
    tiempos = {}
    original = engine._start_level

    def medido(level, colors):
        inicio = time.monotonic()
        original(level, colors)
        tiempos[tuple(s.name for s in level)] = time.monotonic() - inicio

    engine._start_level = medido
    try:
        engine.up()

        juntos = tiempos[("uno", "dos")]
        uno_solo = tiempos[("tres",)]
        assert juntos < uno_solo * 1.6, (
            f"dos servicios tardaron {juntos:.1f}s y uno solo {uno_solo:.1f}s: "
            "arrancaron en serie"
        )
        assert all(p.ready for p in engine.procs), "alguno quedo sin su healthcheck"
        assert {p.service.name for p in engine.procs} == {"uno", "dos", "tres"}
    finally:
        engine.down()


def test_cada_servicio_recibe_su_propio_healthcheck(tmp_path, free_ports):
    """`up` esperaba a `procs[-1]`, que con dos hilos en el mismo nivel es el
    servicio del otro hilo."""
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
        """,
    )
    engine = make_runner(stack)
    try:
        engine.up()
        assert all(p.ready for p in engine.procs)
        assert len({p.color for p in engine.procs}) == 2, "dos servicios, un solo color"
    finally:
        engine.down()


def test_un_fallo_en_el_nivel_no_deja_hermanos_vivos(tmp_path, free_ports):
    a, b = free_ports(2)
    stack = stack_from(
        tmp_path,
        f"""
        services:
          bueno:
            command: {sys.executable} -c "{LENTO.format(port=a)}"
            port: {a}
          malo:
            command: {sys.executable} -c "import time; time.sleep(0.2); raise SystemExit(1)"
            port: {b}
        """,
    )
    engine = make_runner(stack, timeout=10.0)
    with pytest.raises(runner.StartupError):
        engine.up()

    deadline = time.time() + 15
    while time.time() < deadline and not runner.ports.is_free(a):
        time.sleep(0.1)
    assert runner.ports.is_free(a), "el hermano del que fallo quedo huerfano"


def test_niveles_de_una_cadena_lineal():
    from portmaster.config import Service

    def svc(name, needs=()):
        return Service(name, "echo", None, None, "none", tuple(needs), {}, False)

    a, b, c = svc("a"), svc("b", ["a"]), svc("c", ["b"])
    assert [[s.name for s in nivel] for nivel in runner._levels([a, b, c])] == [["a"], ["b"], ["c"]]

    d = svc("d")
    assert [[s.name for s in nivel] for nivel in runner._levels([a, d, b])] == [["a", "d"], ["b"]]
