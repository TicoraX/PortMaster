import sys
import textwrap

import pytest

from portmaster import config, scripts
from portmaster.config import ConfigError


def test_scripts_parsing_simple_and_pipeline(tmp_path):
    body = """
    services:
      srv:
        command: echo srv
    scripts:
      test: pytest tests/
      lint: ruff check .
      check: [lint, test]
    """
    path = tmp_path / "stack.yaml"
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    stack = config.load(path)

    assert stack.scripts["test"] == ("pytest tests/",)
    assert stack.scripts["lint"] == ("ruff check .",)
    assert stack.scripts["check"] == ("lint", "test")


def test_scripts_parsing_invalido(tmp_path):
    path = tmp_path / "stack.yaml"

    # scripts no es un mapa
    path.write_text("services:\n  srv:\n    command: echo\nscripts: [1, 2]", encoding="utf-8")
    with pytest.raises(ConfigError, match="'scripts' debe ser un mapa"):
        config.load(path)

    # script vacio
    path.write_text("services:\n  srv:\n    command: echo\nscripts:\n  vacio: ''", encoding="utf-8")
    with pytest.raises(ConfigError, match="no puede estar vacio"):
        config.load(path)


def test_run_script_exitoso(tmp_path):
    flag = tmp_path / "flag.txt"
    body = f"""
    services:
      srv:
        command: echo srv
    scripts:
      create: {sys.executable} -c "import pathlib; pathlib.Path(r'{flag}').write_text('ok')"
    """
    path = tmp_path / "stack.yaml"
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    stack = config.load(path)

    code = scripts.run_script(stack, "create")
    assert code == 0
    assert flag.exists()
    assert flag.read_text() == "ok"


def test_run_script_con_extra_args(tmp_path):
    out = tmp_path / "args.txt"
    body = f"""
    services:
      srv:
        command: echo srv
    scripts:
      echo_args: {sys.executable} -c "import sys, pathlib; pathlib.Path(r'{out}').write_text(' '.join(sys.argv[1:]))"
    """
    path = tmp_path / "stack.yaml"
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    stack = config.load(path)

    code = scripts.run_script(stack, "echo_args", extra_args=["--foo", "bar"])
    assert code == 0
    assert out.exists()
    assert out.read_text() == "--foo bar"


def test_run_script_falla_y_aborta_pipeline(tmp_path):
    step2_flag = tmp_path / "step2.txt"
    body = f"""
    services:
      srv:
        command: echo srv
    scripts:
      failing_pipeline:
        - {sys.executable} -c "raise SystemExit(3)"
        - {sys.executable} -c "import pathlib; pathlib.Path(r'{step2_flag}').write_text('reached')"
    """
    path = tmp_path / "stack.yaml"
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    stack = config.load(path)

    code = scripts.run_script(stack, "failing_pipeline")
    assert code == 3
    assert not step2_flag.exists()


def test_run_script_desconocido(tmp_path):
    body = """
    services:
      srv:
        command: echo srv
    scripts:
      test: echo test
    """
    path = tmp_path / "stack.yaml"
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    stack = config.load(path)

    with pytest.raises(ConfigError, match="script desconocido: 'inexistente'"):
        scripts.run_script(stack, "inexistente")
