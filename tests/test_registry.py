
from portmaster import registry


def test_find_collisions(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "PROJECTS", tmp_path / "projects.json")

    p1 = tmp_path / "app1"
    p2 = tmp_path / "app2"
    p3 = tmp_path / "app3"
    p1.mkdir()
    p2.mkdir()
    p3.mkdir()

    (p1 / "stack.yaml").write_text("name: a1\nservices:\n  web:\n    command: echo 1\n    port: 3000\n", encoding="utf-8")
    (p2 / "stack.yaml").write_text("name: a2\nservices:\n  web:\n    command: echo 2\n    port: 3000\n", encoding="utf-8")
    (p3 / "stack.yaml").write_text("name: a3\nservices:\n  api:\n    command: echo 3\n    port: 8080\n", encoding="utf-8")

    registry.add(p1)
    registry.add(p2)
    registry.add(p3)

    collisions = registry.find_collisions()
    assert 3000 in collisions
    assert set(collisions[3000]) == {p1.resolve(), p2.resolve()}
    assert 8080 not in collisions


def _proyecto(raiz, nombre, comando):
    root = raiz / nombre
    root.mkdir()
    (root / "stack.yaml").write_text(
        f"services:\n  srv:\n    command: {comando}\n", encoding="utf-8"
    )
    return root


def test_registrar_un_proyecto_con_docker_se_ve_ya_mismo(tmp_path, monkeypatch):
    """Registrar es una accion explicita y su efecto no espera al TTL.

    `_save` ya invalidaba el cache de puertos por este motivo; el de Docker se
    sumo despues y quedo afuera de esa linea. El sintoma: agregabas un proyecto
    con contenedores y la fila de Docker tardaba hasta 30s en aparecer. En la
    suite se veia como un test que pasa solo y falla acompanado, que es la forma
    en que un cache global sin invalidar se delata.
    """
    monkeypatch.setattr(registry, "HOME", tmp_path / "home")
    monkeypatch.setattr(registry, "PROJECTS", tmp_path / "home" / "projects.json")

    registry.add(_proyecto(tmp_path, "simple", "echo hola"))
    assert registry.any_uses_docker(max_age=30.0) is False

    registry.add(_proyecto(tmp_path, "condocker", "docker compose up -d db"))
    assert registry.any_uses_docker(max_age=30.0) is True, "el cache no se invalido al registrar"
