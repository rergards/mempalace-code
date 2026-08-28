"""Tests for the stdlib-only upstream comparison guard."""

from __future__ import annotations

import copy
import importlib.util
import json
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


guard = _load_module("upstream_comparison_guard", ROOT / "scripts" / "upstream_comparison_guard.py")
guard._load_public_read().REVIEWED_UPSTREAM_REPOSITORY = "Example/example"
guard._load_public_read().REVIEWED_UPSTREAM_BRANCH = "main"


def _public_result(data=None, error=""):
    return type("Result", (), {"data": data, "error": error})()


COMMIT = "a" * 40
PREVIOUS_COMMIT = "b" * 40
REPOSITORY = "https://github.com/Example/example"
BRANCH = "main"
REVIEWED_DATE = "2026-07-01"
PREVIOUS_REVIEWED_DATE = "2026-06-01"
COMPARE_REF = f"{REPOSITORY}/compare/{PREVIOUS_COMMIT}...{COMMIT}"
README_REF = f"{REPOSITORY}/blob/{COMMIT}/README.md"
RECOVERY_COMMAND = "python scripts/upstream_comparison_guard.py --check-live --json"
PREDICATE_FILE = "tests/test_example_guard.py"
PREDICATE = f"{PREDICATE_FILE}::test_example"
BRIDGE_CAPABILITY = "backend-chromadb-migration-bridge-only"


def _manifest(**overrides) -> dict:
    manifest = {
        "schema_version": 2,
        "reviewed_date": REVIEWED_DATE,
        "previous_reviewed_date": PREVIOUS_REVIEWED_DATE,
        "canonical_repository": REPOSITORY,
        "branch": BRANCH,
        "commit": COMMIT,
        "previous_commit": PREVIOUS_COMMIT,
        "compare_ref": COMPARE_REF,
        "canonical_document": "docs/UPSTREAM_COMPARISON.md",
        "readme_path": "README.md",
        "recovery_command": RECOVERY_COMMAND,
        "tracked_source_paths": ["README.md"],
        "source_refs": {"README.md": README_REF},
        "readme_markers": ["## This Fork vs Upstream"],
        "comparison_markers": ["## Snapshot"],
        "capabilities": {
            "upstream_advertised": ["some-capability"],
            "fork_current": ["other-capability"],
        },
        "capability_sources": {"some-capability": ["README.md"]},
        "delta_decisions": [
            {
                "id": "guarded-change",
                "upstream_change": "upstream tightened a documented guard",
                "source_refs": ["README.md"],
                "release_critical": True,
                "decision": "adopted",
                "rationale": "this fork adopts a stronger fail-closed form",
                "local_predicates": [PREDICATE],
            },
            {
                "id": "repository-metadata-change",
                "upstream_change": "upstream changed repository review routing",
                "source_refs": ["compare"],
                "release_critical": False,
                "decision": "irrelevant",
                "rationale": "this fork owns its own review configuration",
                "local_predicates": [],
            },
        ],
    }
    manifest.update(overrides)
    return manifest


def _decisions(manifest: dict) -> list[dict]:
    """Return a deep copy of the fixture decisions so a test can mutate one row."""
    return copy.deepcopy(manifest["delta_decisions"])


def _document(manifest: dict) -> str:
    """Render a comparison document that states everything the manifest declares."""
    lines = ["# Upstream Comparison", "", "## Snapshot", ""]
    for field in guard.REQUIRED_STRING_FIELDS:
        value = manifest.get(field)
        if isinstance(value, str):
            lines.append(f"{field}: {value}")
    source_refs = manifest.get("source_refs")
    if isinstance(source_refs, dict):
        lines.extend(f"- <{ref}>" for ref in source_refs.values() if isinstance(ref, str))
    capabilities = manifest.get("capabilities")
    if isinstance(capabilities, dict):
        for group in guard.CAPABILITY_GROUPS:
            group_values = capabilities.get(group)
            if isinstance(group_values, list):
                lines.extend(f"- `{item}`" for item in group_values if isinstance(item, str))
    decisions = manifest.get("delta_decisions")
    if isinstance(decisions, list):
        for decision in decisions:
            if isinstance(decision, dict):
                lines.append(f"- `{decision.get('id')}` — `{decision.get('decision')}`")
    return "\n".join([*lines, ""])


def _root(tmp_path: Path, *, manifest: dict | None = None, document: str | None = None) -> Path:
    manifest = manifest if manifest is not None else _manifest()

    quality_dir = tmp_path / "docs" / "quality"
    quality_dir.mkdir(parents=True)
    (quality_dir / "upstream-comparison.json").write_text(json.dumps(manifest), encoding="utf-8")

    (tmp_path / "README.md").write_text(
        "# Example\n\n## This Fork vs Upstream\n\nSee the comparison doc.\n",
        encoding="utf-8",
    )

    (tmp_path / "docs" / "UPSTREAM_COMPARISON.md").write_text(
        document if document is not None else _document(manifest),
        encoding="utf-8",
    )

    decisions = manifest.get("delta_decisions")
    if isinstance(decisions, list):
        for decision in decisions:
            if not isinstance(decision, dict):
                continue
            for predicate in decision.get("local_predicates", []):
                if not isinstance(predicate, str):
                    continue
                relative = guard.predicate_path(predicate)
                if relative is None:
                    continue
                target = tmp_path / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                test_name = guard.predicate_test_name(predicate)
                content = f"def {test_name}():\n    pass\n" if test_name else "# fixture guard\n"
                target.write_text(content, encoding="utf-8")

    return tmp_path


def test_evaluate_accepts_valid_static_snapshot(tmp_path: Path):
    root = _root(tmp_path)

    facts, errors = guard.evaluate(root, today=date(2026, 7, 10))

    assert errors == []
    assert facts["commit"] == COMMIT
    assert facts["previous_commit"] == PREVIOUS_COMMIT
    assert facts["compare_ref"] == COMPARE_REF
    assert facts["recovery_command"] == RECOVERY_COMMAND
    assert facts["delta_decisions"] == {
        "guarded-change": "adopted",
        "repository-metadata-change": "irrelevant",
    }
    assert facts["release_critical_decisions"] == ["guarded-change"]
    assert facts["review_age_days"] == 9


def test_evaluate_rejects_stale_review_date(tmp_path: Path):
    root = _root(tmp_path)

    _, errors = guard.evaluate(root, max_age_days=30, today=date(2026, 9, 1))

    assert any("review-stale" in error for error in errors)


def test_evaluate_rejects_missing_readme_marker(tmp_path: Path):
    root = _root(tmp_path)
    (root / "README.md").write_text("# Example\n\nNo marker here.\n", encoding="utf-8")

    _, errors = guard.evaluate(root, today=date(2026, 7, 10))

    assert any("readme-pointer" in error for error in errors)


def test_evaluate_rejects_a_pin_that_did_not_move(tmp_path: Path):
    root = _root(tmp_path, manifest=_manifest(previous_commit=COMMIT))

    _, errors = guard.evaluate(root, today=date(2026, 7, 10))

    assert any("manifest-commit" in error for error in errors)


def test_evaluate_rejects_a_refresh_that_predates_the_pin_it_replaces(tmp_path: Path):
    root = _root(tmp_path, manifest=_manifest(previous_reviewed_date="2026-07-02"))

    _, errors = guard.evaluate(root, today=date(2026, 7, 10))

    assert any("manifest-date" in error and "previous_reviewed_date" in error for error in errors)


def test_evaluate_rejects_compare_ref_that_does_not_span_the_two_pins(tmp_path: Path):
    other = "c" * 40
    manifest = _manifest(compare_ref=f"{REPOSITORY}/compare/{other}...{COMMIT}")
    root = _root(tmp_path, manifest=manifest)

    _, errors = guard.evaluate(root, today=date(2026, 7, 10))

    assert any("manifest-compare" in error for error in errors)


def test_evaluate_rejects_recovery_command_that_never_checks_upstream(tmp_path: Path):
    manifest = _manifest(recovery_command="python scripts/upstream_comparison_guard.py")
    root = _root(tmp_path, manifest=manifest)

    _, errors = guard.evaluate(root, today=date(2026, 7, 10))

    assert any("manifest-recovery" in error for error in errors)


def test_evaluate_rejects_source_ref_left_at_the_previous_commit(tmp_path: Path):
    stale = f"{REPOSITORY}/blob/{PREVIOUS_COMMIT}/README.md"
    root = _root(tmp_path, manifest=_manifest(source_refs={"README.md": stale}))

    _, errors = guard.evaluate(root, today=date(2026, 7, 10))

    assert any("source-ref" in error for error in errors)


def test_evaluate_rejects_a_document_that_hides_a_pinned_source_link(tmp_path: Path):
    manifest = _manifest()
    document = _document(manifest).replace(README_REF, "https://example.invalid/readme")
    root = _root(tmp_path, manifest=manifest, document=document)

    _, errors = guard.evaluate(root, today=date(2026, 7, 10))

    assert any("source-ref" in error and "README.md" in error for error in errors)


def test_evaluate_rejects_a_capability_with_no_tracked_source(tmp_path: Path):
    root = _root(tmp_path, manifest=_manifest(capability_sources={"some-capability": []}))

    _, errors = guard.evaluate(root, today=date(2026, 7, 10))

    assert any("capability-source" in error for error in errors)


def test_evaluate_rejects_a_capability_citing_an_untracked_source(tmp_path: Path):
    manifest = _manifest(capability_sources={"some-capability": ["docs/private-notes.md"]})
    root = _root(tmp_path, manifest=manifest)

    _, errors = guard.evaluate(root, today=date(2026, 7, 10))

    assert any("capability-source" in error for error in errors)


def test_evaluate_rejects_an_unknown_delta_decision_category(tmp_path: Path):
    manifest = _manifest()
    decisions = _decisions(manifest)
    decisions[0]["decision"] = "mostly-fine"
    root = _root(tmp_path, manifest=_manifest(delta_decisions=decisions))

    _, errors = guard.evaluate(root, today=date(2026, 7, 10))

    assert any("delta-decision" in error and "mostly-fine" in error for error in errors)


def test_evaluate_rejects_an_adopted_decision_with_no_local_predicate(tmp_path: Path):
    manifest = _manifest()
    decisions = _decisions(manifest)
    decisions[0]["local_predicates"] = []
    root = _root(tmp_path, manifest=_manifest(delta_decisions=decisions))

    _, errors = guard.evaluate(root, today=date(2026, 7, 10))

    assert any("local regression predicate" in error for error in errors)


def test_evaluate_rejects_a_predicate_missing_from_the_checkout(tmp_path: Path):
    root = _root(tmp_path)
    (root / PREDICATE_FILE).unlink()

    _, errors = guard.evaluate(root, today=date(2026, 7, 10))

    assert any("local-predicate" in error and PREDICATE_FILE in error for error in errors)


def test_evaluate_rejects_a_predicate_that_names_no_path(tmp_path: Path):
    manifest = _manifest()
    decisions = _decisions(manifest)
    decisions[0]["local_predicates"] = ["it is obviously fine"]
    root = _root(tmp_path, manifest=_manifest(delta_decisions=decisions))

    _, errors = guard.evaluate(root, today=date(2026, 7, 10))

    assert any("repository-relative path" in error for error in errors)


def test_evaluate_rejects_a_release_critical_decision_backed_only_by_the_compare_range(
    tmp_path: Path,
):
    manifest = _manifest()
    decisions = _decisions(manifest)
    decisions[0]["source_refs"] = [guard.COMPARE_SOURCE_TOKEN]
    root = _root(tmp_path, manifest=_manifest(delta_decisions=decisions))

    _, errors = guard.evaluate(root, today=date(2026, 7, 10))

    assert any("tracked public upstream source" in error for error in errors)


def test_evaluate_rejects_a_decision_citing_an_untracked_source(tmp_path: Path):
    manifest = _manifest()
    decisions = _decisions(manifest)
    decisions[0]["source_refs"] = ["docs/private-notes.md"]
    root = _root(tmp_path, manifest=_manifest(delta_decisions=decisions))

    _, errors = guard.evaluate(root, today=date(2026, 7, 10))

    assert any("untracked sources" in error for error in errors)


def test_evaluate_rejects_a_duplicate_delta_decision_id(tmp_path: Path):
    manifest = _manifest()
    decisions = _decisions(manifest)
    decisions.append(copy.deepcopy(decisions[0]))
    root = _root(tmp_path, manifest=_manifest(delta_decisions=decisions))

    _, errors = guard.evaluate(root, today=date(2026, 7, 10))

    assert any("declared more than once" in error for error in errors)


def test_evaluate_rejects_a_document_missing_a_delta_decision(tmp_path: Path):
    manifest = _manifest()
    document = _document(manifest).replace("`guarded-change`", "`some-other-change`")
    root = _root(tmp_path, manifest=manifest, document=document)

    _, errors = guard.evaluate(root, today=date(2026, 7, 10))

    assert any("does not record delta decision" in error for error in errors)


def test_evaluate_rejects_document_decision_category_drift(tmp_path: Path):
    manifest = _manifest()
    document = _document(manifest).replace(
        "`guarded-change` — `adopted`", "`guarded-change` — `deferred`"
    )
    root = _root(tmp_path, manifest=manifest, document=document)

    _, errors = guard.evaluate(root, today=date(2026, 7, 10))

    assert any("does not bind 'guarded-change'" in error for error in errors)


def test_evaluate_rejects_table_decision_category_drift(tmp_path: Path):
    manifest = _manifest()
    document = _document(manifest).replace(
        "- `guarded-change` — `adopted`",
        "| `guarded-change` | upstream change | `deferred` | yes |",
    )
    root = _root(tmp_path, manifest=manifest, document=document)

    _, errors = guard.evaluate(root, today=date(2026, 7, 10))

    assert any("does not bind 'guarded-change'" in error for error in errors)


def test_evaluate_rejects_a_missing_test_predicate_name(tmp_path: Path):
    manifest = _manifest()
    root = _root(tmp_path, manifest=manifest)
    (root / PREDICATE_FILE).write_text("def test_some_other_name():\n    pass\n")

    _, errors = guard.evaluate(root, today=date(2026, 7, 10))

    assert any("names test 'test_example'" in error for error in errors)


def test_evaluate_rejects_a_chromadb_runtime_backend_claim(tmp_path: Path):
    manifest = _manifest(
        capabilities={
            "upstream_advertised": ["some-capability"],
            "fork_current": ["backend-chromadb-runtime"],
        }
    )
    root = _root(tmp_path, manifest=manifest)

    _, errors = guard.evaluate(root, today=date(2026, 7, 10))

    assert any("chroma-stance" in error for error in errors)


def test_evaluate_rejects_the_retired_chromadb_migration_bridge_stance(tmp_path: Path):
    manifest = _manifest(
        capabilities={
            "upstream_advertised": ["some-capability"],
            "fork_current": [BRIDGE_CAPABILITY, "other-capability"],
        }
    )
    root = _root(tmp_path, manifest=manifest)

    _, errors = guard.evaluate(root, today=date(2026, 7, 10))

    assert any("chroma-stance" in error and BRIDGE_CAPABILITY in error for error in errors)


def test_evaluate_rejects_an_unsupported_schema_version(tmp_path: Path):
    root = _root(tmp_path, manifest=_manifest(schema_version=1))

    _, errors = guard.evaluate(root, today=date(2026, 7, 10))

    assert any("schema_version" in error for error in errors)


def test_predicate_path_reads_the_path_out_of_a_predicate():
    assert guard.predicate_path(PREDICATE) == PREDICATE_FILE
    assert guard.predicate_path("mempalace_code/source_io.py") == "mempalace_code/source_io.py"
    assert guard.predicate_path("pytest tests/test_thing.py -q") == "tests/test_thing.py"
    assert guard.predicate_path("no path here") is None


def test_predicate_test_name_reads_the_final_pytest_node_component():
    assert guard.predicate_test_name(PREDICATE) == "test_example"
    assert guard.predicate_test_name("tests/test_x.py::TestCase::test_value[param]") == "test_value"
    assert guard.predicate_test_name("tests/test_x.py") is None


def test_check_live_accepts_matching_sha_from_injected_fetcher(tmp_path: Path):
    root = _root(tmp_path)
    manifest = guard.load_manifest(root)
    source_before = {
        "manifest": (root / "docs" / "quality" / "upstream-comparison.json").read_bytes(),
        "comparison": (root / "docs" / "UPSTREAM_COMPARISON.md").read_bytes(),
        "readme": (root / "README.md").read_bytes(),
    }

    def public_read(_query):
        return _public_result(COMMIT)

    facts, errors = guard.check_live(manifest, public_read=public_read)

    assert errors == []
    assert facts["live_head"] == COMMIT
    assert source_before == {
        "manifest": (root / "docs" / "quality" / "upstream-comparison.json").read_bytes(),
        "comparison": (root / "docs" / "UPSTREAM_COMPARISON.md").read_bytes(),
        "readme": (root / "README.md").read_bytes(),
    }


def test_check_live_rejects_mismatching_sha(tmp_path: Path):
    root = _root(tmp_path)
    manifest = guard.load_manifest(root)
    other_sha = "b" * 40

    def public_read(_query):
        return _public_result(other_sha)

    facts, errors = guard.check_live(manifest, public_read=public_read)

    assert facts["live_head"] == other_sha
    assert any("upstream-drift" in error for error in errors)


def test_check_live_drift_error_names_the_range_and_the_recovery_command(tmp_path: Path):
    root = _root(tmp_path)
    manifest = guard.load_manifest(root)
    other_sha = "c" * 40

    def public_read(_query):
        return _public_result(other_sha)

    _, errors = guard.check_live(manifest, public_read=public_read)

    assert len(errors) == 1
    assert f"{REPOSITORY}/compare/{COMMIT}...{other_sha}" in errors[0]
    assert RECOVERY_COMMAND in errors[0]


def test_check_live_rejects_invalid_json(tmp_path: Path):
    root = _root(tmp_path)
    manifest = guard.load_manifest(root)

    def public_read(_query):
        return _public_result(error="response was not valid UTF-8 JSON")

    facts, errors = guard.check_live(manifest, public_read=public_read)

    assert facts["live_head"] is None
    assert any("live-response" in error for error in errors)


def test_check_live_fails_closed_on_fetch_failure(tmp_path: Path):
    root = _root(tmp_path)
    manifest = guard.load_manifest(root)

    def public_read(_query):
        return _public_result(error="offline")

    facts, errors = guard.check_live(manifest, public_read=public_read)

    assert facts["live_head"] is None
    assert errors == ["live-response: upstream head request failed (offline)"]


def test_default_public_reader_error_is_an_untrusted_live_response(tmp_path: Path):
    manifest = guard.load_manifest(_root(tmp_path))
    with pytest.raises(guard.LiveCheckError, match="offline"):
        guard.fetch_head_commit(
            manifest,
            public_read=lambda _query: _public_result(error="offline"),
        )


def test_check_live_rejects_empty_or_malformed_head_resolution(tmp_path: Path):
    root = _root(tmp_path)
    manifest = guard.load_manifest(root)

    for payload in (None, "", "not-a-commit"):
        facts, errors = guard.check_live(
            manifest,
            public_read=lambda _query, payload=payload: _public_result(payload),
        )
        assert facts["live_head"] is None
        assert errors == ["live-response: upstream head reply carried no 40-hex commit sha"]


def test_evaluate_rejects_negative_max_age_days(tmp_path: Path):
    root = _root(tmp_path)

    _, errors = guard.evaluate(root, max_age_days=-1, today=date(2026, 7, 10))

    assert any("config-invalid" in error for error in errors)


def test_repository_manifest_and_document_agree():
    """The shipped manifest and document must pass the guard they are checked by."""
    _, errors = guard.evaluate(ROOT, max_age_days=10_000, today=date(2026, 12, 31))

    assert errors == []
