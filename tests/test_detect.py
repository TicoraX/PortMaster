"""Deteccion sobre directorios reales, y descubrimiento del puerto sobre un
proceso real que escucha. Lo mismo que el resto de la suite: nada de mocks."""

import io
import json
import sys
import textwrap

import pytest
from rich.console import Console

from portmaster import config, detect, ports, runner


def write(root, name, body=""):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return path


def test_sin_nada_conocido_no_detecta(tmp_path):
    write(tmp_path, "README.md", "hola")
    assert detect.detect(tmp_path) is None


def test_node_usa_dev_y_el_gestor_del_lockfile(tmp_path):
    write(tmp_path, "package.json", json.dumps({"scripts": {"dev": "vite", "start": "x"}}))
    write(tmp_path, "pnpm-lock.yaml", "lockfileVersion: 9")

    stack = detect.detect(tmp_path)
    assert stack.detected
    assert list(stack.services) == ["web"]
    web = stack.services["web"]
    assert web.command == "pnpm run dev"
    assert web.port is None
    assert web.ready == "listen"


def test_node_cae_a_start_y_a_npm(tmp_path):
    write(tmp_path, "package.json", json.dumps({"scripts": {"start": "next start"}}))
    assert detect.detect(tmp_path).services["web"].command == "npm run start"


def test_package_json_roto_no_revienta(tmp_path):
    write(tmp_path, "package.json", "{ esto no es json")
    assert detect.detect(tmp_path) is None


@pytest.mark.parametrize(
    "entrada, esperado",
    [
        ('["8080:80"]', 8080),
        ('["127.0.0.1:8080:80"]', 8080),
        ('[{"published": 8080, "target": 80}]', 8080),
        ('[{"published": "8080", "target": 80}]', 8080),
        ('["80"]', None),  # host aleatorio, no hay nada que liberar
        ('["8000-8010:80"]', None),  # rango
        ("[]", None),
    ],
)
def test_puerto_publicado_del_compose(tmp_path, entrada, esperado):
    write(tmp_path, "compose.yaml", f'services:\n  db:\n    image: postgres\n    ports: {entrada}\n')
    assert detect.detect(tmp_path).services["db"].port == esperado


def test_un_servicio_por_contenedor(tmp_path):
    write(
        tmp_path,
        "docker-compose.yml",
        """
        services:
          db:
            image: postgres
            ports: ['5433:5432']
          api:
            build: ./api
            ports: ['3100:3100']
            depends_on:
              db:
                condition: service_healthy
          web:
            build: ./web
            ports: ['8080:80']
            depends_on: [api]
        """,
    )

    stack = detect.detect(tmp_path)

    assert [s.name for s in stack.resolve()] == ["db", "api", "web"]
    assert stack.services["web"].command == "docker compose up -d web"
    assert stack.services["web"].port == 8080
    assert stack.services["api"].needs == ("db",)
    assert stack.services["web"].needs == ("api",)
    assert all(s.detached for s in stack.services.values())


def test_cada_contenedor_trae_su_apagado(tmp_path):
    write(tmp_path, "compose.yaml", "services:\n  db:\n    image: postgres\n")
    assert detect.detect(tmp_path).services["db"].stop == "docker compose stop db"


def test_compose_sin_servicios_apaga_todo(tmp_path):
    write(tmp_path, "docker-compose.yml", "name: solo-un-nombre\n")
    assert detect.detect(tmp_path).services["docker"].stop == "docker compose stop"


def test_un_proceso_local_no_tiene_apagado(tmp_path):
    write(tmp_path, "manage.py", "import django")
    assert detect.detect(tmp_path).services["api"].stop is None


def test_contenedor_con_puerto_espera_a_que_acepte(tmp_path):
    write(
        tmp_path,
        "docker-compose.yml",
        """
        services:
          db:
            image: postgres
            ports: ['5433:5432']
          cron:
            image: alpine
        """,
    )
    stack = detect.detect(tmp_path)
    assert stack.services["db"].ready == "port"
    assert stack.services["cron"].ready == "none", "sin puerto no hay nada que sondear"


def test_puerto_desde_variable_con_default(tmp_path):
    write(
        tmp_path,
        "compose.yaml",
        "services:\n  web:\n    image: nginx\n    ports: ['${WEB_PORT:-8080}:80']\n",
    )
    assert detect.detect(tmp_path).services["web"].port == 8080


def test_el_dotenv_le_gana_al_default(tmp_path):
    write(
        tmp_path,
        "compose.yaml",
        "services:\n  web:\n    image: nginx\n    ports: ['${WEB_PORT:-8080}:80']\n",
    )
    write(tmp_path, ".env", "# comentario\nWEB_PORT=9090\n")
    assert detect.detect(tmp_path).services["web"].port == 9090


def test_el_entorno_le_gana_al_dotenv(tmp_path, monkeypatch):
    write(
        tmp_path,
        "compose.yaml",
        "services:\n  web:\n    image: nginx\n    ports: ['${WEB_PORT:-8080}:80']\n",
    )
    write(tmp_path, ".env", "WEB_PORT=9090")
    monkeypatch.setenv("WEB_PORT", "7070")
    assert detect.detect(tmp_path).services["web"].port == 7070


def test_el_contenedor_le_gana_el_nombre_al_local(tmp_path):
    write(tmp_path, "compose.yaml", "services:\n  web:\n    image: nginx\n    ports: ['8080:80']\n")
    write(tmp_path, "package.json", json.dumps({"scripts": {"dev": "vite"}}))

    stack = detect.detect(tmp_path)

    assert list(stack.services) == ["web"]
    assert stack.services["web"].command == "docker compose up -d web"


def test_depends_on_a_un_servicio_inexistente_se_ignora(tmp_path):
    write(
        tmp_path,
        "compose.yaml",
        "services:\n  api:\n    image: node\n    depends_on: [fantasma]\n",
    )
    assert detect.detect(tmp_path).services["api"].needs == ()


def test_compose_sin_servicios_arranca_entero(tmp_path):
    write(tmp_path, "docker-compose.yml", "name: solo-un-nombre\n")
    docker = detect.detect(tmp_path).services["docker"]
    assert docker.command == "docker compose up -d"
    assert docker.detached
    assert docker.ready == "none"


def test_compose_invalido_detecta_sin_puerto(tmp_path):
    write(tmp_path, "compose.yaml", "esto: [no cierra")
    assert detect.detect(tmp_path).services["docker"].port is None


def test_django_por_manage_py(tmp_path):
    write(tmp_path, "manage.py", "import django")
    assert detect.detect(tmp_path).services["api"].command == "python manage.py runserver"


def test_uvicorn_necesita_el_modulo_con_app(tmp_path):
    write(tmp_path, "requirements.txt", "fastapi\nuvicorn\n")
    assert detect.detect(tmp_path) is None, "sin modulo con app no se adivina el comando"

    write(tmp_path, "src/main.py", "from fastapi import FastAPI\napp = FastAPI()\n")
    assert detect.detect(tmp_path).services["api"].command == "uvicorn src.main:app --reload"


def test_backend_python_en_subcarpeta(tmp_path):
    write(tmp_path, "backend/requirements.txt", "fastapi\nuvicorn\n")
    write(tmp_path, "backend/main.py", "from fastapi import FastAPI\napp = FastAPI()\n")

    servicio = detect.detect(tmp_path).services["backend"]
    assert servicio.command == "uvicorn main:app --reload"
    assert servicio.cwd == tmp_path / "backend"


def test_backend_python_en_workspace(tmp_path):
    write(tmp_path, "services/api/manage.py", "import django")
    assert detect.detect(tmp_path).services["api"].cwd == tmp_path / "services" / "api"


def test_la_raiz_python_gana_y_no_baja(tmp_path):
    """Igual que en Node: si la raiz es el proyecto, los hijos no entran."""
    write(tmp_path, "manage.py", "import django")
    write(tmp_path, "backend/manage.py", "import django")

    stack = detect.detect(tmp_path)
    assert list(stack.services) == ["api"]
    assert stack.services["api"].cwd == tmp_path


def test_orden_y_dependencias(tmp_path):
    write(tmp_path, "compose.yaml", "services:\n  db:\n    image: postgres\n")
    write(tmp_path, "manage.py", "import django")
    write(tmp_path, "package.json", json.dumps({"scripts": {"dev": "vite"}}))

    stack = detect.detect(tmp_path)
    assert [s.name for s in stack.resolve()] == ["db", "api", "web"]
    assert stack.services["api"].needs == ("db",), "el backend local espera al contenedor"
    assert stack.services["web"].needs == ("api",)


def test_frontend_en_subcarpeta_de_workspace(tmp_path):
    write(
        tmp_path,
        "apps/web/package.json",
        json.dumps({"scripts": {"dev": "vite"}, "devDependencies": {"vite": "^5"}}),
    )
    write(tmp_path, "pnpm-lock.yaml", "lockfileVersion: 9")

    stack = detect.detect(tmp_path)
    web = stack.services["web"]

    assert web.command == "pnpm run dev", "el lockfile de la raiz vale para el hijo"
    assert web.cwd == tmp_path / "apps" / "web"
    assert web.ready == "listen"


def test_frontend_en_carpeta_con_nombre_conocido(tmp_path):
    write(
        tmp_path,
        "frontend/package.json",
        json.dumps({"scripts": {"dev": "next dev"}, "dependencies": {"next": "^15"}}),
    )
    assert detect.detect(tmp_path).services["frontend"].command == "npm run dev"


def test_nest_usa_start_dev(tmp_path):
    write(
        tmp_path,
        "apps/api/package.json",
        json.dumps(
            {
                "scripts": {"start": "nest start", "start:dev": "nest start --watch"},
                "devDependencies": {"@nestjs/cli": "^10"},
            }
        ),
    )
    assert detect.detect(tmp_path).services["api"].command == "npm run start:dev"


def test_una_libreria_del_workspace_no_es_un_servicio(tmp_path):
    write(
        tmp_path,
        "packages/ui/package.json",
        json.dumps({"scripts": {"dev": "tsc --watch"}, "devDependencies": {"typescript": "^5"}}),
    )
    assert detect.detect(tmp_path) is None, "un tsc --watch nunca abre un puerto"


def test_la_raiz_le_gana_a_las_subcarpetas(tmp_path):
    write(tmp_path, "package.json", json.dumps({"scripts": {"dev": "turbo dev"}}))
    write(
        tmp_path,
        "apps/web/package.json",
        json.dumps({"scripts": {"dev": "vite"}, "devDependencies": {"vite": "^5"}}),
    )

    stack = detect.detect(tmp_path)

    assert list(stack.services) == ["web"]
    assert stack.services["web"].command == "npm run dev"
    assert stack.services["web"].cwd == tmp_path, "el orquestador de la raiz arranca todo"


def test_varios_frontends_del_workspace(tmp_path):
    for name in ("admin", "tienda"):
        write(
            tmp_path,
            f"apps/{name}/package.json",
            json.dumps({"scripts": {"dev": "vite"}, "devDependencies": {"vite": "^5"}}),
        )
    assert sorted(detect.detect(tmp_path).services) == ["admin", "tienda"]


def test_el_contenedor_le_gana_a_la_subcarpeta(tmp_path):
    write(tmp_path, "compose.yaml", "services:\n  web:\n    image: nginx\n    ports: ['8080:80']\n")
    write(
        tmp_path,
        "apps/web/package.json",
        json.dumps({"scripts": {"dev": "vite"}, "devDependencies": {"vite": "^5"}}),
    )

    stack = detect.detect(tmp_path)

    assert list(stack.services) == ["web"]
    assert stack.services["web"].command == "docker compose up -d web"


def test_el_archivo_gana_sobre_la_deteccion(tmp_path):
    write(tmp_path, "package.json", json.dumps({"scripts": {"dev": "vite"}}))
    write(tmp_path, "stack.yaml", "services:\n  solo:\n    command: echo hola\n")

    stack = detect.stack_for(tmp_path)
    assert not stack.detected
    assert list(stack.services) == ["solo"]


def test_stack_yaml_invalido_no_cae_en_la_deteccion(tmp_path):
    write(tmp_path, "package.json", json.dumps({"scripts": {"dev": "vite"}}))
    write(tmp_path, "stack.yaml", "services: {}\n")

    with pytest.raises(config.ConfigError):
        detect.stack_for(tmp_path)


def test_to_yaml_vuelve_a_cargar_igual(tmp_path):
    write(tmp_path, "compose.yaml", "services:\n  db:\n    image: postgres\n    ports: ['5433:5432']\n")
    write(tmp_path, "package.json", json.dumps({"scripts": {"dev": "vite"}}))
    detected = detect.detect(tmp_path)

    write(tmp_path, "stack.yaml", detect.to_yaml(detected))
    reloaded = config.load(tmp_path / "stack.yaml")

    assert {n: (s.command, s.port, s.ready, s.needs, s.detached)
            for n, s in reloaded.services.items()} == {
        n: (s.command, s.port, s.ready, s.needs, s.detached)
        for n, s in detected.services.items()
    }


# ready: listen ------------------------------------------------------------

SERVER = (
    "import socket, time; "
    "s = socket.socket(); s.bind(('127.0.0.1', {port})); s.listen(); "
    "time.sleep(120)"
)


def test_listen_descubre_el_puerto_del_proceso(tmp_path, free_ports):
    (port,) = free_ports(1)
    stack = _stack(
        tmp_path,
        f"""
        services:
          web:
            command: {sys.executable} -c "{SERVER.format(port=port)}"
            ready: listen
        """,
    )

    engine = runner.Runner(stack, console=Console(file=io.StringIO()), timeout=20.0)
    try:
        engine.up()
        proc = engine.procs[0]
        assert proc.ready
        assert proc.port == port, "el puerto sale del proceso, no de la config"
        assert proc.known_port == port
    finally:
        engine.down()


def test_listen_con_puerto_declarado_es_error(tmp_path):
    with pytest.raises(config.ConfigError, match="listen"):
        _stack(
            tmp_path,
            """
            services:
              web:
                command: echo hola
                port: 3000
                ready: listen
            """,
        )


def test_listening_sin_proceso_devuelve_none():
    assert ports.listening(2**31 - 1) is None


def test_detect_package_manager_field(tmp_path):
    (tmp_path / "package.json").write_text(
        '{"scripts": {"dev": "vite"}, "packageManager": "pnpm@9.0.0"}', encoding="utf-8"
    )
    stack = detect.detect(tmp_path)
    assert stack is not None
    assert stack.services["web"].command == "pnpm run dev"


def _stack(tmp_path, body):
    path = tmp_path / "stack.yaml"
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return config.load(path)


COMPOSE_CON_PERFILES = """
    services:
      db:
        image: postgres
        ports: ["5432:5432"]
      api:
        image: api
        ports: ["8080:8080"]
        depends_on: [db]
      seed:
        image: seed
        profiles: [tools]
      mailhog:
        image: mailhog
        profiles: ["dev"]
    """


def test_un_contenedor_con_perfil_no_arranca_por_defecto(tmp_path):
    """En compose, `profiles:` excluye. En PortMaster un perfil es una lista de
    lo que se arranca. Traducirlos al reves arranca lo que compose apaga."""
    write(tmp_path, "compose.yaml", COMPOSE_CON_PERFILES)
    stack = detect.detect(tmp_path)

    por_defecto = [s.name for s in stack.resolve()]
    assert por_defecto == ["db", "api"]
    assert "seed" not in por_defecto
    assert "mailhog" not in por_defecto


def test_cada_perfil_del_compose_es_un_perfil(tmp_path):
    write(tmp_path, "compose.yaml", COMPOSE_CON_PERFILES)
    stack = detect.detect(tmp_path)

    assert sorted(stack.profiles) == ["dev", "tools"]
    # Un perfil arranca lo de siempre mas lo suyo, igual que `--profile` en compose.
    assert [s.name for s in stack.resolve("tools")] == ["db", "api", "seed"]
    assert [s.name for s in stack.resolve("dev")] == ["db", "api", "mailhog"]


def test_un_perfil_como_string_suelto_tambien_cuenta(tmp_path):
    write(
        tmp_path,
        "compose.yaml",
        """
        services:
          db:
            image: postgres
          seed:
            image: seed
            profiles: tools
        """,
    )
    stack = detect.detect(tmp_path)
    assert [s.name for s in stack.resolve()] == ["db"]
    assert "tools" in stack.profiles


def test_el_frontend_no_espera_a_un_contenedor_opcional(tmp_path):
    """Si heredara la cadena entera, el orden topologico arrastraria el
    contenedor con perfil de vuelta al arranque por defecto."""
    write(tmp_path, "compose.yaml", COMPOSE_CON_PERFILES)
    write(tmp_path, "package.json", json.dumps({"scripts": {"dev": "vite"}, "dependencies": {"vite": "5"}}))

    stack = detect.detect(tmp_path)
    assert "seed" not in stack.services["web"].needs
    assert "mailhog" not in stack.services["web"].needs
    assert [s.name for s in stack.resolve()] == ["db", "api", "web"]


def test_un_compose_sin_perfiles_arranca_todo(tmp_path):
    write(
        tmp_path,
        "compose.yaml",
        """
        services:
          db:
            image: postgres
          api:
            image: api
        """,
    )
    stack = detect.detect(tmp_path)
    assert stack.profiles == {}
    assert stack.default is None, "sin perfiles, el default sigue siendo todo"
    assert len(stack.resolve()) == 2


def test_congelar_un_compose_con_perfiles_no_cambia_lo_que_arranca(tmp_path):
    """`portmaster init` tiene que ser fiel: el archivo congelado arranca lo
    mismo que la deteccion, ni un contenedor mas."""
    write(tmp_path, "compose.yaml", COMPOSE_CON_PERFILES)
    detectado = detect.detect(tmp_path)

    write(tmp_path, "stack.yaml", detect.to_yaml(detectado))
    cargado = config.load(tmp_path / "stack.yaml")

    assert [s.name for s in cargado.resolve()] == [s.name for s in detectado.resolve()]
    assert cargado.profiles == detectado.profiles
    assert [s.name for s in cargado.resolve("tools")] == ["db", "api", "seed"]


# go y rust ----------------------------------------------------------------


def test_go_con_framework(tmp_path):
    write(tmp_path, "go.mod", "module ejemplo\n\nrequire github.com/gin-gonic/gin v1.9.1\n")
    write(tmp_path, "main.go", "package main\n\nfunc main() {}\n")

    stack = detect.detect(tmp_path)
    assert stack.services["api"].command == "go run ."
    assert stack.services["api"].ready == "listen"


def test_go_con_solo_la_stdlib(tmp_path):
    """net/http no aparece en go.mod: la llamada en el fuente es la unica senal."""
    write(tmp_path, "go.mod", "module ejemplo\n\ngo 1.22\n")
    write(
        tmp_path,
        "main.go",
        """
        package main

        import "net/http"

        func main() { http.ListenAndServe(":8080", nil) }
        """,
    )
    assert detect.detect(tmp_path).services["api"].command == "go run ."


def test_go_que_no_sirve_nada_no_se_detecta(tmp_path):
    """Una herramienta de linea de comandos: arrancarla esperaria un puerto que
    nunca abre, hasta el timeout."""
    write(tmp_path, "go.mod", "module herramienta\n\ngo 1.22\n")
    write(tmp_path, "main.go", 'package main\n\nfunc main() { println("hola") }\n')
    assert detect.detect(tmp_path) is None


def test_go_en_cmd(tmp_path):
    write(tmp_path, "go.mod", "module ejemplo\n\nrequire github.com/go-chi/chi/v5 v5.0.0\n")
    write(tmp_path, "cmd/server/main.go", "package main\n\nfunc main() {}\n")
    assert detect.detect(tmp_path).services["api"].command == "go run ./cmd/server"


def test_go_en_subcarpeta_de_backend(tmp_path):
    write(tmp_path, "backend/go.mod", "module api\n\nrequire github.com/gin-gonic/gin v1.9.1\n")
    write(tmp_path, "backend/main.go", "package main\n\nfunc main() {}\n")

    servicio = detect.detect(tmp_path).services["backend"]
    assert servicio.command == "go run ."
    assert servicio.cwd == tmp_path.resolve() / "backend"


def test_rust_con_framework(tmp_path):
    write(tmp_path, "Cargo.toml", '[dependencies]\naxum = "0.7"\n')
    write(tmp_path, "src/main.rs", "fn main() {}\n")

    stack = detect.detect(tmp_path)
    assert stack.services["api"].command == "cargo run"
    assert stack.services["api"].ready == "listen"


def test_rust_sin_framework_no_se_detecta(tmp_path):
    write(tmp_path, "Cargo.toml", '[dependencies]\nclap = "4"\n')
    write(tmp_path, "src/main.rs", "fn main() {}\n")
    assert detect.detect(tmp_path) is None


def test_rust_libreria_no_se_detecta(tmp_path):
    """Sin src/main.rs no hay binario que arrancar, aunque dependa de hyper."""
    write(tmp_path, "Cargo.toml", '[dependencies]\nhyper = "1"\n')
    write(tmp_path, "src/lib.rs", "pub fn nada() {}\n")
    assert detect.detect(tmp_path) is None


def test_el_frontend_espera_al_backend_de_go(tmp_path):
    write(tmp_path, "go.mod", "module ejemplo\n\nrequire github.com/gin-gonic/gin v1.9.1\n")
    write(tmp_path, "main.go", "package main\n\nfunc main() {}\n")
    write(
        tmp_path,
        "frontend/package.json",
        json.dumps({"scripts": {"dev": "vite"}, "devDependencies": {"vite": "^5"}}),
    )

    stack = detect.detect(tmp_path)
    assert stack.services["frontend"].needs == ("api",)


# rails y laravel ----------------------------------------------------------


def test_rails(tmp_path):
    write(tmp_path, "Gemfile", 'source "https://rubygems.org"\ngem "rails"\n')
    write(tmp_path, "config/application.rb", "module App\nend\n")

    stack = detect.detect(tmp_path)
    assert stack.services["api"].command == "bundle exec rails server"
    assert stack.services["api"].ready == "listen"


def test_una_gema_no_es_una_app_de_rails(tmp_path):
    """Gemfile lo tiene cualquier proyecto Ruby. config/application.rb no."""
    write(tmp_path, "Gemfile", 'source "https://rubygems.org"\ngem "rails"\n')
    write(tmp_path, "lib/mi_gema.rb", "module MiGema\nend\n")
    assert detect.detect(tmp_path) is None


def test_laravel(tmp_path):
    write(tmp_path, "artisan", "#!/usr/bin/env php\n")
    write(tmp_path, "composer.json", json.dumps({"require": {"laravel/framework": "^11"}}))

    stack = detect.detect(tmp_path)
    assert stack.services["api"].command == "php artisan serve"
    assert stack.services["api"].ready == "listen"


def test_composer_sin_artisan_no_es_laravel(tmp_path):
    write(tmp_path, "composer.json", json.dumps({"require": {"monolog/monolog": "^3"}}))
    assert detect.detect(tmp_path) is None


def test_laravel_con_su_frontend(tmp_path):
    """El stack tipico de Laravel: artisan y vite en la misma raiz."""
    write(tmp_path, "artisan", "#!/usr/bin/env php\n")
    write(tmp_path, "composer.json", json.dumps({"require": {"laravel/framework": "^11"}}))
    write(
        tmp_path,
        "package.json",
        json.dumps({"scripts": {"dev": "vite"}, "devDependencies": {"vite": "^5"}}),
    )

    stack = detect.detect(tmp_path)
    assert stack.services["api"].command == "php artisan serve"
    assert stack.services["web"].needs == ("api",)


def test_rails_en_subcarpeta_de_backend(tmp_path):
    write(tmp_path, "backend/Gemfile", 'source "https://rubygems.org"\n')
    write(tmp_path, "backend/config/application.rb", "module App\nend\n")

    servicio = detect.detect(tmp_path).services["backend"]
    assert servicio.command == "bundle exec rails server"
    assert servicio.cwd == tmp_path.resolve() / "backend"
