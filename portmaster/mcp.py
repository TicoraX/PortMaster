"""Servidor MCP (Model Context Protocol) sobre stdio para agentes de IA."""

from __future__ import annotations

import io
import json
import os
import sys
from pathlib import Path
from typing import Any

from . import (
    __version__,
    detect,
    docker,
    doctor,
    history,
    ports,
    registry,
    scripts,
    tunnel,
)

# Los tuneles que abrio esta sesion de MCP. `serve_stdio` los cierra al salir:
# un tunel es lo unico que este servidor deja fuera de su propio proceso, y del
# otro lado no hay nadie mirando la pantalla.
_tuneles: list[tunnel.Tunnel] = []


def cerrar_tuneles() -> None:
    """Cierra lo que quedo abierto. Un fallo no puede tapar a los demas."""
    while _tuneles:
        try:
            _tuneles.pop().stop()
        except Exception:
            pass


def handle_request(req: dict[str, Any]) -> dict[str, Any] | None:
    req_id = req.get("id")
    method = req.get("method")
    params = req.get("params", {})

    # JSON-RPC 2.0: una notificacion es una peticion SIN `id`, y a una
    # notificacion no se contesta nunca. Reconocer solo
    # `notifications/initialized` por nombre dejaba que `notifications/cancelled`
    # y `notifications/progress` cayeran al final y se llevaran una respuesta de
    # error con `id: null`, que es justo lo que el protocolo prohibe.
    if "id" not in req:
        return None

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "portmaster", "version": __version__},
            },
        }

    if method == "notifications/initialized":
        return None

    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "tools": [
                    {
                        "name": "portmaster_status",
                        "description": "Obtiene el estado de los servicios, proyectos y puertos de PortMaster.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "path": {"type": "string", "description": "Ruta opcional al proyecto"}
                            },
                        },
                    },
                    {
                        "name": "portmaster_doctor",
                        "description": "Ejecuta un diagnóstico completo del entorno de desarrollo.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "path": {"type": "string", "description": "Ruta opcional al proyecto"}
                            },
                        },
                    },
                    {
                        "name": "portmaster_ports",
                        "description": "Escanea el estado de los puertos especificados o del stack actual.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "ports": {
                                    "type": "array",
                                    "items": {"type": "integer"},
                                    "description": "Lista de puertos a inspeccionar",
                                }
                            },
                        },
                    },
                    {
                        "name": "portmaster_free_port",
                        "description": "Cierra el proceso que ocupa un puerto específico.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "port": {"type": "integer", "description": "Número de puerto a liberar"}
                            },
                            "required": ["port"],
                        },
                    },
                    {
                        "name": "portmaster_share",
                        "description": "Inicia un túnel público seguro hacia un puerto local.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "port": {"type": "integer", "description": "Número de puerto a compartir"},
                                "provider": {
                                    "type": "string",
                                    "description": "Proveedor opcional: cloudflared, ngrok, lt, tailscale",
                                },
                            },
                            "required": ["port"],
                        },
                    },
                    {
                        "name": "portmaster_run",
                        "description": "Ejecuta un script o pipeline de tareas definido en el stack.yaml del proyecto.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "script": {"type": "string", "description": "Nombre del script a ejecutar"},
                                "args": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "Argumentos extra opcionales",
                                },
                            },
                            "required": ["script"],
                        },
                    },
                    {
                        "name": "portmaster_clean",
                        "description": (
                            "Limpia recursos huérfanos de Docker: contenedores parados, redes, "
                            "imágenes sin tag y caché de build. No borra volúmenes: eso tiene "
                            "datos adentro y lo hace el usuario con `portmaster clean --volumes`."
                        ),
                        # Sin `volumes`: lo que no se puede deshacer no se le ofrece a un
                        # agente. El chequeo de verdad esta en _execute_tool, porque el
                        # esquema es una sugerencia y el campo puede llegar igual.
                        "inputSchema": {"type": "object", "properties": {}},
                    },
                    {
                        "name": "portmaster_history",
                        "description": "Obtiene el historial de arranques y telemetría de un proyecto.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "path": {"type": "string", "description": "Ruta opcional al proyecto"},
                                "limit": {"type": "integer", "description": "Cantidad máxima de entradas (default: 5)"},
                            },
                        },
                    },
                    {
                        "name": "portmaster_init",
                        "description": "Genera o congela la configuración de stack.yaml detectada para el proyecto.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "path": {"type": "string", "description": "Ruta opcional al proyecto"},
                            },
                        },
                    },
                ]
            },
        }

    if method == "tools/call":
        tool_name = params.get("name")
        arguments = params.get("arguments", {})

        try:
            res_content = _execute_tool(tool_name, arguments)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"content": [{"type": "text", "text": res_content}]},
            }
        except Exception as exc:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": f"Error ejecutando {tool_name}: {exc}"}],
                    "isError": True,
                },
            }

    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def _execute_tool(name: str, args: dict[str, Any]) -> str:
    cwd = Path(args.get("path") or Path.cwd())

    if name == "portmaster_status":
        stack = detect.stack_for(cwd)
        registered_paths = registry.paths()
        data = {
            "project_name": stack.name,
            "project_root": str(stack.root),
            "services": [
                {
                    "name": s.name,
                    "command": s.command,
                    "port": s.port,
                    "ready": s.ready,
                    "needs": list(s.needs),
                }
                for s in stack.services.values()
            ],
            "scripts": list(stack.scripts.keys()),
            "registered_projects": [str(p) for p in registered_paths],
        }
        return json.dumps(data, indent=2)

    if name == "portmaster_doctor":
        results = doctor.run(cwd)
        lines = [
            f"[{r.level.upper()}] {r.name}: {r.detail or 'ok'}"
            + (f" -> Solución: {r.fix}" if r.fix else "")
            for r in results
        ]
        return "\n".join(lines)

    if name == "portmaster_ports":
        port_list = args.get("ports")
        if not port_list:
            stack = detect.stack_for(cwd)
            port_list = stack.ports()
        statuses = [ports.scan(p) for p in port_list]
        data = [
            {
                "port": s.port,
                "free": s.free,
                "pid": s.pid,
                "process_name": s.name,
                "command": s.cmdline,
            }
            for s in statuses
        ]
        return json.dumps(data, indent=2)

    if name == "portmaster_free_port":
        port = int(args["port"])
        status = ports.scan(port)
        if status.free:
            return f"El puerto {port} ya esta libre."
        if status.pid is None:
            return f"El puerto {port} esta ocupado por un proceso que no es visible con estos permisos."
        # El pid y el create_time que vio el escaneo. Aca iba `kill(port)`, o sea
        # el numero de puerto en el lugar del pid: liberar el 3000 mataba al
        # proceso 3000, que no tiene nada que ver. El create_time es la
        # verificacion contra reciclado de PIDs y no es opcional en este proyecto.
        #
        # Sin valor de retorno que mirar: `kill` no devuelve nada y levanta si el
        # proceso esta protegido, ya no existe o faltan permisos. Esas excepciones
        # las convierte `tools/call` en isError, que es como el agente se entera.
        ports.kill(status.pid, status.create_time, port=port)
        return f"Proceso en puerto {port} (pid {status.pid}) liberado."

    if name == "portmaster_share":
        port = ports.check_port(int(args["port"]))
        provider = args.get("provider")
        tun = tunnel.start_tunnel(port, provider=provider)
        _tuneles.append(tun)
        return f"Tunel activo via {tun.provider}: {tun.url}"

    if name == "portmaster_run":
        script_name = args["script"]
        extra = args.get("args") or []
        stack = detect.stack_for(cwd)
        code = scripts.run_script(stack, script_name, extra_args=extra)
        return f"Script '{script_name}' finalizado con código de salida {code}."

    if name == "portmaster_clean":
        # Los volumenes no, y no por el esquema sino aca: un agente puede mandar
        # el campo igual. El resto del prune (cache y capas sin tag) se regenera
        # solo; un volumen tiene la base de datos del proyecto adentro y no
        # vuelve. El CLI y la interfaz preguntan antes; el MCP no tiene donde
        # preguntar, asi que lo que no se puede deshacer no se ofrece.
        if bool(args.get("volumes", False)):
            raise ValueError(
                "borrar volumenes de Docker no se hace desde un agente: tienen datos "
                "adentro y no se puede deshacer. Corre `portmaster clean --volumes` "
                "vos mismo, que pregunta antes."
            )
        ok, msg = docker.prune(docker.DEFAULT_TARGETS)
        return f"Docker prune: {'éxito' if ok else 'fallo'} - {msg}"

    if name == "portmaster_history":
        pid = registry.project_id(cwd)
        limit = int(args.get("limit", 5))
        entries = history.read(pid, limit=limit)
        return json.dumps({"project_id": pid, "entries": entries}, indent=2)

    if name == "portmaster_init":
        target = detect.freeze(cwd)
        return f"Stack congelado exitosamente en: {target}"

    raise ValueError(f"Herramienta desconocida: {name}")


def _reservar_stdout():
    """Deja el descriptor 1 solo para el protocolo y manda lo demas a stderr.

    Sobre stdio el JSON-RPC comparte el descriptor 1 con todo lo que imprima el
    proceso. `portmaster_run` lanza los comandos del usuario heredando ese
    descriptor, asi que un `echo` adentro de un script se metia entre dos
    respuestas y el cliente perdia la sesion.

    Se duplica el descriptor antes de reapuntarlo: el protocolo escribe por la
    copia, y lo que siga escribiendo en 1 termina en stderr, que los clientes MCP
    leen como log. Tiene que ser a nivel de descriptor y no cambiando
    `sys.stdout`: un subproceso hereda el descriptor y no el objeto de Python.
    """
    try:
        copia = os.dup(sys.stdout.fileno())
        os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    except (OSError, ValueError, io.UnsupportedOperation):
        # Sin descriptores de verdad (un arnes que captura la salida): queda el
        # stdout de Python, que al menos ordena lo que imprima este proceso.
        return sys.stdout
    return os.fdopen(copia, "w", encoding="utf-8", buffering=1)


def serve_stdio() -> None:
    """Bucle principal de servidor MCP sobre stdio.

    Al terminar cierra los tuneles que abrio, por el mismo motivo que
    `server._ciclo_de_vida`: sin esto el agente cerraba la sesion y el cliente
    de tuneles seguia vivo, con el puerto expuesto a internet, sin nada en
    pantalla que lo dijera. Aca es peor que en la interfaz, porque del otro lado
    no hay nadie mirando.
    """
    protocolo = _reservar_stdout()
    try:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
            except json.JSONDecodeError:
                continue

            resp = handle_request(req)
            if resp is not None:
                protocolo.write(json.dumps(resp) + "\n")
                protocolo.flush()
    finally:
        cerrar_tuneles()
