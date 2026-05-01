import tomllib
from pathlib import Path

from mempalace_code.mcp_server import handle_request


def _pyproject() -> dict:
    root = Path(__file__).resolve().parents[1]
    return tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))


def test_wheel_installs_only_mempalace_code_package():
    config = _pyproject()
    wheel_config = config["tool"]["hatch"]["build"]["targets"]["wheel"]

    assert wheel_config["packages"] == ["mempalace_code"]


def test_console_scripts_use_mempalace_code_namespace():
    config = _pyproject()

    assert config["project"]["scripts"]["mempalace-code"] == "mempalace_code:main"
    assert config["project"]["scripts"]["mempalace-code-alias"] == "mempalace_code.cli:main_alias"


def test_source_compat_mempalace_mcp_server_shim():
    import mempalace.mcp_server as legacy_mcp

    assert legacy_mcp.handle_request is handle_request
    response = legacy_mcp.handle_request({"method": "initialize", "id": 1, "params": {}})
    assert response["result"]["serverInfo"]["name"] == "mempalace-code"
