"""Tests for scripts/workflow_summary_guard.py."""

from __future__ import annotations

import importlib.util
import io
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent


def _load_module_from_path(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]  # reason: spec_from_file_location returns Optional[ModuleSpec] but is non-None for valid paths
    sys.modules[name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]  # reason: spec.loader is guaranteed non-None when spec_from_file_location succeeds
    return mod


guard = _load_module_from_path(
    "workflow_summary_guard",
    ROOT / "scripts" / "workflow_summary_guard.py",
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_FIXED_SUMMARY = """\
## Correctness Finding

- **Review lens**: correctness
- **Finding**: Missing null check in storage adapter before LanceDB write
- **Evidence**: mempalace_code/storage.py:42
- **Action taken**: Updated mempalace_code/storage.py:42 to add guard before write
- **Verification**: python -m pytest tests/test_storage.py -k "test_null_guard" -x
- **Deferral reason**: n/a
"""

_DEFERRED_SUMMARY = """\
## Test Coverage Finding

- **Review lens**: test-coverage
- **Finding**: No integration test for backup restore path
- **Evidence**: mempalace_code/backup.py:100
- **Action taken**: n/a
- **Verification**: n/a
- **Deferral reason**: Backlog BACKUP-RESTORE-TEST, acceptance: restore integration test must cover non-empty backup round-trip
"""

_MISSING_EVIDENCE = """\
## Vague Finding

- **Review lens**: correctness
- **Finding**: Something seems off
- **Evidence**: n/a
- **Action taken**: Updated mempalace_code/storage.py:10 to fix it
- **Verification**: python -m pytest tests/test_storage.py -k "test_fix" -x
- **Deferral reason**: n/a
"""

_MISSING_ACTION_OR_DEFERRAL = """\
## Unresolved Finding

- **Review lens**: correctness
- **Finding**: Potential issue in storage path
- **Evidence**: mempalace_code/storage.py:55
- **Action taken**: Looks fine
- **Verification**: n/a
- **Deferral reason**: n/a
"""

_PRIVATE_PATH_SUMMARY = """\
## Public-Safety Finding

- **Review lens**: public-safety
- **Finding**: Private path in output
- **Evidence**: mempalace_code/storage.py:10
- **Action taken**: Updated mempalace_code/storage.py:10 to remove reference
- **Verification**: python -m pytest tests/test_storage.py -k "test_path" -x
- **Deferral reason**: n/a
- Context: see /Users/alice/project/private.py for details
"""

_FAKE_TOKEN = "gh" + "p_" + "A" * 32
_TOKEN_SUMMARY = f"""\
## Secret Token Finding

- **Review lens**: public-safety
- **Finding**: Token in output
- **Evidence**: mempalace_code/storage.py:10
- **Action taken**: Updated mempalace_code/storage.py:10 to redact token
- **Verification**: python -m pytest tests/test_storage.py -k "test_token" -x
- **Deferral reason**: n/a
- Token: {_FAKE_TOKEN}
"""


# ---------------------------------------------------------------------------
# Acceptance tests (VER-1)
# ---------------------------------------------------------------------------


def test_accepts_fixed_summary_with_required_schema_fields():
    diagnostics = guard.check_text("<test>", _FIXED_SUMMARY)
    assert diagnostics == [], f"expected no diagnostics, got: {diagnostics}"


def test_accepts_deferred_summary_with_backlog_acceptance():
    diagnostics = guard.check_text("<test>", _DEFERRED_SUMMARY)
    assert diagnostics == [], f"expected no diagnostics, got: {diagnostics}"


def test_accepts_empty_summary():
    diagnostics = guard.check_text("<test>", "")
    assert diagnostics == []


def test_accepts_summary_with_no_finding_blocks():
    text = "# Workflow Review Summary\n\nNo surviving findings after refutation.\n"
    diagnostics = guard.check_text("<test>", text)
    assert diagnostics == []


# ---------------------------------------------------------------------------
# Rejection tests — missing evidence (VER-2)
# ---------------------------------------------------------------------------


def test_rejects_missing_evidence():
    diagnostics = guard.check_text("<test>", _MISSING_EVIDENCE)
    rule_ids = [d.rule_id for d in diagnostics]
    assert "missing-evidence" in rule_ids, f"expected missing-evidence, got: {rule_ids}"


def test_rejects_empty_evidence_field():
    text = """\
## Finding

- **Review lens**: correctness
- **Finding**: Something
- **Evidence**:
- **Action taken**: Updated mempalace_code/storage.py:5 to fix
- **Verification**: python -m pytest tests/ -k "test_fix"
- **Deferral reason**: n/a
"""
    diagnostics = guard.check_text("<test>", text)
    rule_ids = [d.rule_id for d in diagnostics]
    assert "missing-evidence" in rule_ids


def test_rejects_none_evidence_field():
    text = """\
## Finding

- **Review lens**: correctness
- **Finding**: Something
- **Evidence**: none
- **Action taken**: Updated mempalace_code/storage.py:5 to fix
- **Verification**: python -m pytest tests/ -k "test_fix"
- **Deferral reason**: n/a
"""
    diagnostics = guard.check_text("<test>", text)
    rule_ids = [d.rule_id for d in diagnostics]
    assert "missing-evidence" in rule_ids


# ---------------------------------------------------------------------------
# Rejection tests — missing action or deferral (VER-2)
# ---------------------------------------------------------------------------


def test_rejects_missing_action_or_deferral():
    diagnostics = guard.check_text("<test>", _MISSING_ACTION_OR_DEFERRAL)
    rule_ids = [d.rule_id for d in diagnostics]
    assert "missing-action-or-deferral" in rule_ids, (
        f"expected missing-action-or-deferral, got: {rule_ids}"
    )


def test_rejects_action_without_path_fragment():
    text = """\
## Finding

- **Review lens**: correctness
- **Finding**: Something
- **Evidence**: mempalace_code/storage.py:10
- **Action taken**: Fixed the issue manually
- **Verification**: n/a
- **Deferral reason**: n/a
"""
    diagnostics = guard.check_text("<test>", text)
    rule_ids = [d.rule_id for d in diagnostics]
    assert "missing-action-or-deferral" in rule_ids


def test_rejects_deferral_without_backlog_id():
    text = """\
## Finding

- **Review lens**: correctness
- **Finding**: Something
- **Evidence**: mempalace_code/storage.py:10
- **Action taken**: n/a
- **Verification**: n/a
- **Deferral reason**: Will look at this later, acceptance: some vague criteria
"""
    diagnostics = guard.check_text("<test>", text)
    rule_ids = [d.rule_id for d in diagnostics]
    assert "missing-action-or-deferral" in rule_ids


def test_rejects_deferral_without_acceptance_text():
    text = """\
## Finding

- **Review lens**: correctness
- **Finding**: Something
- **Evidence**: mempalace_code/storage.py:10
- **Action taken**: n/a
- **Verification**: n/a
- **Deferral reason**: Backlog STORAGE-CLEANUP — needs investigation
"""
    diagnostics = guard.check_text("<test>", text)
    rule_ids = [d.rule_id for d in diagnostics]
    assert "missing-action-or-deferral" in rule_ids


def test_accepts_deferred_finding_with_backlog_id_and_acceptance():
    text = """\
## Finding

- **Review lens**: correctness
- **Finding**: Something
- **Evidence**: mempalace_code/storage.py:10
- **Action taken**: n/a
- **Verification**: n/a
- **Deferral reason**: Backlog STORAGE-CLEANUP, acceptance: cleanup must pass all tests
"""
    diagnostics = guard.check_text("<test>", text)
    assert diagnostics == [], f"expected no diagnostics, got: {diagnostics}"


# ---------------------------------------------------------------------------
# Public-safety tests — private paths and tokens (VER-3)
# ---------------------------------------------------------------------------


def test_rejects_private_paths_and_tokens():
    diagnostics = guard.check_text("<test>", _PRIVATE_PATH_SUMMARY)
    rule_ids = [d.rule_id for d in diagnostics]
    assert any("root" in rid or "home" in rid for rid in rule_ids), (
        f"expected a private-path rule, got: {rule_ids}"
    )


def test_rejects_secret_tokens():
    diagnostics = guard.check_text("<test>", _TOKEN_SUMMARY)
    rule_ids = [d.rule_id for d in diagnostics]
    assert "github-token-prefix" in rule_ids, f"expected github-token-prefix, got: {rule_ids}"


def test_diagnostic_does_not_echo_private_path():
    private_path = "/" + "Users" + "/alice/secret/path"
    text = f"""\
## Finding

- **Review lens**: public-safety
- **Finding**: Private path
- **Evidence**: mempalace_code/storage.py:1
- **Action taken**: Updated mempalace_code/storage.py:1 to fix
- **Verification**: python -m pytest tests/test_storage.py -k "test_fix"
- **Deferral reason**: n/a
- Reference: {private_path}
"""
    diagnostics = guard.check_text("<test>", text)
    assert any(d.rule_id == "macos-home-root" for d in diagnostics)
    summaries = [d.summary() for d in diagnostics]
    for s in summaries:
        assert private_path not in s, f"private path leaked in diagnostic: {s}"


def test_diagnostic_does_not_echo_secret_token():
    token = "gh" + "p_" + "B" * 30
    text = f"""\
## Finding

- **Review lens**: public-safety
- **Finding**: Token reference
- **Evidence**: mempalace_code/storage.py:1
- **Action taken**: Updated mempalace_code/storage.py:1 to remove reference
- **Verification**: python -m pytest tests/test_storage.py -k "test_redact"
- **Deferral reason**: n/a
- Observed: {token}
"""
    diagnostics = guard.check_text("<test>", text)
    assert any(d.rule_id == "github-token-prefix" for d in diagnostics)
    summaries = [d.summary() for d in diagnostics]
    for s in summaries:
        assert token not in s, f"token leaked in diagnostic: {s}"


# ---------------------------------------------------------------------------
# CLI stdin test (VER-3)
# ---------------------------------------------------------------------------


def test_cli_reads_pr_body_from_stdin(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO(_FIXED_SUMMARY))
    exit_code = guard.main([])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "OK" in out


def test_cli_reads_invalid_pr_body_from_stdin(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO(_MISSING_EVIDENCE))
    exit_code = guard.main([])
    assert exit_code == 1
    err = capsys.readouterr().err
    assert "FAIL" in err
    assert "missing-evidence" in err


def test_cli_reads_file(tmp_path, capsys):
    summary_file = tmp_path / "summary.md"
    summary_file.write_text(_FIXED_SUMMARY, encoding="utf-8")
    exit_code = guard.main(["--file", str(summary_file)])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "OK" in out


def test_cli_fails_on_invalid_file(tmp_path, capsys):
    summary_file = tmp_path / "summary.md"
    summary_file.write_text(_MISSING_ACTION_OR_DEFERRAL, encoding="utf-8")
    exit_code = guard.main(["--file", str(summary_file)])
    assert exit_code == 1
    err = capsys.readouterr().err
    assert "FAIL" in err
    assert "missing-action-or-deferral" in err


def test_cli_multiple_files_combined_exit(tmp_path, capsys):
    good_file = tmp_path / "good.md"
    bad_file = tmp_path / "bad.md"
    good_file.write_text(_FIXED_SUMMARY, encoding="utf-8")
    bad_file.write_text(_MISSING_EVIDENCE, encoding="utf-8")
    exit_code = guard.main(["--file", str(good_file), "--file", str(bad_file)])
    assert exit_code == 1
    err = capsys.readouterr().err
    assert "missing-evidence" in err


# ---------------------------------------------------------------------------
# Actionability schema field checks
# ---------------------------------------------------------------------------


def test_fixed_finding_requires_verification_command():
    text = """\
## Finding

- **Review lens**: correctness
- **Finding**: Something
- **Evidence**: mempalace_code/storage.py:10
- **Action taken**: Updated mempalace_code/storage.py:10 to fix issue
- **Verification**: n/a
- **Deferral reason**: n/a
"""
    diagnostics = guard.check_text("<test>", text)
    rule_ids = [d.rule_id for d in diagnostics]
    assert "missing-action-or-deferral" in rule_ids


def test_both_fixed_and_deferred_satisfied_accepts():
    text = """\
## Finding

- **Review lens**: correctness
- **Finding**: Something
- **Evidence**: mempalace_code/storage.py:10
- **Action taken**: Updated mempalace_code/storage.py:10 to fix issue
- **Verification**: python -m pytest tests/test_storage.py -k "test_fix"
- **Deferral reason**: Backlog STORAGE-FOLLOW-UP, acceptance: follow-up test coverage
"""
    diagnostics = guard.check_text("<test>", text)
    assert diagnostics == [], f"expected no diagnostics when both branches satisfied: {diagnostics}"


# ---------------------------------------------------------------------------
# INV-4: top-level file paths accepted as evidence
# ---------------------------------------------------------------------------


def test_accepts_top_level_file_as_evidence():
    text = """\
## Finding

- **Review lens**: correctness
- **Finding**: README install instructions are outdated
- **Evidence**: README.md
- **Action taken**: Updated README.md to fix install instructions
- **Verification**: python -m pytest tests/test_cli.py -k "test_install"
- **Deferral reason**: n/a
"""
    diagnostics = guard.check_text("<test>", text)
    assert diagnostics == [], f"expected no diagnostics for top-level file evidence: {diagnostics}"


def test_accepts_top_level_toml_as_evidence():
    text = """\
## Finding

- **Review lens**: correctness
- **Finding**: pyproject.toml has incorrect version constraint
- **Evidence**: pyproject.toml:42
- **Action taken**: Updated pyproject.toml:42 to fix version constraint
- **Verification**: python -m pytest tests/test_cli.py -k "test_version"
- **Deferral reason**: n/a
"""
    diagnostics = guard.check_text("<test>", text)
    assert diagnostics == [], f"expected no diagnostics for pyproject.toml evidence: {diagnostics}"


# ---------------------------------------------------------------------------
# AC-1 / VER-1: schema fields are documented and enforced
# ---------------------------------------------------------------------------


def test_required_schema_fields_are_documented_and_enforced():
    expected_fields = {
        "review lens",
        "finding",
        "evidence",
        "action taken",
        "verification",
        "deferral reason",
    }
    assert expected_fields == guard.REQUIRED_FIELDS, (
        f"REQUIRED_FIELDS mismatch: expected {expected_fields}, got {guard.REQUIRED_FIELDS}"
    )

    protocol_path = ROOT / "docs" / "quality" / "workflow-review-protocol.md"
    assert protocol_path.exists(), "workflow-review-protocol.md must exist"
    protocol = protocol_path.read_text(encoding="utf-8")
    for field_label in (
        "Review lens",
        "Finding",
        "Evidence",
        "Action taken",
        "Verification",
        "Deferral reason",
    ):
        assert field_label in protocol, f"Protocol doc must document field: {field_label}"

    no_evidence_text = """\
## Finding

- **Review lens**: correctness
- **Finding**: Something suspicious
- **Action taken**: Updated mempalace_code/storage.py:5 to fix
- **Verification**: python -m pytest tests/test_storage.py -k "test_fix"
- **Deferral reason**: n/a
"""
    diags = guard.check_text("<test>", no_evidence_text)
    assert any(d.rule_id == "missing-evidence" for d in diags), (
        f"checker must reject a finding with no evidence field; got: {diags}"
    )


# ---------------------------------------------------------------------------
# AC-2 / VER-2: CLI rejects PR body without concrete evidence or actionability
# ---------------------------------------------------------------------------


def test_cli_rejects_pr_body_snippet_without_concrete_evidence_or_actionability(
    monkeypatch, capsys
):
    pr_body = """\
## Correctness Review Summary

## Surviving Finding

- **Review lens**: correctness
- **Finding**: The storage adapter may have a null pointer issue
- **Evidence**: The code looks suspicious in the storage module
- **Action taken**: n/a
- **Verification**: n/a
- **Deferral reason**: n/a
"""
    monkeypatch.setattr("sys.stdin", io.StringIO(pr_body))
    exit_code = guard.main([])
    assert exit_code == 1
    err = capsys.readouterr().err
    assert "FAIL" in err
    assert "missing-evidence" in err


# ---------------------------------------------------------------------------
# AC-3 / VER-3: rejects raw transcript and local-only artifact references
# ---------------------------------------------------------------------------


def test_rejects_raw_transcript_and_local_only_artifact_references():
    text = """\
## Correctness Finding

- **Review lens**: correctness
- **Finding**: Missing null check in storage adapter
- **Evidence**: mempalace_code/storage.py:10
- **Action taken**: Updated mempalace_code/storage.py:10 to add guard
- **Verification**: python -m pytest tests/test_storage.py -k "test_null"
- **Deferral reason**: n/a
- Context: full evidence in .tasks/SOME-TASK/transcript.md
"""
    diagnostics = guard.check_text("<test>", text)
    rule_ids = [d.rule_id for d in diagnostics]
    assert "local-only-artifact" in rule_ids, (
        f"expected local-only-artifact diagnostic for .tasks/ reference, got: {rule_ids}"
    )
    summaries = [d.summary() for d in diagnostics]
    for s in summaries:
        assert ".tasks/" not in s, f"local-only path must not be echoed in diagnostic: {s}"


def test_rejects_protocols_artifact_reference():
    text = """\
## Finding

- **Review lens**: correctness
- **Finding**: Something
- **Evidence**: mempalace_code/storage.py:10
- **Action taken**: Updated mempalace_code/storage.py:10 to fix
- **Verification**: python -m pytest tests/test_storage.py -k "test_fix"
- **Deferral reason**: n/a
- Raw output: see .protocols/review-2026-08-01/findings.json
"""
    diagnostics = guard.check_text("<test>", text)
    rule_ids = [d.rule_id for d in diagnostics]
    assert "local-only-artifact" in rule_ids


def test_rejects_docs_audits_artifact_reference():
    text = """\
## Finding

- **Review lens**: correctness
- **Finding**: Something
- **Evidence**: mempalace_code/storage.py:10
- **Action taken**: Updated mempalace_code/storage.py:10 to fix
- **Verification**: python -m pytest tests/test_storage.py -k "test_fix"
- **Deferral reason**: n/a
- Audit log: docs/audits/2026-08-01-review.md
"""
    diagnostics = guard.check_text("<test>", text)
    rule_ids = [d.rule_id for d in diagnostics]
    assert "local-only-artifact" in rule_ids


def test_local_only_artifact_diagnostic_is_redacted():
    local_ref = ".tasks/" + "TASK-123/evidence.md"
    text = f"""\
## Finding

- **Review lens**: correctness
- **Finding**: Something
- **Evidence**: mempalace_code/storage.py:10
- **Action taken**: Updated mempalace_code/storage.py:10 to fix
- **Verification**: python -m pytest tests/test_storage.py -k "test_fix"
- **Deferral reason**: n/a
- Reference: {local_ref}
"""
    diagnostics = guard.check_text("<test>", text)
    assert any(d.rule_id == "local-only-artifact" for d in diagnostics)
    summaries = [d.summary() for d in diagnostics]
    for s in summaries:
        assert local_ref not in s, f"local-only artifact path must not be echoed: {s}"


def test_raw_transcript_paths_are_gitignored():
    gitignore_path = ROOT / ".gitignore"
    assert gitignore_path.exists(), ".gitignore must exist"
    gitignore = gitignore_path.read_text(encoding="utf-8")
    for raw_path in (".tasks/", ".protocols/", "docs/audits/"):
        assert raw_path in gitignore, (
            f"raw transcript / local-only artifact path {raw_path!r} must be in .gitignore"
        )


# ---------------------------------------------------------------------------
# AC-4 / VER-4: protocol states passive review output must be resolved
# ---------------------------------------------------------------------------


def test_protocol_says_passive_review_output_must_be_resolved():
    protocol_path = ROOT / "docs" / "quality" / "workflow-review-protocol.md"
    assert protocol_path.exists(), "workflow-review-protocol.md must exist"
    protocol = protocol_path.read_text(encoding="utf-8").lower()

    assert "passive" in protocol, (
        "Protocol must explicitly state that passive review output is not sufficient"
    )
    assert "insufficient" in protocol or "not sufficient" in protocol, (
        "Protocol must say passive review output is insufficient or not sufficient"
    )
    assert "acceptance" in protocol, (
        "Protocol must require acceptance criteria for deferred findings"
    )
    assert "backlog" in protocol or "deferral" in protocol, (
        "Protocol must describe the deferral path as a backlog item"
    )
