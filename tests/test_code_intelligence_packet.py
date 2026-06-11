"""
test_code_intelligence_packet.py — Tests for gen_code_intelligence_packet.py utilities.

Covers:
- Output normalization (path replacement, timing removal, HuggingFace noise filtering)
- Known-answer validation (passes with expected file; raises KnownAnswerError otherwise)
- Packet JSON schema validation
- Check-mode diff detection
- Public-safety rejection
- Fixture project creation and cleanup

Tests do NOT run the full CLI or mining pipeline — they exercise the pure
utility functions from the script directly.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ── Load the script as a module ────────────────────────────────────────────────
# The script lives under scripts/, not mempalace_code/, so load it by path.

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
_SCRIPT_PATH = _SCRIPTS_DIR / "gen_code_intelligence_packet.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("gen_packet", _SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_PKT = _load_script()


# ── normalize_output ───────────────────────────────────────────────────────────


class TestNormalizeOutput:
    def test_replaces_fixture_dir(self):
        text = "  Source: /tmp/fixture_abc123/src/auth.py"
        result = _PKT.normalize_output(text, "/tmp/fixture_abc123", "/tmp/palace_xyz")
        assert "<FIXTURE_DIR>/src/auth.py" in result
        assert "/tmp/fixture_abc123" not in result

    def test_replaces_palace_dir(self):
        text = "  Palace: /tmp/palace_xyz"
        result = _PKT.normalize_output(text, "/tmp/fixture_abc", "/tmp/palace_xyz")
        assert "<PALACE_DIR>" in result
        assert "/tmp/palace_xyz" not in result

    def test_removes_inline_timing(self):
        text = "  >> Embedding batch 1 (47 chunks)... done (2.1s)"
        result = _PKT.normalize_output(text, "/tmp/f", "/tmp/p")
        assert "2.1s" not in result
        assert "(<TIMING>)" in result

    def test_removes_elapsed_timing(self):
        text = "  Time: 0m 5s"
        result = _PKT.normalize_output(text, "/tmp/f", "/tmp/p")
        assert "0m 5s" not in result
        assert "<TIMING>" in result

    def test_removes_loading_embedding_model_line(self):
        text = "  Loading embedding model...\n  Model ready.\n  Files: 5"
        result = _PKT.normalize_output(text, "/tmp/f", "/tmp/p")
        assert "Loading embedding model" not in result
        assert "Model ready" not in result
        assert "Files: 5" in result

    def test_removes_hf_progress_bar(self):
        text = "  Loading weights: 100%|████████| 103/103 [00:00<00:00]\n  Palace: <PALACE_DIR>"
        result = _PKT.normalize_output(text, "/tmp/f", "/tmp/p")
        assert "Loading weights:" not in result
        assert "Palace:" in result

    def test_batch_count_normalized(self):
        text = ">> Embedding batch 1 (47 chunks)... done (1.9s)"
        result = _PKT.normalize_output(text, "/tmp/f", "/tmp/p")
        assert "47" not in result
        assert "<COUNT>" in result

    def test_no_change_on_clean_output(self):
        text = "  Wing: calcdemo\n  Rooms: backend, general\n  Files: 5"
        result = _PKT.normalize_output(text, "/no/match", "/no/match2")
        assert result == text.rstrip()

    def test_both_paths_replaced_in_same_line(self):
        text = "Source: /tmp/fix/src/auth.py  Palace: /tmp/pal"
        result = _PKT.normalize_output(text, "/tmp/fix", "/tmp/pal")
        assert "<FIXTURE_DIR>" in result
        assert "<PALACE_DIR>" in result
        assert "/tmp/fix" not in result
        assert "/tmp/pal" not in result

    def test_trailing_whitespace_stripped(self):
        text = "  Wing: calcdemo   \n  Files: 5   "
        result = _PKT.normalize_output(text, "/f", "/p")
        for line in result.split("\n"):
            assert line == line.rstrip(), f"Trailing whitespace on line: {line!r}"


# ── check_known_answer ─────────────────────────────────────────────────────────


class TestCheckKnownAnswer:
    _BASE_RESULT = {
        "query": "hash password",
        "filters": {},
        "results": [
            {
                "source_file": "/tmp/fixture/src/auth.py",
                "symbol_name": "hash_password",
                "similarity": 0.91,
            },
            {
                "source_file": "/tmp/fixture/src/models.py",
                "symbol_name": "User",
                "similarity": 0.75,
            },
            {
                "source_file": "/tmp/fixture/docs/architecture.md",
                "symbol_name": "",
                "similarity": 0.60,
            },
        ],
    }

    def test_passes_when_file_in_top_n(self):
        _PKT.check_known_answer(self._BASE_RESULT, "auth.py", "hash password", top_n=3)

    def test_passes_when_file_is_second_hit(self):
        _PKT.check_known_answer(self._BASE_RESULT, "models.py", "test", top_n=3)

    def test_raises_when_file_not_in_top_n(self):
        with pytest.raises(_PKT.KnownAnswerError) as exc_info:
            _PKT.check_known_answer(self._BASE_RESULT, "calculator.py", "fibonacci", top_n=3)
        assert "calculator.py" in str(exc_info.value)
        assert "fibonacci" in str(exc_info.value)

    def test_raises_when_results_empty(self):
        empty = {"query": "x", "filters": {}, "results": []}
        with pytest.raises(_PKT.KnownAnswerError):
            _PKT.check_known_answer(empty, "auth.py", "x")

    def test_top_n_1_only_checks_first_result(self):
        _PKT.check_known_answer(self._BASE_RESULT, "auth.py", "x", top_n=1)
        with pytest.raises(_PKT.KnownAnswerError):
            _PKT.check_known_answer(self._BASE_RESULT, "models.py", "x", top_n=1)

    def test_fragment_match_not_exact(self):
        result = {
            "query": "x",
            "filters": {},
            "results": [
                {
                    "source_file": "/tmp/fixture/src/auth.py",
                    "symbol_name": "verify_password",
                    "similarity": 0.88,
                },
            ],
        }
        _PKT.check_known_answer(result, "auth.py", "x", top_n=3)

    def test_error_message_lists_actual_hits(self):
        with pytest.raises(_PKT.KnownAnswerError) as exc_info:
            _PKT.check_known_answer(self._BASE_RESULT, "missing.py", "q")
        err = str(exc_info.value)
        assert "auth.py" in err or "models.py" in err


# ── validate_packet_schema ─────────────────────────────────────────────────────


def _minimal_valid_packet() -> dict:
    return {
        "schema_version": 1,
        "generated_from": "scripts/gen_code_intelligence_packet.py",
        "fixture": {
            "description": "test fixture",
            "wing": "calcdemo",
            "files": ["src/auth.py"],
            "mine_summary": {"wing": "calcdemo", "files_processed": 1, "drawers_filed": 3},
        },
        "exhibits": {
            "mine_output": "=====\n  Done.\n=====",
            "search_queries": [
                {
                    "label": "test",
                    "query": "hash password",
                    "command": "mempalace-code search ...",
                    "expected_file": "auth.py",
                    "top_hits": [
                        {
                            "source_file": "<FIXTURE_DIR>/src/auth.py",
                            "symbol_name": "hash_password",
                            "similarity": 0.91,
                        }
                    ],
                    "output": "  [1] calcdemo / backend",
                }
            ],
            "read_exhibit": {
                "command": "mempalace-code read ...",
                "output": "     1: def hash_password(...)",
            },
            "mcp_exhibit": {
                "initialize": {
                    "request": {"jsonrpc": "2.0", "id": 1, "method": "initialize"},
                    "response": {"jsonrpc": "2.0", "id": 1, "result": {}},
                },
                "tools_list": {
                    "request": {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                    "response": {"jsonrpc": "2.0", "id": 2, "result": {"tools": []}},
                },
                "code_search": {
                    "request": {"jsonrpc": "2.0", "id": 3, "method": "tools/call"},
                    "response": {"jsonrpc": "2.0", "id": 3, "result": {}},
                },
            },
        },
        "owner_acceptance": {
            "checklist": [
                {
                    "id": "OA-1",
                    "label": "fixture_determinism",
                    "description": "Fixture files are static.",
                    "evidence_keys": ["fixture.files"],
                },
                {
                    "id": "OA-2",
                    "label": "json_markdown_parity",
                    "description": "JSON and Markdown match.",
                    "evidence_keys": ["exhibits.search_queries[*].label"],
                },
                {
                    "id": "OA-3",
                    "label": "mcp_stdio_provenance",
                    "description": "MCP exhibit from real subprocess.",
                    "evidence_keys": ["exhibits.mcp_exhibit.initialize"],
                },
            ]
        },
    }


class TestValidatePacketSchema:
    def test_valid_packet_has_no_errors(self):
        errors = _PKT.validate_packet_schema(_minimal_valid_packet())
        assert errors == []

    def test_missing_schema_version(self):
        p = _minimal_valid_packet()
        del p["schema_version"]
        errors = _PKT.validate_packet_schema(p)
        assert any("schema_version" in e for e in errors)

    def test_wrong_schema_version(self):
        p = _minimal_valid_packet()
        p["schema_version"] = 99
        errors = _PKT.validate_packet_schema(p)
        assert any("schema_version" in e for e in errors)

    def test_missing_generated_from(self):
        p = _minimal_valid_packet()
        del p["generated_from"]
        errors = _PKT.validate_packet_schema(p)
        assert any("generated_from" in e for e in errors)

    def test_empty_fixture_files(self):
        p = _minimal_valid_packet()
        p["fixture"]["files"] = []
        errors = _PKT.validate_packet_schema(p)
        assert any("files" in e for e in errors)

    def test_missing_mcp_exhibit_key(self):
        p = _minimal_valid_packet()
        del p["exhibits"]["mcp_exhibit"]["initialize"]
        errors = _PKT.validate_packet_schema(p)
        assert any("initialize" in e for e in errors)

    def test_missing_read_exhibit(self):
        p = _minimal_valid_packet()
        del p["exhibits"]["read_exhibit"]
        errors = _PKT.validate_packet_schema(p)
        assert any("read_exhibit" in e for e in errors)

    def test_empty_search_queries(self):
        p = _minimal_valid_packet()
        p["exhibits"]["search_queries"] = []
        errors = _PKT.validate_packet_schema(p)
        assert any("search_queries" in e for e in errors)


# ── _compare_packets ───────────────────────────────────────────────────────────


class TestComparePackets:
    def test_identical_packets_return_empty_diffs(self):
        p = _minimal_valid_packet()
        diffs = _PKT._compare_packets(p, p)
        assert diffs == []

    def test_scalar_value_differs(self):
        p = _minimal_valid_packet()
        q = _minimal_valid_packet()
        q["fixture"]["mine_summary"]["drawers_filed"] = 99
        diffs = _PKT._compare_packets(p, q)
        assert any("drawers_filed" in d for d in diffs)

    def test_missing_key_in_committed(self):
        p = _minimal_valid_packet()
        q = _minimal_valid_packet()
        del q["generated_from"]
        diffs = _PKT._compare_packets(p, q)
        assert any("generated_from" in d for d in diffs)

    def test_extra_key_in_committed(self):
        p = _minimal_valid_packet()
        q = _minimal_valid_packet()
        q["extra_field"] = "unexpected"
        diffs = _PKT._compare_packets(p, q)
        assert any("extra_field" in d for d in diffs)

    def test_list_length_differs(self):
        p = _minimal_valid_packet()
        q = _minimal_valid_packet()
        q["fixture"]["files"].append("extra.py")
        diffs = _PKT._compare_packets(p, q)
        assert any("files" in d for d in diffs)

    def test_float_close_values_are_equal(self):
        diffs = _PKT._compare_packets(0.91, 0.909)
        assert diffs == []

    def test_float_far_values_differ(self):
        diffs = _PKT._compare_packets(0.91, 0.50)
        assert len(diffs) == 1


# ── _public_safety_check ───────────────────────────────────────────────────────


class TestPublicSafetyCheck:
    def test_passes_on_clean_text(self):
        _PKT._public_safety_check("Source: <FIXTURE_DIR>/src/auth.py\nPalace: <PALACE_DIR>")

    def test_rejects_macos_home_path(self):
        with pytest.raises(_PKT.PublicSafetyError):
            _PKT._public_safety_check("Source: /Users/alice/projects/auth.py")

    def test_rejects_linux_home_path(self):
        with pytest.raises(_PKT.PublicSafetyError):
            _PKT._public_safety_check("Palace: /home/bob/.mempalace/palace")

    def test_rejects_root_home(self):
        with pytest.raises(_PKT.PublicSafetyError):
            _PKT._public_safety_check("Config: /root/.mempalace/config.json")

    def test_placeholder_paths_are_safe(self):
        text = '{"source_file": "<FIXTURE_DIR>/src/auth.py", "palace": "<PALACE_DIR>"}'
        _PKT._public_safety_check(text)

    def test_rejects_windows_user_path(self):
        with pytest.raises(_PKT.PublicSafetyError):
            _PKT._public_safety_check("Path: C:\\Users\\alice\\palace")


# ── Fixture creation and cleanup ───────────────────────────────────────────────


class TestFixtureCreation:
    def test_creates_all_expected_files(self, tmp_path):
        fixture_dir = tmp_path / "fixture"
        fixture_dir.mkdir()
        _PKT.create_fixture_project(fixture_dir)

        expected = sorted(_PKT._FIXTURE_FILES.keys())
        for rel in expected:
            assert (fixture_dir / rel).exists(), f"Missing fixture file: {rel}"

    def test_python_files_are_syntactically_valid(self, tmp_path):
        import ast

        fixture_dir = tmp_path / "fixture"
        fixture_dir.mkdir()
        _PKT.create_fixture_project(fixture_dir)

        for rel, content in _PKT._FIXTURE_FILES.items():
            if rel.endswith(".py"):
                try:
                    ast.parse(content)
                except SyntaxError as exc:
                    pytest.fail(f"Syntax error in fixture {rel}: {exc}")

    def test_fixture_files_are_deterministic(self, tmp_path):
        d1 = tmp_path / "f1"
        d2 = tmp_path / "f2"
        d1.mkdir()
        d2.mkdir()
        _PKT.create_fixture_project(d1)
        _PKT.create_fixture_project(d2)

        for rel in _PKT._FIXTURE_FILES:
            assert (d1 / rel).read_text() == (d2 / rel).read_text(), (
                f"Fixture file {rel} is not deterministic"
            )

    def test_fixture_contains_polyglot_files(self):
        extensions = {Path(k).suffix for k in _PKT._FIXTURE_FILES}
        assert ".py" in extensions, "Should have Python files"
        assert ".md" in extensions, "Should have Markdown files"
        assert ".yaml" in extensions, "Should have YAML files"


# ── Known-answer query catalog ─────────────────────────────────────────────────


class TestKnownAnswerCatalog:
    def test_catalog_has_five_or_more_queries(self):
        assert len(_PKT.KNOWN_ANSWER_QUERIES) >= 5

    def test_each_entry_has_three_fields(self):
        for entry in _PKT.KNOWN_ANSWER_QUERIES:
            assert len(entry) == 3, f"Expected 3-tuple, got: {entry}"
            query, expected_file, label = entry
            assert isinstance(query, str)
            assert query
            assert isinstance(expected_file, str)
            assert expected_file
            assert isinstance(label, str)
            assert label

    def test_expected_files_exist_in_fixture(self):
        fixture_files_flat = " ".join(_PKT._FIXTURE_FILES.keys())
        for _, expected_file, _ in _PKT.KNOWN_ANSWER_QUERIES:
            # Each expected file fragment should appear in at least one fixture file path.
            assert expected_file in fixture_files_flat, (
                f"Expected file {expected_file!r} not found in fixture files"
            )

    def test_labels_are_unique(self):
        labels = [label for _, _, label in _PKT.KNOWN_ANSWER_QUERIES]
        assert len(labels) == len(set(labels)), "Duplicate labels in KNOWN_ANSWER_QUERIES"


# ── Render functions (smoke) ───────────────────────────────────────────────────


class TestRenderFunctions:
    def test_render_json_is_valid_json(self):
        p = _minimal_valid_packet()
        js = _PKT.render_json(p)
        parsed = json.loads(js)
        assert parsed["schema_version"] == 1

    def test_render_markdown_contains_key_sections(self):
        p = _minimal_valid_packet()
        md = _PKT.render_markdown(p)
        assert "# Code-Intelligence Demo Packet" in md
        assert "## 1. Fixture Inventory" in md
        assert "## 2. Known-Answer Search Queries" in md
        assert "## 3. Source Slice" in md
        assert "## 4. MCP stdio Exhibit" in md

    def test_render_markdown_no_absolute_paths(self):
        p = _minimal_valid_packet()
        md = _PKT.render_markdown(p)
        # No /tmp or /Users paths should appear in the rendered Markdown.
        assert "/tmp/" not in md
        assert "/Users/" not in md
        assert "/home/" not in md

    def test_render_json_sorted_keys(self):
        p = _minimal_valid_packet()
        js = _PKT.render_json(p)
        # JSON produced with sort_keys=True — verify top-level keys are sorted.
        parsed_keys = list(json.loads(js).keys())
        assert parsed_keys == sorted(parsed_keys)


# ── _public_safety_check — extended path and token coverage ───────────────────


class TestPublicSafetyCheckExtended:
    def test_rejects_tmp_path(self):
        with pytest.raises(_PKT.PublicSafetyError):
            _PKT._public_safety_check("Source: /tmp/leak/path.txt")

    def test_rejects_srv_path(self):
        with pytest.raises(_PKT.PublicSafetyError):
            _PKT._public_safety_check("Repo: /srv/private/repo/file.py")

    def test_rejects_openai_api_key(self):
        with pytest.raises(_PKT.PublicSafetyError):
            _PKT._public_safety_check("key=sk-" + "a" * 20)

    def test_rejects_github_personal_access_token(self):
        with pytest.raises(_PKT.PublicSafetyError):
            _PKT._public_safety_check("token=ghp_" + "a" * 20)

    def test_rejects_anthropic_api_key(self):
        with pytest.raises(_PKT.PublicSafetyError):
            _PKT._public_safety_check("key=sk-ant-api03-" + "a" * 16)

    def test_placeholder_tmp_context_does_not_trip_on_fixture_dir(self):
        # After normalization, paths become <FIXTURE_DIR>/... — no /tmp/ remains.
        _PKT._public_safety_check("<FIXTURE_DIR>/src/auth.py")

    def test_short_sk_prefix_is_not_rejected(self):
        # 'sk-' + fewer than 20 alphanumeric chars must not match (not a real token).
        _PKT._public_safety_check("sk-short")


# ── _run_cli returncode handling ───────────────────────────────────────────────


class TestRunCliReturncode:
    def test_raises_on_nonzero_exit(self):
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = "partial output"
        mock_result.stderr = "error: something went wrong"

        with patch("subprocess.run", return_value=mock_result):
            with pytest.raises(RuntimeError, match="exit 1"):
                _PKT._run_cli(["search", "query"])

    def test_returns_stdout_on_zero_exit(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "search output here"
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result):
            result = _PKT._run_cli(["search", "query"])

        assert "search output here" in result


# ── _mcp_exchange response validation ─────────────────────────────────────────


class TestMcpExchangeValidation:
    _GOOD_RESPONSES = [
        {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2024-11-05"}},
        {"jsonrpc": "2.0", "id": 2, "result": {"tools": []}},
        {"jsonrpc": "2.0", "id": 3, "result": {"content": []}},
    ]

    def _mock_proc(self, returncode=0, responses=None):
        mock = MagicMock()
        mock.returncode = returncode
        if responses is None:
            responses = self._GOOD_RESPONSES
        mock.stdout = "\n".join(json.dumps(r) for r in responses) + "\n"
        mock.stderr = ""
        return mock

    def test_raises_on_nonzero_mcp_process_exit(self, tmp_path):
        palace_dir = tmp_path / "palace"
        palace_dir.mkdir()

        with patch("subprocess.run", return_value=self._mock_proc(returncode=1)):
            with pytest.raises(RuntimeError, match="exit.*1"):
                _PKT._mcp_exchange(palace_dir)

    def test_raises_on_error_response(self, tmp_path):
        palace_dir = tmp_path / "palace"
        palace_dir.mkdir()
        bad_responses = [
            {"jsonrpc": "2.0", "id": 1, "result": {}},
            {"jsonrpc": "2.0", "id": 2, "result": {"tools": []}},
            {"jsonrpc": "2.0", "id": 3, "error": {"code": -32601, "message": "Method not found"}},
        ]

        with patch("subprocess.run", return_value=self._mock_proc(responses=bad_responses)):
            with pytest.raises(RuntimeError, match="JSON-RPC error"):
                _PKT._mcp_exchange(palace_dir)

    def test_raises_on_id_mismatch(self, tmp_path):
        palace_dir = tmp_path / "palace"
        palace_dir.mkdir()
        bad_responses = [
            {"jsonrpc": "2.0", "id": 99, "result": {}},  # wrong id
            {"jsonrpc": "2.0", "id": 2, "result": {"tools": []}},
            {"jsonrpc": "2.0", "id": 3, "result": {}},
        ]

        with patch("subprocess.run", return_value=self._mock_proc(responses=bad_responses)):
            with pytest.raises(RuntimeError, match="id mismatch"):
                _PKT._mcp_exchange(palace_dir)

    def test_raises_on_extra_mcp_response(self, tmp_path):
        """Four responses with three requests should fail, not silently truncate."""
        palace_dir = tmp_path / "palace"
        palace_dir.mkdir()

        extra_responses = list(self._GOOD_RESPONSES) + [{"jsonrpc": "2.0", "id": 4, "result": {}}]

        with patch("subprocess.run", return_value=self._mock_proc(responses=extra_responses)):
            with pytest.raises(RuntimeError, match="responses"):
                _PKT._mcp_exchange(palace_dir)


# ── Owner acceptance checklist ─────────────────────────────────────────────────


_DEMO_DIR = Path(__file__).resolve().parent.parent / "docs" / "demo"
_PACKET_JSON_PATH = _DEMO_DIR / "code-intelligence-packet.json"
_PACKET_MD_PATH = _DEMO_DIR / "code-intelligence-packet.md"


class TestOwnerAcceptanceChecklist:
    def test_committed_packet_artifacts_expose_owner_acceptance_checklist(self):
        """Committed JSON and Markdown both visibly expose checklist evidence."""
        data = json.loads(_PACKET_JSON_PATH.read_text(encoding="utf-8"))
        md = _PACKET_MD_PATH.read_text(encoding="utf-8")

        # JSON must carry the owner_acceptance key with required checklist ids.
        oa = data.get("owner_acceptance", {})
        checklist = oa.get("checklist", [])
        ids = {item["id"] for item in checklist}
        assert "OA-1" in ids, f"OA-1 missing from checklist ids: {ids}"
        assert "OA-2" in ids, f"OA-2 missing from checklist ids: {ids}"
        assert "OA-3" in ids, f"OA-3 missing from checklist ids: {ids}"

        labels = {item["label"] for item in checklist}
        assert "fixture_determinism" in labels
        assert "json_markdown_parity" in labels
        assert "mcp_stdio_provenance" in labels

        # Markdown must expose the same checklist labels for human review.
        assert "fixture_determinism" in md
        assert "json_markdown_parity" in md
        assert "mcp_stdio_provenance" in md

        # Markdown must show the MCP exhibit method/key names for provenance.
        assert "initialize" in md
        assert "tools_list" in md or "tools/list" in md
        assert "code_search" in md or "tools/call" in md

    def test_schema_rejects_missing_owner_acceptance_checklist(self):
        """validate_packet_schema fails when owner_acceptance is absent or checklist empty."""
        # Missing owner_acceptance key entirely.
        p = _minimal_valid_packet()
        del p["owner_acceptance"]
        errors = _PKT.validate_packet_schema(p)
        assert any("owner_acceptance" in e for e in errors), (
            f"Expected owner_acceptance error, got: {errors}"
        )

        # Empty checklist — should also fail.
        p2 = _minimal_valid_packet()
        p2["owner_acceptance"]["checklist"] = []
        errors2 = _PKT.validate_packet_schema(p2)
        assert any("checklist" in e for e in errors2), (
            f"Expected checklist error for empty list, got: {errors2}"
        )
