"""Focused tests for the packaged Agent Plugins 1.0.0 directory."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

from jsonschema import Draft202012Validator

from mempalace_code.agent_plugins import (
    MCP_JSON,
    MCP_SCHEMA_ID,
    PLUGIN_JSON,
    PLUGIN_SCHEMA_ID,
    REQUIRED_AGENT_PLUGIN_MEMBERS,
    SKILL_PATH,
    get_agent_plugin_member,
    get_agent_plugin_root,
    load_mcp_json,
    load_plugin_json,
)
from mempalace_code.mcp_tool_profiles import PROFILES

ROOT = Path(__file__).resolve().parents[1]
MINIMAL_TOOLS = (
    "mempalace_status",
    "mempalace_search",
    "mempalace_check_duplicate",
    "mempalace_add_drawer",
)


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _mcp_server_config() -> dict:
    config = load_mcp_json()
    return config["mcpServers"]["mempalace-code"]


def _run_launcher_stdio(requests: list[dict], tmp_path: Path) -> list[dict]:
    stdin_data = "\n".join(json.dumps(request) for request in requests) + "\n"
    env = os.environ.copy()
    env["HOME"] = str(tmp_path / "home")
    env["USERPROFILE"] = str(tmp_path / "home")
    env["HF_HUB_OFFLINE"] = "1"
    env["TRANSFORMERS_OFFLINE"] = "1"
    cmd = [sys.executable, "-m", "mempalace_code.mcp_launcher", *_mcp_server_config()["args"]]
    result = subprocess.run(
        cmd,
        input=stdin_data,
        capture_output=True,
        text=True,
        timeout=60,
        cwd=str(ROOT),
        env=env,
    )
    assert result.returncode == 0, result.stderr

    responses: list[dict] = []
    for line in result.stdout.splitlines():
        if line.strip():
            responses.append(json.loads(line))
    return responses


class TestAgentPluginLayout:
    def test_installed_plugin_root_contains_fixed_locations(self):
        root = get_agent_plugin_root()

        assert root.is_dir()
        assert (root / PLUGIN_JSON).is_file()
        assert (root / MCP_JSON).is_file()
        assert (root / SKILL_PATH).is_file()
        for member in REQUIRED_AGENT_PLUGIN_MEMBERS:
            relative = Path(member).relative_to("mempalace_code/agent_plugin")
            assert get_agent_plugin_member(relative).is_file()


class TestAgentPluginSchemas:
    def test_manifests_validate_against_vendored_schemas(self):
        root = get_agent_plugin_root()
        plugin_schema = _read_json(root / "schemas" / "1.0.0" / "plugin.schema.json")
        mcp_schema = _read_json(root / "schemas" / "1.0.0" / "mcp.schema.json")
        plugin_json = load_plugin_json()
        mcp_json = load_mcp_json()

        assert plugin_json["$schema"] == PLUGIN_SCHEMA_ID
        assert mcp_json["$schema"] == MCP_SCHEMA_ID
        assert plugin_schema["$id"] == PLUGIN_SCHEMA_ID
        assert mcp_schema["$id"] == MCP_SCHEMA_ID
        Draft202012Validator(plugin_schema).validate(plugin_json)
        Draft202012Validator(mcp_schema).validate(mcp_json)

    def test_plugin_version_matches_project_version(self):
        pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        project_version = pyproject["project"]["version"]

        plugin_json = load_plugin_json()

        assert plugin_json["version"] == project_version

    def test_schema_notice_names_source_license_and_ids(self):
        notice = (get_agent_plugin_root() / "schemas" / "SCHEMA-NOTICE.md").read_text(
            encoding="utf-8"
        )

        assert "agentplugins/agent-plugins-spec" in notice
        assert "Apache License 2.0" in notice
        assert PLUGIN_SCHEMA_ID in notice
        assert MCP_SCHEMA_ID in notice


class TestAgentPluginMCP:
    def test_mcp_json_stdio_launcher_is_portable(self):
        server = _mcp_server_config()

        assert server == {
            "type": "stdio",
            "command": "mempalace-code-mcp",
            "args": ["--profile=minimal"],
        }
        assert not Path(server["command"]).is_absolute()
        assert "/" not in server["command"]
        assert "\\" not in server["command"]
        assert " " not in server["command"]
        assert server["command"] not in {"python", "python3", "pip", "pipx", "uv", "uvx", "npx"}
        assert "env" not in server
        assert "cwd" not in server

        pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        scripts = pyproject["project"]["scripts"]
        assert scripts["mempalace-code-mcp"] == "mempalace_code.mcp_launcher:main"

    def test_declared_mcp_command_lists_minimal_tools(self, tmp_path):
        responses = _run_launcher_stdio(
            [
                {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            ],
            tmp_path,
        )

        assert responses[0]["result"]["serverInfo"]["name"] == "mempalace-code"
        tool_names = [tool["name"] for tool in responses[1]["result"]["tools"]]
        assert len(tool_names) == len(set(tool_names)), f"duplicate tool names: {tool_names}"
        assert set(tool_names) == set(MINIMAL_TOOLS) == PROFILES["minimal"]

    def test_disabled_tool_reports_profile_error(self, tmp_path):
        responses = _run_launcher_stdio(
            [
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": "mempalace_delete_wing", "arguments": {}},
                }
            ],
            tmp_path,
        )

        error = responses[0]["error"]
        assert error["code"] == -32601
        assert "not enabled" in error["message"]
        assert "active MCP profile" in error["message"]


class TestAgentPluginSkill:
    def test_skill_front_matter_and_minimal_tool_drift(self):
        skill = (get_agent_plugin_root() / SKILL_PATH).read_text(encoding="utf-8")

        assert skill.startswith("---\n")
        front_matter = skill.split("---", 2)[1]
        assert "name: mempalace" in front_matter
        assert "description:" in front_matter
        mentioned_tools = set(re.findall(r"mempalace_\w+", skill))
        assert mentioned_tools == PROFILES["minimal"]
        assert len(skill.splitlines()) <= 55

    def test_skill_contains_search_write_secret_and_deletion_guards(self):
        skill = (get_agent_plugin_root() / SKILL_PATH).read_text(encoding="utf-8").lower()

        for term in ("search", "duplicate", "verbatim", "secret", "remove"):
            assert term in skill
        for forbidden in (
            "mempalace_kg_",
            "mempalace_code_",
            "mempalace_diary_",
            "mempalace_delete_",
            "mempalace_mine",
            "mempalace_read",
        ):
            assert forbidden not in skill


class TestAgentPluginSafety:
    def test_plugin_paths_stay_within_root(self):
        root = get_agent_plugin_root().resolve()

        for member in REQUIRED_AGENT_PLUGIN_MEMBERS:
            relative = Path(member).relative_to("mempalace_code/agent_plugin")
            member_path = get_agent_plugin_member(relative).resolve()
            member_path.relative_to(root)

    def test_plugin_metadata_contains_no_secrets_or_private_paths(self):
        plugin_json = load_plugin_json()
        mcp_json = load_mcp_json()
        combined = json.dumps({"plugin": plugin_json, "mcp": mcp_json}, sort_keys=True)

        assert not re.search(
            r"token|secret|password|credential|private_key|api_key", combined, re.I
        )
        assert "/Users/" not in combined
        assert "/home/" not in combined
        assert "git@" not in combined
        assert "://" not in _mcp_server_config()["command"]
