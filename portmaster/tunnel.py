"""Exposicion de servicios locales via tuneles seguros (Cloudflare, ngrok, localtunnel, tailscale)."""

from __future__ import annotations

import re
import shutil
import subprocess
import threading
from dataclasses import dataclass
from typing import Callable

PROVIDERS = ("cloudflared", "ngrok", "lt", "tailscale")

CLOUDFLARE_REGEX = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")
NGROK_REGEX = re.compile(r"https://[a-zA-Z0-9-]+\.ngrok(?:-free)?\.app")
LOCALTUNNEL_REGEX = re.compile(r"https://[a-zA-Z0-9-]+\.loca\.lt")


class TunnelError(Exception):
    """Falla al iniciar o detectar un proveedor de tuneles."""


@dataclass
class Tunnel:
    provider: str
    port: int
    url: str
    proc: subprocess.Popen

    def stop(self) -> None:
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()


def detect_providers() -> list[str]:
    """Retorna los clientes de tuneles instalados en el sistema."""
    return [p for p in PROVIDERS if shutil.which(p) is not None]


def start_tunnel(
    port: int,
    provider: str | None = None,
    timeout: float = 15.0,
) -> Tunnel:
    """Inicia un tunel efimero hacia el puerto especificado y extrae la URL publica."""
    available = detect_providers()
    if provider:
        if provider not in PROVIDERS:
            raise TunnelError(f"proveedor desconocido: {provider!r}. Soportados: {', '.join(PROVIDERS)}")
        if shutil.which(provider) is None:
            raise TunnelError(f"el binario '{provider}' no esta instalado o no se encuentra en el PATH")
        chosen = provider
    else:
        if not available:
            raise TunnelError(
                "no se encontro ningun cliente de tuneles en el PATH. "
                "Instala 'cloudflared' (recomendado), 'ngrok' o 'localtunnel'."
            )
        chosen = available[0]

    cmd, url_extractor = _provider_config(chosen, port)
    proc = subprocess.Popen(
        cmd,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        errors="replace",
    )

    found_url: list[str] = []
    ready_event = threading.Event()

    def _reader():
        assert proc.stdout is not None
        for line in proc.stdout:
            url = url_extractor(line)
            if url and not found_url:
                found_url.append(url)
                ready_event.set()

    thread = threading.Thread(target=_reader, daemon=True)
    thread.start()

    if not ready_event.wait(timeout=timeout):
        proc.terminate()
        raise TunnelError(f"no se pudo obtener la URL publica del tunel '{chosen}' en {timeout:.0f}s")

    return Tunnel(provider=chosen, port=port, url=found_url[0], proc=proc)


def _provider_config(
    provider: str, port: int
) -> tuple[str, Callable[[str], str | None]]:
    if provider == "cloudflared":
        cmd = f"cloudflared tunnel --url http://127.0.0.1:{port}"
        def extract(line: str) -> str | None:
            m = CLOUDFLARE_REGEX.search(line)
            return m.group(0) if m else None
        return cmd, extract

    if provider == "ngrok":
        cmd = f"ngrok http {port} --log stdout"
        def extract(line: str) -> str | None:
            m = NGROK_REGEX.search(line)
            return m.group(0) if m else None
        return cmd, extract

    if provider == "lt":
        cmd = f"lt --port {port}"
        def extract(line: str) -> str | None:
            m = LOCALTUNNEL_REGEX.search(line)
            return m.group(0) if m else None
        return cmd, extract

    if provider == "tailscale":
        cmd = f"tailscale funnel {port}"
        def extract(line: str) -> str | None:
            if "https://" in line:
                for part in line.split():
                    if part.startswith("https://"):
                        return part.strip()
            return None
        return cmd, extract

    raise TunnelError(f"configuracion no implementada para: {provider}")
