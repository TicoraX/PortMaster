"""Safety Guardrails para validación de identificadores, rutas y comandos."""

from __future__ import annotations

import re

# Longitud máxima permitida para identificadores seguros
MAX_IDENT_LEN = 64

# Identificadores alfanuméricos seguros para IDs de proyecto y servicios
_IDENT_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")

# Nombres de dispositivos reservados en Windows (DOS Device Names)
_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
}

# Patrones de comandos destructivos irrecuperables
_DESTRUCTIVE_PATTERNS = [
    (re.compile(r"\brm\s+(-[a-zA-Z]*r[a-zA-Z]*\s+-[a-zA-Z]*f[a-zA-Z]*|-[a-zA-Z]*f[a-zA-Z]*\s+-[a-zA-Z]*r[a-zA-Z]*|-[a-zA-Z]*r[a-zA-Z]*f[a-zA-Z]*|--recursive\s+--force|--force\s+--recursive)\s+[/~*]", re.IGNORECASE), "comando destructivo raíz o home ('rm -rf /' o '~')"),
    (re.compile(r"\b(rmdir|rd)\s+.*[/\\]s.*[a-zA-Z]:\\?", re.IGNORECASE), "borrado recursivo de disco completo ('rmdir /s /q C:\\')"),
    (re.compile(r"\bdel\s+.*[/\\]s.*[a-zA-Z]:", re.IGNORECASE), "borrado recursivo de archivos en unidad de disco"),
    (re.compile(r"\b(remove-item)\s+.*-recurse.*[a-zA-Z]:", re.IGNORECASE), "borrado recursivo en PowerShell ('Remove-Item -Recurse C:\\')"),
    (re.compile(r"\bformat\s+[a-zA-Z]:", re.IGNORECASE), "formateo de unidad de disco ('format X:')"),
    (re.compile(r"\bmkfs(\.[a-zA-Z0-9]+)?\s+", re.IGNORECASE), "formateo de sistema de archivos ('mkfs')"),
    (re.compile(r"\bdd\s+if=.*?of=/dev/[a-zA-Z0-9]+", re.IGNORECASE), "escritura directa en bloque de dispositivo ('dd of=/dev/...')"),
    (re.compile(r"\b(drop\s+database|drop\s+schema)\s+", re.IGNORECASE), "eliminación de base de datos completa sin confirmación"),
]


class GuardrailError(ValueError):
    """Acción o comando bloqueado por políticas de seguridad."""


def validate_identifier(ident: str, field_name: str = "identificador") -> str:
    """Valida que un ID de proyecto o servicio sea alfanumérico seguro (sin path traversal ni DOS devices)."""
    clean = str(ident).strip()
    if not clean:
        raise GuardrailError(f"{field_name} no puede estar vacío")
    if len(clean) > MAX_IDENT_LEN:
        raise GuardrailError(f"{field_name} excede la longitud máxima permitida ({MAX_IDENT_LEN} caracteres)")
    if not _IDENT_PATTERN.match(clean):
        raise GuardrailError(
            f"{field_name} inválido ({clean!r}): solo se permiten letras, números, guiones y guiones bajos"
        )
    if clean.upper() in _WINDOWS_RESERVED:
        raise GuardrailError(f"{field_name} inválido ({clean!r}): nombre de dispositivo reservado en Windows")
    return clean


def check_command(cmd: str) -> tuple[bool, str]:
    """Verifica si un comando contiene patrones destructivos que pongan en riesgo el sistema.
    
    Devuelve (True, 'ok') si es seguro, o (False, motivo) si es bloqueado.
    """
    cmd_str = cmd.strip()
    for pattern, reason in _DESTRUCTIVE_PATTERNS:
        if pattern.search(cmd_str):
            return False, f"Comando bloqueado por Guardrails: {reason}"
    return True, "ok"


def assert_safe_command(cmd: str) -> None:
    """Levanta GuardrailError si el comando viola las políticas de seguridad."""
    ok, reason = check_command(cmd)
    if not ok:
        raise GuardrailError(reason)
