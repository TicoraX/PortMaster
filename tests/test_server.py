import contextlib
import os
import shutil
import socket
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from portmaster import config, docker, ports, registry, server

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


def test_los_estaticos_no_se_cachean(client):
    """El HTML pide app.js y app.css sin `?v=`, apoyado en este header. Si el
    mount de StaticFiles dejara de pasar por el middleware, el navegador se
    quedaria con la version vieja hasta un hard refresh y nadie se enteraria."""
    for asset in ("/static/app.js", "/static/app.css"):
        respuesta = client.get(asset)
        assert respuesta.status_code == 200
        assert respuesta.headers["cache-control"] == "no-store"


def test_version_sella_todos_los_estaticos(tmp_path, monkeypatch):
    """Cada archivo que sirve `web/` tiene que mover el sello del pie de pagina.

    Ese sello existe para contestar "estoy viendo la pagina nueva o una vieja de
    la cache". Con la lista de archivos escrita a mano se olvidaba tokens.css,
    que es donde viven los colores y los espaciados: un cambio de solo estilos
    no movia la fecha y el sello afirmaba que la pagina era mas vieja de lo que
    era, justo en el caso para el que se puso.

    Recorre el arbol en vez de nombrar los archivos, asi el dia que aparezca un
    quinto estatico el test lo cubre sin que nadie se acuerde.
    """
    web = tmp_path / "web"
    shutil.copytree(server.WEB, web)
    # `web/` es plano hoy, y el mount sirve el arbol entero: un estatico anidado
    # se descarga igual y con `iterdir` no contaba para el sello. El archivo lo
    # pone el test y no el paquete, para que la trampa quede cubierta antes de
    # que alguien cree el primer `web/img/`.
    anidado = web / "anidado" / "extra.css"
    anidado.parent.mkdir()
    anidado.write_text("/* un estatico en un subdirectorio */", encoding="utf-8")
    monkeypatch.setattr(server, "WEB", web)

    estaticos = sorted(f for f in web.rglob("*") if f.is_file())
    assert anidado in estaticos
    assert len(estaticos) >= 5, "index.html, app.js, app.css, tokens.css y el anidado"

    viejo = time.time() - 86400
    for archivo in estaticos:
        os.utime(archivo, (viejo, viejo))

    app = server.create_app(TOKEN)
    with TestClient(app, base_url="http://127.0.0.1") as test_client:
        test_client.headers.update({"Authorization": f"Bearer {TOKEN}"})
        # La premisa del sello: si el mount no sirviera esto, mirarlo no haria falta.
        assert test_client.get("/static/anidado/extra.css").status_code == 200
        for archivo in estaticos:
            nuevo = time.time()
            os.utime(archivo, (nuevo, nuevo))
            sello = test_client.get("/api/version").json()["assets"]
            esperado = time.strftime("%Y-%m-%d %H:%M", time.localtime(nuevo))
            assert sello == esperado, f"{archivo.name} no mueve el sello"
            os.utime(archivo, (viejo, viejo))


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


# busqueda y paginado ------------------------------------------------------


def registrar(tmp_path, *nombres):
    for nombre in nombres:
        root = tmp_path / nombre
        root.mkdir(parents=True)
        (root / "stack.yaml").write_text("services:\n  a:\n    command: echo a\n", encoding="utf-8")
        registry.add(root)


@pytest.fixture
def proxy_de_docker(free_ports):
    """Un proceso con el nombre del proxy de Docker, escuchando un puerto.

    Copiado al directorio del interprete porque un python suelto en otra
    carpeta no encuentra sus DLLs. Del interprete base y no del venv: en
    Windows el python.exe del venv relanza al real como hijo, y quien termina
    escuchando el puerto es ese hijo, con su nombre y no con el del impostor.
    """
    (port,) = free_ports(1)
    nombre = "wslrelay.exe" if os.name == "nt" else "docker-proxy"
    base = getattr(sys, "_base_executable", None) or sys.executable
    impostor = Path(base).with_name(nombre)
    try:
        shutil.copy2(base, impostor)
    except OSError:
        pytest.skip("directorio del interprete no escribible")

    proc = subprocess.Popen([str(impostor), "-c", SERVER.format(port=port)])
    try:
        deadline = time.time() + 10
        while time.time() < deadline and ports.is_free(port):
            time.sleep(0.1)
        # En macOS el interprete vive dentro de un bundle y el proceso se sigue
        # llamando "Python" por mas que el binario se copie con otro nombre, asi
        # que ahi no hay forma de hacerse pasar por el proxy.
        if (ports.scan(port).name or "").lower() != nombre:
            pytest.skip("el proceso no toma el nombre del ejecutable en esta plataforma")
        yield port
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        impostor.unlink(missing_ok=True)


def test_el_estado_delata_el_puerto_compartido(client, tmp_path, free_ports):
    """Dos proyectos que declaran el mismo puerto, sin que ninguno corra."""
    (port,) = free_ports(1)
    for nombre in ("blog", "fitness"):
        root = tmp_path / nombre
        root.mkdir()
        (root / "stack.yaml").write_text(
            f"services:\n  web:\n    command: python web\n    port: {port}\n", encoding="utf-8"
        )
        registry.add(root)

    proyectos = client.get("/api/state").json()["projects"]
    compartidos = {p["name"]: p["services"][0]["shared_with"] for p in proyectos}
    assert compartidos == {"blog": ["fitness"], "fitness": ["blog"]}


def test_un_puerto_propio_no_figura_compartido(client, tmp_path, free_ports):
    uno, otro = free_ports(2)
    for nombre, port in (("blog", uno), ("fitness", otro)):
        root = tmp_path / nombre
        root.mkdir()
        (root / "stack.yaml").write_text(
            f"services:\n  web:\n    command: python web\n    port: {port}\n", encoding="utf-8"
        )
        registry.add(root)

    proyectos = client.get("/api/state").json()["projects"]
    assert all(p["services"][0]["shared_with"] == [] for p in proyectos)


def _proyecto_compose(tmp_path, port):
    root = tmp_path / "condocker"
    root.mkdir()
    (root / "stack.yaml").write_text(
        textwrap.dedent(f"""
        services:
          db:
            command: docker compose up -d db
            detached: true
            port: {port}
        """),
        encoding="utf-8",
    )
    registry.add(root)


def test_un_contenedor_arriba_no_es_un_intruso(client, tmp_path, proxy_de_docker):
    """Lo que publica el proxy de Docker es el propio stack, no un okupa."""
    _proyecto_compose(tmp_path, proxy_de_docker)

    intrusos = client.get("/api/ports/orphans").json()["orphans"]
    assert [o for o in intrusos if o["port"] == proxy_de_docker] == []


def test_un_contenedor_arriba_figura_corriendo(client, tmp_path, proxy_de_docker):
    """Un stack levantado desde la terminal no se ve detenido y en rojo."""
    _proyecto_compose(tmp_path, proxy_de_docker)

    proyecto = client.get("/api/state").json()["projects"][0]
    (db,) = proyecto["services"]
    assert db["state"] == "ready"
    assert db["occupant"] is None


def test_paginado(client, tmp_path):
    registrar(tmp_path, *(f"app{i:02d}" for i in range(11)))

    primera = client.get("/api/state").json()
    assert primera["total"] == 11
    esperadas = -(-11 // server.PAGE_SIZE)
    assert primera["pages"] == esperadas
    assert len(primera["projects"]) == server.PAGE_SIZE

    segunda = client.get("/api/state?page=2").json()
    assert len(segunda["projects"]) == server.PAGE_SIZE
    ids = {p["id"] for p in primera["projects"]} | {p["id"] for p in segunda["projects"]}
    assert len(ids) == server.PAGE_SIZE * 2, "ningun proyecto se repite ni se pierde entre paginas"


def test_una_pagina_de_mas_cae_en_la_ultima(client, tmp_path):
    registrar(tmp_path, "sola")
    datos = client.get("/api/state?page=99").json()
    assert datos["page"] == 1
    assert len(datos["projects"]) == 1


def test_busqueda_por_nombre_y_por_ruta(client, tmp_path):
    registrar(tmp_path, "tienda", "blog", "tienda-admin")

    por_nombre = client.get("/api/state?q=tienda").json()
    assert por_nombre["total"] == 2
    assert {p["path"].split("\\")[-1].split("/")[-1] for p in por_nombre["projects"]} == {
        "tienda",
        "tienda-admin",
    }

    assert por_nombre["registered"] == 3, "el total registrado no lo mueve el filtro"
    assert client.get("/api/state?q=TIENDA").json()["total"] == 2, "sin distinguir mayusculas"
    assert client.get("/api/state?q=nada-de-esto").json()["total"] == 0
    assert client.get(f"/api/state?q={tmp_path.name}").json()["total"] == 3, "tambien por ruta"


def test_la_busqueda_no_acepta_cualquier_cosa(client):
    assert client.get("/api/state?q=" + "x" * 500).status_code == 422
    assert client.get("/api/state?page=0").status_code == 422
    assert client.get("/api/state?size=999").status_code == 422


# ciclo de vida ------------------------------------------------------------


def esperar(condicion, segundos=20):
    limite = time.time() + segundos
    while time.time() < limite:
        if condicion():
            return True
        time.sleep(0.2)
    return False


def esperar_listo(client):
    """Espera a que el primer servicio quede listo, y si no llega dice por que.

    El motivo va en el mensaje porque este fallo aparecio dos veces en CI
    (ubuntu 3.10) como un "nunca quedo listo" pelado, que no distingue un
    arranque que reviento de uno que solo tardo mas que la ventana.
    """

    def listo():
        estado = client.get("/api/state").json()["projects"][0]
        return estado["services"][0]["state"] == "ready"

    if esperar(listo):
        return
    final = client.get("/api/state").json()["projects"][0]
    raise AssertionError(
        f"el servicio nunca quedo listo: proyecto {final['state']},"
        f" error {final.get('error')!r},"
        f" servicios {[(s['name'], s['state']) for s in final['services']]}"
    )


def test_arranque_y_apagado(client, proyecto):
    path, port = proyecto
    pid = registry.project_id(path)

    assert client.post(f"/api/projects/{pid}/up", json={}).status_code == 200
    esperar_listo(client)

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


def test_la_tarjeta_marca_el_puerto_que_ya_estaba_ocupado(client, tmp_path, free_ports):
    """El arranque por la web no libera puertos, asi que este caso es alcanzable."""
    (port,) = free_ports(1)
    root = tmp_path / "conintruso"
    root.mkdir()
    (root / "stack.yaml").write_text(
        textwrap.dedent(f"""
        services:
          srv:
            command: {sys.executable} -c "import time; time.sleep(60)"
            port: {port}
        """),
        encoding="utf-8",
    )
    registry.add(root)
    pid = client.get("/api/state").json()["projects"][0]["id"]

    # `closing` y no un try/finally con el socket abierto afuera: el `finally`
    # tocaba `pid`, que se asigna adentro, y un fallo temprano lo tapaba con un
    # NameError. El apagado del stack lo hace la fixture `aislado`.
    with contextlib.closing(socket.socket()) as intruso:
        intruso.bind(("127.0.0.1", port))
        intruso.listen()

        assert client.post(f"/api/projects/{pid}/up", json={}).status_code == 200
        esperar_listo(client)
        servicio = client.get("/api/state").json()["projects"][0]["services"][0]
        assert servicio["port_taken"] is True
        client.post(f"/api/projects/{pid}/down")


def test_un_puerto_libre_no_marca_la_tarjeta(client, proyecto):
    path, _ = proyecto
    pid = registry.project_id(path)
    try:
        assert client.post(f"/api/projects/{pid}/up", json={}).status_code == 200
        esperar_listo(client)
        servicio = client.get("/api/state").json()["projects"][0]["services"][0]
        assert servicio["port_taken"] is False
    finally:
        client.post(f"/api/projects/{pid}/down")


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


def test_busqueda_por_estado(client, tmp_path):
    registrar(tmp_path, "detenido1", "detenido2")
    detenidos = client.get("/api/state?status=stopped").json()
    assert detenidos["total"] == 2

    corriendo = client.get("/api/state?status=running").json()
    assert corriendo["total"] == 0


def test_sink_flush_linea_parcial():
    sink = server._Sink()
    sink.write("linea completa\nsin salto final")
    assert len(sink.lines) == 1
    assert sink.lines[0][1] == "linea completa"
    sink.flush()
    assert len(sink.lines) == 2
    assert sink.lines[1][1] == "sin salto final"


def test_un_servidor_que_contesta_tarde_igual_consigue_el_boton_abrir(
    client, tmp_path, free_ports
):
    """El caso de Next: el puerto acepta enseguida y el HTTP recien aparece
    cuando termina de compilar. El sondeo unico del arranque da falso negativo."""
    (port,) = free_ports(1)
    # Acepta conexiones ya (para que `ready: port` de listo) y recien despues de
    # unos segundos empieza a contestar HTTP de verdad.
    tarde = (
        "import socket, threading, time; "
        "s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); "
        f"s.bind(('127.0.0.1', {port})); s.listen(); "
        "time.sleep(4); s.close(); "
        "from http.server import HTTPServer, BaseHTTPRequestHandler; "
        f"HTTPServer(('127.0.0.1', {port}), BaseHTTPRequestHandler).serve_forever()"
    )
    root = tmp_path / "tardio"
    root.mkdir()
    (root / "stack.yaml").write_text(
        f'services:\n  web:\n    command: {sys.executable} -c "{tarde}"\n    port: {port}\n',
        encoding="utf-8",
    )
    pid = registry.project_id(registry.add(root))
    assert client.post(f"/api/projects/{pid}/up", json={}).status_code == 200

    def abrible():
        proyecto = client.get("/api/state").json()["projects"][0]
        return proyecto["services"][0]["openable"]

    # HTTP_RETRIES suma 37s, y el primer intento no arranca hasta que el stack
    # esta listo. Con 40 el ultimo re-sondeo caia justo fuera de la ventana.
    total = sum(server.HTTP_RETRIES) + 20
    assert esperar(abrible, total), "el re-sondeo nunca le devolvio el boton"


def test_un_puerto_mudo_no_frena_la_vista_de_estado(client, proyecto):
    """El re-sondeo vive en su propio hilo. Si corriera en `_project_view`, un
    puerto que acepta y no contesta bloquearia el request el timeout entero, y
    con el al apagado, que comparte el threadpool."""
    path, port = proyecto
    pid = registry.project_id(path)
    client.post(f"/api/projects/{pid}/up", json={})
    esperar_listo(client)

    # El socket pelado del fixture nunca contesta HTTP: es el peor caso.
    inicio = time.time()
    for _ in range(5):
        assert client.get("/api/state").status_code == 200
    assert time.time() - inicio < 2, "la vista de estado se llevo el timeout del sondeo"

    inicio = time.time()
    assert client.post(f"/api/projects/{pid}/down").status_code == 200
    assert time.time() - inicio < 2, "apagar quedo detras del sondeo"


def _con_compose(tmp_path, nombre="congelable"):
    root = tmp_path / nombre
    root.mkdir()
    (root / "compose.yaml").write_text(
        'services:\n  db:\n    image: postgres\n    ports: ["5432:5432"]\n', encoding="utf-8"
    )
    return root, registry.project_id(registry.add(root))


def test_congelar_escribe_un_stack_yaml_que_carga(client, tmp_path):
    root, pid = _con_compose(tmp_path)
    cuerpo = client.post(f"/api/projects/{pid}/freeze").json()

    escrito = Path(cuerpo["path"])
    assert escrito == root / "stack.yaml"
    # Lo escrito tiene que ser cargable: congelar algo que despues no abre seria peor
    # que no ofrecerlo.
    assert [s.name for s in config.load(escrito).resolve()] == ["db"]
    # Y deja de ser un proyecto detectado.
    assert client.get("/api/state").json()["projects"][0]["detected"] is False


def test_congelar_dos_veces_no_pisa_el_archivo(client, tmp_path):
    root, pid = _con_compose(tmp_path)
    client.post(f"/api/projects/{pid}/freeze")
    original = (root / "stack.yaml").read_text(encoding="utf-8")

    (root / "stack.yaml").write_text(original + "\n# editado a mano\n", encoding="utf-8")
    respuesta = client.post(f"/api/projects/{pid}/freeze")

    assert respuesta.status_code == 409
    assert "editado a mano" in (root / "stack.yaml").read_text(encoding="utf-8")


def test_health_ve_todas_las_sesiones_y_no_solo_la_pagina(client, tmp_path, free_ports):
    """Alimentar el aviso de "algo se cayo" desde /api/state seria mentira apenas
    hay una segunda pagina."""
    puertos = free_ports(server.PAGE_SIZE + 1)
    ids = []
    for i, port in enumerate(puertos):
        root = tmp_path / f"app{i}"
        root.mkdir()
        (root / "stack.yaml").write_text(
            f'services:\n  srv:\n    command: {sys.executable} -c "{SERVER.format(port=port)}"\n'
            f"    port: {port}\n",
            encoding="utf-8",
        )
        ids.append(registry.project_id(registry.add(root)))

    for pid in ids:
        assert client.post(f"/api/projects/{pid}/up", json={}).status_code == 200
    assert esperar(lambda: client.get("/api/health").json()["running"] == len(ids), 40)

    # El ultimo cae fuera de la primera pagina.
    primera = {p["id"] for p in client.get("/api/state").json()["projects"]}
    assert ids[-1] not in primera

    salud = client.get("/api/health").json()
    assert salud["running"] == len(ids)
    assert salud["fallen"] == []


def test_health_delata_al_servicio_que_se_murio_solo(client, tmp_path, free_ports):
    (port,) = free_ports(1)
    root = tmp_path / "efimero"
    root.mkdir()
    corto = (
        "import socket, time; s = socket.socket(); "
        f"s.bind(('127.0.0.1', {port})); s.listen(); "
        "print('arriba', flush=True); time.sleep(2)"
    )
    (root / "stack.yaml").write_text(
        f'services:\n  srv:\n    command: {sys.executable} -c "{corto}"\n    port: {port}\n',
        encoding="utf-8",
    )
    pid = registry.project_id(registry.add(root))
    client.post(f"/api/projects/{pid}/up", json={})

    def caido():
        return len(client.get("/api/health").json()["fallen"]) == 1

    assert esperar(caido, 30), "el servicio se murio y health no lo dice"
    assert client.get("/api/health").json()["fallen"][0]["project"] == pid


def test_apagar_a_mano_no_es_una_caida(client, proyecto):
    """Apagar y morirse llegan al mismo estado por caminos distintos. Solo uno
    de los dos es noticia."""
    path, _ = proyecto
    pid = registry.project_id(path)
    client.post(f"/api/projects/{pid}/up", json={})
    assert esperar(lambda: client.get("/api/health").json()["running"] == 1)

    client.post(f"/api/projects/{pid}/down")
    assert esperar(lambda: client.get("/api/health").json()["running"] == 0)
    assert client.get("/api/health").json()["fallen"] == []


def test_reiniciar_no_cuenta_como_caida(client, proyecto):
    """Sin esto, el aviso se dispararia con cada Reiniciar: entre matar el
    proceso viejo y arrancar el nuevo no hay nadie vivo."""
    path, _ = proyecto
    pid = registry.project_id(path)
    client.post(f"/api/projects/{pid}/up", json={})
    assert esperar(lambda: client.get("/api/health").json()["running"] == 1)

    client.post(f"/api/projects/{pid}/services/srv/restart")
    for _ in range(30):
        assert client.get("/api/health").json()["fallen"] == [], "aviso falso al reiniciar"
        time.sleep(0.1)


def test_persistencia_de_sesiones_al_reiniciar_servidor(client, proyecto):
    path, port = proyecto
    pid = registry.project_id(path)
    client.post(f"/api/projects/{pid}/up", json={})
    assert esperar(lambda: client.get("/api/state").json()["projects"][0]["state"] == "running")

    # Simulamos reinicio del servidor limpiando la memoria de sessions
    server._save_sessions_state()
    assert server._sessions_file().is_file()

    server.sessions.clear()
    server._load_sessions_state()

    # La sesion debe haber sido restaurada en estado running
    assert pid in server.sessions
    assert server.sessions[pid].state == "running"


def test_browse_autocompletado_de_rutas(client, tmp_path):
    root = tmp_path / "proyectos"
    (root / "app_alpha").mkdir(parents=True)
    (root / "app_beta").mkdir(parents=True)

    res = client.get(f"/api/browse?path={root}")
    assert res.status_code == 200
    nombres = [e["name"] for e in res.json()["entries"]]
    assert "app_alpha" in nombres
    assert "app_beta" in nombres


def test_export_e_import_api(client, tmp_path):
    root = tmp_path / "app_api"
    root.mkdir()
    (root / "stack.yaml").write_text("services:\n  web:\n    command: python web\n", encoding="utf-8")
    registry.add(root)

    res_exp = client.get("/api/projects/export")
    assert res_exp.status_code == 200
    assert str(root) in res_exp.json()

    pid = registry.project_id(root)
    registry.remove(pid)

    res_imp = client.post("/api/projects/import", json=[str(root)])
    assert res_imp.status_code == 200
    assert res_imp.json()["count"] == 1


def test_la_pagina_no_regala_el_token(client):
    """GET / es publico, pero contestaba con el token de verdad en un Set-Cookie
    aunque no lo trajeras: cualquier proceso local conseguia la llave con un
    curl, y con ella corre comandos."""
    respuesta = client.get("/", headers={"Authorization": ""})
    assert respuesta.status_code == 200
    assert "portmaster_token" not in respuesta.headers.get("set-cookie", "")
    assert TOKEN not in respuesta.headers.get("set-cookie", "")


def test_la_cookie_se_entrega_a_quien_ya_tiene_el_token(client):
    respuesta = client.get(f"/?token={TOKEN}", headers={"Authorization": ""})
    assert TOKEN in respuesta.headers.get("set-cookie", "")


def test_un_token_inventado_no_consigue_cookie(client):
    respuesta = client.get("/?token=no-es-el-token-pero-es-largo", headers={"Authorization": ""})
    assert "portmaster_token" not in respuesta.headers.get("set-cookie", "")


def test_la_cookie_autentica_la_api(client):
    """El <a download> de exportar no manda el header Authorization: sin cookie
    ese boton no existiria."""
    client.get(f"/?token={TOKEN}", headers={"Authorization": ""})
    respuesta = client.get("/api/projects/export", headers={"Authorization": ""})
    assert respuesta.status_code == 200


def test_el_chequeo_de_docker_no_corre_en_cada_request(client, tmp_path, monkeypatch):
    """Corria una vez por proyecto y por request, con la interfaz sondeando cada
    2.5s. Tres proyectos con contenedores se llevaban un segundo de cada
    /api/state y saturaban el threadpool que comparte con apagar y matar."""
    veces = []

    def contado():
        veces.append(1)
        return server.doctor.Check("daemon de docker", "fail", "de prueba")

    monkeypatch.setattr(server.doctor, "_docker", contado)
    monkeypatch.setattr(server, "_docker_seen", (0.0, False))

    for nombre in ("a", "b", "c"):
        root = tmp_path / nombre
        root.mkdir()
        (root / "stack.yaml").write_text(
            "services:\n  c:\n    command: docker compose up -d\n    detached: true\n",
            encoding="utf-8",
        )
        registry.add(root)

    for _ in range(4):
        assert client.get("/api/state").status_code == 200

    assert len(veces) == 1, f"el daemon se chequeo {len(veces)} veces en 12 vistas de proyecto"
    assert client.get("/api/state").json()["projects"][0]["docker_down"] is True


def _sesion_recuperada(tmp_path, port):
    """Simula un reinicio de `portmaster serve` con el proceso todavia vivo."""
    import json

    root = tmp_path / "sobreviviente"
    root.mkdir()
    (root / "stack.yaml").write_text(
        f"services:\n  srv:\n    command: echo hola\n    port: {port}\n", encoding="utf-8"
    )
    pid = registry.project_id(registry.add(root))
    registry.HOME.mkdir(parents=True, exist_ok=True)
    server._sessions_file().write_text(
        json.dumps({pid: {"path": str(root), "profile": None, "state": "running"}}),
        encoding="utf-8",
    )
    server.sessions.clear()
    server._load_sessions_state()
    return pid


def test_una_sesion_recuperada_muestra_sus_servicios(client, tmp_path, monkeypatch, free_ports):
    """Devolvia {} y la tarjeta decia "corriendo" con la lista vacia."""
    import socket

    (port,) = free_ports(1)
    vivo = socket.socket()
    vivo.bind(("127.0.0.1", port))
    vivo.listen()
    try:
        pid = _sesion_recuperada(tmp_path, port)
        estados = server.sessions[pid].service_states()
        assert estados == {"srv": "ready"}
    finally:
        vivo.close()


def test_reiniciar_una_sesion_recuperada_lo_dice_en_vez_de_reventar(
    client, tmp_path, monkeypatch, free_ports
):
    """Sin motor, restart_async moria con un AssertionError en un hilo daemon:
    el usuario apretaba el boton y no pasaba nada."""
    import socket

    (port,) = free_ports(1)
    vivo = socket.socket()
    vivo.bind(("127.0.0.1", port))
    vivo.listen()
    try:
        pid = _sesion_recuperada(tmp_path, port)
        respuesta = client.post(f"/api/projects/{pid}/services/srv/restart")
        assert respuesta.status_code == 409
        assert "reinicio del servidor" in respuesta.json()["detail"]
    finally:
        vivo.close()


@pytest.fixture
def intruso(tmp_path, free_ports):
    """Un proyecto registrado con su puerto tomado por un proceso ajeno."""
    (port,) = free_ports(1)
    root = tmp_path / "conintruso"
    root.mkdir()
    (root / "stack.yaml").write_text(
        f"services:\n  web:\n    command: python web\n    port: {port}\n", encoding="utf-8"
    )
    registry.add(root)

    proc = subprocess.Popen([sys.executable, "-c", SERVER.format(port=port)])
    assert esperar(lambda: not ports.is_free(port)), "el intruso nunca tomo el puerto"
    yield port
    if proc.poll() is None:
        proc.kill()
        proc.wait()


def test_kill_all_cierra_los_puertos_pedidos(client, intruso):
    assert any(o["port"] == intruso for o in client.get("/api/ports/orphans").json()["orphans"])

    res = client.post("/api/ports/kill-all", json={"ports": [intruso]})
    assert res.status_code == 200
    assert [k["port"] for k in res.json()["killed"]] == [intruso]
    assert esperar(lambda: ports.is_free(intruso)), "el puerto siguio ocupado"


def test_kill_all_sin_lista_no_mata_nada(client, intruso):
    """El filtro es obligatorio a proposito.

    Con un campo opcional, un body mal formado se leia como "sin filtro" y el
    endpoint pasaba de cerrar lo que el usuario nombro a cerrar todo lo que
    encontrara. Un endpoint que mata procesos falla cerrado.
    """
    assert client.post("/api/ports/kill-all", json={}).status_code == 422
    assert client.post("/api/ports/kill-all", json={"ports": None}).status_code == 422
    assert not ports.is_free(intruso), "el intruso murio con un body invalido"


def test_kill_all_solo_toca_lo_que_le_pidieron(client, intruso, free_ports):
    """Un puerto ajeno a la lista no se cierra aunque sea intruso."""
    res = client.post("/api/ports/kill-all", json={"ports": [free_ports(1)[0]]})
    assert res.status_code == 200
    assert res.json()["killed"] == []
    assert not ports.is_free(intruso)


def test_kill_all_exceder_max_targets_devuelve_422(client):
    """Una lista mayor a MAX_TARGETS (200) debe fallar con 422 Unprocessable Entity."""
    puertos = list(range(1000, 1201))  # 201 puertos
    assert client.post("/api/ports/kill-all", json={"ports": puertos}).status_code == 422


# docker ------------------------------------------------------------------

# Parchean `docker.ACTIONS` por procesos reales, y no por mocks: lo que hay que
# probar es que se mira el resultado, y para eso hace falta un proceso que
# devuelva un codigo de verdad. Sin el parche, cada corrida de la suite
# arrancaria Docker Desktop en la maquina de quien la corre y en los cinco
# runners del CI.


def _acciones(comando: tuple[str, ...]) -> dict[str, tuple[str, ...]]:
    return {"start": comando, "restart": comando}


def test_docker_dice_que_no_cuando_el_comando_no_existe(monkeypatch):
    monkeypatch.setattr(docker, "ACTIONS", _acciones(("no-existe-este-binario-12345",)))
    ok, detail = docker.run("start")
    assert ok is False
    assert "PATH" in detail


def test_docker_dice_que_no_cuando_el_comando_falla(monkeypatch):
    """El caso de Linux sin el plugin: docker existe y el subcomando no."""
    guion = "import sys; print('desktop is not a docker command', file=sys.stderr); sys.exit(1)"
    monkeypatch.setattr(docker, "ACTIONS", _acciones((sys.executable, "-c", guion)))
    ok, detail = docker.run("start")
    assert ok is False
    assert detail == "desktop is not a docker command", "el motivo tiene que llegar al usuario"


@pytest.mark.parametrize("accion", ["start", "restart"])
def test_docker_dice_que_si_cuando_el_comando_sale_bien(client, monkeypatch, accion):
    monkeypatch.setattr(docker, "ACTIONS", _acciones((sys.executable, "-c", "pass")))
    respuesta = client.post(f"/api/docker/{accion}")
    assert respuesta.status_code == 200
    assert respuesta.json()["ok"] is True


def test_docker_rechaza_una_accion_inventada(client, monkeypatch):
    """La ruta es la unica entrada, y el `Literal` la cierra antes de ejecutar nada."""
    monkeypatch.setattr(docker, "ACTIONS", _acciones((sys.executable, "-c", "pass")))
    for inventada in ("stop", "borrar-todo", "start;rm"):
        respuesta = client.post(f"/api/docker/{inventada}")
        assert respuesta.status_code == 422, inventada
        assert "start" in respuesta.json()["detail"][0]["msg"], "el error dice que se acepta"


def test_docker_exige_token(client):
    client.headers.pop("Authorization")
    assert client.post("/api/docker/start").status_code == 401


def test_docker_clean_endpoint(client, monkeypatch):
    monkeypatch.setattr(docker, "prune", lambda volumes=False: (True, "Total space reclaimed: 10MB"))
    res = client.post("/api/docker/clean")
    assert res.status_code == 200
    assert res.json()["ok"] is True
    assert "10MB" in res.json()["detail"]


def test_share_endpoint(client, monkeypatch):
    monkeypatch.setattr(
        server.tunnel,
        "start_tunnel",
        lambda port, provider=None: server.tunnel.Tunnel(
            provider="cloudflared",
            port=port,
            url="https://test-tunnel.trycloudflare.com",
            proc=subprocess.Popen("echo ok", shell=True),
        ),
    )
    res = client.post("/api/share?port=3000")
    assert res.status_code == 200
    assert res.json()["ok"] is True
    assert res.json()["url"] == "https://test-tunnel.trycloudflare.com"

    res_del = client.delete("/api/share/3000")
    assert res_del.status_code == 200
    assert res_del.json()["ok"] is True



# interfaz -----------------------------------------------------------------


def test_la_interfaz_arranca_sola():
    """app.js se poblaba solo al tocar algo: el bloque de arranque se perdio en
    a252013 al reescribir el final del archivo, y la pagina cargaba en blanco.
    Todas las demas llamadas a `refresh` viven adentro de un handler."""
    fuente = (server.WEB / "app.js").read_text(encoding="utf-8")
    assert "setInterval(refresh" in fuente, "no hay sondeo periodico"
    # La llamada inicial, la que puebla la pagina antes del primer intervalo.
    assert "\nrefresh();" in fuente, "no hay una llamada a refresh fuera de un handler"


def test_cada_id_del_html_lo_usa_el_js():
    """Un id que el JS no toca es un control muerto, y no se nota mirando."""
    import re

    html = (server.WEB / "index.html").read_text(encoding="utf-8")
    js = (server.WEB / "app.js").read_text(encoding="utf-8")
    huerfanos = []
    for ident in re.findall(r'id="([^"]+)"', html):
        camel = re.sub(r"-([a-z])", lambda m: m.group(1).upper(), ident)
        # `btn-export` es un <a href> puro: no necesita JS.
        if ident in ("btn-export",):
            continue
        if ident not in js and camel not in js:
            huerfanos.append(ident)
    assert not huerfanos, f"ids del HTML que el JS nunca toca: {huerfanos}"
