
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
