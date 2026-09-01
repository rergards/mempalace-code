import json
import os
import subprocess
import sys
import tomllib
import zipfile
from email.parser import Parser
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from mempalace_code.mcp_server import handle_request
from mempalace_code.version import __version__

_MODERN_META = {
    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
    "io.modelcontextprotocol/clientInfo": {"name": "pytest-client", "version": "1.0"},
    "io.modelcontextprotocol/clientCapabilities": {},
}


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


def test_overrides_is_one_direct_unmarked_runtime_requirement_in_project_lock_and_wheel(
    tmp_path,
):
    root = Path(__file__).resolve().parents[1]
    config = _pyproject()
    project_requirements = [Requirement(value) for value in config["project"]["dependencies"]]
    project_overrides = [
        requirement
        for requirement in project_requirements
        if canonicalize_name(requirement.name) == "overrides"
    ]

    assert len(project_overrides) == 1
    assert str(project_overrides[0].specifier) == ">=7.7"
    assert project_overrides[0].marker is None

    lock = tomllib.loads((root / "uv.lock").read_text(encoding="utf-8"))
    root_packages = [
        package
        for package in lock["package"]
        if package["name"] == "mempalace-code" and package.get("source") == {"editable": "."}
    ]
    assert len(root_packages) == 1
    root_package = root_packages[0]
    assert [row for row in root_package["dependencies"] if row["name"] == "overrides"] == [
        {"name": "overrides"}
    ]
    assert [
        row for row in root_package["metadata"]["requires-dist"] if row["name"] == "overrides"
    ] == [{"name": "overrides", "specifier": ">=7.7"}]

    locked_overrides = [package for package in lock["package"] if package["name"] == "overrides"]
    assert len(locked_overrides) == 1
    assert locked_overrides[0]["version"] == "7.7.0"

    build = subprocess.run(
        [
            sys.executable,
            "-m",
            "build",
            "--wheel",
            "--outdir",
            str(tmp_path),
            str(root),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert build.returncode == 0, f"stdout: {build.stdout!r}\nstderr: {build.stderr!r}"

    wheels = list(tmp_path.glob("mempalace_code-*.whl"))
    assert len(wheels) == 1
    with zipfile.ZipFile(wheels[0]) as archive:
        metadata_members = [
            name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
        ]
        assert len(metadata_members) == 1
        metadata = Parser().parsestr(archive.read(metadata_members[0]).decode("utf-8"))

    wheel_requirements = [Requirement(value) for value in metadata.get_all("Requires-Dist", [])]
    wheel_overrides = [
        requirement
        for requirement in wheel_requirements
        if canonicalize_name(requirement.name) == "overrides"
    ]
    assert len(wheel_overrides) == 1
    assert str(wheel_overrides[0].specifier) == ">=7.7"
    assert wheel_overrides[0].marker is None


def test_source_compat_mempalace_mcp_server_shim():
    import mempalace.mcp_server as legacy_mcp

    assert legacy_mcp.handle_request is handle_request
    response = legacy_mcp.handle_request({"method": "initialize", "id": 1, "params": {}})
    assert response["result"]["serverInfo"]["name"] == "mempalace-code"  # type: ignore[reportOptionalSubscript]  # reason: handle_request always returns a dict for valid requests; None only for notifications


def test_source_compat_shim_supports_modern_discover():
    """AC-4/INV-6: the source-checkout shim speaks 2026-07-28 server/discover too, via the same handle_request."""
    import mempalace.mcp_server as legacy_mcp

    response = legacy_mcp.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "server/discover",
            "params": {"_meta": dict(_MODERN_META)},
        }
    )
    server_info = response["result"]["_meta"]["io.modelcontextprotocol/serverInfo"]  # type: ignore[reportOptionalSubscript]  # reason: handle_request always returns a dict for valid requests; None only for notifications
    assert server_info == {"name": "mempalace-code", "version": __version__}


def test_both_entrypoints_serve_initialize_and_discover_over_real_stdio(tmp_path):
    """AC-4: python -m mempalace_code.mcp_server and python -m mempalace.mcp_server both keep
    working unchanged for local stdio registrations, for both the legacy and modern dialect."""
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "server/discover",
            "params": {"_meta": dict(_MODERN_META)},
        },
    ]
    stdin_data = "\n".join(json.dumps(r) for r in requests) + "\n"
    root = Path(__file__).resolve().parents[1]

    for module in ("mempalace_code.mcp_server", "mempalace.mcp_server"):
        palace_dir = tmp_path / module.replace(".", "_") / "palace"
        home_dir = tmp_path / module.replace(".", "_") / "home"
        palace_dir.mkdir(parents=True)
        home_dir.mkdir(parents=True)

        env = os.environ.copy()
        env["MEMPALACE_PALACE_PATH"] = str(palace_dir)
        env["HOME"] = str(home_dir)
        env["USERPROFILE"] = str(home_dir)
        env["HF_HUB_OFFLINE"] = "1"
        env["TRANSFORMERS_OFFLINE"] = "1"

        result = subprocess.run(
            [sys.executable, "-m", module],
            input=stdin_data,
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(root),
            env=env,
        )
        assert result.returncode == 0, (
            f"{module} exited {result.returncode}\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )
        responses = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
        assert len(responses) == 2, f"{module}: stdout={result.stdout!r} stderr={result.stderr!r}"

        assert responses[0]["result"]["serverInfo"] == {
            "name": "mempalace-code",
            "version": __version__,
        }
        assert responses[1]["result"]["_meta"]["io.modelcontextprotocol/serverInfo"] == {
            "name": "mempalace-code",
            "version": __version__,
        }
