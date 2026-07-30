import textwrap

import pytest

from portmaster import config

VALID = """
name: demo

services:
  db:
    command: docker compose up -d postgres
    port: 5432
    detached: true
  api:
    command: npm run dev
    cwd: backend
    port: 8080
    needs: [db]
    env:
      DATABASE_URL: postgres://localhost:5432/app
      WORKERS: 4
  web:
    command: npm run dev
    port: 3000
    needs: [api]

profiles:
  backend: [api]
  db-only: [db]
"""


def write(tmp_path, body, **dirs):
    (tmp_path / "backend").mkdir(exist_ok=True)
    for name in dirs:
        (tmp_path / name).mkdir(exist_ok=True)
    path = tmp_path / "stack.yaml"
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return path


def test_carga_completa(tmp_path):
    stack = config.load(write(tmp_path, VALID))

    assert stack.name == "demo"
    assert set(stack.services) == {"db", "api", "web"}
    assert stack.ports() == [5432, 8080, 3000]

    api = stack.services["api"]
    assert api.cwd == (tmp_path / "backend").resolve()
    assert api.needs == ("db",)
    assert api.env == {"DATABASE_URL": "postgres://localhost:5432/app", "WORKERS": "4"}
    assert api.ready == "port"       # default cuando hay puerto
    assert stack.services["db"].detached is True


def test_orden_topologico(tmp_path):
    stack = config.load(write(tmp_path, VALID))
    assert [s.name for s in stack.resolve()] == ["db", "api", "web"]


def test_perfil_arrastra_dependencias(tmp_path):
    stack = config.load(write(tmp_path, VALID))
    # El perfil lista solo 'api', pero sin 'db' arriba no sirve de nada.
    assert [s.name for s in stack.resolve("backend")] == ["db", "api"]
    assert [s.name for s in stack.resolve("db-only")] == ["db"]


def test_perfil_desconocido(tmp_path):
    stack = config.load(write(tmp_path, VALID))
    with pytest.raises(config.ConfigError, match="perfil desconocido"):
        stack.resolve("noexiste")


def test_ciclo_falla_al_cargar(tmp_path):
    body = """
    services:
      a:
        command: echo a
        needs: [b]
      b:
        command: echo b
        needs: [a]
    """
    with pytest.raises(config.ConfigError, match="circular"):
        config.load(write(tmp_path, body))


def test_cwd_no_puede_escapar_de_la_raiz(tmp_path):
    body = """
    services:
      api:
        command: echo hola
        cwd: ../../etc
    """
    with pytest.raises(config.ConfigError, match="sale de la raiz"):
        config.load(write(tmp_path, body))


def test_cwd_absoluto_rechazado(tmp_path):
    body = f"""
    services:
      api:
        command: echo hola
        cwd: {tmp_path.as_posix()}
    """
    with pytest.raises(config.ConfigError, match="relativa"):
        config.load(write(tmp_path, body))


def test_cwd_inexistente(tmp_path):
    body = """
    services:
      api:
        command: echo hola
        cwd: no-existe
    """
    with pytest.raises(config.ConfigError, match="no existe"):
        config.load(write(tmp_path, body))


@pytest.mark.parametrize(
    "body, mensaje",
    [
        ("services: {}", "services"),
        ("nombre: sin-servicios", "services"),
        ("services:\n  api:\n    port: 8080", "command"),
        ("services:\n  api:\n    command: ''", "command"),
        ("services:\n  api:\n    command: x\n    port: 70000", "port"),
        ("services:\n  api:\n    command: x\n    ready: port", "no hay 'port'"),
        ("services:\n  api:\n    command: x\n    ready: raro", "ready"),
        ("services:\n  api:\n    command: x\n    needs: [fantasma]", "no existe"),
        ("services:\n  api:\n    command: x\n    needs: [api]", "a si mismo"),
        ("services:\n  api:\n    command: x\n    detached: quizas", "detached"),
        ("services:\n  api:\n    command: x\n    typo: 1", "desconocidos"),
        ("services:\n  api:\n    command: x\n    env:\n      A: [1, 2]", "valor simple"),
        ("services:\n  api:\n    command: x\nprofiles:\n  p: [fantasma]", "no existe"),
        ("services:\n  api:\n    command: x\nprofiles:\n  p: []", "no vacia"),
        ("- solo\n- una\n- lista", "mapa"),
    ],
)
def test_configuraciones_invalidas(tmp_path, body, mensaje):
    with pytest.raises(config.ConfigError, match=mensaje):
        config.load(write(tmp_path, body))


def test_yaml_roto(tmp_path):
    with pytest.raises(config.ConfigError, match="no se pudo leer"):
        config.load(write(tmp_path, "services: [a: ]]"))


def test_find_sube_directorios(tmp_path):
    write(tmp_path, VALID)
    hondo = tmp_path / "backend" / "src" / "app"
    hondo.mkdir(parents=True)
    assert config.find(hondo) == (tmp_path / "stack.yaml").resolve()


def test_find_sin_archivo(tmp_path):
    with pytest.raises(config.ConfigError, match="no se encontro"):
        config.find(tmp_path)


def test_el_ejemplo_del_repo_es_valido(tmp_path):
    """stack.example.yaml es la especificacion publicada: tiene que cargar."""
    from pathlib import Path

    ejemplo = Path(__file__).parent.parent / "stack.example.yaml"
    (tmp_path / "backend").mkdir()
    (tmp_path / "frontend").mkdir()
    destino = tmp_path / "stack.yaml"
    destino.write_text(ejemplo.read_text(encoding="utf-8"), encoding="utf-8")

    stack = config.load(destino)
    assert [s.name for s in stack.resolve("fullstack")] == ["db", "api", "web"]
