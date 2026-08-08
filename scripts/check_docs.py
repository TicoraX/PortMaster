"""Verifica que partir el README no se haya comido ningun parrafo.

Compara los parrafos del README de un commit anterior contra la union del
README actual y los docs/*.md. Normaliza espacios y saltos, porque reflowear
un parrafo al moverlo es esperable; perderlo no.

Uso: python scripts/check_docs.py <ref-de-git>
"""

import pathlib
import re
import subprocess
import sys

# Debajo de esto quedan las lineas de entrada a un bloque de codigo ("Levantar
# el stack entero:") y poco mas. Arranco en 80 y once parrafos de contenido real
# caian afuera, entre ellos "Nada de esto es recursivo", de 77 caracteres: el
# verificador daba verde sobre un README al que le habia sacado un parrafo.
MINIMO = 40


def parrafos(texto: str) -> list[str]:
    """Bloques de prosa, sin codigo ni tablas ni titulos."""
    texto = re.sub(r"```.*?```", "", texto, flags=re.DOTALL)
    fuera = []
    for bloque in texto.split("\n\n"):
        limpio = " ".join(bloque.split())
        if not limpio or limpio.startswith("#") or limpio.startswith("|"):
            continue
        if limpio.startswith("- ") or limpio.startswith("["):
            continue
        if len(limpio) >= MINIMO:
            fuera.append(limpio)
    return fuera


def main() -> int:
    if len(sys.argv) != 2:
        print("uso: check_docs.py <ref-de-git>")
        return 1
    ref = sys.argv[1]

    viejo = subprocess.run(
        ["git", "show", f"{ref}:README.md"],
        capture_output=True, text=True, encoding="utf-8", check=True,
    ).stdout

    actual = pathlib.Path("README.md").read_text(encoding="utf-8")
    for doc in sorted(pathlib.Path("docs").glob("*.md")):
        actual += "\n\n" + doc.read_text(encoding="utf-8")
    presentes = set(parrafos(actual))

    faltan = [p for p in parrafos(viejo) if p not in presentes]

    print(f"{ref}: {len(parrafos(viejo))} parrafos, faltan {len(faltan)}")
    for p in faltan:
        print(f"\n  FALTA: {p[:140]}...")
    return 1 if faltan else 0


if __name__ == "__main__":
    sys.exit(main())
