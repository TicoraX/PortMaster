"""Verifica que el wheel declare los classifiers que PyPI usa para filtrar.

No es un test de pytest a proposito: no corre en CI ni en cada commit, corre
una vez por release contra el artefacto construido. Un test que afirma el
contenido de pyproject.toml solo se afirma a si mismo.
"""

import email
import pathlib
import sys
import zipfile

ESPERADOS = {
    "Development Status :: 5 - Production/Stable",
    "Environment :: Console",
    "Intended Audience :: Developers",
    "License :: OSI Approved :: MIT License",
    "Operating System :: OS Independent",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.10",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Programming Language :: Python :: 3.13",
    "Topic :: Software Development",
    "Topic :: System :: Systems Administration",
    "Topic :: Utilities",
}


def main() -> int:
    wheels = sorted(pathlib.Path("dist").glob("*.whl"))
    if not wheels:
        print("no hay wheel en dist/: corre `python -m build` primero")
        return 1
    wheel = wheels[-1]

    with zipfile.ZipFile(wheel) as z:
        nombre = next(n for n in z.namelist() if n.endswith(".dist-info/METADATA"))
        meta = email.message_from_bytes(z.read(nombre))

    presentes = set(meta.get_all("Classifier") or [])
    faltan = ESPERADOS - presentes
    sobran = presentes - ESPERADOS

    print(f"{wheel.name}: {len(presentes)} classifiers")
    for c in sorted(faltan):
        print(f"  falta: {c}")
    for c in sorted(sobran):
        print(f"  no esperado: {c}")

    version = meta.get("Requires-Python")
    print(f"Requires-Python: {version}")
    if version != ">=3.10":
        print("  Requires-Python no coincide con el piso declarado")
        return 1

    return 1 if faltan else 0


if __name__ == "__main__":
    sys.exit(main())
