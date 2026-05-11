"""
test_mcp_registry.py — Registry integrity tests for the MCP module split.

Covers:
  - Exact 28-tool order (AC-1): mempalace_status through mempalace_diary_read.
  - Family disjointness: no tool name appears in more than one family spec.
  - Duplicate-name rejection: _build_tools raises on duplicate.
  - Schema shape: each entry has description, input_schema, handler.
  - mcp_server compatibility re-exports: TOOLS/handle_request/main all resolve.
  - AC-4: hidden profile tool returns -32601 with profile-disabled message.
  - AC-5/AC-6: argument validation and unknown-tool error distinction.
"""

import pytest

# ── Canonical tool order (AC-1) ──────────────────────────────────────────────

_EXPECTED_ORDER = [
    # read family
    "mempalace_status",
    "mempalace_list_wings",
    "mempalace_list_rooms",
    "mempalace_get_taxonomy",
    # kg family
    "mempalace_kg_query",
    "mempalace_kg_add",
    "mempalace_kg_invalidate",
    "mempalace_kg_timeline",
    "mempalace_kg_stats",
    # architecture family
    "mempalace_find_implementations",
    "mempalace_find_references",
    "mempalace_show_project_graph",
    "mempalace_show_type_dependencies",
    "mempalace_explain_subsystem",
    "mempalace_extract_reusable",
    # graph family
    "mempalace_traverse",
    "mempalace_find_tunnels",
    "mempalace_graph_stats",
    # search family
    "mempalace_search",
    "mempalace_code_search",
    "mempalace_file_context",
    "mempalace_check_duplicate",
    # write family
    "mempalace_add_drawer",
    "mempalace_delete_drawer",
    "mempalace_delete_wing",
    "mempalace_mine",
    # diary family
    "mempalace_diary_write",
    "mempalace_diary_read",
]


class TestRegistryOrder:
    def test_tool_count_is_28(self):
        from mempalace_code.mcp.registry import TOOLS

        assert len(TOOLS) == 28, f"Expected 28 tools, got {len(TOOLS)}: {list(TOOLS)}"

    def test_exact_insertion_order(self):
        from mempalace_code.mcp.registry import TOOLS

        assert list(TOOLS) == _EXPECTED_ORDER

    def test_all_expected_names_present(self):
        from mempalace_code.mcp.registry import TOOLS

        missing = [n for n in _EXPECTED_ORDER if n not in TOOLS]
        assert not missing, f"Missing tools: {missing}"

    def test_registry_via_mcp_server_shim(self):
        """mcp_server.TOOLS must be the same object as mcp.registry.TOOLS."""
        from mempalace_code.mcp.registry import TOOLS as registry_tools
        from mempalace_code.mcp_server import TOOLS as shim_tools

        assert shim_tools is registry_tools


class TestSchemaShape:
    def test_all_entries_have_required_keys(self):
        from mempalace_code.mcp.registry import TOOLS

        for name, spec in TOOLS.items():
            assert "description" in spec, f"{name}: missing 'description'"
            assert "input_schema" in spec, f"{name}: missing 'input_schema'"
            assert "handler" in spec, f"{name}: missing 'handler'"
            assert callable(spec["handler"]), f"{name}: handler is not callable"
            assert isinstance(spec["description"], str), f"{name}: description is not str"
            assert isinstance(spec["input_schema"], dict), f"{name}: input_schema is not dict"

    def test_input_schema_has_type_object(self):
        from mempalace_code.mcp.registry import TOOLS

        for name, spec in TOOLS.items():
            schema = spec["input_schema"]
            assert schema.get("type") == "object", f"{name}: input_schema.type != 'object'"


class TestFamilyDisjointness:
    def test_no_duplicate_names_across_families(self):
        """Each family TOOL_SPECS must have disjoint keys."""
        from mempalace_code.mcp.tools.architecture import TOOL_SPECS as arch
        from mempalace_code.mcp.tools.diary import TOOL_SPECS as diary
        from mempalace_code.mcp.tools.graph import TOOL_SPECS as graph
        from mempalace_code.mcp.tools.kg import TOOL_SPECS as kg
        from mempalace_code.mcp.tools.read import TOOL_SPECS as read
        from mempalace_code.mcp.tools.search import TOOL_SPECS as search
        from mempalace_code.mcp.tools.write import TOOL_SPECS as write

        families = [
            ("read", read),
            ("kg", kg),
            ("architecture", arch),
            ("graph", graph),
            ("search", search),
            ("write", write),
            ("diary", diary),
        ]

        seen: dict = {}
        for family_name, specs in families:
            for tool_name in specs:
                if tool_name in seen:
                    pytest.fail(
                        f"Tool {tool_name!r} appears in both {seen[tool_name]!r} and {family_name!r}"
                    )
                seen[tool_name] = family_name

    def test_build_tools_rejects_duplicate(self):
        """_build_tools raises ValueError if two families share a name."""
        from mempalace_code.mcp.registry import _build_tools

        family_a = {
            "mempalace_status": {"description": "a", "input_schema": {}, "handler": lambda: None}
        }
        family_b = {
            "mempalace_status": {"description": "b", "input_schema": {}, "handler": lambda: None}
        }

        with pytest.raises(ValueError, match="Duplicate"):
            _build_tools(family_a, family_b)


class TestCompatibilityReExports:
    def test_mcp_server_exports_handle_request(self):
        from mempalace_code.mcp_server import handle_request

        assert callable(handle_request)

    def test_mcp_server_exports_main(self):
        from mempalace_code.mcp_server import main

        assert callable(main)

    def test_mcp_server_exports_tools(self):
        from mempalace_code.mcp_server import TOOLS

        assert isinstance(TOOLS, dict)
        assert len(TOOLS) == 28

    def test_mcp_package_exports_stable_surface(self):
        from mempalace_code.mcp import TOOLS, handle_request, main

        assert callable(handle_request)
        assert callable(main)
        assert isinstance(TOOLS, dict)

    def test_tool_get_aaak_spec_exported_from_shim(self):
        """tool_get_aaak_spec is a non-registry helper; must still be importable from mcp_server."""
        from mempalace_code.mcp_server import tool_get_aaak_spec

        result = tool_get_aaak_spec()
        assert "aaak_spec" in result
        assert "AAAK" in result["aaak_spec"]


class TestDispatchBehavior:
    def test_ac4_hidden_profile_tool_returns_profile_disabled_error(self):
        """AC-4: tool hidden by active profile returns -32601 with 'not enabled' message."""
        from mempalace_code.mcp_server import TOOLS, handle_request

        # Build a minimal registry that excludes mempalace_delete_wing
        minimal_registry = {k: v for k, v in TOOLS.items() if k != "mempalace_delete_wing"}

        resp = handle_request(
            {
                "method": "tools/call",
                "id": 1,
                "params": {"name": "mempalace_delete_wing", "arguments": {}},
            },
            active_registry=minimal_registry,
        )
        assert resp is not None
        assert resp["error"]["code"] == -32601
        assert "not enabled" in resp["error"]["message"]
        assert "active MCP profile" in resp["error"]["message"]

    def test_ac6_truly_unknown_tool_returns_unknown_tool_error(self):
        """AC-6: tool that doesn't exist in TOOLS at all returns 'Unknown tool' message."""
        from mempalace_code.mcp_server import TOOLS, handle_request

        # Build registry that excludes a tool — but call a name that is NOT in TOOLS at all
        minimal_registry = {k: v for k, v in TOOLS.items() if k != "mempalace_delete_wing"}

        resp = handle_request(
            {
                "method": "tools/call",
                "id": 2,
                "params": {"name": "mempalace_does_not_exist", "arguments": {}},
            },
            active_registry=minimal_registry,
        )
        assert resp is not None
        assert resp["error"]["code"] == -32601
        assert "Unknown tool" in resp["error"]["message"]

    def test_ac5_non_object_arguments_returns_invalid_params(self):
        """AC-5: non-object arguments returns -32602."""
        from mempalace_code.mcp_server import handle_request

        resp = handle_request(
            {
                "method": "tools/call",
                "id": 3,
                "params": {"name": "mempalace_status", "arguments": ["not", "a", "dict"]},
            }
        )
        assert resp is not None
        assert resp["error"]["code"] == -32602
        assert "arguments must be an object" in resp["error"]["message"]
