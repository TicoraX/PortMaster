import json
import textwrap

from portmaster import mcp


def test_mcp_initialize():
    req = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    res = mcp.handle_request(req)
    assert res["id"] == 1
    assert res["result"]["serverInfo"]["name"] == "portmaster"
    assert "tools" in res["result"]["capabilities"]


def test_mcp_tools_list():
    req = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
    res = mcp.handle_request(req)
    tool_names = [t["name"] for t in res["result"]["tools"]]
    assert "portmaster_status" in tool_names
    assert "portmaster_doctor" in tool_names
    assert "portmaster_ports" in tool_names
    assert "portmaster_run" in tool_names
    assert "portmaster_clean" in tool_names


def test_mcp_tool_call_status(tmp_path):
    body = """
    name: mcp-test
    services:
      web:
        command: echo web
        port: 3000
    scripts:
      test: echo ok
    """
    (tmp_path / "stack.yaml").write_text(textwrap.dedent(body), encoding="utf-8")

    req = {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {
            "name": "portmaster_status",
            "arguments": {"path": str(tmp_path)},
        },
    }
    res = mcp.handle_request(req)
    assert res["id"] == 3
    assert not res.get("isError")
    content = json.loads(res["result"]["content"][0]["text"])
    assert content["project_name"] == "mcp-test"
    assert content["services"][0]["name"] == "web"
    assert content["services"][0]["port"] == 3000
    assert "test" in content["scripts"]


def test_mcp_tool_call_run(tmp_path):
    flag = tmp_path / "mcp_flag.txt"
    body = f"""
    name: mcp-run-test
    services:
      web:
        command: echo web
    scripts:
      touch: python -c "import pathlib; pathlib.Path(r'{flag}').write_text('mcp_ok')"
    """
    (tmp_path / "stack.yaml").write_text(textwrap.dedent(body), encoding="utf-8")

    req = {
        "jsonrpc": "2.0",
        "id": 4,
        "method": "tools/call",
        "params": {
            "name": "portmaster_run",
            "arguments": {"script": "touch", "path": str(tmp_path)},
        },
    }
    res = mcp.handle_request(req)
    assert not res.get("isError")
    assert "finalizado con código de salida 0" in res["result"]["content"][0]["text"]
    assert flag.exists()
    assert flag.read_text() == "mcp_ok"


def test_mcp_unknown_method():
    req = {"jsonrpc": "2.0", "id": 5, "method": "unsupported", "params": {}}
    res = mcp.handle_request(req)
    assert res["error"]["code"] == -32601
