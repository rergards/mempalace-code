"""Tests for docs/quality/autopilot-demo-gate-ledger.json.

Validates that:
1. The JSON ledger is well-formed and has the required schema fields.
2. Every archived AUTOPILOT-DEMO backlog item has a ledger entry.
3. Each entry has required fields: key, summary, status, commands, behavioral_evidence,
   enforcing_gate, and either (before + after) or gap_rationale.
4. The current task AUTOPILOT-DEMO-END-TO-END-GATE-CLOSURE is covered.
5. Enforcing gate commands are non-empty strings.
6. The Markdown ledger covers the same set of keys.

No subprocess calls, no network access, no palace imports.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).parent.parent
LEDGER_JSON = ROOT / "docs" / "quality" / "autopilot-demo-gate-ledger.json"
LEDGER_MD = ROOT / "docs" / "quality" / "autopilot-demo-gate-ledger.md"
BACKLOG_ARCHIVED = ROOT / "docs" / "BACKLOG-archived.yaml"
BACKLOG_ACTIVE = ROOT / "docs" / "BACKLOG.yaml"

# Every archived AUTOPILOT-DEMO key that the ledger must cover.
REQUIRED_ARCHIVED_KEYS = {
    "AUTOPILOT-DEMO-QUALITY-SCORECARD",
    "AUTOPILOT-DEMO-PUBLIC-SAFETY-GATE",
    "AUTOPILOT-DEMO-RUFF-RATCHET",
    "AUTOPILOT-DEMO-PYRIGHT-STRICT-SLICE",
    "AUTOPILOT-DEMO-WORKFLOW-REVIEW-PROTOCOL",
    "AUTOPILOT-DEMO-CODE-INTELLIGENCE-GOLDEN-PACKET",
    "AUTOPILOT-DEMO-CODE-INTELLIGENCE-PACKET-ACCEPTANCE-FIX",
    "AUTOPILOT-DEMO-PUBLIC-SAFETY-COMMITTED-MODE",
    "AUTOPILOT-DEMO-MCP-STDIO-CONTRACTS",
    "AUTOPILOT-DEMO-SCORECARD-METRIC-EXPANSION",
    "AUTOPILOT-DEMO-DOCS-DRIFT-GUARD",
    "AUTOPILOT-DEMO-CLI-GOLDEN-SCENARIOS",
    "AUTOPILOT-DEMO-SECURITY-BOUNDARY-TESTS",
    "AUTOPILOT-DEMO-ARCHITECTURE-GUARD",
    "AUTOPILOT-DEMO-PYRIGHT-STRICT-SLICE-EXPANSION",
    "AUTOPILOT-DEMO-PERF-BUDGETS",
    "AUTOPILOT-DEMO-WORKFLOW-EFFECTIVENESS-GUARD",
}

# The current task must also appear in the ledger.
CURRENT_TASK_KEY = "AUTOPILOT-DEMO-END-TO-END-GATE-CLOSURE"

VALID_STATUSES = {"pass", "gap", "in_progress"}


# ── Helpers ────────────────────────────────────────────────────────────────────


def _load_ledger() -> dict:
    assert LEDGER_JSON.exists(), f"Ledger not found: {LEDGER_JSON}"
    return json.loads(LEDGER_JSON.read_text(encoding="utf-8"))


# ── Schema tests ───────────────────────────────────────────────────────────────


def test_ledger_json_is_parseable():
    ledger = _load_ledger()
    assert isinstance(ledger, dict)
    assert "schema_version" in ledger, "ledger must have schema_version"
    assert "items" in ledger, "ledger must have items list"
    assert isinstance(ledger["items"], list)
    assert len(ledger["items"]) > 0, "ledger must have at least one item"


def test_ledger_schema_version_is_integer():
    ledger = _load_ledger()
    assert isinstance(ledger["schema_version"], int), "schema_version must be an integer"
    assert ledger["schema_version"] >= 1


# ── Coverage tests ─────────────────────────────────────────────────────────────


def test_all_archived_autopilot_demo_keys_are_covered():
    ledger = _load_ledger()
    present = {item["key"] for item in ledger["items"]}
    missing = REQUIRED_ARCHIVED_KEYS - present
    assert not missing, (
        f"Ledger is missing entries for archived AUTOPILOT-DEMO items: {sorted(missing)}"
    )


def test_current_task_is_covered():
    ledger = _load_ledger()
    keys = {item["key"] for item in ledger["items"]}
    assert CURRENT_TASK_KEY in keys, (
        f"Ledger must include an entry for the current task '{CURRENT_TASK_KEY}'"
    )


def test_no_duplicate_keys():
    ledger = _load_ledger()
    keys = [item["key"] for item in ledger["items"]]
    dupes = {k for k in keys if keys.count(k) > 1}
    assert not dupes, f"Ledger has duplicate keys: {sorted(dupes)}"


# ── Per-entry field validation ─────────────────────────────────────────────────


def test_every_item_has_required_fields():
    ledger = _load_ledger()
    required = {"key", "summary", "status", "commands", "behavioral_evidence", "enforcing_gate"}
    for item in ledger["items"]:
        missing = required - set(item.keys())
        assert not missing, (
            f"Item '{item.get('key', '?')}' is missing required fields: {sorted(missing)}"
        )


def test_every_item_has_before_after_or_gap_rationale():
    ledger = _load_ledger()
    for item in ledger["items"]:
        has_before_after = "before" in item and "after" in item
        has_gap = "gap_rationale" in item
        assert has_before_after or has_gap, (
            f"Item '{item['key']}' must have either (before + after) or gap_rationale"
        )


def test_every_item_status_is_valid():
    ledger = _load_ledger()
    for item in ledger["items"]:
        assert item["status"] in VALID_STATUSES, (
            f"Item '{item['key']}' has invalid status '{item['status']}'; "
            f"must be one of {sorted(VALID_STATUSES)}"
        )


def test_every_item_has_nonempty_commands():
    ledger = _load_ledger()
    for item in ledger["items"]:
        commands = item.get("commands", [])
        assert isinstance(commands, list), f"Item '{item['key']}' commands must be a list"
        assert len(commands) > 0, f"Item '{item['key']}' must have at least one command string"
        for cmd in commands:
            assert isinstance(cmd, str), f"Item '{item['key']}' command must be a string: {cmd!r}"
            assert cmd.strip(), f"Item '{item['key']}' has an empty command: {cmd!r}"


def test_every_item_has_nonempty_enforcing_gate():
    ledger = _load_ledger()
    for item in ledger["items"]:
        gate = item.get("enforcing_gate", "")
        assert isinstance(gate, str), f"Item '{item['key']}' enforcing_gate must be a string"
        assert gate.strip(), f"Item '{item['key']}' must have a non-empty enforcing_gate"


def test_every_item_has_nonempty_behavioral_evidence():
    ledger = _load_ledger()
    for item in ledger["items"]:
        evidence = item.get("behavioral_evidence", "")
        assert isinstance(evidence, str), (
            f"Item '{item['key']}' behavioral_evidence must be a string"
        )
        assert len(evidence.strip()) > 20, (
            f"Item '{item['key']}' has an empty or too-short behavioral_evidence"
        )


def test_every_item_has_nonempty_summary():
    ledger = _load_ledger()
    for item in ledger["items"]:
        summary = item.get("summary", "")
        assert isinstance(summary, str), f"Item '{item['key']}' summary must be a string"
        assert summary.strip(), f"Item '{item['key']}' has an empty summary"


# ── Archived key cross-check ────────────────────────────────────────────────────


def test_archived_backlog_keys_match_required_set():
    """Cross-check that the required keys match what's in BACKLOG-archived.yaml."""
    if not BACKLOG_ARCHIVED.exists():
        import pytest

        pytest.skip("BACKLOG-archived.yaml not present — skipping cross-check")

    content = BACKLOG_ARCHIVED.read_text(encoding="utf-8")
    for key in REQUIRED_ARCHIVED_KEYS:
        assert key in content, (
            f"Expected archived key '{key}' not found in BACKLOG-archived.yaml — "
            "update REQUIRED_ARCHIVED_KEYS if this item was renamed or removed"
        )


# ── Systemic BACKLOG.yaml parity ────────────────────────────────────────────────


def test_backlog_done_items_have_pass_status_in_ledger():
    """Every ledger-covered key marked 'done' in docs/BACKLOG.yaml must report status 'pass'.

    Guards against the ledger drifting to 'in_progress'/'gap' after the active
    backlog marks the same item complete (or vice versa).
    """
    if not BACKLOG_ACTIVE.exists():
        import pytest

        pytest.skip("BACKLOG.yaml not present — skipping cross-check")

    backlog = yaml.safe_load(BACKLOG_ACTIVE.read_text(encoding="utf-8"))
    items = backlog.get("items", []) if isinstance(backlog, dict) else []
    done_keys = {item["key"] for item in items if item.get("status") == "done"}

    ledger = _load_ledger()
    ledger_status_by_key = {item["key"]: item["status"] for item in ledger["items"]}

    mismatches = [
        f"{key} (ledger status: {ledger_status_by_key[key]!r})"
        for key in sorted(done_keys)
        if key in ledger_status_by_key and ledger_status_by_key[key] != "pass"
    ]
    assert not mismatches, (
        "docs/BACKLOG.yaml marks these keys done but the ledger disagrees: " + ", ".join(mismatches)
    )


# ── Markdown ledger parity ─────────────────────────────────────────────────────


def test_markdown_ledger_exists():
    assert LEDGER_MD.exists(), f"Markdown ledger not found: {LEDGER_MD}"


def test_markdown_ledger_covers_same_keys():
    ledger = _load_ledger()
    md_text = LEDGER_MD.read_text(encoding="utf-8")
    for item in ledger["items"]:
        key = item["key"]
        assert key in md_text, f"Markdown ledger does not mention key '{key}'"


def test_no_private_data_in_ledger_json():
    """The ledger must not contain absolute paths, tokens, or private remote URLs."""
    raw = LEDGER_JSON.read_text(encoding="utf-8")

    private_path_patterns = ["/Users/", "/home/", "/root/", "/tmp/autopilot"]
    for pattern in private_path_patterns:
        assert pattern not in raw, (
            f"Ledger JSON contains a private path pattern '{pattern}' — "
            "use repo-relative paths only"
        )

    # Constructed via concatenation so this source file does not itself match the scanner patterns.
    token_markers = ["gh" + "p_", "gi" + "thub_pat_", "py" + "pi-"]
    for marker in token_markers:
        assert marker not in raw, (
            f"Ledger JSON contains a token marker '{marker}' — remove all secrets"
        )


def test_no_private_data_in_ledger_md():
    """The Markdown ledger must not contain absolute paths, tokens, or private remotes."""
    raw = LEDGER_MD.read_text(encoding="utf-8")

    private_path_patterns = ["/Users/", "/home/", "/root/"]
    for pattern in private_path_patterns:
        assert pattern not in raw, f"Markdown ledger contains a private path pattern '{pattern}'"
