import json
import re
from importlib import metadata
from pathlib import Path
from urllib.parse import unquote, urlparse

import pytest

from mempalace_code import __version__
from mempalace_code.mcp_server import handle_request

ROOT = Path(__file__).resolve().parents[1]


def _expected_version() -> str:
    pyproject = ROOT / "pyproject.toml"
    content = pyproject.read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', content, re.MULTILINE)
    assert match is not None, "Could not find project version in pyproject.toml"
    return match.group(1)


def _checkout_install_version() -> str | None:
    """Return the installed metadata version when that install was made from this checkout."""
    try:
        distribution = metadata.distribution("mempalace-code")
    except metadata.PackageNotFoundError:
        return None
    url = urlparse(json.loads(distribution.read_text("direct_url.json") or "{}").get("url", ""))
    if url.scheme != "file" or Path(unquote(url.path)).resolve() != ROOT:
        return None
    return distribution.version


def test_package_version_matches_pyproject():
    assert __version__ == _expected_version()


def test_checkout_install_metadata_matches_pyproject():
    """version.py reads pyproject.toml in a checkout; the install record is the independent source."""
    installed = _checkout_install_version()
    if installed is None:
        pytest.skip("mempalace-code metadata was not installed from this checkout")
    assert installed == _expected_version(), (
        f"installed metadata is {installed}; reinstall this checkout: "
        "python -m pip install -e '.[dev]'"
    )


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
