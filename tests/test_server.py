import sys
import textwrap
import time

import pytest
from fastapi.testclient import TestClient

from portmaster import registry, server

TOKEN = "token-de-prueba-suficientemente-largo"
SERVER = (
    "import socket, time; "
    "s = socket.socket(); s.bind(('127.0.0.1', {port})); s.listen(); "
    "print('arriba', flush=True); time.sleep(60)"
)


@pytest.fixture(autouse=True)
def aislado(tmp_path, monkeypatch):
    """Registro propio y limiter limpio en cada test."""
    monkeypatch.setattr(registry, "HOME", tmp_path / "home")
    monkeypatch.setattr(registry, "PROJECTS", tmp_path / "home" / "projects.json")
    server.limiter._hits.clear()
    with server.sessions_lock:
        server.sessions.clear()
    yield
    for session in list(server.sessions.values()):
        session.stop()
    server.sessions.clear()


@pytest.fixture
def client():
    app = server.create_app(TOKEN)
    with TestClient(app, base_url="http://127.0.0.1") as test_client:
        test_client.headers.update({"Authorization": f"Bearer {TOKEN}"})
        yield test_client


@pytest.fixture
def proyecto(tmp_path, free_ports):
    (port,) = free_ports(1)
    root = tmp_path / "proyecto"
    root.mkdir()
    (root / "stack.yaml").write_text(
        textwrap.dedent(f"""
        name: prueba
        services:
          srv:
            command: {sys.executable} -c "{SERVER.format(port=port)}"
            port: {port}
        profiles:
          solo: [srv]
        """),
        encoding="utf-8",
    )
    return registry.add(root), port


# seguridad ----------------------------------------------------------------


def test_sin_token_rechaza(client):
    respuesta = client.get("/api/state", headers={"Authorization": ""})
    assert respuesta.status_code == 401


def test_token_incorrecto_rechaza(client):
    respuesta = client.get("/api/state", headers={"Authorization": "Bearer otro"})
    assert respuesta.status_code == 401


def test_host_ajeno_rechaza(client):
    """Rebinding de DNS: un dominio cualquiera resolviendo a 127.0.0.1."""
    respuesta = client.get("/api/state", headers={"Host": "malicioso.example"})
    assert respuesta.status_code == 400


def test_headers_de_seguridad(client):
    headers = client.get("/api/state").headers
    assert "default-src 'self'" in headers["content-security-policy"]
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-frame-options"] == "DENY"
    assert headers["referrer-policy"] == "no-referrer"


def test_rate_limit_en_kill(client):
    ruta = "/api/ports/1/kill"
    for _ in range(server.QUOTA_KILL):
        client.post(ruta)
    assert client.post(ruta).status_code == 429


def test_la_pagina_no_pide_token(client):
    """El HTML es publico; los datos no. El token viaja en la URL de arranque."""
    respuesta = client.get("/", headers={"Authorization": ""})
    assert respuesta.status_code == 200
    assert "PortMaster" in respuesta.text


# proyectos ----------------------------------------------------------------


def test_alta_exige_stack_yaml(client, tmp_path):
    vacio = tmp_path / "vacio"
    vacio.mkdir()
    respuesta = client.post("/api/projects", json={"path": str(vacio)})
    assert respuesta.status_code == 400
    assert "stack.yaml" in respuesta.json()["detail"]


def test_alta_y_listado(client, tmp_path, free_ports):
    (port,) = free_ports(1)
    root = tmp_path / "app"
    root.mkdir()
    (root / "stack.yaml").write_text(
        f"services:\n  web:\n    command: echo hola\n    port: {port}\n",
        encoding="utf-8",
    )

    assert client.post("/api/projects", json={"path": str(root)}).status_code == 200

    proyectos = client.get("/api/state").json()["projects"]
    assert len(proyectos) == 1
    assert proyectos[0]["state"] == "stopped"
    assert proyectos[0]["services"][0]["name"] == "web"
    assert proyectos[0]["services"][0]["port"] == port


def test_config_rota_no_tumba_el_listado(client, tmp_path):
    root = tmp_path / "roto"
    root.mkdir()
    (root / "stack.yaml").write_text("services:\n  a:\n    port: 1\n", encoding="utf-8")
    registry.add(root)

    proyecto = client.get("/api/state").json()["projects"][0]
    assert proyecto["state"] == "invalid"
    assert "command" in proyecto["error"]


def test_baja(client, proyecto):
    path, _ = proyecto
    pid = registry.project_id(path)
    assert client.delete(f"/api/projects/{pid}").status_code == 200
    assert client.get("/api/state").json()["projects"] == []


def test_proyecto_desconocido(client):
    assert client.post("/api/projects/nohay/up", json={}).status_code == 404


def test_perfil_invalido(client, proyecto):
    path, _ = proyecto
    pid = registry.project_id(path)
    respuesta = client.post(f"/api/projects/{pid}/up", json={"profile": "fantasma"})
    assert respuesta.status_code == 400
    assert "perfil desconocido" in respuesta.json()["detail"]


# ciclo de vida ------------------------------------------------------------


def esperar(condicion, segundos=20):
    limite = time.time() + segundos
    while time.time() < limite:
        if condicion():
            return True
        time.sleep(0.2)
    return False


def test_arranque_y_apagado(client, proyecto):
    path, port = proyecto
    pid = registry.project_id(path)

    assert client.post(f"/api/projects/{pid}/up", json={}).status_code == 200

    def corriendo():
        estado = client.get("/api/state").json()["projects"][0]
        return estado["services"][0]["state"] == "ready"

    assert esperar(corriendo), "el servicio nunca quedo listo"

    logs = client.get(f"/api/projects/{pid}/logs").json()
    assert any("arriba" in linea["text"] for linea in logs["lines"])

    assert client.post(f"/api/projects/{pid}/down").status_code == 200
    from portmaster import ports

    assert esperar(lambda: ports.is_free(port)), "el puerto quedo tomado"


def test_apagar_mientras_arranca_no_deja_huerfanos(client, proyecto):
    """El apagado llega con el proceso arriba pero todavia no listo. Sin cortar
    el arranque, el hilo sigue detras del apagado y el servicio queda vivo."""
    from portmaster import ports

    path, port = proyecto
    pid = registry.project_id(path)
    assert client.post(f"/api/projects/{pid}/up", json={}).status_code == 200

    sesion = server.sessions[pid]
    assert esperar(lambda: sesion.engine is not None and sesion.engine.procs)

    assert client.post(f"/api/projects/{pid}/down").status_code == 200
    assert esperar(lambda: ports.is_free(port)), "el arranque siguio detras del apagado"


def test_arranque_doble_choca(client, proyecto):
    path, _ = proyecto
    pid = registry.project_id(path)
    assert client.post(f"/api/projects/{pid}/up", json={}).status_code == 200
    assert client.post(f"/api/projects/{pid}/up", json={}).status_code == 409


def test_apagar_contesta_sin_esperar_al_apagado(client, tmp_path):
    """`docker compose stop` tarda decenas de segundos: el request no los espera."""
    root = tmp_path / "lento"
    root.mkdir()
    (root / "stack.yaml").write_text(
        textwrap.dedent(f"""
        services:
          srv:
            command: {sys.executable} -c "import time; time.sleep(60)"
            stop: {sys.executable} -c "import time; time.sleep(3)"
        """),
        encoding="utf-8",
    )
    registry.add(root)
    pid = client.get("/api/state").json()["projects"][0]["id"]

    assert client.post(f"/api/projects/{pid}/up", json={}).status_code == 200
    assert esperar(lambda: server.sessions[pid].state == "running")

    empezo = time.monotonic()
    assert client.post(f"/api/projects/{pid}/down").status_code == 200
    assert time.monotonic() - empezo < 2, "el request espero al comando de apagado"

    # Un segundo despues el comando de apagado sigue corriendo: el stack tiene
    # que seguir diciendo "apagando" y no "detenido".
    time.sleep(1)
    proyecto = client.get("/api/state").json()["projects"][0]
    assert proyecto["state"] == "stopping"
    assert esperar(lambda: server.sessions[pid].state == "stopped")


def test_reiniciar_un_servicio(client, proyecto):
    path, port = proyecto
    pid = registry.project_id(path)
    client.post(f"/api/projects/{pid}/up", json={})

    sesion = server.sessions[pid]
    assert esperar(lambda: sesion.state == "running")
    viejo = sesion.engine.procs[0].popen.pid

    assert client.post(f"/api/projects/{pid}/services/srv/restart").status_code == 200
    assert esperar(lambda: sesion.engine.procs[0].popen.pid != viejo)
    assert esperar(lambda: sesion.engine.procs[0].ready)
    assert sesion.state == "running", "reiniciar un servicio no baja el stack"


def test_reiniciar_un_servicio_que_no_existe(client, proyecto):
    path, _ = proyecto
    pid = registry.project_id(path)
    client.post(f"/api/projects/{pid}/up", json={})
    assert esperar(lambda: server.sessions[pid].state == "running")

    respuesta = client.post(f"/api/projects/{pid}/services/../../etc/restart")
    assert respuesta.status_code == 404


def test_reiniciar_con_el_stack_apagado(client, proyecto):
    path, _ = proyecto
    pid = registry.project_id(path)
    assert client.post(f"/api/projects/{pid}/services/srv/restart").status_code == 404


def test_apagar_lo_que_no_arrancamos(client, proyecto):
    path, _ = proyecto
    pid = registry.project_id(path)
    assert client.post(f"/api/projects/{pid}/down").status_code == 404


# puertos ------------------------------------------------------------------


def test_kill_de_puerto_libre(client, free_ports):
    (port,) = free_ports(1)
    respuesta = client.post(f"/api/ports/{port}/kill")
    assert respuesta.status_code == 200
    assert respuesta.json()["detail"] == "ya estaba libre"


def test_kill_de_puerto_invalido(client):
    assert client.post("/api/ports/70000/kill").status_code == 400


def test_stack_solo_detached_queda_corriendo(client, tmp_path):
    """Un compose deja contenedores vivos fuera de nuestro arbol: el comando
    termina, pero el stack no esta detenido."""
    root = tmp_path / "contenedores"
    root.mkdir()
    (root / "stack.yaml").write_text(
        textwrap.dedent(f"""
        services:
          setup:
            command: {sys.executable} -c "print('arriba')"
            detached: true
        """),
        encoding="utf-8",
    )
    registry.add(root)
    pid = client.get("/api/state").json()["projects"][0]["id"]

    assert client.post(f"/api/projects/{pid}/up", json={}).status_code == 200
    for _ in range(50):
        proyecto = client.get("/api/state").json()["projects"][0]
        if proyecto["state"] == "running":
            break
        time.sleep(0.1)

    assert proyecto["state"] == "running"
    assert proyecto["services"][0]["state"] == "ready"
    assert proyecto["services"][0]["kind"] == "container"


# explorador ---------------------------------------------------------------


def test_browse_exige_token(client):
    client.headers.pop("Authorization")
    assert client.get("/api/browse").status_code == 401


def test_browse_sin_ruta_da_las_raices(client):
    cuerpo = client.get("/api/browse").json()
    assert cuerpo["path"] == ""
    assert cuerpo["parent"] is None, "la vista de raices no tiene a donde subir"
    assert cuerpo["entries"], "al menos la home del usuario"


def test_browse_lista_solo_carpetas(client, tmp_path):
    raiz = tmp_path / "arbol"
    (raiz / "proyecto").mkdir(parents=True)
    (raiz / "node_modules").mkdir()
    (raiz / ".oculta").mkdir()
    (raiz / "secreto.txt").write_text("no me listes", encoding="utf-8")
    (raiz / "proyecto" / "package.json").write_text("{}", encoding="utf-8")

    cuerpo = client.get("/api/browse", params={"path": str(raiz)}).json()

    assert [e["name"] for e in cuerpo["entries"]] == ["proyecto"]
    assert cuerpo["entries"][0]["markers"] == ["package.json"]
    assert cuerpo["parent"] == str(raiz.parent)


def test_browse_marca_los_proyectos(client, tmp_path):
    raiz = tmp_path / "arbol"
    (raiz / "app").mkdir(parents=True)
    (raiz / "app" / "compose.yaml").write_text("services: {}", encoding="utf-8")
    (raiz / "app" / "manage.py").write_text("", encoding="utf-8")
    (raiz / "vacia").mkdir()

    entries = {e["name"]: e["markers"] for e in
               client.get("/api/browse", params={"path": str(raiz)}).json()["entries"]}

    assert entries["app"] == ["compose.yaml", "manage.py"]
    assert entries["vacia"] == []


@pytest.mark.parametrize("ruta", ["relativa/mala", "no-existe-en-ningun-lado-12345"])
def test_browse_rechaza_rutas_invalidas(client, ruta):
    assert client.get("/api/browse", params={"path": ruta}).status_code == 400


def test_browse_rechaza_un_archivo(client, tmp_path):
    archivo = tmp_path / "archivo.txt"
    archivo.write_text("hola", encoding="utf-8")
    assert client.get("/api/browse", params={"path": str(archivo)}).status_code == 400


def test_browse_normaliza_los_puntos(client, tmp_path):
    (tmp_path / "a" / "b").mkdir(parents=True)
    cuerpo = client.get("/api/browse", params={"path": str(tmp_path / "a" / "b" / "..")}).json()
    assert cuerpo["path"] == str((tmp_path / "a").resolve())


def test_sink_flush_linea_parcial():
    sink = server._Sink()
    sink.write("linea completa\nsin salto final")
    assert len(sink.lines) == 1
    assert sink.lines[0][1] == "linea completa"
    sink.flush()
    assert len(sink.lines) == 2
    assert sink.lines[1][1] == "sin salto final"
