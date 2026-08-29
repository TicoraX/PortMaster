import pytest

from portmaster import guardrails


def test_validate_identifier_valid():
    assert guardrails.validate_identifier("proj123") == "proj123"
    assert guardrails.validate_identifier("my-cool_project") == "my-cool_project"


def test_validate_identifier_invalid():
    with pytest.raises(guardrails.GuardrailError):
        guardrails.validate_identifier("../evil")
    with pytest.raises(guardrails.GuardrailError):
        guardrails.validate_identifier("proj/sub")
    with pytest.raises(guardrails.GuardrailError):
        guardrails.validate_identifier("")
    with pytest.raises(guardrails.GuardrailError):
        guardrails.validate_identifier("CON")
    with pytest.raises(guardrails.GuardrailError):
        guardrails.validate_identifier("NUL")
    with pytest.raises(guardrails.GuardrailError):
        guardrails.validate_identifier("a" * 65)


def test_check_command_safe():
    ok, _ = guardrails.check_command("npm run build")
    assert ok is True
    ok, _ = guardrails.check_command("pytest -v tests")
    assert ok is True


def test_check_command_blocks_destructive():
    ok, reason = guardrails.check_command("rm -rf /")
    assert ok is False
    assert "destructivo" in reason

    ok, _ = guardrails.check_command("rm -r -f /")
    assert ok is False

    ok, _ = guardrails.check_command('rm -rf "/"')
    assert ok is False

    ok, _ = guardrails.check_command("rm -rf -- /")
    assert ok is False

    ok, _ = guardrails.check_command('rm -rf -- "$HOME"')
    assert ok is False

    ok, _ = guardrails.check_command("rm -rf ~")
    assert ok is False

    ok, _ = guardrails.check_command("rd /s /q C:\\")
    assert ok is False

    ok, _ = guardrails.check_command("del /s /q C:\\*")
    assert ok is False

    ok, _ = guardrails.check_command("Remove-Item -Recurse -Force C:\\")
    assert ok is False

    ok, _ = guardrails.check_command("format C:")
    assert ok is False

    ok, _ = guardrails.check_command("DROP DATABASE production")
    assert ok is False


def test_assert_safe_command_raises():
    with pytest.raises(guardrails.GuardrailError):
        guardrails.assert_safe_command("rm -rf /")
    with pytest.raises(guardrails.GuardrailError):
        guardrails.assert_safe_command('rm -rf -- "$HOME"')
