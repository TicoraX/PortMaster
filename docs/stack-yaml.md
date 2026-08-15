# Referencia de stack.yaml

El ejemplo mínimo está en el [README](../README.md#stackyaml). Acá está cada
campo, con el ejemplo completo y comentado en
[`stack.example.yaml`](../stack.example.yaml).

## Campos

`command` es el único campo obligatorio. `needs` define el orden de arranque
y los ciclos fallan al cargar el archivo, no a mitad del arranque. Un perfil
arrastra sus dependencias transitivas: pedir `api` sin su base de datos nunca
es lo que alguien quiso decir.

Los servicios que no dependen entre sí arrancan juntos, y cada tanda espera a
estar lista antes de la siguiente. El stack tarda el healthcheck más lento de
cada nivel en lugar de la suma de todos, a cambio de que los logs de los
primeros segundos se entreveren. Van prefijados por servicio y con un color
propio cada uno, así que se siguen leyendo.

`default` es opcional y lista qué arranca cuando no pedís perfil. Sin él,
arranca todo, que es lo que casi siempre querés. Existe para el caso de abajo.

## Perfiles de un compose detectado

Un `compose.yaml` con `profiles:` los trae puestos:

```yaml
services:
  db: { image: postgres }
  seed:
    image: seed
    profiles: [tools]
```

Ahí `seed` queda afuera del arranque por defecto y entra con
`portmaster up --profile tools`, igual que con `docker compose --profile tools`.
Ojo con la semántica, porque está invertida: en compose `profiles:` **excluye**
un servicio hasta que lo pidas, mientras que en `stack.yaml` un perfil es la
lista de lo que se arranca. `detect` traduce de una a la otra, y por eso
`portmaster init` sobre ese proyecto escribe también un `default`: sin él, el
archivo congelado prendería lo que el compose deja apagado a propósito.

## ready

`ready` decide cuándo un servicio cuenta como listo, y acepta cinco formas:

| Valor | Espera a que |
|---|---|
| `port` | el puerto acepte conexiones (default si hay `port`) |
| `listen` | el proceso abra un puerto cualquiera, y lo reporta |
| `log:texto` | ese texto aparezca en la salida del servicio |
| `http://...` | esa URL responda con menos de 400 |
| `none` | nada (default si no hay `port`) |

`listen` es para servicios que eligen su propio puerto. Es incompatible con
`port`: si lo conocés, el healthcheck es `port`.

`port` no distingue quién contesta. Si alguien ya escuchaba ahí antes de
arrancar, el servicio se declara listo en el acto aunque el `listo` sea de otro
proceso, y por eso el arranque lo dice: `listo (3000) · el puerto ya estaba
ocupado antes de arrancar`. Con `up` normal no pasa, porque libera los puertos
primero; aparece con `--no-free`, y en el caso legítimo de un
`docker compose up -d` sobre un contenedor que ya estaba arriba.

## stop

`stop` es un comando de apagado propio, opcional. Sin él, apagar mata el árbol
de procesos del servicio, que es lo correcto para un `npm run dev` y no alcanza
para un contenedor: `docker compose up -d` termina enseguida y lo que queda
vivo no es hijo nuestro. Los servicios detectados de un compose traen
`stop: docker compose stop <nombre>`. Si el comando falla o tarda más de 90s, se
loguea y el apagado sigue con el resto.

## env_file

`env_file` permite cargar variables de entorno desde uno o varios archivos (ej.
`env_file: .env` o `env_file: [.env, .env.local]`). La precedencia de variables es:
1. `os.environ` del sistema anfitrión.
2. `~/.portmaster/env.global` (bóveda global de variables compartidas, si existe).
3. Archivos listados en `env_file` (en orden de aparición).
4. `env:` declarado explícitamente en el servicio (máxima prioridad).

## pre_start y post_start

Hooks síncronos de ciclo de vida:
*   `pre_start`: Comando que se ejecuta antes de lanzar el proceso principal (ej.
    migraciones de base de datos o compilación). Si retorna un código distinto de 0,
    el arranque del servicio se aborta inmediatamente.
*   `post_start`: Comando que se ejecuta una vez que el servicio confirma que está
    listo (`ready`). Si falla, se reporta el error y se detiene el stack.

