# Partir el README Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) o superpowers:executing-plans para implementar este plan tarea por tarea. Los pasos usan checkbox (`- [ ]`) para tracking.

**Goal:** Bajar `README.md` de 477 a menos de 200 líneas moviendo el material que explica "por qué decide así" a tres documentos de `docs/`, y subir "cómo se usa" a la primera pantalla.

**Architecture:** El README de hoy es dos documentos fusionados: un manual de uso y la defensa de un diseño. La separación es por pregunta, no por tema. Lo que contesta "qué comando corro" queda en el README. Lo que contesta "por qué `hyper` no cuenta como servidor de Rust" se va a `docs/`. Nada se borra: cada párrafo del original tiene que terminar en alguno de los cuatro archivos, y eso se verifica con un script, no a ojo.

**Tech Stack:** Markdown. Un script de verificación en Python con stdlib.

## Global Constraints

- **Sin `Co-Authored-By: Claude`** ni atribución al asistente en commits ni en PRs.
- **Sin emojis** ni iconos decorativos en tablas ni títulos.
- **Sin em dashes.** Coma, punto o dos puntos.
- **No se reescribe el contenido.** Esta tarea mueve texto. Reescribir párrafos mientras se los mueve hace imposible verificar que no se perdió nada. Las únicas excepciones son las declaradas explícitamente en los pasos.
- El README final tiene que estar **por debajo de 200 líneas**.
- Todo link interno tiene que resolver a un archivo que existe.
- Trabajo sobre `develop`. `main` solo por PR.

---

### Task 1: El verificador de que no se pierde nada

Un refactor de documentación falla de una sola forma interesante: un párrafo que estaba y ya no está, y nadie se entera hasta que alguien busca esa explicación seis meses después. El chequeo compara los párrafos del README original, leído desde git, contra la unión del README nuevo y los `docs/` nuevos.

**Files:**
- Create: `scripts/check_docs.py`

**Interfaces:**
- Consumes: nada.
- Produces: `python scripts/check_docs.py <ref>` sale 0 si cada párrafo de `<ref>:README.md` aparece en los archivos actuales, y 1 con la lista de los que faltan. Las Tasks 2 y 3 lo usan como gate.

- [ ] **Step 1: Escribir el verificador**

```python
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

# Un parrafo de menos de esto es un titulo, una linea de tabla o un fragmento
# de codigo: hay demasiados y coinciden por casualidad.
MINIMO = 80


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
```

- [ ] **Step 2: Verificar que pasa contra HEAD, donde nada cambió todavía**

Un verificador que no puede dar verde sobre el estado actual está roto, y eso hay que saberlo antes de empezar a mover texto.

```bash
.venv/Scripts/python.exe scripts/check_docs.py HEAD
```

Esperado: exit 0, `faltan 0`.

- [ ] **Step 3: Verificar que sabe fallar**

```bash
.venv/Scripts/python.exe -c "
import pathlib
p = pathlib.Path('README.md')
t = p.read_text(encoding='utf-8')
t = t.replace('Nada de esto es recursivo: un scan profundo termina dentro de \`node_modules\`.', '')
p.write_text(t, encoding='utf-8')
"
.venv/Scripts/python.exe scripts/check_docs.py HEAD
git checkout -- README.md
```

Esperado: exit 1, con una línea `FALTA:` que menciona `node_modules`. Después del `git checkout`, el README vuelve a estar intacto.

- [ ] **Step 4: Commit**

```bash
git add scripts/check_docs.py
git commit -m "docs: verificador de que partir el README no pierde parrafos"
```

---

### Task 2: Los tres documentos de docs/

Se crean primero, con el texto movido tal cual. El README todavía no se toca, así que en este punto el contenido está duplicado y el verificador pasa por construcción. Se separa en dos tareas a propósito: si el README se vaciara antes de que los `docs/` existan, un error a mitad de camino deja el repo sin la explicación en ningún lado.

**Files:**
- Create: `docs/deteccion.md`
- Create: `docs/interfaz.md`
- Create: `docs/stack-yaml.md`

**Interfaces:**
- Consumes: `scripts/check_docs.py` de la Task 1.
- Produces: los tres archivos a los que la Task 3 va a linkear, con estos nombres exactos.

- [ ] **Step 1: `docs/deteccion.md`**

Encabezado nuevo, y después el texto de `README.md:81-136` movido sin tocar (desde "Si la raíz no tiene `package.json`" hasta "No sobreescribe uno existente."). El encabezado es contenido nuevo y por eso se escribe acá y no se copia:

```markdown
# Detección sin stack.yaml

Cuando un proyecto no tiene `stack.yaml`, PortMaster infiere los servicios de
lo que encuentra en el disco. La tabla de qué reconoce está en el
[README](../README.md#sin-stackyaml). Acá está por qué reconoce eso y no otra
cosa, que es lo que hay que leer antes de agregar un detector.

La regla que ordena todo lo de abajo: solo se detecta lo que sirve en un
puerto. Un binario que no abre ninguno, arrancado como servicio, deja al stack
esperando un healthcheck que no va a llegar nunca.

## Dónde busca
```

Después de ese `## Dónde busca` van los párrafos de `README.md:81-92` (monorepo y lista de frameworks de backend), luego un `## Por lenguaje` con los párrafos de `README.md:94-119`, luego `## Compose` con `README.md:121-126`, y `## De dónde sale el puerto` con `README.md:128-136`.

- [ ] **Step 2: `docs/interfaz.md`**

```markdown
# Interfaz web

Cómo se arranca y qué muestra está en el
[README](../README.md#interfaz-web). Acá está el detalle de cada control y por
qué se comporta como se comporta.
```

Después van los párrafos de `README.md:230-291`, o sea desde "Cuando un servicio se muere solo" hasta "Podés fijar el token vos mismo con `PORTMASTER_TOKEN`.", con estos `##` intercalados: `## Caídas y avisos` (antes de 230), `## Congelar a stack.yaml` (antes de 236), `## Reiniciar un servicio` (antes de 242), `## El botón Abrir` (antes de 246), `## Docker` (antes de 254), `## Explorar carpetas` (antes de 280), `## Seguridad` (antes de 287).

Además se mueve acá el párrafo de `README.md:337-340` ("Esa sección de la interfaz se ve siempre..."), bajo el `## Docker`, porque habla de la interfaz y hoy está perdido dentro de la sección de puertos del CLI.

- [ ] **Step 3: `docs/stack-yaml.md`**

```markdown
# Referencia de stack.yaml

El ejemplo mínimo está en el [README](../README.md#stackyaml). Acá está cada
campo, con el ejemplo completo y comentado en
[`stack.example.yaml`](../stack.example.yaml).
```

Después: los párrafos de `README.md:390-402`, la sección `### Perfiles de un compose detectado` completa (`README.md:404-422`) promovida a `##`, y `README.md:424-452` (la tabla de `ready`, sus tres párrafos y el de `stop`).

- [ ] **Step 4: Verificar que no se perdió nada**

En este punto el contenido está duplicado, así que el verificador tiene que pasar sí o sí. Si falla acá, es que al copiar se rompió un párrafo.

```bash
.venv/Scripts/python.exe scripts/check_docs.py HEAD
```

Esperado: exit 0, `faltan 0`.

- [ ] **Step 5: Verificar que los links relativos resuelven**

```bash
.venv/Scripts/python.exe -c "
import pathlib, re
malos = []
for md in list(pathlib.Path('docs').glob('*.md')) + [pathlib.Path('README.md')]:
    for destino in re.findall(r']\((?!https?:)([^)#]+)', md.read_text(encoding='utf-8')):
        if not (md.parent / destino).resolve().exists():
            malos.append(f'{md}: {destino}')
print('links rotos:', malos or 'ninguno')
raise SystemExit(1 if malos else 0)
"
```

Esperado: `links rotos: ninguno`, exit 0.

- [ ] **Step 6: Commit**

```bash
git add docs/deteccion.md docs/interfaz.md docs/stack-yaml.md
git commit -F - <<'EOF'
docs: mover a docs/ el material de diseno del README

Tres archivos con el texto tal cual estaba, sin reescribir. El README todavia
lo tiene duplicado: lo saca el commit que sigue. Separado en dos pasos para
que ningun estado intermedio se quede sin la explicacion en ningun lado.
EOF
```

---

### Task 3: El README nuevo

Recién acá se saca el texto duplicado y se reordena. El cambio de fondo es que "cómo se usa" sube: hoy la lista de comandos no existe como tal, están desperdigados en subsecciones y el primer `serve` aparece en la línea 215.

**Files:**
- Modify: `README.md` (reescritura de la estructura, con el texto que se queda sin tocar)

**Interfaces:**
- Consumes: los tres archivos de la Task 2, linkeados como `docs/deteccion.md`, `docs/interfaz.md`, `docs/stack-yaml.md`.
- Produces: el README final. Nadie depende de él.

- [ ] **Step 1: Escribir el README nuevo**

Orden de secciones, con el origen de cada una:

| Sección | Contenido |
|---|---|
| Título, badges, pitch | Se queda igual (`1-14`), menos el segundo párrafo, que repite el primero |
| `## Instalación` | Igual (`16-24`) |
| `## Comandos` | Tabla nueva, ver abajo |
| `## Arrancar un stack` | `28-56` tal cual, con el bloque de log |
| `## Sin stack.yaml` | La tabla de detección (`62-67`), el bloque de ejemplo (`69-79`), la línea de `init` (`135-136`), y el link a `docs/deteccion.md` |
| `## stack.yaml` | El YAML de ejemplo (`363-388`) y el link a `docs/stack-yaml.md` |
| `## Interfaz web` | `211-228` y el link a `docs/interfaz.md` |
| `## Puertos` | `295-335` sin el párrafo de `337-340`, que se fue a `docs/interfaz.md` |
| `## Qué no hace el kill switch` | Igual (`342-356`) |
| `## Otros comandos` | `down` (`138-149`), `switch` (`151-165`), `doctor` (`167-195`), `open` (`197-207`) |
| `## Modelo de confianza` | Igual (`454-462`) |
| `## Desarrollo` | Igual (`464-473`) |
| `## Licencia` | Igual (`475-477`) |

La tabla de comandos es contenido nuevo, y es el arreglo de fondo: la queja concreta fue que "cómo se usa" queda lejos. Va tercera, antes que cualquier explicación.

```markdown
## Comandos

| Comando | Qué hace |
|---|---|
| `portmaster up` | Levanta el stack entero: libera puertos, arranca en orden y sigue los logs |
| `portmaster down` | Baja lo que sobrevive a la terminal, o sea contenedores |
| `portmaster serve` | Abre la interfaz web en `http://127.0.0.1:7666` |
| `portmaster doctor` | Revisa qué puede impedir el arranque, sin arrancar nada |
| `portmaster ports` | Estado de los puertos declarados |
| `portmaster free 3000` | Cierra el proceso que ocupa un puerto, preguntando antes |
| `portmaster free --all` | Lo mismo para todos los puertos de todos los proyectos registrados |
| `portmaster switch fitness` | Baja los proyectos que le pisan los puertos a este, y lo levanta |
| `portmaster open` | Abre en el navegador el primer servicio que conteste HTTP |
| `portmaster init` | Congela lo detectado en un `stack.yaml` editable |
| `portmaster add .` | Registra el proyecto para que aparezca en la interfaz |
| `portmaster list` | Lista los proyectos registrados (alias: `ls`) |
| `portmaster remove .` | Des-registra un proyecto (alias: `rm`) |
| `portmaster version` | Versión instalada (también `--version`) |

Cada uno con `--help`.
```

El segundo párrafo del pitch (`12-14`) se borra: dice lo mismo que el primero con otras palabras, y es la única eliminación de esta tarea. Queda registrado acá para que el verificador la señale y se la apruebe a conciencia.

- [ ] **Step 2: Verificar el largo**

```bash
wc -l README.md
```

Esperado: menos de 200.

- [ ] **Step 3: Verificar que no se perdió nada**

```bash
.venv/Scripts/python.exe scripts/check_docs.py HEAD~2
```

`HEAD~2` es el commit anterior a la Task 1, o sea el README de 477 líneas. Esperado: exit 1, con exactamente **un** `FALTA:`, el del párrafo del pitch que se borró a propósito en el Step 1. Cualquier otro es una pérdida accidental y hay que recuperarla.

- [ ] **Step 4: Verificar los links**

Mismo comando que el Step 5 de la Task 2. Esperado: `links rotos: ninguno`.

Además, los anchors que apuntan de los `docs/` al README (`#sin-stackyaml`, `#interfaz-web`, `#stackyaml`) tienen que coincidir con los títulos nuevos:

```bash
grep -n "^## " README.md
```

Esperado: entre ellos, `## Sin stack.yaml`, `## Interfaz web` y `## stack.yaml`.

- [ ] **Step 5: Leerlo entero**

El único paso que no automatiza nada. Abrir `README.md` y leerlo de arriba a abajo buscando: una sección que quedó sin transición porque el párrafo que la unía se fue a `docs/`, un "como se explicó arriba" que ahora apunta a otro archivo, una tabla que perdió su introducción.

- [ ] **Step 6: Commit**

```bash
git add README.md
git commit -F - <<'EOF'
docs: README de 477 a menos de 200 lineas

El material de diseno ya vive en docs/. Lo que queda es el manual de uso, con
una tabla de comandos tercera, antes de cualquier explicacion: la queja fue
que "como se usa" quedaba lejos, y el primer `serve` aparecia en la linea 215.

Se borro el segundo parrafo del pitch, que repetia el primero. Es la unica
eliminacion; el resto es texto movido sin tocar.
EOF
```

---

### Task 4: Publicar

**Files:**
- Ninguno.

**Interfaces:**
- Consumes: los commits de las Tasks 1 a 3.
- Produces: `main` actualizado.

- [ ] **Step 1: PR**

```bash
git push origin develop
gh pr create --base main --head develop --title "README: partir en README + docs/" --body "477 lineas a menos de 200. El material de diseno se va a docs/deteccion.md, docs/interfaz.md y docs/stack-yaml.md. Tabla de comandos arriba de todo."
```

- [ ] **Step 2: CI verde**

```bash
gh pr checks --watch
```

Esperado: cinco jobs en `pass`.

- [ ] **Step 3: Merge**

```bash
gh pr merge --merge
git checkout develop && git pull
```

- [ ] **Step 4: No taggear**

Esta versión no se publica. La descripción larga de PyPI sale del README, así que el cambio se va a ver en la página del proyecto recién en el próximo release. No amerita un 1.0.2 por sí solo: si el README fuera lo único que cambió, un número de versión quemado por un refactor de documentación es peor que esperar.
