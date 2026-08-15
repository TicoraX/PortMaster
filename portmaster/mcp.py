"""Servidor MCP (Model Context Protocol) sobre stdio para agentes de IA."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from . import __version__, detect, docker, doctor, ports, registry, scripts


def handle_request(req: dict[str, Any]) -> dict[str, Any] | None:
    req_id = req.get("id")
    method = req.get("method")
    params = req.get("params", {})

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
                        "description": "Limpia recursos huérfanos de Docker (contenedores parados, redes, imágenes sin tag).",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "volumes": {
                                    "type": "boolean",
                                    "description": "Si true, limpia también volúmenes anónimos huérfanos",
                                }
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
        results = doctor.check(cwd)
        lines = [f"[{r.kind.upper()}] {r.name}: {r.detail or 'ok'}" for r in results]
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

    if name == "portmaster_run":
        script_name = args["script"]
        extra = args.get("args") or []
        stack = detect.stack_for(cwd)
        code = scripts.run_script(stack, script_name, extra_args=extra)
        return f"Script '{script_name}' finalizado con código de salida {code}."

    if name == "portmaster_clean":
        volumes = bool(args.get("volumes", False))
        ok, msg = docker.prune(volumes=volumes)
        return f"Docker prune: {'éxito' if ok else 'fallo'} - {msg}"

    raise ValueError(f"Herramienta desconocida: {name}")


def serve_stdio() -> None:
    """Bucle principal de servidor MCP sobre stdio."""
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
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()
