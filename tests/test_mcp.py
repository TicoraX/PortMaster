import json
import subprocess
import sys
import textwrap
import time

from portmaster import mcp, ports


def test_mcp_initialize():
    req = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    res = mcp.handle_request(req)
    assert res["id"] == 1
    assert res["result"]["serverInfo"]["name"] == "portmaster"
    assert "tools" in res["result"]["capabilities"]


def test_mcp_tools_list():
    req = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
    res = mcp.handle_request(req)
    tool_names = [t["name"] for t in res["result"]["tools"]]
    assert "portmaster_status" in tool_names
    assert "portmaster_doctor" in tool_names
    assert "portmaster_ports" in tool_names
    assert "portmaster_free_port" in tool_names
    assert "portmaster_share" in tool_names
    assert "portmaster_run" in tool_names
    assert "portmaster_clean" in tool_names


def _pedir_liberar(port):
    return mcp.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 10,
            "method": "tools/call",
            "params": {"name": "portmaster_free_port", "arguments": {"port": port}},
        }
    )


def test_mcp_free_port_cierra_al_dueno_del_puerto(free_ports):
    """Un proceso real, como el resto de la suite.

    El mock que habia aca nombraba el parametro `port` y devolvia True, y la
    firma de verdad es `kill(pid, create_time, ...)` y no devuelve nada. O sea
    que el test afirmaba un mensaje que el codigo real no podia producir, y
    tapaba que se le pasaba el numero de puerto en el lugar del pid: pedir
    liberar el 3000 mataba al proceso 3000.
    """
    (port,) = free_ports(1)
    code = (
        "import socket, time; s = socket.socket(); "
        f"s.bind(('127.0.0.1', {port})); s.listen(); time.sleep(60)"
    )
    proc = subprocess.Popen([sys.executable, "-c", code])
    try:
        limite = time.time() + 10
        while time.time() < limite and ports.is_free(port):
            time.sleep(0.1)
        dueno = ports.scan(port)
        assert dueno.pid is not None, "el proceso nunca tomo el puerto"

        res = _pedir_liberar(port)

        assert res["result"].get("isError") is not True, res["result"]
        assert "liberado" in res["result"]["content"][0]["text"]
        assert str(dueno.pid) in res["result"]["content"][0]["text"]

        limite = time.time() + 10
        while time.time() < limite and not ports.is_free(port):
            time.sleep(0.1)
        assert ports.is_free(port), "el puerto siguio ocupado"
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


def test_mcp_free_port_con_el_puerto_libre_no_mata_nada(free_ports, monkeypatch):
    """Nadie escucha: no hay a quien cerrar, y `kill` no se llama."""
    (port,) = free_ports(1)
    llamadas = []
    monkeypatch.setattr(mcp.ports, "kill", lambda *a, **k: llamadas.append((a, k)))

    res = _pedir_liberar(port)

    assert "ya esta libre" in res["result"]["content"][0]["text"]
    assert llamadas == []


def test_mcp_tool_call_share(monkeypatch):
    monkeypatch.setattr(
        mcp.tunnel,
        "start_tunnel",
        lambda port, provider=None: mcp.tunnel.Tunnel(
            provider="cloudflared",
            port=port,
            url="https://ai-tunnel.trycloudflare.com",
            proc=None,
        ),
    )
    req = {
        "jsonrpc": "2.0",
        "id": 11,
        "method": "tools/call",
        "params": {
            "name": "portmaster_share",
            "arguments": {"port": 3000},
        },
    }
    res = mcp.handle_request(req)
    assert res["result"].get("isError") is not True, res["result"]
    assert "https://ai-tunnel.trycloudflare.com" in res["result"]["content"][0]["text"]


def test_mcp_unknown_method():
    req = {"jsonrpc": "2.0", "id": 5, "method": "unsupported", "params": {}}
    res = mcp.handle_request(req)
    assert res["error"]["code"] == -32601


def test_mcp_tool_call_status(tmp_path):
    body = """
    name: mcp-test
    services:
      web:
        command: echo web
        port: 3000
    scripts:
      test: echo ok
    """
    (tmp_path / "stack.yaml").write_text(textwrap.dedent(body), encoding="utf-8")

    req = {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {
            "name": "portmaster_status",
            "arguments": {"path": str(tmp_path)},
        },
    }
    res = mcp.handle_request(req)
    assert res["id"] == 3
    assert res["result"].get("isError") is not True, res["result"]
    content = json.loads(res["result"]["content"][0]["text"])
    assert content["project_name"] == "mcp-test"
    assert content["services"][0]["name"] == "web"
    assert content["services"][0]["port"] == 3000
    assert "test" in content["scripts"]


def test_mcp_tool_call_run(tmp_path):
    flag = tmp_path / "mcp_flag.txt"
    body = f"""
    name: mcp-run-test
    services:
      web:
        command: echo web
    scripts:
      touch: python -c "import pathlib; pathlib.Path(r'{flag}').write_text('mcp_ok')"
    """
    (tmp_path / "stack.yaml").write_text(textwrap.dedent(body), encoding="utf-8")

    req = {
        "jsonrpc": "2.0",
        "id": 4,
        "method": "tools/call",
        "params": {
            "name": "portmaster_run",
            "arguments": {"script": "touch", "path": str(tmp_path)},
        },
    }
    res = mcp.handle_request(req)
    assert res["result"].get("isError") is not True, res["result"]
    assert "finalizado con código de salida 0" in res["result"]["content"][0]["text"]
    assert flag.exists()
    assert flag.read_text() == "mcp_ok"



def test_un_script_ruidoso_no_ensucia_el_protocolo(tmp_path):
    """Un `echo` adentro de un script se colaba entre dos respuestas JSON-RPC.

    Proceso real y no una llamada a `handle_request`: el problema vive en el
    descriptor 1, que el subproceso del script hereda, y eso no se ve desde el
    proceso del test.
    """
    (tmp_path / "stack.yaml").write_text(
        "services:\n  web:\n    command: echo web\n"
        "scripts:\n  ruidoso: echo RUIDO-EN-STDOUT\n",
        encoding="utf-8",
    )
    peticiones = (
        "\n".join(
            json.dumps(r)
            for r in (
                {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {
                        "name": "portmaster_run",
                        "arguments": {"script": "ruidoso", "path": str(tmp_path)},
                    },
                },
            )
        )
        + "\n"
    )

    done = subprocess.run(
        [sys.executable, "-m", "portmaster.cli", "mcp"],
        input=peticiones,
        capture_output=True,
        text=True,
        errors="replace",
        timeout=60,
        cwd=tmp_path,
    )

    lineas = [line for line in done.stdout.splitlines() if line.strip()]
    for linea in lineas:
        json.loads(linea)  # cada linea de stdout tiene que ser una respuesta valida
    assert [json.loads(line)["id"] for line in lineas] == [1, 2]
    assert "RUIDO-EN-STDOUT" not in done.stdout, "la salida del script llego al protocolo"
    assert "RUIDO-EN-STDOUT" in done.stderr, "la salida del script tiene que ir a stderr"


def _pedir_clean(argumentos):
    return mcp.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 20,
            "method": "tools/call",
            "params": {"name": "portmaster_clean", "arguments": argumentos},
        }
    )


def test_mcp_clean_se_niega_a_borrar_volumenes(monkeypatch):
    """El CLI y la interfaz preguntan antes; el MCP no tiene donde preguntar.

    El resto del prune se regenera solo. Un volumen tiene la base de datos del
    proyecto adentro y no vuelve, asi que un agente no lo borra: lo hace el
    usuario, con el comando que pregunta.
    """
    llamadas = []
    monkeypatch.setattr(mcp.docker, "prune", lambda volumes=False: llamadas.append(volumes) or (True, "ok"))

    res = _pedir_clean({"volumes": True})

    assert res["result"]["isError"] is True
    assert "no se hace desde un agente" in res["result"]["content"][0]["text"]
    assert llamadas == [], "llego a llamar al prune con volumes"


def test_mcp_clean_sin_volumenes_limpia(monkeypatch):
    llamadas = []
    monkeypatch.setattr(mcp.docker, "prune", lambda volumes=False: llamadas.append(volumes) or (True, "ok"))

    res = _pedir_clean({})

    assert res["result"].get("isError") is not True
    assert llamadas == [False]


def test_mcp_clean_no_le_ofrece_volumes_al_agente():
    """El esquema es lo que el agente lee para decidir que puede pedir."""
    tools = mcp.handle_request(
        {"jsonrpc": "2.0", "id": 21, "method": "tools/list", "params": {}}
    )["result"]["tools"]
    clean = next(t for t in tools if t["name"] == "portmaster_clean")
    assert "volumes" not in clean["inputSchema"].get("properties", {})
