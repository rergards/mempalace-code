"""Regression coverage for memory growth, duplicate admission and recovery points.

Fixtures encode the observed failure classes independently of the implementation:
nested task checkouts and plain technical copies of project files, equal digests
with different chunks, protected and missing sources, interrupted reconciliation,
opposite and conditional facts, identical notes in another project, and degraded
forensic backups offered as recovery points.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, cast

import pytest

from mempalace_code.backup import managed_backups_dir
from mempalace_code.mining import orchestrator, scanner
from mempalace_code.mining.orchestrator import mine
from mempalace_code.mining.scanner import scan_project
from mempalace_code.storage import LanceStore, open_store

WIDGET = (
    "class Widget(BaseWidget):\n"
    '    """A widget that renders a labelled value on the operations dashboard."""\n'
    "\n"
    "    def __init__(self, label: str, value: int) -> None:\n"
    "        self.label = label\n"
    "        self.value = value\n"
    "\n"
    "    def render(self) -> str:\n"
    '        return f"{self.label}: {self.value}"\n'
)
MODULE = (
    "def scale(value: int, factor: int = 3) -> int:\n"
    '    """Scale a dashboard value by the configured factor before it is rendered."""\n'
    "    return value * factor\n"
)
REJECTED_REPORT = (
    "# Review: REJECT\n\n"
    "The billing candidate was rejected because its patch paths did not match the agreed\n"
    "paths, even though its code checks passed. Keep this reason for later reviews.\n"
)
# research-3: the opposite statement was refused at similarity 0.991.
SQLITE = (
    "ProjectStone metadata storage policy covers local offline operation, backup recovery, "
    "stable migrations, ordinary query performance, and clear ownership of the storage "
    "boundary. The decision for the metadata component is to use SQLite for persistent "
    "metadata storage."
)
NOT_SQLITE = SQLITE.replace("is to use SQLite", "is to not use SQLite")
DISTINCT_PAIRS = [
    (SQLITE, NOT_SQLITE),
    ("Allow reads; deny writes.", "Allow writes; deny reads."),
    (
        "Use SQLite for metadata only when the palace runs offline.",
        "Use SQLite for metadata.",
    ),
    (
        "Reject delta-sync version2 because restore lost KG.",
        "Delta-sync version3 has not been tested; version2 finding does not establish "
        "version3 safety.",
    ),
]


def _project(tmp_path: Path) -> Path:
    project = (tmp_path / "proj").resolve()
    (project / "src").mkdir(parents=True)
    (project / "mempalace.yaml").write_text(
        "wing: proj\nrooms:\n  - name: general\n    description: All project files\n",
        encoding="utf-8",
    )
    (project / "src" / "widget.py").write_text(WIDGET, encoding="utf-8")
    return project


def _with_task_copy(project: Path) -> Path:
    task = project / ".tasks" / "T1"
    (task / "src").mkdir(parents=True)
    (task / "src" / "widget.py").write_text(WIDGET, encoding="utf-8")
    (task / "astra-billing-review.md").write_text(REJECTED_REPORT, encoding="utf-8")
    return task


def _nested_checkout(project: Path) -> Path:
    checkout = project / ".tasks" / "T2" / "repo"
    (checkout / "src").mkdir(parents=True)
    (checkout / "src" / "widget.py").write_text(WIDGET, encoding="utf-8")
    return checkout


def _mine(project: Path, palace: Path, **kwargs) -> dict[str, Any]:
    return cast("dict[str, Any]", mine(str(project), str(palace), skip_optimize=True, **kwargs))


def _rows(palace: Path) -> dict[str, int]:
    store = open_store(str(palace), create=False, read_only=True)
    found = store.get(where={"wing": "proj"}, include=["metadatas"], limit=100000)
    counts: dict[str, int] = {}
    for meta in found["metadatas"]:
        counts[meta["source_file"]] = counts.get(meta["source_file"], 0) + 1
    return counts


def _records(palace: Path) -> list[dict[str, Any]]:
    path = orchestrator._copy_reconcile_record_path(str(palace))
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _kg_dump(kg) -> dict[str, list]:
    conn = sqlite3.connect(kg.db_path)
    try:
        tables = [
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        ]
        return {
            table: sorted(conn.execute(f'SELECT * FROM "{table}"').fetchall(), key=repr)
            for table in sorted(tables)
        }
    finally:
        conn.close()


def _call(handler, **kwargs) -> dict[str, Any]:
    return cast("dict[str, Any]", handler(**kwargs))


def _patch_runtime(monkeypatch, config, palace_path, kg) -> None:
    from mempalace_code.mcp import runtime

    monkeypatch.setattr(runtime, "_config", config)
    monkeypatch.setattr(runtime, "_kg", kg)
    monkeypatch.setattr(runtime, "_store", None)
    open_store(palace_path, create=True)


# Source selection


def test_scan_skips_nested_checkout_and_worktree_but_not_the_project_root(tmp_path):
    project = _project(tmp_path)
    (project / ".git").mkdir()
    # Outside the project-root technical directories, so nested-marker detection runs.
    checkout = project / "work" / "T2" / "repo"
    (checkout / "src").mkdir(parents=True)
    (checkout / "src" / "widget.py").write_text(WIDGET, encoding="utf-8")
    (checkout / ".git").mkdir()
    worktree = project / "wt"
    worktree.mkdir(parents=True)
    (worktree / ".git").write_text("gitdir: /elsewhere/.git/worktrees/wt\n", encoding="utf-8")
    (worktree / "notes.py").write_text(MODULE, encoding="utf-8")
    # Below .tasks and .local the scanner prunes before any marker is examined.
    technical_checkout = _nested_checkout(project)
    (technical_checkout / ".git").mkdir()
    technical_worktree = project / ".local" / "wt"
    technical_worktree.mkdir(parents=True)
    (technical_worktree / ".git").write_text("gitdir: /elsewhere\n", encoding="utf-8")

    nested: list = []
    found = scan_project(str(project), nested_roots=nested)

    assert set(found) == {project / "src" / "widget.py"}
    assert sorted(nested) == sorted([(checkout, "nested"), (worktree, "nested")])


def test_scan_traverses_directories_whose_marker_is_absent(tmp_path):
    project = _project(tmp_path)
    (project / "src" / "module.py").write_text(MODULE, encoding="utf-8")
    # A same-named directory below the project root is ordinary project content.
    plain = project / "docs" / ".tasks" / "T1"
    plain.mkdir(parents=True)
    (plain / "report.md").write_text(REJECTED_REPORT, encoding="utf-8")
    root_report = project / ".tasks" / "T1" / "report.md"
    root_report.parent.mkdir(parents=True)
    root_report.write_text(REJECTED_REPORT, encoding="utf-8")

    nested: list = []
    found = scan_project(str(project), nested_roots=nested)

    assert set(found) == {
        project / "src" / "widget.py",
        project / "src" / "module.py",
        plain / "report.md",
    }
    assert root_report not in found
    assert nested == []


def test_scan_include_ignored_keeps_a_nested_checkout(tmp_path):
    project = _project(tmp_path)
    checkout = _nested_checkout(project)
    (checkout / ".git").mkdir()

    nested: list = []
    found = scan_project(str(project), include_ignored=[".tasks/T2/repo"], nested_roots=nested)

    assert checkout / "src" / "widget.py" in found
    assert nested == []


def test_scan_unclassifiable_marker_is_skipped_as_unknown(tmp_path):
    project = _project(tmp_path)
    odd = project / "odd"
    (odd / "data").mkdir(parents=True)
    (odd / "a.py").write_text(MODULE, encoding="utf-8")
    try:
        (odd / ".git").symlink_to(odd / "data", target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is not available")

    nested: list = []
    found = scan_project(str(project), nested_roots=nested)

    assert odd / "a.py" not in found
    assert nested == [(odd, "unknown")]


def test_unchanged_ordinary_subdirectory_keeps_rows_and_kg(tmp_path, kg):
    project = _project(tmp_path)
    (project / "src" / "module.py").write_text(MODULE, encoding="utf-8")
    palace = tmp_path / "palace"
    _mine(project, palace, kg=kg)
    rows = _rows(palace)
    facts = _kg_dump(kg)

    stats = _mine(project, palace, kg=kg)

    assert str(project / "src" / "module.py") in rows
    assert _rows(palace) == rows
    assert _kg_dump(kg) == facts
    assert stats["nested_roots_skipped"] == 0
    assert stats["stale_sources_removed"] == []


def test_unknown_marker_prefix_is_not_swept_even_after_the_error_clears(tmp_path, monkeypatch):
    project = _project(tmp_path)
    (project / "lib").mkdir()
    (project / "lib" / "module.py").write_text(MODULE, encoding="utf-8")
    palace = tmp_path / "palace"
    _mine(project, palace)
    target = str(project / "lib" / "module.py")
    assert _rows(palace).get(target)
    real_marker = scanner.nested_git_marker

    def flaky_marker(path):
        return "unknown" if path == project / "lib" else real_marker(path)

    monkeypatch.setattr(scanner, "nested_git_marker", flaky_marker)
    stats = _mine(project, palace)

    # No marker exists on disk, so ownership checks alone would call this source stale.
    assert _rows(palace).get(target)
    assert target not in stats["stale_sources_removed"]
    assert stats["nested_roots_skipped"] == 1


# Reconciliation of generated copies


def test_first_mine_does_not_ingest_a_proven_plain_copy(tmp_path):
    project = _project(tmp_path)
    task = _with_task_copy(project)
    palace = tmp_path / "palace"
    report = str(task / "astra-billing-review.md")

    stats = _mine(project, palace)

    rows = _rows(palace)
    assert str(project / "src" / "widget.py") in rows
    # Project-root .tasks is no longer walked by default: neither the unique report nor
    # the plain copy is selected, so the copy-skip counter has nothing to count.
    assert report not in rows
    assert str(task / "src" / "widget.py") not in rows
    assert stats["copy_files_skipped"] == 0

    # An exact include still selects the report without admitting its sibling copy.
    included = _mine(project, palace, include_ignored=[".tasks/T1/astra-billing-review.md"])

    rows = _rows(palace)
    assert rows.get(report)
    assert str(task / "src" / "widget.py") not in rows
    assert included["copy_sources_removed"] == 0


def test_plain_task_copy_is_reconciled_once_and_the_unique_report_is_kept(tmp_path):
    project = _project(tmp_path)
    task = _with_task_copy(project)
    palace = tmp_path / "palace"
    canonical = str(project / "src" / "widget.py")
    copy_file = str(task / "src" / "widget.py")
    report = str(task / "astra-billing-review.md")
    _mine(project, palace, include_ignored=[".tasks"])
    first = _rows(palace)
    assert first.get(canonical)
    assert first.get(copy_file)
    assert first.get(report)

    stats = _mine(project, palace)

    after = _rows(palace)
    assert copy_file not in after
    assert after[canonical] == first[canonical]
    assert after[report] == first[report]
    assert stats["copy_sources_removed"] == 1
    assert stats["copy_rows_removed"] == first[copy_file]
    assert stats["copy_disk"]["disk_reclaimed"] is False
    removed = [record for record in _records(palace) if record["event"] == "removed"]
    assert [item["source_file"] for record in removed for item in record["sources"]] == [copy_file]
    assert removed[0]["sources"][0]["counterpart"] == canonical
    assert list(Path(managed_backups_dir(str(palace))).glob("pre_optimize_*.tar.gz"))

    again = _mine(project, palace)

    assert again["copy_sources_removed"] == 0
    # The copy is no longer walked by default, so it is never counted as skipped.
    assert again["copy_files_skipped"] == 0
    assert copy_file not in _rows(palace)
    assert _rows(palace)[report] == first[report]


def test_explicitly_included_copy_is_neither_skipped_nor_reconciled(tmp_path):
    project = _project(tmp_path)
    task = _with_task_copy(project)
    palace = tmp_path / "palace"
    copy_file = str(task / "src" / "widget.py")
    include = [".tasks/T1/src/widget.py"]
    _mine(project, palace, include_ignored=include)
    first = _rows(palace)

    stats = _mine(project, palace, include_ignored=include)

    assert _rows(palace).get(copy_file) == first[copy_file]
    assert stats["copy_sources_removed"] == 0
    assert stats["copy_files_skipped"] == 0


@pytest.mark.parametrize("change", ["text", "strategy"])
def test_equal_digest_with_different_chunks_is_retained(tmp_path, change):
    project = _project(tmp_path)
    task = _with_task_copy(project)
    palace = tmp_path / "palace"
    copy_file = str(task / "src" / "widget.py")
    _mine(project, palace, include_ignored=[".tasks"])
    store = open_store(str(palace), create=False)
    stored = store.get(where={"source_file": copy_file}, include=["documents", "metadatas"])
    documents = list(stored["documents"])
    metadatas = [dict(meta) for meta in stored["metadatas"]]
    if change == "text":
        documents = [doc + "\n# split by another chunker" for doc in documents]
    else:
        for meta in metadatas:
            meta["chunker_strategy"] = "regex_structural_v1"
    store.upsert(ids=stored["ids"], documents=documents, metadatas=metadatas)

    stats = _mine(project, palace)

    assert _rows(palace).get(copy_file) == len(stored["ids"])
    assert stats["copy_sources_removed"] == 0
    assert stats["copy_sources_retained_by_reason"] == {"chunks-differ": 1}


def test_manual_drawer_on_a_copy_source_keeps_that_source(tmp_path):
    project = _project(tmp_path)
    task = _with_task_copy(project)
    palace = tmp_path / "palace"
    copy_file = str(task / "src" / "widget.py")
    _mine(project, palace, include_ignored=[".tasks"])
    first = _rows(palace)
    open_store(str(palace), create=False).add(
        ids=["manual_note_on_copy"],
        documents=["Reviewer note: this copy reproduced the rejected billing candidate."],
        metadatas=[
            {
                "wing": "proj",
                "room": "general",
                "source_file": copy_file,
                "chunk_index": 0,
                "added_by": "mcp",
                "filed_at": "2026-10-17T00:00:00",
                "chunker_strategy": "manual_v1",
            }
        ],
    )

    stats = _mine(project, palace)

    assert _rows(palace)[copy_file] == first[copy_file] + 1
    assert stats["copy_sources_retained_by_reason"] == {"protected-or-legacy-row": 1}
    kept = open_store(str(palace), create=False, read_only=True).get(ids=["manual_note_on_copy"])
    assert kept["ids"] == ["manual_note_on_copy"]


@pytest.mark.parametrize("failure", ["degraded", "failed"])
def test_unusable_backup_refuses_reconciliation_and_keeps_the_forensic_archive(
    tmp_path, monkeypatch, failure
):
    from mempalace_code import backup

    project = _project(tmp_path)
    _with_task_copy(project)
    palace = tmp_path / "palace"
    _mine(project, palace, include_ignored=[".tasks"])
    first = _rows(palace)
    forensic = tmp_path / "pre_optimize_20261017_000000_000000_DEGRADED.tar.gz"
    forensic.write_bytes(b"forensic copy")

    def unusable_backup(*args, **kwargs):
        if failure == "failed":
            raise OSError("disk full")
        return {"degraded": True, "degraded_error": "kg_corrupt: test"}, str(forensic)

    monkeypatch.setattr(backup, "create_backup", unusable_backup)
    stats = _mine(project, palace)

    assert _rows(palace) == first
    assert stats["copy_sources_removed"] == 0
    assert failure in stats["copy_reconcile_refusal"]
    assert forensic.read_bytes() == b"forensic copy"


def test_source_drift_between_assessment_and_delete_keeps_rows(tmp_path, monkeypatch):
    project = _project(tmp_path)
    task = _with_task_copy(project)
    palace = tmp_path / "palace"
    copy_path = task / "src" / "widget.py"
    _mine(project, palace, include_ignored=[".tasks"])
    first = _rows(palace)
    real_rows = orchestrator._rows_by_source
    calls: list = []

    def drifting_rows(collection, wing, sources):
        calls.append(sources)
        if len(calls) == 2:
            copy_path.write_text(WIDGET + "# edited after assessment\n", encoding="utf-8")
        return real_rows(collection, wing, sources)

    monkeypatch.setattr(orchestrator, "_rows_by_source", drifting_rows)
    stats = _mine(project, palace)

    assert _rows(palace) == first
    assert stats["copy_sources_removed"] == 0
    assert stats["copy_sources_retained_by_reason"] == {"changed-before-delete:content-differs": 1}


def test_interrupted_reconciliation_converges_without_extra_loss(tmp_path, monkeypatch):
    project = _project(tmp_path)
    task = _with_task_copy(project)
    palace = tmp_path / "palace"
    copy_file = str(task / "src" / "widget.py")
    _mine(project, palace, include_ignored=[".tasks"])
    first = _rows(palace)
    real_delete = LanceStore.delete
    interrupted: list = []

    def interrupt_once(self, ids):
        if not interrupted:
            interrupted.append(ids)
            raise KeyboardInterrupt
        return real_delete(self, ids)

    monkeypatch.setattr(LanceStore, "delete", interrupt_once)
    with pytest.raises(KeyboardInterrupt):
        _mine(project, palace)
    assert _rows(palace) == first

    resumed = _mine(project, palace)
    final = _mine(project, palace)

    assert resumed["copy_sources_removed"] == 1
    assert final["copy_sources_removed"] == 0
    assert _rows(palace) == {
        source: count for source, count in first.items() if source != copy_file
    }


def test_dry_run_reconciles_nothing(tmp_path):
    project = _project(tmp_path)
    _with_task_copy(project)
    palace = tmp_path / "palace"
    _mine(project, palace, include_ignored=[".tasks"])
    first = _rows(palace)

    _mine(project, palace, dry_run=True)

    assert _rows(palace) == first


@pytest.mark.parametrize(
    ("location", "nested_roots_skipped"),
    [
        # Below .tasks the parent is pruned before marker detection; stored metadata
        # still selects the copy.
        ((".tasks", "T2", "repo"), 0),
        # Elsewhere the nested-checkout marker still skips and pairs the checkout.
        (("work", "T2", "repo"), 1),
    ],
)
def test_nested_checkout_rows_are_reconciled_and_every_kg_fact_is_kept(
    tmp_path, kg, location, nested_roots_skipped
):
    project = _project(tmp_path)
    checkout = project.joinpath(*location)
    (checkout / "src").mkdir(parents=True)
    (checkout / "src" / "widget.py").write_text(WIDGET, encoding="utf-8")
    nested_copy = str(checkout / "src" / "widget.py")
    canonical = str(project / "src" / "widget.py")
    palace = tmp_path / "palace"
    # Before the upgrade the checkout was ingested like ordinary project files, and
    # canonical KG synchronization may reuse a fact first recorded for the copy.
    _mine(project, palace, include_ignored=[".tasks"], kg=kg)
    kg.add_triple("ReviewNote", "mentions", "Widget", source_file=nested_copy)
    first = _rows(palace)
    facts = _kg_dump(kg)
    (checkout / ".git").mkdir()

    stats = _mine(project, palace, kg=kg)

    assert stats["nested_roots_skipped"] == nested_roots_skipped
    assert stats["copy_sources_removed"] == 1
    assert nested_copy not in _rows(palace)
    assert _rows(palace)[canonical] == first[canonical]
    assert _kg_dump(kg) == facts


def test_nested_checkout_with_a_missing_original_is_retained(tmp_path):
    project = _project(tmp_path)
    checkout = _nested_checkout(project)
    nested_copy = checkout / "src" / "widget.py"
    palace = tmp_path / "palace"
    _mine(project, palace, include_ignored=[".tasks"])
    first = _rows(palace)
    (checkout / ".git").mkdir()
    nested_copy.unlink()

    stats = _mine(project, palace)

    assert _rows(palace)[str(nested_copy)] == first[str(nested_copy)]
    assert stats["copy_sources_retained_by_reason"] == {"source-missing-or-not-regular": 1}


# Project-root technical directories

RECEIPT_TREE = {
    "src/main.py": MODULE,
    "docs/decision.md": "# Decision\n\nKeep metadata storage local and offline.\n",
    "docs/.tasks/report.md": REJECTED_REPORT,
    ".tasks/t1/plain-receipt.json": '{"status": "PASS", "fixture": "plain"}\n',
    ".local/cycle/tmp/current.json": '{"stage": "write", "attempt": 1}\n',
}
DEFAULT_SELECTION = {"src/main.py", "docs/decision.md", "docs/.tasks/report.md"}


def _receipt_project(tmp_path: Path) -> Path:
    # Shapes from the observed default selection: temporary receipts below the
    # project-root technical directories next to canonical code and documentation.
    project = (tmp_path / "receipts").resolve()
    for relative, text in RECEIPT_TREE.items():
        path = project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return project


def _selected(project: Path, **kwargs) -> set[str]:
    found = scan_project(str(project), **kwargs)
    return {path.relative_to(project).as_posix() for path in found}


def test_default_scan_excludes_project_root_technical_receipts(tmp_path):
    project = _receipt_project(tmp_path)

    # The previous default selection also returned both technical receipts.
    assert _selected(project) == DEFAULT_SELECTION


@pytest.mark.parametrize(
    ("include", "added"),
    [
        (
            ".tasks",
            {".tasks/t1/plain-receipt.json", ".tasks/t1/sibling.json", ".tasks/t2/other.json"},
        ),
        (".tasks/t1", {".tasks/t1/plain-receipt.json", ".tasks/t1/sibling.json"}),
        (".tasks/t1/plain-receipt.json", {".tasks/t1/plain-receipt.json"}),
        (".local/cycle", {".local/cycle/tmp/current.json"}),
    ],
)
def test_include_ignored_selects_technical_roots_subtrees_and_files(tmp_path, include, added):
    project = _receipt_project(tmp_path)
    for relative in (".tasks/t1/sibling.json", ".tasks/t2/other.json"):
        (project / relative).parent.mkdir(parents=True, exist_ok=True)
        (project / relative).write_text('{"status": "PASS"}\n', encoding="utf-8")

    assert _selected(project) == DEFAULT_SELECTION
    assert _selected(project, include_ignored=[include]) == DEFAULT_SELECTION | added


def test_included_technical_root_still_rejects_symlinked_sources(tmp_path):
    project = _receipt_project(tmp_path)
    link = project / ".tasks" / "t1" / "linked.py"
    try:
        link.symlink_to(project / "src" / "main.py")
    except OSError:
        pytest.skip("symlink creation is not available")

    rejected: list = []
    found = scan_project(str(project), include_ignored=[".tasks"], symlink_diagnostics=rejected)

    assert link not in found
    assert str(link) in {entry["path"] for entry in rejected}


def test_default_mine_reconciles_stored_technical_copies_without_walking_them(
    tmp_path, kg, monkeypatch
):
    project = _project(tmp_path)
    task = _with_task_copy(project)
    receipt = project / ".local" / "cycle" / "tmp" / "current.json"
    receipt.parent.mkdir(parents=True)
    receipt.write_text('{"stage": "write", "attempt": 1}\n', encoding="utf-8")
    palace = tmp_path / "palace"
    canonical = str(project / "src" / "widget.py")
    copy_file = str(task / "src" / "widget.py")
    report = str(task / "astra-billing-review.md")
    # Records filed while the technical directories were still selected.
    _mine(project, palace, include_ignored=[".tasks", ".local"], kg=kg)
    open_store(str(palace), create=False).add(
        ids=["manual_note_on_report"],
        documents=["Reviewer note: keep the rejected billing reason for later reviews."],
        metadatas=[
            {
                "wing": "proj",
                "room": "general",
                "source_file": report,
                "chunk_index": 0,
                "added_by": "mcp",
                "filed_at": "2026-10-18T00:00:00",
                "chunker_strategy": "manual_v1",
            }
        ],
    )
    kg.add_triple("BillingCandidate", "status", "rejected", source_file=report)
    first = _rows(palace)
    facts = _kg_dump(kg)
    assert first.get(copy_file)
    assert first.get(report)
    assert first.get(str(receipt))
    walked: list[Path] = []
    real_walk = scanner.os.walk

    def recording_walk(top, *args, **kwargs):
        for entry in real_walk(top, *args, **kwargs):
            walked.append(Path(entry[0]))
            yield entry

    monkeypatch.setattr(scanner.os, "walk", recording_walk)
    stats = _mine(project, palace, kg=kg)
    again = _mine(project, palace, kg=kg)

    technical = (project / ".tasks", project / ".local")
    assert project in walked
    assert [p for p in walked if any(p == root or root in p.parents for root in technical)] == []
    after = _rows(palace)
    assert copy_file not in after
    assert after[canonical] == first[canonical]
    assert after[report] == first[report]
    assert after[str(receipt)] == first[str(receipt)]
    assert stats["copy_sources_removed"] == 1
    assert stats["copy_files_skipped"] == 0
    assert again["copy_sources_removed"] == 0
    assert _rows(palace) == after
    assert _kg_dump(kg) == facts
    store = open_store(str(palace), create=False, read_only=True)
    assert store.get(ids=["manual_note_on_report"])["ids"] == ["manual_note_on_report"]


def test_canonical_change_keeps_stored_technical_originals_and_their_kg_facts(tmp_path, kg):
    project = _project(tmp_path)
    task = _with_task_copy(project)
    copy_file = str(task / "src" / "widget.py")
    report = str(task / "astra-billing-review.md")
    palace = tmp_path / "palace"
    _mine(project, palace, include_ignored=[".tasks"], kg=kg)
    kg.add_triple("BillingCandidate", "status", "rejected", source_file=report)
    first = _rows(palace)
    technical = [r for r in _kg_dump(kg)["triples"] if copy_file in r or report in r]
    assert technical

    (project / "src" / "widget.py").write_text(WIDGET.replace("Widget", "ChangedService"))
    stats = _mine(project, palace, kg=kg)

    after = _rows(palace)
    assert after[copy_file] == first[copy_file]
    assert after[report] == first[report]
    assert stats["files_processed"] == 1
    assert stats["copy_sources_removed"] == 0
    assert [r for r in _kg_dump(kg)["triples"] if copy_file in r or report in r] == technical
    assert any(
        f["subject"] == "ChangedService" and f["valid_to"] is None
        for f in kg.query_relationship("in_project")
    )


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ("changed", "content-differs"),
        ("missing", "source-missing-or-not-regular"),
        ("symlink", "source-missing-or-not-regular"),
    ],
)
def test_pruned_technical_copy_that_is_not_an_exact_current_copy_is_retained(
    tmp_path, change, reason
):
    project = _project(tmp_path)
    task = _with_task_copy(project)
    palace = tmp_path / "palace"
    copy_path = task / "src" / "widget.py"
    _mine(project, palace, include_ignored=[".tasks"])
    first = _rows(palace)
    if change == "changed":
        copy_path.write_text(WIDGET + "# edited in the task checkout\n", encoding="utf-8")
    else:
        copy_path.unlink()
        if change == "symlink":
            try:
                copy_path.symlink_to(project / "src" / "widget.py")
            except OSError:
                pytest.skip("symlink creation is not available")

    stats = _mine(project, palace)
    again = _mine(project, palace)

    assert _rows(palace) == first
    assert stats["copy_sources_removed"] == 0
    assert stats["copy_sources_retained_by_reason"] == {reason: 1}
    assert again["copy_sources_removed"] == 0


# Duplicate admission


@pytest.mark.parametrize(
    ("first", "second"), DISTINCT_PAIRS + [(second, first) for first, second in DISTINCT_PAIRS]
)
def test_distinct_statements_are_both_stored_in_one_wing(
    monkeypatch, config, palace_path, kg, first, second
):
    from mempalace_code.mcp.tools.write import tool_add_drawer

    _patch_runtime(monkeypatch, config, palace_path, kg)

    stored = _call(tool_add_drawer, wing="project_a", room="decisions", content=first)
    other = _call(tool_add_drawer, wing="project_a", room="decisions", content=second)

    assert stored["success"] is True
    assert other["success"] is True


def test_identical_text_in_another_wing_is_stored_and_a_same_wing_repeat_is_refused(
    monkeypatch, config, palace_path, kg
):
    from mempalace_code.mcp.tools.write import tool_add_drawer

    _patch_runtime(monkeypatch, config, palace_path, kg)
    first = _call(tool_add_drawer, wing="project_a", room="decisions", content=SQLITE)
    other = _call(tool_add_drawer, wing="project_b", room="decisions", content=SQLITE)
    assert first["success"] is True
    assert other["success"] is True

    # The exact proof must not depend on semantic ranking returning the stored drawer.
    def no_neighbours(self, *args, **kwargs):
        return {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}

    monkeypatch.setattr(LanceStore, "query", no_neighbours)
    repeat = _call(tool_add_drawer, wing="project_a", room="experiments", content=SQLITE)

    assert repeat["success"] is False
    assert repeat["reason"] == "duplicate"
    assert [match["id"] for match in repeat["matches"]] == [first["drawer_id"]]


def test_check_duplicate_stays_compatible_and_scopes_exact_matches(
    monkeypatch, config, palace_path, kg
):
    from mempalace_code.mcp.tools.search import tool_check_duplicate
    from mempalace_code.mcp.tools.write import tool_add_drawer

    _patch_runtime(monkeypatch, config, palace_path, kg)
    stored = _call(tool_add_drawer, wing="project_a", room="decisions", content=SQLITE)

    plain = tool_check_duplicate(SQLITE)
    with_threshold = tool_check_duplicate(SQLITE, 0.95)
    other_wing = tool_check_duplicate(SQLITE, wing="project_b")
    opposite = tool_check_duplicate(NOT_SQLITE, wing="project_a")

    assert plain["is_duplicate"] is True
    assert [match["id"] for match in plain["same_facts"]] == [stored["drawer_id"]]
    assert with_threshold["is_duplicate"] is True
    assert other_wing["is_duplicate"] is False
    assert other_wing["same_facts"] == []
    assert opposite["is_duplicate"] is False
    assert opposite["same_facts"] == []
    assert "matches" in opposite


# Search provenance


def test_search_hits_expose_stored_provenance_without_inventing_it(palace_path):
    from mempalace_code.searcher import search_memories

    store = open_store(palace_path, create=True)
    store.add(
        ids=["mined_auth", "manual_note"],
        documents=[
            "def authenticate(token): validate the session token and return the user",
            "Session tokens expire after one day; decided in the security review.",
        ],
        metadatas=[
            {
                "wing": "project",
                "room": "backend",
                "source_file": "/project/src/auth.py",
                "chunk_index": 0,
                "added_by": "miner",
                "filed_at": "2026-01-01T00:00:00",
                "ingest_mode": "file",
                "source_hash": "0123456789abcdef0123456789abcdef",
                "extractor_version": "1.13.8",
                "chunker_strategy": "treesitter_v3",
            },
            {
                "wing": "project",
                "room": "decisions",
                "source_file": "",
                "chunk_index": 0,
                "added_by": "mcp",
                "filed_at": "2026-02-01T00:00:00",
                "chunker_strategy": "manual_v1",
            },
        ],
    )

    result = search_memories("session token", palace_path, wing="project", n_results=5)

    hits = {hit["id"]: hit for hit in result["results"]}
    assert hits["mined_auth"]["provenance"] == {
        "filed_at": "2026-01-01T00:00:00",
        "extractor_version": "1.13.8",
        "source_hash": "0123456789abcdef0123456789abcdef",
        "chunker_strategy": "treesitter_v3",
    }
    assert hits["manual_note"]["provenance"]["source_hash"] is None
    assert hits["manual_note"]["provenance"]["extractor_version"] is None
    assert hits["manual_note"]["provenance"]["chunker_strategy"] == "manual_v1"


# Recovery points


def test_degraded_pre_watch_backup_refuses_start_and_keeps_the_archive(
    tmp_path, monkeypatch, capsys
):
    from mempalace_code import watcher

    forensic = tmp_path / "pre_watch_20261017_000000_000000_DEGRADED.tar.gz"
    forensic.write_bytes(b"forensic copy")

    def degraded_backup(*args, **kwargs):
        return {"degraded": True, "degraded_error": "kg_corrupt: test"}, str(forensic)

    monkeypatch.setattr(watcher, "create_backup", degraded_backup)
    with pytest.raises(SystemExit) as exc_info:
        watcher._create_pre_watch_backup(str(tmp_path / "palace"), str(tmp_path / "kg"), "RUN")

    assert exc_info.value.code == 1
    assert forensic.read_bytes() == b"forensic copy"
    output = capsys.readouterr()
    combined = output.out + output.err
    assert "pre-watch-backup-degraded" in combined
    assert "not a recovery point" in combined


def test_healthy_pre_watch_backup_is_used(tmp_path, monkeypatch):
    from mempalace_code import watcher

    archive = str(tmp_path / "pre_watch_20261017_000000_000000.tar.gz")
    monkeypatch.setattr(watcher, "create_backup", lambda *a, **k: ({"degraded": False}, archive))

    palace, kg_file = str(tmp_path / "palace"), str(tmp_path / "kg")
    assert watcher._create_pre_watch_backup(palace, kg_file, "RUN") == archive


def test_degraded_pre_optimize_backup_refuses_optimize_and_keeps_the_archive(
    palace_path, monkeypatch
):
    from mempalace_code import backup

    store = open_store(palace_path, create=True)
    store.add(
        ids=["kept"],
        documents=["A drawer that must survive a refused optimize."],
        metadatas=[{"wing": "w", "room": "r"}],
    )
    forensic = Path(palace_path).parent / "pre_optimize_20261017_000000_000000_DEGRADED.tar.gz"
    forensic.write_bytes(b"forensic copy")

    def degraded_backup(*args, **kwargs):
        return {"degraded": True}, str(forensic)

    monkeypatch.setattr(backup, "create_backup", degraded_backup)

    assert store.safe_optimize(palace_path, backup_first=True) is False
    assert forensic.read_bytes() == b"forensic copy"
    assert store.count() == 1


# Packaged skill


def test_packaged_skill_retrieval_needs_only_search_and_offers_cli_fallback():
    from mempalace_code.agent_plugins import SKILL_PATH, get_agent_plugin_root

    skill = (get_agent_plugin_root() / SKILL_PATH).read_text(encoding="utf-8")
    normalized = " ".join(skill.lower().split())

    assert "use this skill only when the mcp client exposes these tools" not in normalized
    assert "retrieval needs only `mempalace_search`" in normalized
    assert 'mempalace-code search "<query>" --wing <wing> --results 3 --json' in skill
    assert "never drop or invent the filter" in normalized
    assert "evidence, not authority" in normalized
    assert "trivial edits" in normalized
    assert "identical text already in that wing" in normalized


@pytest.mark.parametrize("marker", ["nested", "unknown"])
def test_changed_full_mine_preserves_excluded_architecture_support(
    tmp_path, kg, monkeypatch, marker
):
    project = _project(tmp_path)
    nested = project / "lib"
    nested.mkdir()
    nested_source = nested / "unique.py"
    nested_source.write_text(WIDGET.replace("Widget", "UniqueRepository"))
    palace = tmp_path / "palace"
    _mine(project, palace, include_ignored=[".tasks"], kg=kg)
    # Include unique open evidence and closed history under the excluded prefix.
    kg.add_triple(
        "UniqueRepository", "is_pattern", "private-pattern", source_file=str(nested_source)
    )
    kg.add_triple("OldRepository", "is_pattern", "closed-pattern", source_file=str(nested_source))
    kg.invalidate("OldRepository", "is_pattern", "closed-pattern")
    from mempalace_code.architecture import namespace_project_source_file

    kg.add_triple(
        "UniqueRepository", "in_namespace", "Unique.Space", source_file=str(nested_source)
    )
    kg.add_triple(
        "Unique.Space", "in_project", "proj", source_file=namespace_project_source_file("proj")
    )
    before = [r for r in _kg_dump(kg)["triples"] if str(nested_source) in r]
    if marker == "nested":
        (nested / ".git").mkdir()
    else:
        real = scanner.nested_git_marker
        monkeypatch.setattr(
            scanner, "nested_git_marker", lambda path: "unknown" if path == nested else real(path)
        )
    (project / "src" / "widget.py").write_text(WIDGET.replace("Widget", "ChangedService"))
    _mine(project, palace, kg=kg)
    assert [r for r in _kg_dump(kg)["triples"] if str(nested_source) in r] == before
    assert any(
        f["subject"] == "Unique.Space" and f["valid_to"] is None
        for f in kg.query_relationship("in_project")
    )
    assert any(
        f["subject"] == "ChangedService" and f["valid_to"] is None
        for f in kg.query_relationship("in_project")
    )
    assert all(
        f["valid_to"] is not None
        for f in kg.query_relationship("in_project")
        if f["subject"] == "Widget"
    )


@pytest.mark.parametrize("strategy", ["manual_v1", "diary_v1", "future_v9", ""])
def test_file_mode_does_not_authorize_unknown_or_manual_strategy(strategy):
    from mempalace_code.mining.orchestrator import _is_current_generated_row

    row = {"ingest_mode": "file", "type": "", "source_hash": "a" * 32, "chunker_strategy": strategy}
    assert _is_current_generated_row(row, "a" * 32) is False


@pytest.mark.parametrize("metadata", [None, [], "healthy"])
def test_invalid_backup_metadata_refuses_maintenance_and_watch(
    palace_path, tmp_path, monkeypatch, metadata
):
    from mempalace_code import backup, watcher

    store = open_store(palace_path)
    store.add(ids=["kept"], documents=["Keep this drawer"], metadatas=[{}])
    archive = str(tmp_path / "archive.tar.gz")
    monkeypatch.setattr(backup, "create_backup", lambda *a, **k: (metadata, archive))
    monkeypatch.setattr(watcher, "create_backup", lambda *a, **k: (metadata, archive))
    assert store.safe_optimize(palace_path, backup_first=True) is False
    assert store.get(ids=["kept"])["ids"] == ["kept"]
    with pytest.raises(SystemExit) as exc:
        watcher._create_pre_watch_backup(palace_path, str(tmp_path / "kg"), "RUN")
    assert exc.value.code == 1


def test_stream_refuses_same_thread_cleanup_but_allows_writes(palace_path):
    from mempalace_code.operation_lock import palace_write_lease

    store = open_store(palace_path)
    store.add(ids=["a", "b"], documents=["alpha", "beta"], metadatas=[{}, {}])
    stream = store.iter_all(batch_size=1)
    first = next(stream)
    with palace_write_lease(palace_path, "mine", wait=0):
        store.add(ids=["c"], documents=["gamma"], metadatas=[{}])
    result = store.cleanup_stale_fragments(older_than_days=0)
    assert result["ok"] is False
    assert result["deferred"] is True
    assert sorted(row["id"] for batch in [first, *stream] for row in batch) == ["a", "b"]
    assert store.cleanup_stale_fragments(older_than_days=0)["ok"] is True


def test_stale_handle_is_refreshed_before_projected_scan_and_stream(palace_path):
    store = open_store(palace_path)
    store.add(ids=["a"], documents=["alpha"], metadatas=[{"wing": "fixture"}])
    stale = open_store(palace_path, create=False, read_only=True)
    stale._require_table().checkout(1)
    store.add(ids=["b"], documents=["beta"], metadatas=[{"wing": "fixture"}])
    projected = stale.scan_wing_metadata("fixture", ["id"])
    assert projected is not None
    assert sorted(r["id"] for r in projected) == ["a", "b"]
    assert sorted(row["id"] for batch in stale.iter_all() for row in batch) == ["a", "b"]


def test_reader_fence_covers_stream_in_another_process(palace_path):
    import os
    import subprocess
    import sys

    from mempalace_code.operation_lock import palace_write_lease

    store = open_store(palace_path)
    store.add(ids=["a", "b"], documents=["alpha", "beta"], metadatas=[{}, {}])
    script = """
import sys
from mempalace_code.storage import open_store
s = open_store(sys.argv[1], create=False, read_only=True)
stream = s.iter_all(batch_size=1)
first = next(stream)
print("ready", flush=True)
sys.stdin.readline()
assert sorted(r["id"] for b in [first, *stream] for r in b) == ["a", "b"]
"""
    with subprocess.Popen(
        [sys.executable, "-c", script, palace_path],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=os.environ.copy(),
    ) as child:
        try:
            assert child.stdout is not None
            assert child.stdout.readline().strip() == "ready"
            with palace_write_lease(palace_path, "mine", wait=0):
                store.add(ids=["c"], documents=["gamma"], metadatas=[{}])
                assert store.get(ids=["c"])["ids"] == ["c"]
            result = store.cleanup_stale_fragments(older_than_days=0)
            assert result["ok"] is False
            assert result["deferred"] is True
        finally:
            _, errors = child.communicate("release\n", timeout=30)
        assert child.returncode == 0, errors
    assert store.cleanup_stale_fragments(older_than_days=0)["ok"] is True


def test_reconcile_noop_path_runs_supported_maintenance_once(tmp_path, monkeypatch):
    from mempalace_code import backup, storage

    project = _project(tmp_path)
    _with_task_copy(project)
    palace = tmp_path / "palace"
    _mine(project, palace, include_ignored=[".tasks"])
    original_backup = backup.create_backup
    backups = []

    def counted_backup(*args, **kwargs):
        backups.append(kwargs.get("kind"))
        return original_backup(*args, **kwargs)

    monkeypatch.setattr(backup, "create_backup", counted_backup)
    monkeypatch.setenv("MEMPALACE_OPTIMIZE_AFTER_MINE", "1")
    waits = []
    monkeypatch.setattr(orchestrator.time, "sleep", waits.append)
    result = mine(str(project), str(palace), skip_optimize=False)
    assert result["drawers_filed"] == 0
    assert result["copy_rows_removed"] > 0
    assert backups == ["pre_optimize"]
    assert waits == [storage.READER_VERSION_GRACE.total_seconds() + 0.1]
    disk = result["copy_disk"]
    assert disk["maintenance"]["ok"] is True
    assert isinstance(disk["on_disk_bytes_before"], int)
    assert isinstance(disk["on_disk_bytes_after"], int)
    assert disk["disk_reclaimed"] == (disk["on_disk_bytes_after"] < disk["on_disk_bytes_before"])
    # This test omits elapsed grace and verifies routing/measurement only.
    removal = next(record for record in _records(palace) if record["event"] == "remove")
    alias = removal["sources"][0]["aliases"][0]
    assert alias["id"]
    assert alias["room"] == "general"
    assert alias["filed_at"]
    completion = next(record for record in _records(palace) if record["event"] == "removed")
    assert completion["alias_record_timestamp"] == removal["timestamp"]
    assert all("aliases" not in source for source in completion["sources"])
    assert "Lance table files" in disk["measurement_scope"]


def test_missing_fcntl_keeps_reads_and_refuses_version_prune(palace_path, monkeypatch):
    from mempalace_code import operation_lock

    store = open_store(palace_path)
    store.add(ids=["kept"], documents=["local record"], metadatas=[{}])
    monkeypatch.setattr(operation_lock, "fcntl", None)
    assert store.get(ids=["kept"])["ids"] == ["kept"]
    assert store.cleanup_stale_fragments(older_than_days=0)["ok"] is False


def test_nested_streams_keep_fence_when_closed_out_of_order(palace_path):
    store = open_store(palace_path)
    store.add(ids=["a", "b"], documents=["alpha", "beta"], metadatas=[{}, {}])
    first, second = store.iter_all(batch_size=1), store.iter_all(batch_size=1)
    next(first)
    next(second)
    first.close()
    assert store.cleanup_stale_fragments(older_than_days=0)["deferred"] is True
    second.close()
    assert store.cleanup_stale_fragments(older_than_days=0)["ok"] is True


def test_empty_ingest_mode_is_not_proof_of_generated_ownership(tmp_path):
    project = _project(tmp_path)
    task = _with_task_copy(project)
    palace = tmp_path / "palace"
    _mine(project, palace, include_ignored=[".tasks"])
    store = open_store(str(palace), create=False)
    paths = [str(project / "src/widget.py"), str(task / "src/widget.py")]
    rows = store.get(where={"source_file": {"$in": paths}}, include=["documents", "metadatas"])
    meta = [{**m, "ingest_mode": ""} for m in rows["metadatas"]]
    store.upsert(ids=rows["ids"], documents=rows["documents"], metadatas=meta)
    before = set(store.get()["ids"])
    result = _mine(project, palace)
    assert result["copy_rows_removed"] == 0
    assert set(store.get()["ids"]) == before


@pytest.mark.parametrize("interrupted", [False, True])
@pytest.mark.parametrize(
    "record_tail",
    [
        pytest.param(b"", id="complete"),
        pytest.param(b'{"partial":', id="interrupted-tail"),
        pytest.param(b"x" * 70000, id="oversized-tail"),
    ],
)
def test_unchanged_mine_retries_maintenance_after_last_copy_delete(
    tmp_path, monkeypatch, interrupted, record_tail
):
    from mempalace_code import storage
    from mempalace_code.mining import orchestrator

    project = _project(tmp_path)
    _with_task_copy(project)
    palace = tmp_path / "palace"
    _mine(project, palace, include_ignored=[".tasks"])
    monkeypatch.setenv("MEMPALACE_OPTIMIZE_AFTER_MINE", "1")
    waits = []
    monkeypatch.setattr(orchestrator.time, "sleep", waits.append)
    actual = storage.LanceStore.cleanup_stale_fragments
    attempts = []
    busy = [True]

    def defer_once(self, *args, **kwargs):
        attempts.append(1)
        if busy[0]:
            if interrupted:
                raise KeyboardInterrupt
            return {"ok": False, "deferred": True, "freed_bytes": 0, "error": "active reader"}
        return actual(self, *args, **kwargs)

    monkeypatch.setattr(storage.LanceStore, "cleanup_stale_fragments", defer_once)
    if interrupted:
        with pytest.raises(KeyboardInterrupt):
            mine(str(project), str(palace), skip_optimize=False)
    else:
        first = mine(str(project), str(palace), skip_optimize=False)
        assert first["copy_rows_removed"] > 0
        assert first["copy_disk"]["maintenance"]["deferred"] is True
    first_attempts = len(attempts)
    first_waits = len(waits)
    if record_tail:
        with orchestrator._copy_reconcile_record_path(str(palace)).open("ab") as handle:
            handle.write(record_tail)
    busy[0] = False
    rows = set(open_store(str(palace), create=False).get()["ids"])
    second = mine(str(project), str(palace), skip_optimize=False)
    assert len(attempts) > first_attempts
    assert len(waits) == first_waits
    assert second["drawers_filed"] == 0
    assert second["copy_rows_removed"] == 0
    assert second["copy_disk"]["maintenance"] is not None
    assert set(open_store(str(palace), create=False).get()["ids"]) == rows


def test_snapshot_open_failure_keeps_structured_health_and_originals(palace_path, monkeypatch):
    store = open_store(palace_path)
    store.add(ids=["original"], documents=["Independent original record"], metadatas=[{}])

    def refuse(*args, **kwargs):
        raise RuntimeError("current table unavailable")

    with monkeypatch.context() as fault:
        fault.setattr(type(store._db), "open_table", refuse)
        health = store.health_check()
        assert health["ok"] is False
        assert health["errors"][0]["probe"] == "table_open"
        assert "current table unavailable" in health["errors"][0]["message"]
        cleanup = store.cleanup_stale_fragments(older_than_days=0)
        assert cleanup["ok"] is False
        assert cleanup["freed_bytes"] == 0
    assert store.get(ids=["original"])["ids"] == ["original"]


def test_failed_alias_directory_publication_preserves_copy_rows(tmp_path, monkeypatch):
    import os
    import stat

    project = _project(tmp_path)
    task = _with_task_copy(project)
    palace = tmp_path / "palace"
    _mine(project, palace, include_ignored=[".tasks"])
    before = _rows(palace)
    actual_fsync = os.fsync

    def cannot_publish_directory(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError("synthetic directory publication failure")
        return actual_fsync(fd)

    monkeypatch.setattr(os, "fsync", cannot_publish_directory)
    result = _mine(project, palace)
    assert result["copy_rows_removed"] == 0
    assert result["copy_reconcile_refusal"]
    assert _rows(palace)[str(task / "src/widget.py")] == before[str(task / "src/widget.py")]


def test_removed_technical_report_is_preserved_as_original_evidence(tmp_path):
    project = _project(tmp_path)
    task = _with_task_copy(project)
    palace = tmp_path / "palace"
    report = task / "astra-billing-review.md"
    _mine(project, palace, include_ignored=[".tasks"])
    before = _rows(palace)[str(report)]
    report.unlink()
    _mine(project, palace)
    assert _rows(palace)[str(report)] == before


def test_removed_technical_code_keeps_original_open_architecture_facts(tmp_path, kg):
    from mempalace_code.architecture import ARCH_PREDICATES

    project = _project(tmp_path)
    task = _with_task_copy(project)
    source = task / "rejected.cs"
    source.write_text(
        "namespace Rejected;\npublic class ShadowReplay { public int Id { get; set; } }\n",
        encoding="utf-8",
    )
    palace = tmp_path / "palace"
    _mine(project, palace, include_ignored=[".tasks"], kg=kg)
    before = {
        (fact["subject"], predicate, fact["object"])
        for predicate in ARCH_PREDICATES
        for fact in kg.query_relationship(predicate)
        if fact.get("source_file") == str(source) and fact.get("valid_to") is None
    }
    assert before
    source.unlink()
    (project / "src/widget.py").write_text(WIDGET + "\n# Current canonical source change\n")
    _mine(project, palace, kg=kg)
    after = {
        (fact["subject"], predicate, fact["object"])
        for predicate in ARCH_PREDICATES
        for fact in kg.query_relationship(predicate)
        if fact.get("source_file") == str(source) and fact.get("valid_to") is None
    }
    assert before <= after
    assert str(source) in _rows(palace)


def test_equal_generated_chunks_from_previous_extractor_version_reconcile(tmp_path):
    project = _project(tmp_path)
    task = _with_task_copy(project)
    palace = tmp_path / "palace"
    _mine(project, palace, include_ignored=[".tasks"])
    store = open_store(str(palace), create=False)
    copy_file = str(task / "src/widget.py")
    found = store.get(where={"source_file": copy_file}, include=["documents", "metadatas"])
    store.upsert(
        ids=found["ids"],
        documents=found["documents"],
        metadatas=[{**meta, "extractor_version": "1.16.0"} for meta in found["metadatas"]],
    )
    result = _mine(project, palace)
    assert result["copy_rows_removed"] == len(found["ids"])
    aliases = [r for r in _records(palace) if r["event"] == "remove"][0]["sources"][0]["aliases"]
    assert {a["extractor_version"] for a in aliases} == {"1.16.0"}


@pytest.mark.parametrize("operation", ["backup-restore", "rebuild"])
def test_copy_provenance_survives_existing_data_lifecycle(tmp_path, operation):
    from mempalace_code.backup import create_backup, restore_backup

    project = _project(tmp_path)
    _with_task_copy(project)
    palace = tmp_path / "palace"
    _mine(project, palace, include_ignored=[".tasks"])
    _mine(project, palace)
    record = orchestrator._copy_reconcile_record_path(str(palace)).read_bytes()
    destination = tmp_path / "destination"
    store = open_store(str(palace), create=False)
    original_ids = set(store.get()["ids"])
    if operation == "backup-restore":
        _, archive = create_backup(str(palace), kind="manual")
        restore_backup(archive, str(destination))
    else:
        stored = store.read_all_for_rebuild()
        store.write_rebuilt_table(str(destination), stored["rows"])
    assert orchestrator._copy_reconcile_record_path(str(destination)).read_bytes() == record
    assert set(open_store(str(destination), create=False).get()["ids"]) == original_ids


def test_compact_retry_does_not_create_another_backup(tmp_path, monkeypatch):
    from mempalace_code import backup, storage

    project = _project(tmp_path)
    _with_task_copy(project)
    palace = tmp_path / "palace"
    _mine(project, palace, include_ignored=[".tasks"])
    actual = backup.create_backup
    calls = []

    def counted(*args, **kwargs):
        calls.append(kwargs.get("kind"))
        return actual(*args, **kwargs)

    monkeypatch.setattr(backup, "create_backup", counted)
    monkeypatch.setenv("MEMPALACE_OPTIMIZE_AFTER_MINE", "1")
    monkeypatch.setattr(orchestrator.time, "sleep", lambda _: None)
    first = mine(str(project), str(palace), skip_optimize=False)
    assert first["copy_rows_removed"] > 0
    before = len(calls)
    second = mine(str(project), str(palace), skip_optimize=False)
    assert len(calls) == before
    assert second["drawers_filed"] == 0
    assert open_store(str(palace), create=False).storage_stats()["version_count"] > 1
    assert storage.READER_VERSION_GRACE.total_seconds() > 0


@pytest.mark.parametrize("entrypoint", ["watch_and_mine", "watch_all"])
def test_reader_grace_keeps_copy_retry_pending_until_physical_prune(
    tmp_path, monkeypatch, entrypoint
):
    import time

    import watchfiles
    from watchfiles import Change

    from mempalace_code import backup, storage
    from mempalace_code import watcher as watcher_module
    from mempalace_code.knowledge_graph import KnowledgeGraph, palace_kg_path

    project = _project(tmp_path)
    _with_task_copy(project)
    palace = tmp_path / "palace"
    monkeypatch.setenv("MEMPALACE_OPTIMIZE_AFTER_MINE", "0")
    _mine(project, palace, include_ignored=[".tasks"])
    removed = _mine(project, palace)
    assert removed["copy_rows_removed"] > 0
    store = open_store(str(palace), create=False)
    store.add(
        ids=["operator-note"],
        documents=["Keep the original rejected decision and its reason."],
        metadatas=[{"wing": "proj", "room": "decisions", "ingest_mode": "manual"}],
    )
    kg = KnowledgeGraph(palace_kg_path(str(palace)))
    kg.add_triple("candidate", "review_status", "rejected", source_file="manual-review")
    facts = _kg_dump(kg)
    kept_ids = set(store.get()["ids"])
    aliases = [record for record in _records(palace) if record["event"] == "remove"]
    actual_backup = backup.create_backup
    backups = []

    def counted_backup(*args, **kwargs):
        backups.append(kwargs.get("kind"))
        return actual_backup(*args, **kwargs)

    monkeypatch.setattr(backup, "create_backup", counted_backup)
    monkeypatch.setenv("MEMPALACE_OPTIMIZE_AFTER_MINE", "1")

    monkeypatch.setattr(watcher_module, "create_backup", counted_backup)

    def batches(*args, **kwargs):
        # The actual initial mine and cleanup ran before entering the event loop.
        maintenance = _records(palace)[-1]["maintenance"]
        assert maintenance["ok"] is True
        assert maintenance["version_count_after"] > 1
        assert maintenance["versions_kept_for_readers"] > 0
        assert orchestrator._copy_maintenance_due(str(palace))
        before = store.storage_stats()["on_disk_bytes"]
        time.sleep(storage.READER_VERSION_GRACE.total_seconds() + 1)
        # A duplicate event changes no file and files no new drawers.
        yield {(Change.modified, str(project / "src/widget.py"))}
        assert store.storage_stats()["on_disk_bytes"] < before
        assert store.storage_stats()["version_count"] == 1
        assert set(store.get()["ids"]) == kept_ids
        assert not orchestrator._copy_maintenance_due(str(palace))
        record = orchestrator._copy_reconcile_record_path(str(palace))
        settled = record.read_bytes()
        yield {(Change.modified, str(project / "src/widget.py"))}
        assert record.read_bytes() == settled

    monkeypatch.setattr(watchfiles, "watch", batches)
    if entrypoint == "watch_and_mine":
        watcher_module.watch_and_mine(str(project), str(palace))
    else:
        watcher_module.watch_all(str(project), str(palace), on_commit=False)
    assert backups.count("pre_optimize") == 1
    assert backups.count("pre_watch") == 1
    assert set(store.get()["ids"]) == kept_ids
    assert [record for record in _records(palace) if record["event"] == "remove"] == aliases
    assert _kg_dump(kg) == facts


def test_legacy_success_hint_settles_once_from_current_single_version(tmp_path, monkeypatch):
    palace = tmp_path / "palace"
    record = orchestrator._copy_reconcile_record_path(str(palace))
    record.parent.mkdir(parents=True)
    record.write_text(json.dumps({"event": "summary", "maintenance": {"ok": True}}) + "\n")
    monkeypatch.setenv("MEMPALACE_OPTIMIZE_AFTER_MINE", "1")
    reads = []

    class SettledStore:
        def storage_stats(self):
            reads.append(True)
            return {"latest_version_compact": True, "version_count": 1}

    assert orchestrator._copy_maintenance_due(str(palace))
    store = SettledStore()
    orchestrator._run_copy_reconcile(store, "proj", [], str(palace), None, False)
    assert not orchestrator._copy_maintenance_due(str(palace))
    settled = record.read_bytes()
    orchestrator._run_copy_reconcile(store, "proj", [], str(palace), None, False)
    assert record.read_bytes() == settled
    assert reads == [True]


def test_nested_reader_refreshes_each_store_handle(palace_path):
    first = open_store(palace_path)
    first.add(ids=["original"], documents=["Independent original"], metadatas=[{}])
    second = open_store(palace_path, create=False)

    class StaleTable:
        def __getattr__(self, name):
            raise RuntimeError("stale snapshot handle was used")

    second._table = cast("Any", StaleTable())
    stream = first.iter_all(batch_size=1)
    next(stream)
    try:
        assert second.get(ids=["original"])["ids"] == ["original"]
    finally:
        stream.close()


def test_interrupted_copy_record_does_not_corrupt_next_entry(tmp_path):
    record = tmp_path / "lance" / "copy_reconcile.jsonl"
    record.parent.mkdir()
    partial = b'{"interrupted":'
    record.write_bytes(partial)
    assert orchestrator._append_copy_record(record, {"complete": True})
    lines = record.read_bytes().splitlines()
    assert lines[0] == partial
    assert json.loads(lines[1]) == {"complete": True}


@pytest.mark.parametrize("ordinary_write", ["changed-file", "api-add"])
def test_completed_reconcile_does_not_force_backups_for_later_ordinary_writes(
    tmp_path, monkeypatch, ordinary_write
):
    from mempalace_code import backup, storage

    project = _project(tmp_path)
    _with_task_copy(project)
    palace = tmp_path / "palace"
    _mine(project, palace, include_ignored=[".tasks"])
    monkeypatch.setenv("MEMPALACE_OPTIMIZE_AFTER_MINE", "1")
    monkeypatch.setenv("MEMPALACE_AUTO_BACKUP_BEFORE_OPTIMIZE", "0")
    monkeypatch.setenv("MEMPALACE_BACKUP_BEFORE_OPTIMIZE", "0")
    real_sleep = orchestrator.time.sleep
    monkeypatch.setattr(orchestrator.time, "sleep", lambda _: None)
    first = mine(str(project), str(palace), skip_optimize=False)
    assert first["copy_rows_removed"] > 0
    assert first["copy_disk"]["maintenance"]["ok"] is True
    # Establish completion before testing later ordinary writes. An ok reader-safe
    # no-op within grace does not establish this test's completed-state premise.
    real_sleep(storage.READER_VERSION_GRACE.total_seconds() + 1)
    store = open_store(str(palace), create=False)
    orchestrator._run_copy_reconcile(store, "proj", [], str(palace), None, False)
    assert store.storage_stats()["version_count"] == 1
    assert not orchestrator._copy_maintenance_due(str(palace))
    actual_backup = backup.create_backup
    calls = []

    def counted(*args, **kwargs):
        calls.append(kwargs.get("kind"))
        return actual_backup(*args, **kwargs)

    monkeypatch.setattr(backup, "create_backup", counted)
    if ordinary_write == "changed-file":
        (project / "src/widget.py").write_text(WIDGET + "\n# Ordinary source update\n")
    else:
        store = open_store(str(palace), create=False)
        store.add(
            ids=["ordinary-note"], documents=["Independent later ordinary note"], metadatas=[{}]
        )
        assert store.storage_stats()["latest_version_compact"] is False
    mine(str(project), str(palace), skip_optimize=False)
    assert calls == []
    if ordinary_write == "api-add":
        assert open_store(str(palace), create=False).get(ids=["ordinary-note"])["ids"] == [
            "ordinary-note"
        ]


def test_changed_mine_keeps_normal_backup_policy_while_old_reader_defers_prune(
    tmp_path, monkeypatch
):
    from mempalace_code import backup

    project = _project(tmp_path)
    _with_task_copy(project)
    palace = tmp_path / "palace"
    _mine(project, palace, include_ignored=[".tasks"])
    monkeypatch.setenv("MEMPALACE_OPTIMIZE_AFTER_MINE", "1")
    monkeypatch.setenv("MEMPALACE_AUTO_BACKUP_BEFORE_OPTIMIZE", "0")
    monkeypatch.setenv("MEMPALACE_BACKUP_BEFORE_OPTIMIZE", "0")
    monkeypatch.setattr(orchestrator.time, "sleep", lambda _: None)
    store = open_store(str(palace), create=False)
    reader = store.iter_all(batch_size=1)
    next(reader)
    try:
        first = mine(str(project), str(palace), skip_optimize=False)
        assert first["copy_rows_removed"] > 0
        assert first["copy_disk"]["maintenance"]["deferred"] is True
        actual_backup = backup.create_backup
        calls = []

        def counted(*args, **kwargs):
            calls.append(kwargs.get("kind"))
            return actual_backup(*args, **kwargs)

        monkeypatch.setattr(backup, "create_backup", counted)
        (project / "src/widget.py").write_text(WIDGET + "\n# Later ordinary change\n")
        mine(str(project), str(palace), skip_optimize=False)
        assert calls == []
    finally:
        reader.close()


def test_whole_fragment_delete_eventually_prunes_after_real_reader_grace(tmp_path, monkeypatch, kg):
    import time

    from mempalace_code.storage import READER_VERSION_GRACE

    project = _project(tmp_path)
    task = _with_task_copy(project)
    palace = tmp_path / "palace"
    _mine(project, palace, kg=kg)
    store = open_store(str(palace), create=False)
    original = store.get(
        where={"source_file": str(project / "src/widget.py")}, include=["documents", "metadatas"]
    )
    assert original["ids"]
    store.add(ids=["manual-original"], documents=["Preserve independent original"], metadatas=[{}])
    kg.add_triple("OriginalDecision", "status", "rejected", source_file="manual:decision")
    keep = set(store.get()["ids"])
    facts = _kg_dump(kg)
    copy_ids = [f"legacy-copy-{i}" for i in range(len(original["ids"]))]
    store.add(
        ids=copy_ids,
        documents=original["documents"],
        metadatas=[
            {**m, "source_file": str(task / "src/widget.py")} for m in original["metadatas"]
        ],
    )
    monkeypatch.setenv("MEMPALACE_OPTIMIZE_AFTER_MINE", "1")

    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt("Synthetic interruption after committed copy deletion")

    with monkeypatch.context() as fault:
        fault.setattr(orchestrator, "optimize_store", interrupted)
        with pytest.raises(KeyboardInterrupt, match="after committed copy deletion"):
            mine(str(project), str(palace), skip_optimize=False, kg=kg)
    before = store.storage_stats()
    assert before["current_deletion_files"] == 0
    assert before["current_data_files"] >= 2
    assert not store.get(ids=copy_ids)["ids"]
    retry = mine(str(project), str(palace), skip_optimize=False, kg=kg)
    assert retry["drawers_filed"] == 0
    assert retry["copy_rows_removed"] == 0
    assert retry["copy_disk"]["maintenance"] is not None
    assert store.storage_stats()["current_data_files"] == 1
    time.sleep(READER_VERSION_GRACE.total_seconds() + 0.25)
    mine(str(project), str(palace), skip_optimize=False, kg=kg)
    after = store.storage_stats()
    assert after["version_count"] == 1
    assert after["on_disk_bytes"] < before["on_disk_bytes"]
    assert set(store.get()["ids"]) == keep
    assert _kg_dump(kg) == facts


# Watcher batch maintenance


def _fake_watch(batches: list):
    def watch(*args, stop_event=None, **kwargs):
        yield from batches

    return watch


def _watch(entrypoint: str, project: Path, palace: Path, batches: list, kg=None) -> None:
    from unittest.mock import patch

    from mempalace_code import watcher

    with (
        patch("watchfiles.watch", side_effect=_fake_watch(batches)),
        patch("mempalace_code.disk_budget.free_bytes", return_value=10 * 1024**3),
    ):
        if entrypoint == "watch_and_mine":
            watcher.watch_and_mine(str(project), str(palace), kg=kg)
        else:
            watcher.watch_all(str(project), str(palace), on_commit=False)


def _pending_copy_removal(tmp_path: Path, monkeypatch) -> tuple[Path, Path]:
    """Remove a stored exact copy without maintenance, as a watcher mine leaves it."""
    from mempalace_code import watcher

    project = _project(tmp_path)
    _with_task_copy(project)
    palace = tmp_path / "palace"
    _mine(project, palace, include_ignored=[".tasks"])
    assert _mine(project, palace)["copy_sources_removed"] == 1
    assert orchestrator._copy_maintenance_due(str(palace))
    # The startup recovery point is covered elsewhere; keep it out of these counts.
    archive = str(tmp_path / "pre_watch.tar.gz")
    monkeypatch.setattr(watcher, "create_backup", lambda *a, **k: ({"degraded": False}, archive))
    return project, palace


@pytest.mark.parametrize("entrypoint", ["watch_and_mine", "watch_all"])
def test_watcher_batches_remove_copies_and_retry_pending_maintenance(
    tmp_path, monkeypatch, kg, entrypoint
):
    from watchfiles import Change

    from mempalace_code import backup, storage, watcher

    project = _project(tmp_path)
    task = _with_task_copy(project)
    palace = tmp_path / "palace"
    canonical = str(project / "src" / "widget.py")
    copy_file = str(task / "src" / "widget.py")
    report = str(task / "astra-billing-review.md")
    # Records filed while the task directory was still selected.
    _mine(project, palace, include_ignored=[".tasks"], kg=kg)
    store = open_store(str(palace), create=False)
    store.add(
        ids=["manual_note_on_report"],
        documents=["Reviewer note: keep the rejected billing reason for later reviews."],
        metadatas=[
            {
                "wing": "proj",
                "room": "general",
                "source_file": report,
                "chunk_index": 0,
                "added_by": "mcp",
                "filed_at": "2026-10-18T00:00:00",
                "chunker_strategy": "manual_v1",
            }
        ],
    )
    kg.add_triple("BillingCandidate", "status", "rejected", source_file=report)
    copy_ids = set(store.get(where={"source_file": copy_file})["ids"])
    protected = set(store.get()["ids"]) - copy_ids
    first = _rows(palace)
    facts = _kg_dump(kg)
    assert copy_ids
    assert first.get(report)
    assert "manual_note_on_report" in protected

    monkeypatch.setenv("MEMPALACE_OPTIMIZE_AFTER_MINE", "1")
    archive = str(tmp_path / "pre_watch.tar.gz")
    monkeypatch.setattr(watcher, "create_backup", lambda *a, **k: ({"degraded": False}, archive))
    kinds: list = []
    actual_backup = backup.create_backup

    def counted_backup(*args, **kwargs):
        kinds.append(kwargs.get("kind"))
        return actual_backup(*args, **kwargs)

    monkeypatch.setattr(backup, "create_backup", counted_backup)
    actual_cleanup = storage.LanceStore.cleanup_stale_fragments
    unsafe: list = []
    reader = [True]

    def reader_safe_cleanup(self, *args, **kwargs):
        unsafe.append(kwargs.get("unsafe_now"))
        if reader[0]:
            return {"ok": False, "deferred": True, "freed_bytes": 0, "error": "active reader"}
        return actual_cleanup(self, *args, **kwargs)

    monkeypatch.setattr(storage.LanceStore, "cleanup_stale_fragments", reader_safe_cleanup)
    actual_retry = watcher._retry_copy_maintenance
    retries: list = []

    def counted_retry(*args, **kwargs):
        retries.append(args[1])
        return actual_retry(*args, **kwargs)

    monkeypatch.setattr(watcher, "_retry_copy_maintenance", counted_retry)

    # Startup removes only the copy and files nothing, then attempts maintenance. An
    # active reader defers the prune, so an unchanged event batch retries it without
    # removing anything new.
    _watch(entrypoint, project, palace, [{(Change.modified, canonical)}], kg=kg)

    after = _rows(palace)
    assert after == {path: count for path, count in first.items() if path != copy_file}
    assert set(open_store(str(palace), create=False).get()["ids"]) == protected
    assert len(retries) == 2
    assert kinds
    assert set(kinds) == {"pre_optimize"}
    assert unsafe
    assert True not in unsafe
    assert orchestrator._copy_maintenance_due(str(palace))
    aliases = [
        alias
        for record in _records(palace)
        if record["event"] == "remove"
        for source in record["sources"]
        for alias in source["aliases"]
    ]
    assert {alias["id"] for alias in aliases} == copy_ids
    if entrypoint == "watch_and_mine":
        assert _kg_dump(kg) == facts

    # Removing the artificial reader still leaves the real grace fence in force.
    # The real-clock regression above proves eventual settlement at both entrypoints.
    archives = len(kinds)
    reader[0] = False
    _watch(entrypoint, project, palace, [], kg=kg)
    assert len(retries) == 3
    assert orchestrator._copy_maintenance_due(str(palace))
    assert _records(palace)[-1]["maintenance"]["versions_kept_for_readers"] > 0
    # Pending work gets one retry per startup/event batch, without another archive.
    _watch(entrypoint, project, palace, [{(Change.modified, canonical)}], kg=kg)
    assert len(retries) == 5
    assert orchestrator._copy_maintenance_due(str(palace))
    assert len(kinds) == archives
    assert True not in unsafe
    assert _rows(palace) == after
    assert set(open_store(str(palace), create=False).get()["ids"]) == protected
    if entrypoint == "watch_and_mine":
        assert _kg_dump(kg) == facts


@pytest.mark.parametrize("entrypoint", ["watch_and_mine", "watch_all"])
def test_watcher_maintenance_refuses_a_degraded_backup_and_completes_later(
    tmp_path, monkeypatch, entrypoint
):
    from mempalace_code import backup

    project, palace = _pending_copy_removal(tmp_path, monkeypatch)
    ids = set(open_store(str(palace), create=False).get()["ids"])
    rows = _rows(palace)
    monkeypatch.setenv("MEMPALACE_OPTIMIZE_AFTER_MINE", "1")
    forensic = tmp_path / "pre_optimize_20261018_000000_000000_DEGRADED.tar.gz"
    forensic.write_bytes(b"forensic copy")
    actual_backup = backup.create_backup

    def degraded_backup(*args, **kwargs):
        return {"degraded": True}, str(forensic)

    monkeypatch.setattr(backup, "create_backup", degraded_backup)
    _watch(entrypoint, project, palace, [])

    # A degraded archive is no recovery point: nothing is compacted and the record stays.
    assert orchestrator._copy_maintenance_due(str(palace))
    assert _records(palace)[-1]["maintenance"]["ok"] is False
    assert forensic.read_bytes() == b"forensic copy"
    assert set(open_store(str(palace), create=False).get()["ids"]) == ids
    assert _rows(palace) == rows

    monkeypatch.setattr(backup, "create_backup", actual_backup)
    _watch(entrypoint, project, palace, [])

    # A healthy backup authorizes maintenance, while the real reader grace still
    # defers version pruning. Retry after that fence expires without new writes.
    assert orchestrator._copy_maintenance_due(str(palace))
    assert _records(palace)[-1]["maintenance"]["versions_kept_for_readers"] > 0
    import time

    time.sleep(61)
    _watch(entrypoint, project, palace, [])

    assert not orchestrator._copy_maintenance_due(str(palace))
    assert open_store(str(palace), create=False).storage_stats()["version_count"] == 1
    assert _records(palace)[-1]["maintenance"]["ok"] is True
    assert set(open_store(str(palace), create=False).get()["ids"]) == ids
    assert _rows(palace) == rows


@pytest.mark.parametrize("entrypoint", ["watch_and_mine", "watch_all"])
def test_watcher_honors_disabled_optimize_for_pending_copy_maintenance(
    tmp_path, monkeypatch, entrypoint
):
    from mempalace_code import backup, storage, watcher

    project, palace = _pending_copy_removal(tmp_path, monkeypatch)
    records = _records(palace)
    monkeypatch.setenv("MEMPALACE_OPTIMIZE_AFTER_MINE", "0")
    calls: list = []

    def refused(name: str):
        def record(*args, **kwargs):
            calls.append(name)
            raise AssertionError(f"{name} must not run while optimize is disabled")

        return record

    monkeypatch.setattr(backup, "create_backup", refused("backup"))
    monkeypatch.setattr(storage.LanceStore, "cleanup_stale_fragments", refused("cleanup"))
    monkeypatch.setattr(watcher, "optimize_store", refused("watcher optimize"))
    monkeypatch.setattr(orchestrator, "optimize_store", refused("copy optimize"))

    _watch(entrypoint, project, palace, [])

    assert calls == []
    assert _records(palace) == records
    assert orchestrator._copy_maintenance_due(str(palace))


# Exact legacy peers of one canonical source


def _peer_project(tmp_path: Path, names: list[str], **kwargs) -> tuple[Path, Path, list[str]]:
    """File task copies of src/widget.py and a unique report beside the first copy."""
    project = _project(tmp_path)
    copies = []
    for name in names:
        path = project / ".tasks" / name / "src" / "widget.py"
        path.parent.mkdir(parents=True)
        path.write_text(WIDGET, encoding="utf-8")
        copies.append(str(path))
    report = project / ".tasks" / names[0] / "astra-billing-review.md"
    report.write_text(REJECTED_REPORT, encoding="utf-8")
    palace = tmp_path / "palace"
    _mine(project, palace, include_ignored=[".tasks"], **kwargs)
    return project, palace, sorted(copies)


def _legacy_snapshot(palace: Path, sources: list[str], **variant: str) -> None:
    """Store each source as one regex_structural_v1 chunk, as an older chunker filed it."""
    store = open_store(str(palace), create=False)
    stored = store.get(
        where={"source_file": {"$in": sources}},
        include=["documents", "metadatas"],
        limit=100000,
    )
    chunks: dict[str, list] = {}
    for row in zip(stored["ids"], stored["documents"], stored["metadatas"]):
        chunks.setdefault(row[2]["source_file"], []).append(row)
    assert sorted(chunks) == sorted(sources)
    ids: list[str] = []
    documents: list[str] = []
    metadatas: list[dict] = []
    extra: list[str] = []
    for rows in chunks.values():
        rows.sort(key=lambda row: row[2]["chunk_index"])
        ids.append(rows[0][0])
        documents.append("".join(row[1] for row in rows))
        metadatas.append(
            {**rows[0][2], **variant, "chunker_strategy": "regex_structural_v1", "chunk_index": 0}
        )
        extra.extend(row[0] for row in rows[1:])
    if extra:
        store.delete(extra)
    store.upsert(ids=ids, documents=documents, metadatas=metadatas)


def _removed(palace: Path) -> dict[str, str]:
    """Map each removed copy to the counterpart its alias record names."""
    return {
        source["source_file"]: source["counterpart"]
        for record in _records(palace)
        if record["event"] == "removed"
        for source in record["sources"]
    }


def test_mismatched_copies_are_selected_only_as_a_peer_group(tmp_path):
    project = tmp_path.resolve()
    canonical = str(project / "src" / "widget.py")
    tasks = project / ".tasks"
    t1, t2, t3 = [str(tasks / name / "src" / "widget.py") for name in ("T1", "T2", "T3")]
    mapping = dict.fromkeys((t1, t2, t3), canonical)
    old, new = "a" * 32, "b" * 32

    def pairs(hashes: dict) -> list:
        return orchestrator._generated_copy_pairs(hashes, [], mapping, project, {canonical})

    # Equal stored digests keep the existing selection.
    assert pairs({canonical: old, t1: old}) == [(t1, canonical)]
    # A lone changed copy, or copies without a filed counterpart, are not selected.
    assert pairs({canonical: new, t1: old}) == []
    assert pairs({t1: old, t2: old}) == []
    group = {canonical: new, t1: old, t2: old, t3: "c" * 32}
    assert pairs(group) == [(t1, canonical), (t2, canonical)]


@pytest.mark.parametrize("primary", ["equal-bytes", "evolved"])
def test_exact_legacy_peers_keep_one_snapshot_beside_a_different_primary(tmp_path, kg, primary):
    project, palace, copies = _peer_project(tmp_path, ["T1", "T2", "T3"], kg=kg)
    canonical = str(project / "src" / "widget.py")
    report = str(project / ".tasks" / "T1" / "astra-billing-review.md")
    if primary == "evolved":
        # The primary moved on and was filed again; the copies keep their old bytes.
        Path(canonical).write_text(WIDGET.replace("labelled", "formatted"), encoding="utf-8")
        _mine(project, palace, include_ignored=[".tasks"], kg=kg)
    _legacy_snapshot(palace, copies)
    first = _rows(palace)
    facts = _kg_dump(kg)

    stats = _mine(project, palace, kg=kg)

    after = _rows(palace)
    assert stats["copy_sources_removed"] == 2
    assert [copy for copy in copies if copy in after] == [copies[0]]
    assert after[copies[0]] == 1
    assert after[canonical] == first[canonical]
    assert after[report] == first[report]
    assert _removed(palace) == dict.fromkeys(copies[1:], copies[0])
    reason = "content-differs" if primary == "evolved" else "chunks-differ"
    assert stats["copy_sources_retained_by_reason"] == {reason: 1}
    assert _kg_dump(kg) == facts
    again = _mine(project, palace, kg=kg)
    assert again["copy_sources_removed"] == 0
    assert _rows(palace) == after


def test_each_distinct_legacy_snapshot_keeps_its_own_representative(tmp_path):
    project, palace, copies = _peer_project(tmp_path, ["T1", "T2", "T3", "T4", "T5"])
    t1, t2, t3, t4, t5 = copies
    _legacy_snapshot(palace, [t1, t2])
    _legacy_snapshot(palace, [t3, t4], symbol_name="LegacyVariant")
    _legacy_snapshot(palace, [t5], symbol_name="UniqueVariant")
    first = _rows(palace)

    stats = _mine(project, palace)

    after = _rows(palace)
    assert stats["copy_sources_removed"] == 2
    assert [copy for copy in copies if copy in after] == [t1, t3, t5]
    assert _removed(palace) == {t2: t1, t4: t3}
    assert stats["copy_sources_retained_by_reason"] == {"chunks-differ": 3}
    assert after[t5] == first[t5]


def test_protected_missing_and_linked_copies_are_never_peers_or_representatives(tmp_path):
    project, palace, copies = _peer_project(tmp_path, ["T1", "T2", "T3", "T4", "T5"])
    t1, t2, t3, t4, t5 = copies
    _legacy_snapshot(palace, copies)
    open_store(str(palace), create=False).add(
        ids=["manual_note_on_copy"],
        documents=["Reviewer note: this copy reproduced the rejected billing candidate."],
        metadatas=[
            {
                "wing": "proj",
                "room": "general",
                "source_file": t1,
                "chunk_index": 0,
                "added_by": "mcp",
                "filed_at": "2026-10-19T00:00:00",
                "chunker_strategy": "manual_v1",
            }
        ],
    )
    Path(t2).unlink()
    Path(t3).unlink()
    Path(t3).symlink_to(project / "src" / "widget.py")
    first = _rows(palace)

    stats = _mine(project, palace)

    assert stats["copy_sources_removed"] == 1
    assert _removed(palace) == {t5: t4}
    assert _rows(palace) == {source: count for source, count in first.items() if source != t5}
    assert stats["copy_sources_retained_by_reason"] == {
        "chunks-differ": 1,
        "protected-or-legacy-row": 1,
        "source-missing-or-not-regular": 2,
    }
    kept = open_store(str(palace), create=False, read_only=True).get(ids=["manual_note_on_copy"])
    assert kept["ids"] == ["manual_note_on_copy"]


def test_explicitly_included_peer_is_neither_a_candidate_nor_a_representative(tmp_path):
    project, palace, copies = _peer_project(tmp_path, ["T1", "T2", "T3"])
    t1, t2, t3 = copies
    _legacy_snapshot(palace, copies)

    stats = _mine(project, palace, include_ignored=[".tasks/T1/src/widget.py"])

    assert t1 in _rows(palace)
    assert stats["copy_sources_removed"] == 1
    assert _removed(palace) == {t3: t2}


def test_degraded_backup_refuses_peer_deletion_and_keeps_the_archive(tmp_path, monkeypatch):
    from mempalace_code import backup

    project, palace, copies = _peer_project(tmp_path, ["T1", "T2", "T3"])
    _legacy_snapshot(palace, copies)
    first = _rows(palace)
    forensic = tmp_path / "pre_optimize_20261019_000000_000000_DEGRADED.tar.gz"
    forensic.write_bytes(b"forensic copy")

    def degraded_backup(*args, **kwargs):
        return {"degraded": True, "degraded_error": "kg_corrupt: test"}, str(forensic)

    monkeypatch.setattr(backup, "create_backup", degraded_backup)
    stats = _mine(project, palace)

    assert _rows(palace) == first
    assert stats["copy_sources_removed"] == 0
    assert "degraded" in stats["copy_reconcile_refusal"]
    assert stats["copy_sources_retained_by_reason"] == {"chunks-differ": 1, "backup-refused": 2}
    assert forensic.read_bytes() == b"forensic copy"


def test_peers_across_the_batch_boundary_alias_one_kept_snapshot(tmp_path):
    # Filed out of sorted order; the 204 peers span two exact-id batches.
    names = [f"C{index:03d}" for index in (*range(100, 205), *range(100))]
    project, palace, copies = _peer_project(tmp_path, names)
    _legacy_snapshot(palace, copies)

    stats = _mine(project, palace)

    after = _rows(palace)
    assert stats["copy_sources_removed"] == 204
    assert [copy for copy in copies if copy in after] == [copies[0]]
    assert _removed(palace) == dict.fromkeys(copies[1:], copies[0])
    assert [record["event"] for record in _records(palace)].count("removed") == 2
    assert _mine(project, palace)["copy_sources_removed"] == 0


def test_interrupted_peer_removal_resumes_with_the_recorded_representative(tmp_path, monkeypatch):
    project, palace, copies = _peer_project(tmp_path, ["T1", "T2", "T3"])
    _legacy_snapshot(palace, copies)
    first = _rows(palace)
    real_delete = LanceStore.delete
    interrupted: list = []

    def interrupt_once(self, ids):
        if not interrupted:
            interrupted.append(ids)
            raise KeyboardInterrupt
        return real_delete(self, ids)

    monkeypatch.setattr(LanceStore, "delete", interrupt_once)
    with pytest.raises(KeyboardInterrupt):
        _mine(project, palace)
    assert _rows(palace) == first
    pending = _records(palace)[-1]
    assert pending["event"] == "remove"
    assert {source["counterpart"] for source in pending["sources"]} == {copies[0]}

    resumed = _mine(project, palace)
    final = _mine(project, palace)

    assert resumed["copy_sources_removed"] == 2
    assert final["copy_sources_removed"] == 0
    assert _removed(palace) == dict.fromkeys(copies[1:], copies[0])
    assert _rows(palace) == {
        source: count for source, count in first.items() if source not in copies[1:]
    }


def test_representative_drift_before_delete_keeps_every_peer(tmp_path, monkeypatch):
    project, palace, copies = _peer_project(tmp_path, ["T1", "T2", "T3"])
    _legacy_snapshot(palace, copies)
    first = _rows(palace)
    real_assess = orchestrator._assess_copy_batch
    edited: list = []

    def drift_representative(collection, wing, batch, retained, prefix="", **kwargs):
        if prefix and not edited:
            edited.append(prefix)
            Path(copies[0]).write_text(WIDGET + "# edited after assessment\n", encoding="utf-8")
        return real_assess(collection, wing, batch, retained, prefix, **kwargs)

    monkeypatch.setattr(orchestrator, "_assess_copy_batch", drift_representative)
    stats = _mine(project, palace)

    assert edited == ["changed-before-delete:"]
    assert _rows(palace) == first
    assert stats["copy_sources_removed"] == 0
    assert stats["copy_sources_retained_by_reason"] == {
        "chunks-differ": 1,
        "changed-before-delete:content-differs": 2,
    }


def _converged_peers(tmp_path: Path) -> tuple[Path, Path, list[str]]:
    """Remove two exact legacy peers, then file the primary as the kept snapshot."""
    project, palace, copies = _peer_project(tmp_path, ["T1", "T2", "T3"])
    _legacy_snapshot(palace, copies)
    assert _mine(project, palace)["copy_sources_removed"] == 2
    _legacy_snapshot(palace, [str(project / "src" / "widget.py")])
    return project, palace, copies


def test_kept_representative_survives_a_primary_that_now_repeats_it(tmp_path):
    project, palace, copies = _converged_peers(tmp_path)
    keeper, primary = copies[0], str(project / "src" / "widget.py")
    before = _rows(palace)
    store = open_store(str(palace), create=False)
    # The unchanged assessor alone would now prove the kept snapshot a copy.
    assert orchestrator._assess_copy_batch(store, "proj", [(keeper, primary)], {})

    stats = orchestrator._reconcile_generated_copies(
        store, "proj", [(keeper, primary)], str(palace), None, False
    )

    assert stats["copy_sources_removed"] == 0
    assert stats["copy_sources_retained_by_reason"] == {"historical-alias-target": 1}
    assert _rows(palace) == before


def _damaged(line: bytes, damage: str) -> bytes:
    """Damage one remove/removed record line the way *damage* names; keep the others."""
    entry = json.loads(line)
    if damage == "torn-tail" or entry["event"] not in ("remove", "removed"):
        return line
    if damage == "duplicate-wing":
        return (json.dumps(entry)[:-1] + ', "wing": "other"}\n').encode("utf-8")
    if damage == "duplicate-counterpart":
        target = json.dumps(entry["sources"][0]["counterpart"])
        raw = json.dumps(entry).replace(
            '"counterpart": ' + target,
            '"counterpart": ' + target + ', "counterpart": "/ambiguous/other"',
            1,
        )
        return (raw + "\n").encode("utf-8")
    if damage == "malformed":
        return line[: len(line) // 2] + b"\n"
    if damage == "invalid-source":
        entry["sources"] = [{}]
    elif damage == "unknown-event":
        entry["event"] = "unknown"
    elif damage == "ambiguous-summary":
        entry["event"] = "summary"
    elif damage == "empty-wing":
        entry["wing"] = ""
    else:
        del entry["wing"]
    return (json.dumps(entry) + "\n").encode("utf-8")


@pytest.mark.parametrize(
    "damage",
    [
        "malformed",
        "invalid-source",
        "missing-wing",
        "torn-tail",
        "unknown-event",
        "ambiguous-summary",
        "empty-wing",
        "duplicate-wing",
        "duplicate-counterpart",
    ],
)
def test_damaged_copy_history_refuses_every_deletion(tmp_path, damage):
    project, palace, copies = _converged_peers(tmp_path)
    keeper, primary = copies[0], str(project / "src" / "widget.py")
    record = orchestrator._copy_reconcile_record_path(str(palace))
    lines = record.read_bytes().splitlines(keepends=True)
    damaged = b"".join(_damaged(line, damage) for line in lines)
    if damage == "torn-tail":
        damaged += b'{"event": "remo'
    record.write_bytes(damaged)
    before = _rows(palace)
    store = open_store(str(palace), create=False)
    ids = set(store.get()["ids"])

    stats = orchestrator._reconcile_generated_copies(
        store, "proj", [(keeper, primary)], str(palace), None, False
    )

    assert stats["copy_sources_removed"] == 0
    assert "copy reconciliation history line" in stats["copy_reconcile_refusal"]
    assert stats["copy_sources_retained_by_reason"] == {"history-refused": 1}
    assert set(store.get()["ids"]) == ids
    assert _rows(palace) == before
    assert record.read_bytes() == damaged


def test_damaged_history_also_refuses_a_canonical_copy_removal(tmp_path):
    project = _project(tmp_path)
    task = _with_task_copy(project)
    palace = tmp_path / "palace"
    copy_file = str(task / "src" / "widget.py")
    _mine(project, palace, include_ignored=[".tasks"])
    first = _rows(palace)
    record = orchestrator._copy_reconcile_record_path(str(palace))
    damaged = b'{"event": "removed", "wing": "proj", "sources": [\n'
    record.write_bytes(damaged)

    stats = _mine(project, palace)

    assert _rows(palace) == first
    assert stats["copy_sources_removed"] == 0
    assert "history line 1 is not valid JSON" in stats["copy_reconcile_refusal"]
    assert stats["copy_sources_retained_by_reason"] == {"history-refused": 1}
    assert record.read_bytes() == damaged
    record.unlink()
    assert _mine(project, palace)["copy_sources_removed"] == 1
    assert copy_file not in _rows(palace)
