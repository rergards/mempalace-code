import re
from pathlib import Path

from mempalace_code import __version__
from mempalace_code.mcp_server import handle_request


def _expected_version() -> str:
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    content = pyproject.read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', content, re.MULTILINE)
    assert match is not None, "Could not find project version in pyproject.toml"
    return match.group(1)


def test_package_version_matches_pyproject():
    assert __version__ == _expected_version()


def test_mcp_initialize_reports_package_version():
    response = handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    assert response["result"]["serverInfo"]["version"] == _expected_version()  # type: ignore[reportOptionalSubscript]  # reason: handle_request always returns a dict for valid requests; None only for notifications


def test_mcp_discover_reports_package_version():
    """AC-6: the modern server/discover result stamps the same package version as legacy initialize."""
    response = handle_request(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "server/discover",
            "params": {
                "_meta": {
                    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
                    "io.modelcontextprotocol/clientInfo": {"name": "pytest", "version": "1.0"},
                    "io.modelcontextprotocol/clientCapabilities": {},
                }
            },
        }
    )
    server_info = response["result"]["_meta"]["io.modelcontextprotocol/serverInfo"]  # type: ignore[reportOptionalSubscript]  # reason: handle_request always returns a dict for valid requests; None only for notifications
    assert server_info["version"] == _expected_version()
    assert server_info["name"] == "mempalace-code"
