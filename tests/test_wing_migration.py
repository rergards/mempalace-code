from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import threading
from contextlib import contextmanager
from pathlib import Path

import lancedb
import pytest

from mempalace_code import wing_migration

SCRIPT = Path(wing_migration.__file__)
REAL_RUNTIME_PROBE = wing_migration._runtime_probe


@pytest.fixture(autouse=True)
def bounded_runtime_probe(monkeypatch):
    """Keep state-machine tests focused; CLI qualification exercises the real probe."""

    def proved(receipt):
        return {
            "command": [receipt["runtime"]["interpreter"], "fixture-probe"],
            "predicates": {
                "source_baseline_real_mine": True,
                "resolver_destination": True,
                "destination_reported": True,
                "zero_drawer_writes": True,
                "incremental_noop": True,
            },
            "identity": receipt["runtime"],
            "measurements": {
                "source_rows_before": 1,
                "destination_rows_before": 0,
                "source_rows_after": 0,
                "destination_rows_after": 1,
                "source_filed_drawers": 1,
                "destination_filed_drawers": 0,
            },
        }

    monkeypatch.setattr(wing_migration, "_runtime_probe", proved)


def fixture(tmp_path: Path) -> tuple[Path, Path, dict]:
    root = tmp_path / "fixture"
    inventory_path, receipt_path = wing_migration._create_synthetic_fixture(root)
    inventory = json.loads(inventory_path.read_text())
    return inventory_path, receipt_path, inventory


def inventory_receipt(inventory_path: Path, receipt_path: Path) -> dict:
    return wing_migration.inventory(
        str(inventory_path),
        str(receipt_path),
        frozen_at="2026-01-15T12:00:00+00:00",
    )


def table_for(inventory: dict):
    return lancedb.connect(str(Path(inventory["palace"]) / "lance")).open_table(
        wing_migration.TABLE_NAME
    )


def rewrite_inventory(path: Path, inventory: dict) -> None:
    path.write_text(json.dumps(inventory))
    os.chmod(path, 0o600)


def write_retained_snapshot(inventory: dict, root: Path) -> Path:
    root.mkdir(mode=0o700)
    manifest = {
        "files": {},
        "kg": [],
        "lance": None,
        "lance_hashes": {},
        "recovery_root": str(root / "recovery"),
        "root": str(root),
    }
    wing_migration._atomic_json(root / "manifest.json", manifest)
    receipt_path = Path(inventory["evidence_root"]) / f"{root.name}-receipt.json"
    receipt = {
        "version": wing_migration.RECEIPT_VERSION - 1,
        "receipt_path": str(receipt_path),
        "qualification_mode": "full-copy",
        "inventory": {
            "fixture_root": inventory["fixture_root"],
            "evidence_root": inventory["evidence_root"],
            "snapshot_root": str(root),
        },
        "snapshot": manifest,
    }
    receipt["seal"] = wing_migration._digest(receipt)
    wing_migration._atomic_json(receipt_path, receipt)
    inventory["retained_snapshot_roots"][str(root)] = str(receipt_path)
    inventory["copy_verification"]["source_preimage_sha256"] = wing_migration._digest(
        wing_migration._copy_preimage(inventory)
    )
    return receipt_path


@pytest.mark.skipif(sys.platform != "darwin", reason="APFS clone is a macOS capability")
def test_clone_tree_is_independent_copy_on_write(tmp_path):
    source = tmp_path / "source"
    copied = tmp_path / "copied"
    source.mkdir()
    copied.mkdir()
    source_file = source / "payload.bin"
    source_file.write_bytes(b"source payload")

    assert wing_migration._clone_tree_if_supported(source, copied)

    copied_file = copied / "payload.bin"
    assert copied_file.read_bytes() == source_file.read_bytes()
    assert copied_file.stat().st_ino != source_file.stat().st_ino
    copied_file.write_bytes(b"changed copy")
    assert source_file.read_bytes() == b"source payload"


def test_copytree_fallback_excludes_sqlite_files(tmp_path, monkeypatch):
    source = tmp_path / "source"
    copied = tmp_path / "copied"
    source.mkdir()
    copied.mkdir()
    (source / "ordinary.txt").write_text("ordinary", encoding="utf-8")
    sqlite_path = source / "knowledge.sqlite3"
    sqlite_path.write_bytes(b"sqlite")
    Path(f"{sqlite_path}-wal").write_bytes(b"wal")
    monkeypatch.setattr(wing_migration, "_clone_tree_if_supported", lambda *_args: False)

    wing_migration._copytree_without_sqlite(source, copied, [sqlite_path])

    assert (copied / "ordinary.txt").read_text(encoding="utf-8") == "ordinary"
    assert not (copied / "knowledge.sqlite3").exists()
    assert not (copied / "knowledge.sqlite3-wal").exists()


def add_retained_snapshot(inventory: dict, name: str = "retained-snapshot") -> Path:
    root = Path(inventory["fixture_root"]) / name
    write_retained_snapshot(inventory, root)
    return root


def full_copy_fixture(tmp_path: Path, monkeypatch) -> tuple[Path, Path, dict]:
    inventory_path, seed_receipt_path, inventory = fixture(tmp_path)
    seed_receipt = inventory_receipt(inventory_path, seed_receipt_path)
    logical_root = Path("/owner-original/repository")
    physical_source = str(Path(inventory["project_root"]) / "app.py")
    logical_source = str(logical_root / "app.py")
    table_for(inventory).update(where="id = 'source-file'", values={"source_file": logical_source})
    tiny_path = Path(inventory["tiny_hashes"])
    tiny = json.loads(tiny_path.read_text())
    for hashes in tiny.values():
        if physical_source in hashes:
            hashes[logical_source] = hashes.pop(physical_source)
    tiny_path.write_text(json.dumps(tiny), encoding="utf-8")
    connection = sqlite3.connect(inventory["kg_candidates"][0])
    connection.execute(
        "UPDATE triples SET source_file=? WHERE source_file=?", (logical_source, physical_source)
    )
    connection.commit()
    connection.close()

    owner_inventory_path = tmp_path / "full-copy-inventory.json"
    inventory_path.replace(owner_inventory_path)
    inventory_path = owner_inventory_path

    paths = {
        key: Path(inventory[key])
        for key in (
            "palace",
            "project_root",
            "marker",
            "tiny_hashes",
            "lock",
            "snapshot_root",
            "runtime_root",
            "evidence_root",
            "configuration",
        )
    }
    qualification_device = paths["palace"].stat().st_dev
    source_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=SCRIPT.parents[1],
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    inventory.update(
        {
            "logical_source_root": str(logical_root),
            "retained_snapshot_roots": {},
            "authority": {
                "fixture_process_authority": wing_migration.FULL_COPY_PROCESS_AUTHORITY,
                "live_mutation": False,
                "original_host": "source.example.invalid",
                "original_paths_excluded_from_mutation": [
                    str(logical_root),
                    "/owner-original/palace",
                    "/owner-original/knowledge-graph.sqlite3",
                    "/owner-original/config.json",
                    "/owner-original/runtime",
                ],
                "owner_approval": "fixture owner approval",
                "qualification_host": socket.gethostname(),
                "retention_rule": wing_migration.FULL_COPY_RETENTION_RULE,
                "scope": wing_migration.FULL_COPY_SCOPE,
                "watcher_restart": False,
            },
            "runtime_authority": {
                "model_cache_home": seed_receipt["runtime"]["model_cache_home"],
                "model_cache_seal": seed_receipt["runtime"]["model_cache_seal"],
                "original_interpreter": "/owner-original/runtime/bin/python",
                "original_version": seed_receipt["runtime"]["distribution_version"],
                "pyproject_sha256": wing_migration._file_digest(
                    SCRIPT.parents[1] / "pyproject.toml"
                ),
                "qualification_distribution_hashes": seed_receipt["runtime"]["distribution_hashes"],
                "qualification_distribution_origin": seed_receipt["runtime"]["distribution_origin"],
                "qualification_interpreter": seed_receipt["runtime"]["interpreter"],
                "qualification_module_origin": seed_receipt["runtime"]["module_origin"],
                "qualification_package_hashes": seed_receipt["runtime"]["package_hashes"],
                "qualification_runtime_prefix": seed_receipt["runtime"]["runtime_prefix"],
                "qualification_source_commit": source_commit,
                "runner_sha256": wing_migration._file_digest(SCRIPT),
            },
            "copy_verification": {
                "checksum_dry_run_differences": 0,
                "copied_targets": [
                    wing_migration._copied_target_state(paths["palace"]),
                    wing_migration._copied_target_state(paths["project_root"]),
                ],
                "method": "fixture full-copy verification",
                "qualification_device": qualification_device,
                "source_device": -1,
                "source_filesystem_id": "source-filesystem-fixture",
                "source_host": "source.example.invalid",
                "source_snapshot_id": "source-snapshot-fixture",
                "source_snapshot_root": "/owner-snapshot",
            },
        }
    )
    source_preimage = wing_migration._copy_preimage(inventory)
    inventory["copy_verification"]["source_preimage_sha256"] = wing_migration._digest(
        source_preimage
    )
    inventory["copy_verification"]["copied_targets"] = [
        wing_migration._copied_target_state(paths["palace"]),
        wing_migration._copied_target_state(paths["project_root"]),
    ]
    rewrite_inventory(inventory_path, inventory)
    assert wing_migration._copy_preimage(inventory) == source_preimage
    monkeypatch.setenv("WING_MIGRATION_INVENTORY_PATH", str(inventory_path))
    return inventory_path, seed_receipt_path, inventory


def model_cache_state(root: Path) -> dict[str, tuple]:
    state = {}
    for path in [root, *sorted(root.rglob("*"))]:
        metadata = path.lstat()
        content = None
        if path.is_symlink():
            content = ("symlink", os.readlink(path))
        elif path.is_file():
            content = ("file", hashlib.sha256(path.read_bytes()).hexdigest())
        state[str(path.relative_to(root))] = (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_mode,
            metadata.st_nlink,
            metadata.st_uid,
            metadata.st_gid,
            metadata.st_size,
            metadata.st_mtime_ns,
            metadata.st_ctime_ns,
            content,
        )
    return state


def filesystem_manifest(root: Path, *absent: Path) -> dict[str, tuple | None]:
    state: dict[str, tuple | None] = {}
    for current, directories, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        for name in sorted([*directories, *files]):
            path = current_path / name
            metadata = path.lstat()
            content = None
            if path.is_symlink():
                content = os.readlink(path)
            elif path.is_file():
                content = hashlib.sha256(path.read_bytes()).hexdigest()
            state[str(path.relative_to(root))] = (
                metadata.st_mode,
                metadata.st_nlink,
                metadata.st_size,
                metadata.st_mtime_ns,
                content,
            )
    for path in absent:
        state[f"absent:{path.relative_to(root)}"] = None if not path.exists() else ("present",)
    return state


def test_native_merge_preserves_exact_union_and_all_kg_read_surfaces(tmp_path):
    inventory_path, receipt_path, inventory = fixture(tmp_path)
    receipt = inventory_receipt(inventory_path, receipt_path)
    source = next(row for row in receipt["pre"]["lance_rows"] if row["id"] == "source-file")
    unrelated = next(row for row in receipt["pre"]["lance_rows"] if row["id"] == "unrelated")

    wing_migration.snapshot(str(receipt_path))
    result = wing_migration.apply(str(receipt_path))

    assert result["state"] == "merged"
    assert result["writes"] == 5
    assert wing_migration.classify(str(receipt_path)) == "merged"
    sealed = wing_migration._load_receipt(receipt_path)
    observed = wing_migration._capture(sealed["inventory"])
    assert observed == {key: sealed["expected"][key] for key in observed}
    migrated = next(row for row in observed["lance_rows"] if row["id"] == "source-file")
    assert migrated["wing"] == "new-wing"
    assert {key: value for key, value in migrated.items() if key != "wing"} == {
        key: value for key, value in source.items() if key != "wing"
    }
    assert next(row for row in observed["lance_rows"] if row["id"] == "unrelated") == unrelated
    assert (
        next(row for row in observed["lance_rows"] if row["id"] == "destination-diary")["text"]
        == "keep diary"
    )

    from mempalace_code.knowledge_graph import KnowledgeGraph

    graph = KnowledgeGraph(inventory["kg_candidates"][0])
    assert graph.query_relationship("in_project", as_of="2026-01-15")[0]["object"] == "new-wing"
    assert (
        graph.query_entity("new-wing", as_of="2026-01-15", direction="incoming")[0]["predicate"]
        == "in_project"
    )
    assert any(row["object"] == "new-wing" for row in graph.timeline("new-wing"))
    all_triples = [row for batch in graph.iter_all_triples(batch_size=1) for row in batch]
    assert {row["id"] for row in all_triples} == {"eligible-0", "historical-0"}
    assert next(row for row in all_triples if row["id"] == "historical-0")["object"] == "old-wing"


def test_snapshot_captures_committed_wal_and_restores_logical_preimage(tmp_path):
    inventory_path, receipt_path, inventory = fixture(tmp_path)
    kg_path = Path(inventory["kg_candidates"][0])
    writer = sqlite3.connect(str(kg_path))
    writer.execute("PRAGMA journal_mode=WAL")
    writer.execute(
        "INSERT INTO entities(id,name,type,properties) VALUES('wal-fact','WAL Fact','type','{}')"
    )
    writer.commit()
    inventory_receipt(inventory_path, receipt_path)
    receipt = wing_migration.snapshot(str(receipt_path))
    writer.close()

    backup = Path(receipt["snapshot"]["kg"][0]["backup"])
    restored = wing_migration._sqlite_rows(backup)
    assert any(entity["id"] == "wal-fact" for entity in restored["entities"])
    assert restored == receipt["pre"]["kg"][0]["state"]


def test_reused_wal_generation_materializes_descendant_and_recovers_current_state(
    tmp_path, monkeypatch
):
    inventory_path, _, inventory = full_copy_fixture(tmp_path, monkeypatch)
    kg_path = Path(inventory["kg_candidates"][0])
    writer = sqlite3.connect(str(kg_path))
    writer.execute("PRAGMA journal_mode=WAL")
    for index in range(500):
        writer.execute(
            "INSERT INTO entities(id,name,type,properties,created_at) VALUES(?,?,?,?,?)",
            (
                f"wal-old-{index}",
                f"WAL old {index}",
                "type",
                json.dumps({"payload": "x" * 200}),
                "2026-01-01T00:00:00+00:00",
            ),
        )
    writer.commit()
    assert writer.execute("PRAGMA wal_checkpoint(RESTART)").fetchone()[0] == 0
    writer.execute(
        "INSERT INTO entities(id,name,type,properties,created_at) VALUES(?,?,?,?,?)",
        (
            "wal-current",
            "WAL current",
            "type",
            "{}",
            "2026-01-02T00:00:00+00:00",
        ),
    )
    writer.commit()

    connection = wing_migration._sqlite_read_connection(kg_path)
    try:
        assert connection.execute(
            "SELECT name FROM entities WHERE id='wal-current'"
        ).fetchone() == ("WAL current",)
    finally:
        connection.close()
    assert any(
        entity["id"] == "wal-current" for entity in wing_migration._sqlite_rows(kg_path)["entities"]
    )

    inventory["copy_verification"]["source_preimage_sha256"] = wing_migration._digest(
        wing_migration._copy_preimage(inventory)
    )
    inventory["copy_verification"]["copied_targets"] = [
        wing_migration._copied_target_state(Path(inventory["palace"])),
        wing_migration._copied_target_state(Path(inventory["project_root"])),
    ]
    rewrite_inventory(inventory_path, inventory)
    parent_path = Path(inventory["evidence_root"]) / "reused-wal-parent.json"
    wing_migration.inventory(str(inventory_path), str(parent_path))
    wing_migration.snapshot(str(parent_path))
    trial_path, trial = wing_migration._create_full_copy_trial(
        wing_migration._load_receipt(parent_path), "reused-wal"
    )
    assert any(
        entity["id"] == "wal-current" for entity in trial["pre"]["kg"][0]["state"]["entities"]
    )
    writer.close()

    wing_migration.apply(str(trial_path))
    assert wing_migration.recover(str(trial_path)) == {"state": "original", "restored": True}
    assert any(
        entity["id"] == "wal-current"
        for entity in wing_migration._sqlite_rows(Path(trial["inventory"]["kg_candidates"][0]))[
            "entities"
        ]
    )


@pytest.mark.parametrize(
    "stage", ["lance:1", "kg:0", "kg:1", "tiny_hashes", "runtime_proved", "marker"]
)
def test_each_apply_boundary_classifies_and_recovers_whole_state(tmp_path, stage):
    inventory_path, receipt_path, _ = fixture(tmp_path)
    receipt = inventory_receipt(inventory_path, receipt_path)
    wing_migration.snapshot(str(receipt_path))

    with pytest.raises(wing_migration.InjectedStop, match=stage):
        wing_migration.apply(str(receipt_path), stop_after=stage)

    assert wing_migration.classify(str(receipt_path)) in {"partial", "merged"}
    recovered = wing_migration.recover(str(receipt_path))
    assert recovered == {"state": "original", "restored": True}
    assert wing_migration._capture(receipt["inventory"]) == receipt["pre"]


@pytest.mark.parametrize(
    "stage", ["lance:1:data", "kg:0:data", "kg:1:data", "tiny_hashes:data", "marker:data"]
)
def test_data_commit_before_receipt_boundary_uses_observed_state(tmp_path, stage):
    inventory_path, receipt_path, _ = fixture(tmp_path)
    receipt = inventory_receipt(inventory_path, receipt_path)
    wing_migration.snapshot(str(receipt_path))

    with pytest.raises(wing_migration.InjectedStop, match=stage):
        wing_migration.apply(str(receipt_path), stop_after=stage)

    assert wing_migration.classify(str(receipt_path)) in {"partial", "merged"}
    assert wing_migration.recover(str(receipt_path))["state"] == "original"
    assert wing_migration._capture(receipt["inventory"]) == receipt["pre"]


@pytest.mark.parametrize(
    "stage",
    [
        "recover:lance:removed",
        "recover:lance:installed",
        "recover:lance",
        "recover:kg:0:removed",
        "recover:kg:0:backup",
        "recover:kg:0:installed",
        "recover:kg:0",
        "recover:kg:1:removed",
        "recover:kg:1:backup",
        "recover:kg:1:installed",
        "recover:kg:1",
        "recover:tiny_hashes",
        "recover:marker",
    ],
)
def test_recovery_interruption_remains_classifiable_and_retryable(tmp_path, stage):
    inventory_path, receipt_path, _ = fixture(tmp_path)
    receipt = inventory_receipt(inventory_path, receipt_path)
    wing_migration.snapshot(str(receipt_path))
    wing_migration.apply(str(receipt_path))

    with pytest.raises(wing_migration.InjectedStop, match=stage):
        wing_migration.recover(str(receipt_path), stop_after=stage)

    assert wing_migration.classify(str(receipt_path)) in {"partial", "original"}
    wing_migration.recover(str(receipt_path))
    assert wing_migration._capture(receipt["inventory"]) == receipt["pre"]


def test_exact_merged_retry_is_zero_write_and_does_not_replace_receipt(tmp_path):
    inventory_path, receipt_path, _ = fixture(tmp_path)
    inventory_receipt(inventory_path, receipt_path)
    wing_migration.snapshot(str(receipt_path))
    wing_migration.apply(str(receipt_path))
    before = receipt_path.read_bytes()

    assert wing_migration.apply(str(receipt_path)) == {
        "state": "merged",
        "writes": 0,
        "retry": True,
    }
    assert receipt_path.read_bytes() == before


def test_unknown_state_refuses_recovery(tmp_path):
    inventory_path, receipt_path, inventory = fixture(tmp_path)
    inventory_receipt(inventory_path, receipt_path)
    wing_migration.snapshot(str(receipt_path))
    with pytest.raises(wing_migration.InjectedStop):
        wing_migration.apply(str(receipt_path), stop_after="lance:1")
    table_for(inventory).update(where="id = 'unrelated'", values={"text": "unexpected drift"})

    assert wing_migration.classify(str(receipt_path)) == "unknown"
    with pytest.raises(wing_migration.MigrationError, match="unknown_state_refused"):
        wing_migration.recover(str(receipt_path))


@pytest.mark.parametrize("mutation", ["duplicate_row", "schema_only"])
def test_lance_multiplicity_and_schema_drift_are_unknown(tmp_path, mutation):
    inventory_path, receipt_path, inventory = fixture(tmp_path)
    inventory_receipt(inventory_path, receipt_path)
    wing_migration.snapshot(str(receipt_path))
    table = table_for(inventory)
    if mutation == "duplicate_row":
        duplicate = next(row for row in table.to_arrow().to_pylist() if row["id"] == "unrelated")
        table.add([duplicate])
    else:
        table.add_columns({"schema_only_drift": "'unexpected'"})

    assert wing_migration.classify(str(receipt_path)) == "unknown"
    with pytest.raises(wing_migration.MigrationError) as caught:
        wing_migration.recover(str(receipt_path))
    assert caught.value.code == "unknown_state_refused"


def test_frozen_temporal_population_does_not_change_on_later_retry(tmp_path):
    inventory_path, receipt_path, inventory = fixture(tmp_path)
    kg_path = inventory["kg_candidates"][0]
    connection = sqlite3.connect(kg_path)
    connection.execute(
        "INSERT INTO triples(id,subject,predicate,object,valid_from,valid_to,confidence,source_file) "
        "VALUES('future-finite','subject-0','in_project','old-wing','2026-02-01','2026-02-02',1.0,?)",
        (str(Path(inventory["project_root"]) / "app.py"),),
    )
    connection.commit()
    connection.close()
    receipt = inventory_receipt(inventory_path, receipt_path)
    assert receipt["expected"]["kg_eligible"][kg_path] == ["eligible-0"]
    wing_migration.snapshot(str(receipt_path))
    wing_migration.apply(str(receipt_path))

    connection = sqlite3.connect(kg_path)
    rows = dict(connection.execute("SELECT id,object FROM triples"))
    connection.close()
    assert rows["eligible-0"] == "new-wing"
    assert rows["future-finite"] == "old-wing"
    assert wing_migration.classify(str(receipt_path)) == "merged"


def test_logically_duplicate_triples_keep_distinct_ids(tmp_path):
    inventory_path, receipt_path, inventory = fixture(tmp_path)
    kg_path = inventory["kg_candidates"][0]
    connection = sqlite3.connect(kg_path)
    connection.execute(
        "INSERT INTO triples(id,subject,predicate,object,valid_from,confidence,source_file) "
        "VALUES('eligible-copy','subject-0','in_project','old-wing','2025-01-01',0.75,?)",
        (str(Path(inventory["project_root"]) / "app.py"),),
    )
    connection.commit()
    connection.close()
    inventory_receipt(inventory_path, receipt_path)
    wing_migration.snapshot(str(receipt_path))
    wing_migration.apply(str(receipt_path))

    connection = sqlite3.connect(kg_path)
    rows = connection.execute(
        "SELECT id,object FROM triples WHERE id IN ('eligible-0','eligible-copy') ORDER BY id"
    ).fetchall()
    connection.close()
    assert rows == [("eligible-0", "new-wing"), ("eligible-copy", "new-wing")]


def test_triple_ids_are_scoped_to_each_physical_kg(tmp_path):
    inventory_path, receipt_path, inventory = fixture(tmp_path)
    second_kg = inventory["kg_candidates"][1]
    connection = sqlite3.connect(second_kg)
    connection.execute("UPDATE triples SET id='eligible-0' WHERE id='eligible-1'")
    connection.commit()
    connection.close()

    inventory_receipt(inventory_path, receipt_path)
    wing_migration.snapshot(str(receipt_path))
    wing_migration.apply(str(receipt_path))

    for kg_path in inventory["kg_candidates"]:
        connection = sqlite3.connect(kg_path)
        value = connection.execute("SELECT object FROM triples WHERE id='eligible-0'").fetchone()
        connection.close()
        assert value == ("new-wing",)


def test_equal_content_distinct_drawer_ids_are_preserved(tmp_path):
    inventory_path, receipt_path, inventory = fixture(tmp_path)
    source = next(
        row for row in table_for(inventory).to_arrow().to_pylist() if row["id"] == "source-file"
    )
    source["id"] = "destination-copy"
    source["wing"] = "new-wing"
    table_for(inventory).add([source])
    receipt = inventory_receipt(inventory_path, receipt_path)
    wing_migration.snapshot(str(receipt_path))
    wing_migration.apply(str(receipt_path))

    final_ids = [row["id"] for row in wing_migration._capture(receipt["inventory"])["lance_rows"]]
    assert "source-file" in final_ids
    assert "destination-copy" in final_ids


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        ("duplicate_id", "duplicate_drawer_id"),
        ("file_collision", "file_identity_collision"),
        ("protected", "protected_replacement_exposure"),
        ("malformed_tiny", "tiny_hashes_invalid"),
        ("tiny_collision", "tiny_hash_collision"),
        ("entity_conflict", "destination_entity_conflict"),
    ],
)
def test_collision_matrix_refuses_before_mutation(tmp_path, mutation, code):
    inventory_path, receipt_path, inventory = fixture(tmp_path)
    table = table_for(inventory)
    before = wing_migration._read_lance_rows(Path(inventory["palace"]))
    if mutation == "duplicate_id":
        duplicate = dict(before[0])
        table.add([duplicate])
    elif mutation == "file_collision":
        row = next(row for row in before if row["id"] == "source-file")
        conflict = dict(row)
        conflict.update({"id": "conflict", "wing": "new-wing", "text": "different"})
        table.add([conflict])
    elif mutation == "protected":
        table.update(where="id = 'source-file'", values={"ingest_mode": "diary"})
    elif mutation == "malformed_tiny":
        Path(inventory["tiny_hashes"]).write_text('{"old-wing":{"x":"bad"}}')
    elif mutation == "tiny_collision":
        Path(inventory["tiny_hashes"]).write_text(
            json.dumps({"old-wing": {"x": "a" * 32}, "new-wing": {"x": "b" * 32}})
        )
    else:
        connection = sqlite3.connect(inventory["kg_candidates"][0])
        connection.execute(
            "INSERT INTO entities(id,name,type,properties) VALUES('new-wing','Wrong Name','type','{}')"
        )
        connection.commit()
        connection.close()

    state_at_attempt = wing_migration._read_lance_rows(Path(inventory["palace"]))
    with pytest.raises(wing_migration.MigrationError) as caught:
        inventory_receipt(inventory_path, receipt_path)
    assert caught.value.code == code
    assert wing_migration._read_lance_rows(Path(inventory["palace"])) == state_at_attempt
    assert not receipt_path.exists()


@pytest.mark.parametrize("strategy", sorted(wing_migration.LEGACY_FILE_CHUNKER_STRATEGIES))
def test_legacy_file_strategy_proves_scoped_source_row(tmp_path, strategy):
    inventory_path, receipt_path, inventory = fixture(tmp_path)
    table_for(inventory).update(
        where="id = 'source-file'",
        values={"ingest_mode": "", "chunker_strategy": strategy},
    )

    receipt = inventory_receipt(inventory_path, receipt_path)

    source = next(row for row in receipt["expected"]["lance_rows"] if row["id"] == "source-file")
    assert source["wing"] == "new-wing"


@pytest.mark.parametrize("strategy", ["manual_v1", "diary_v1", "unknown_v1", ""])
def test_legacy_non_file_strategy_remains_protected(tmp_path, strategy):
    inventory_path, receipt_path, inventory = fixture(tmp_path)
    table_for(inventory).update(
        where="id = 'source-file'",
        values={"ingest_mode": "", "chunker_strategy": strategy},
    )

    with pytest.raises(wing_migration.MigrationError) as caught:
        inventory_receipt(inventory_path, receipt_path)

    assert caught.value.code == "protected_replacement_exposure"


@pytest.mark.parametrize(
    "values",
    [
        {"ingest_mode": "", "chunker_strategy": "regex_structural_v1", "type": "diary"},
        {"ingest_mode": "", "chunker_strategy": "regex_structural_v1", "source_hash": "bad"},
        {"ingest_mode": "diary", "chunker_strategy": "regex_structural_v1"},
    ],
)
def test_legacy_file_strategy_requires_every_provenance_guard(tmp_path, values):
    inventory_path, receipt_path, inventory = fixture(tmp_path)
    table_for(inventory).update(where="id = 'source-file'", values=values)

    with pytest.raises(wing_migration.MigrationError) as caught:
        inventory_receipt(inventory_path, receipt_path)

    assert caught.value.code == "protected_replacement_exposure"
    assert not receipt_path.exists()


def test_same_wing_chunks_with_inconsistent_hashes_are_rejected(tmp_path):
    inventory_path, receipt_path, inventory = fixture(tmp_path)
    source = next(
        row for row in table_for(inventory).to_arrow().to_pylist() if row["id"] == "source-file"
    )
    source.update({"id": "source-file-chunk-1", "chunk_index": 1, "source_hash": "e" * 32})
    table_for(inventory).add([source])

    with pytest.raises(wing_migration.MigrationError) as caught:
        inventory_receipt(inventory_path, receipt_path)

    assert caught.value.code == "file_identity_collision"
    assert "inconsistent old-wing source hashes" in caught.value.detail
    assert not receipt_path.exists()


def test_marker_hash_is_preserved_without_manufacturing_noop(tmp_path):
    inventory_path, receipt_path, inventory = fixture(tmp_path)
    marker_hash = "c" * 32
    tiny_path = Path(inventory["tiny_hashes"])
    tiny_path.write_text(
        json.dumps({"old-wing": {inventory["marker"]: marker_hash}}), encoding="utf-8"
    )

    receipt = inventory_receipt(inventory_path, receipt_path)
    expected = wing_migration._decode_json_state(receipt["expected"]["tiny_hashes"], "test")

    assert expected == {"new-wing": {inventory["marker"]: marker_hash}}
    assert not hasattr(wing_migration, "_seal_marker_hash")


def test_full_copy_uses_logical_provenance_and_restores_retained_copy(tmp_path, monkeypatch):
    inventory_path, _, inventory = full_copy_fixture(tmp_path, monkeypatch)
    retained_v1 = Path(inventory["evidence_root"]) / "full-copy-receipt-v1.json"
    retained_v1.write_bytes(b"retained-v1-evidence")
    os.chmod(retained_v1, 0o600)

    report = wing_migration.qualify("full-copy")

    receipt_path, private_report = wing_migration._full_copy_evidence_paths(inventory)
    assert report["status"] == "qualified"
    assert report["predicates"]["original_path_noop_unproved"] is True
    assert report["predicates"]["all_interruptions_recovered"] is True
    assert retained_v1.read_bytes() == b"retained-v1-evidence"
    assert receipt_path.is_file()
    assert private_report.is_file()
    sealed = wing_migration._load_receipt(receipt_path)
    assert wing_migration._capture(sealed["inventory"]) == sealed["pre"]
    assert (
        json.loads(private_report.read_text())["retention_rule"]
        == inventory["authority"]["retention_rule"]
    )
    outcomes = json.loads(private_report.read_text())["outcomes"]
    assert [(row["trial"], row.get("stage")) for row in outcomes] == [
        ("rehearsal", None),
        ("collision", None),
        *(
            ("apply-interruption", stage)
            for stage in wing_migration._apply_interruption_stages(sealed)
        ),
        *(
            ("recovery-interruption", stage)
            for stage in wing_migration._recovery_interruption_stages(sealed)
        ),
    ]
    assert all(row["evidence_disposition"] == "verified_and_removed" for row in outcomes)
    assert all(len(row["receipt_seal"]) == 64 for row in outcomes)
    assert all(len(row["preimage_sha256"]) == 64 for row in outcomes)
    assert not (
        Path(inventory["evidence_root"]) / "trials" / f"v{wing_migration.RECEIPT_VERSION}"
    ).exists()
    assert outcomes[0]["trial"] == "rehearsal"
    private = json.loads(private_report.read_text())
    assert private["resume"] == {"runner_sha256": sealed["runner_hash"]}
    assert private["runtime_measurements"] == {
        "source_rows_before": 1,
        "destination_rows_before": 0,
        "source_rows_after": 0,
        "destination_rows_after": 1,
        "source_filed_drawers": 1,
        "destination_filed_drawers": 0,
    }
    assert "runtime_measurements" not in report


def test_full_copy_refuses_stale_trial_copies_before_evidence_writes(tmp_path, monkeypatch):
    _, _, inventory = full_copy_fixture(tmp_path, monkeypatch)
    stale = Path(inventory["evidence_root"]) / "trials" / "v2" / "rehearsal"
    stale.mkdir(parents=True)
    sentinel = stale / "sentinel"
    sentinel.write_text("retained stale trial\n")
    receipt_path, report_path = wing_migration._full_copy_evidence_paths(inventory)

    with pytest.raises(wing_migration.MigrationError) as caught:
        wing_migration.qualify("full-copy")

    assert caught.value.code == "stale_trial_evidence"
    assert sentinel.read_text() == "retained stale trial\n"
    assert not receipt_path.exists()
    assert not report_path.exists()


def test_full_copy_refuses_unaccounted_snapshot_generation(tmp_path, monkeypatch):
    _, _, inventory = full_copy_fixture(tmp_path, monkeypatch)
    stale = Path(inventory["fixture_root"]) / "snapshot-v14"
    stale.mkdir()
    sentinel = stale / "sentinel"
    sentinel.write_text("retained stale snapshot\n")

    with pytest.raises(wing_migration.MigrationError) as caught:
        wing_migration.qualify("full-copy")

    assert caught.value.code == "stale_fixture_generation"
    assert sentinel.read_text() == "retained stale snapshot\n"


def test_full_copy_caps_retained_snapshot_generations(tmp_path, monkeypatch):
    inventory_path, _, inventory = full_copy_fixture(tmp_path, monkeypatch)
    fixture_root = Path(inventory["fixture_root"])
    write_retained_snapshot(inventory, fixture_root / "retained-one")
    write_retained_snapshot(inventory, fixture_root / "retained-two")
    rewrite_inventory(inventory_path, inventory)

    with pytest.raises(wing_migration.MigrationError) as caught:
        wing_migration._load_inventory(inventory_path)

    assert caught.value.code == "retained_snapshot_limit_exceeded"


def test_full_copy_trial_cleanup_refuses_partial_state(tmp_path, monkeypatch):
    inventory_path, _, inventory = full_copy_fixture(tmp_path, monkeypatch)
    receipt_path = Path(inventory["evidence_root"]) / "cleanup-parent.json"
    parent = wing_migration.inventory(str(inventory_path), str(receipt_path))
    trial_path, trial = wing_migration._create_full_copy_trial(parent, "partial-cleanup")
    trial["phase"] = "lance"
    wing_migration._save_receipt(trial)
    trial_root = Path(trial["inventory"]["fixture_root"])

    with pytest.raises(wing_migration.MigrationError) as caught:
        wing_migration._dispose_verified_full_copy_trial(parent, trial_path)

    assert caught.value.code == "trial_cleanup_refused"
    assert trial_root.is_dir()
    assert trial_path.is_file()


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        ("missing_field", "retained_snapshot_roots_invalid"),
        ("wrong_type", "retained_snapshot_roots_invalid"),
        ("relative", "retained_snapshot_root_invalid"),
        ("outside", "outside_fixture"),
        ("missing_root", "retained_snapshot_root_invalid"),
        ("unproved", "retained_snapshot_unproved"),
        ("manifest_mismatch", "retained_snapshot_unproved"),
        ("wrong_manifest_root", "retained_snapshot_unproved"),
        ("symlink", "fixture_symlink"),
        ("active_snapshot", "target_overlap"),
        ("duplicate", "retained_snapshot_limit_exceeded"),
    ],
)
def test_full_copy_retained_snapshot_roots_fail_closed(tmp_path, monkeypatch, mutation, code):
    inventory_path, _, inventory = full_copy_fixture(tmp_path, monkeypatch)
    fixture_root = Path(inventory["fixture_root"])
    if mutation == "missing_field":
        inventory.pop("retained_snapshot_roots")
    elif mutation == "wrong_type":
        inventory["retained_snapshot_roots"] = "retained"
    elif mutation == "relative":
        inventory["retained_snapshot_roots"] = {"retained": "/retained-receipt.json"}
    elif mutation == "outside":
        outside = tmp_path / "outside-snapshot"
        outside.mkdir()
        inventory["retained_snapshot_roots"] = {str(outside): "/retained-receipt.json"}
    elif mutation == "missing_root":
        inventory["retained_snapshot_roots"] = {
            str(fixture_root / "missing-snapshot"): "/retained-receipt.json"
        }
    elif mutation == "unproved":
        unproved = fixture_root / "unproved-snapshot"
        unproved.mkdir()
        inventory["retained_snapshot_roots"] = {str(unproved): "/retained-receipt.json"}
    elif mutation == "manifest_mismatch":
        retained = add_retained_snapshot(inventory)
        manifest_path = retained / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["kg"] = "invalid"
        rewrite_inventory(manifest_path, manifest)
    elif mutation == "wrong_manifest_root":
        retained = add_retained_snapshot(inventory)
        receipt_path = Path(inventory["retained_snapshot_roots"][str(retained)])
        manifest_path = retained / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["root"] = str(fixture_root / "another-snapshot")
        rewrite_inventory(manifest_path, manifest)
        receipt = json.loads(receipt_path.read_text())
        receipt["snapshot"] = manifest
        receipt.pop("seal")
        receipt["seal"] = wing_migration._digest(receipt)
        rewrite_inventory(receipt_path, receipt)
    elif mutation == "symlink":
        retained = add_retained_snapshot(inventory)
        alias = fixture_root / "retained-alias"
        alias.symlink_to(retained, target_is_directory=True)
        receipt_path = next(iter(inventory["retained_snapshot_roots"].values()))
        inventory["retained_snapshot_roots"] = {str(alias): receipt_path}
    elif mutation == "active_snapshot":
        active = Path(inventory["snapshot_root"])
        write_retained_snapshot(inventory, active)
    else:
        retained = add_retained_snapshot(inventory)
        receipt_path = inventory["retained_snapshot_roots"][str(retained)]
        alternate = f"//{str(retained).lstrip('/')}"
        inventory["retained_snapshot_roots"][alternate] = receipt_path
    rewrite_inventory(inventory_path, inventory)

    with pytest.raises(wing_migration.MigrationError) as caught:
        wing_migration._load_inventory(inventory_path)

    assert caught.value.code == code


def test_retained_snapshot_pruning_preserves_ordinary_drift_detection(tmp_path, monkeypatch):
    inventory_path, _, inventory = full_copy_fixture(tmp_path, monkeypatch)
    retained = add_retained_snapshot(inventory)
    retained_payload = retained / "payload.bin"
    retained_payload.write_bytes(b"retained evidence")
    ordinary = Path(inventory["project_root"]) / "ordinary.txt"
    ordinary.write_text("baseline\n")
    inventory["copy_verification"]["source_preimage_sha256"] = wing_migration._digest(
        wing_migration._copy_preimage(inventory)
    )
    inventory["copy_verification"]["copied_targets"] = [
        wing_migration._copied_target_state(Path(inventory["palace"])),
        wing_migration._copied_target_state(Path(inventory["project_root"])),
    ]
    rewrite_inventory(inventory_path, inventory)

    without_exclusion = wing_migration._unrelated_file_hashes(
        {**inventory, "retained_snapshot_roots": {}}
    )
    admitted = wing_migration._load_inventory(inventory_path)
    visited: list[Path] = []
    real_walk = os.walk

    def observing_walk(*args, **kwargs):
        for current, directories, files in real_walk(*args, **kwargs):
            visited.append(Path(current))
            yield current, directories, files

    monkeypatch.setattr(wing_migration.os, "walk", observing_walk)
    baseline = wing_migration._unrelated_file_hashes(admitted)

    removed = set(without_exclusion) - set(baseline)
    assert removed == {
        str((retained / "manifest.json").relative_to(inventory["fixture_root"])),
        str(retained_payload.relative_to(inventory["fixture_root"])),
    }
    assert not (set(baseline) - set(without_exclusion))
    assert str(ordinary.relative_to(inventory["fixture_root"])) in baseline
    assert not any(wing_migration._inside(path, retained) for path in visited)
    assert not any(
        wing_migration._inside(path, Path(inventory["evidence_root"])) for path in visited
    )

    ordinary.write_text("drift\n")
    assert wing_migration._unrelated_file_hashes(admitted) != baseline


def test_parent_baseline_assertion_uses_one_complete_observation(tmp_path, monkeypatch):
    inventory_path, _, inventory = full_copy_fixture(tmp_path, monkeypatch)
    add_retained_snapshot(inventory)
    rewrite_inventory(inventory_path, inventory)
    receipt_path = Path(inventory["evidence_root"]) / "single-observation-parent.json"
    receipt = wing_migration.inventory(str(inventory_path), str(receipt_path))
    calls = 0
    real_copy_preimage = wing_migration._copy_preimage

    def counted(current):
        nonlocal calls
        calls += 1
        return real_copy_preimage(current)

    monkeypatch.setattr(wing_migration, "_copy_preimage", counted)

    wing_migration._assert_baseline_unchanged(receipt)

    assert calls == 1


def test_snapshotted_parent_baseline_does_not_rescan_lance_rows(tmp_path, monkeypatch):
    inventory_path, _, inventory = full_copy_fixture(tmp_path, monkeypatch)
    receipt_path = Path(inventory["evidence_root"]) / "proved-lance-parent.json"
    wing_migration.inventory(str(inventory_path), str(receipt_path))
    wing_migration.snapshot(str(receipt_path))
    receipt = wing_migration._load_receipt(receipt_path)

    def forbidden_lance_read(*_args, **_kwargs):
        raise AssertionError("snapshot-proved parent reopened Lance")

    monkeypatch.setattr(wing_migration, "_read_lance", forbidden_lance_read)

    wing_migration._assert_baseline_unchanged(receipt)


def test_parent_baseline_hash_detects_lance_content_drift_with_preserved_size_and_mtime(
    tmp_path, monkeypatch
):
    inventory_path, _, inventory = full_copy_fixture(tmp_path, monkeypatch)
    receipt_path = Path(inventory["evidence_root"]) / "lance-content-parent.json"
    wing_migration.inventory(str(inventory_path), str(receipt_path))
    wing_migration.snapshot(str(receipt_path))
    receipt = wing_migration._load_receipt(receipt_path)
    lance_file = next(
        path for path in sorted((Path(inventory["palace"]) / "lance").rglob("*")) if path.is_file()
    )
    metadata = lance_file.stat()
    payload = bytearray(lance_file.read_bytes())
    payload[0] ^= 1
    lance_file.write_bytes(payload)
    os.utime(lance_file, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))

    monkeypatch.setattr(
        wing_migration,
        "_read_lance",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("drift detection reopened Lance")
        ),
    )
    with pytest.raises(wing_migration.MigrationError) as caught:
        wing_migration._assert_baseline_unchanged(receipt)

    assert caught.value.code == "full_copy_baseline_drift"


@pytest.mark.parametrize("mutation", ["added", "deleted", "symlink"])
def test_parent_baseline_hash_refuses_lance_tree_drift(tmp_path, monkeypatch, mutation):
    inventory_path, _, inventory = full_copy_fixture(tmp_path, monkeypatch)
    receipt_path = Path(inventory["evidence_root"]) / f"lance-tree-{mutation}-parent.json"
    wing_migration.inventory(str(inventory_path), str(receipt_path))
    wing_migration.snapshot(str(receipt_path))
    receipt = wing_migration._load_receipt(receipt_path)
    lance_root = Path(inventory["palace"]) / "lance"
    if mutation == "added":
        (lance_root / "unexpected.bin").write_bytes(b"unexpected")
        expected_code = "full_copy_baseline_drift"
    elif mutation == "deleted":
        next(path for path in sorted(lance_root.rglob("*")) if path.is_file()).unlink()
        expected_code = "full_copy_baseline_drift"
    else:
        (lance_root / "unsafe-link").symlink_to(Path(inventory["configuration"]))
        expected_code = "fixture_symlink"

    with pytest.raises(wing_migration.MigrationError) as caught:
        wing_migration._assert_baseline_unchanged(receipt)

    assert caught.value.code == expected_code


def test_stable_tree_hash_refuses_root_replaced_by_symlink_during_hash(tmp_path, monkeypatch):
    root = tmp_path / "lance"
    root.mkdir()
    (root / "data.bin").write_bytes(b"sealed bytes")
    moved = tmp_path / "moved-lance"
    real_file_digest = wing_migration._file_digest
    replaced = False

    def replace_root(path):
        nonlocal replaced
        if not replaced:
            replaced = True
            root.rename(moved)
            root.symlink_to(moved, target_is_directory=True)
        return real_file_digest(path)

    monkeypatch.setattr(wing_migration, "_file_digest", replace_root)

    with pytest.raises(wing_migration.MigrationError) as caught:
        wing_migration._stable_private_tree_hashes(root)

    assert caught.value.code == "fixture_symlink"


def test_full_copy_trial_does_not_inherit_parent_retained_snapshots(tmp_path, monkeypatch):
    inventory_path, _, inventory = full_copy_fixture(tmp_path, monkeypatch)
    add_retained_snapshot(inventory)
    rewrite_inventory(inventory_path, inventory)
    receipt_path = Path(inventory["evidence_root"]) / "retained-parent.json"
    receipt = wing_migration.inventory(str(inventory_path), str(receipt_path))

    trial_path, trial = wing_migration._create_full_copy_trial(receipt, "retained-root-reset")

    assert trial_path.is_file()
    assert trial["inventory"]["retained_snapshot_roots"] == {}


def test_full_copy_receipt_uses_compact_lance_witnesses(tmp_path, monkeypatch):
    inventory_path, _, inventory = full_copy_fixture(tmp_path, monkeypatch)
    receipt_path = Path(inventory["evidence_root"]) / "compact-parent.json"

    receipt = wing_migration.inventory(str(inventory_path), str(receipt_path))

    witness = receipt["pre"]["lance_rows"][0]
    assert set(witness) == {*wing_migration.LANCE_WITNESS_FIELDS, "payload_sha256"}
    assert "text" not in witness
    assert "vector" not in witness
    assert len(witness["payload_sha256"]) == 64
    assert len(receipt["pre"]["lance_rows"]) == table_for(inventory).count_rows()
    assert receipt_path.stat().st_size < 1024 * 1024


def test_compact_lance_scan_refuses_truncated_batch_stream(tmp_path, monkeypatch):
    _, _, inventory = fixture(tmp_path)
    table = table_for(inventory)
    truncated = table.search().limit(1).to_batches(batch_size=1)

    class TruncatedTable:
        def search(self):
            return self

        def to_batches(self, *, batch_size):
            assert batch_size == wing_migration.LANCE_SCAN_BATCH_SIZE
            return truncated

        def count_rows(self):
            return table.count_rows()

    class TruncatedDatabase:
        def open_table(self, name):
            assert name == wing_migration.TABLE_NAME
            return TruncatedTable()

    monkeypatch.setattr(lancedb, "connect", lambda _path: TruncatedDatabase())

    with pytest.raises(wing_migration.MigrationError) as caught:
        wing_migration._read_lance(Path(inventory["palace"]), compact=True)

    assert caught.value.code == "lance_scan_incomplete"


@pytest.mark.parametrize("mutation", ["text", "vector", "unused_metadata"])
def test_full_copy_witness_detects_every_payload_mutation(tmp_path, monkeypatch, mutation):
    inventory_path, _, inventory = full_copy_fixture(tmp_path, monkeypatch)
    receipt_path = Path(inventory["evidence_root"]) / "payload-parent.json"
    wing_migration.inventory(str(inventory_path), str(receipt_path))
    wing_migration.snapshot(str(receipt_path))
    source = next(
        row for row in table_for(inventory).to_arrow().to_pylist() if row["id"] == "source-file"
    )
    if mutation == "text":
        values = {"text": f"{source['text']} changed"}
    elif mutation == "vector":
        vector = list(source["vector"])
        vector[0] = float(vector[0]) + 0.125
        values = {"vector": vector}
    else:
        values = {"agent": "unexpected-agent"}
    table_for(inventory).update(where="id = 'source-file'", values=values)

    assert wing_migration.classify(str(receipt_path)) == "unknown"
    with pytest.raises(wing_migration.MigrationError) as caught:
        wing_migration.recover(str(receipt_path), inventory_path=str(inventory_path))
    assert caught.value.code == "unknown_state_refused"


def test_oversized_receipt_refuses_before_json_decode(tmp_path, monkeypatch, capsys):
    receipt_path = tmp_path / "oversized-receipt.json"
    with receipt_path.open("wb") as handle:
        handle.truncate(wing_migration.MAX_RECEIPT_BYTES + 1)
    os.chmod(receipt_path, 0o600)

    def forbidden_decode(_path):
        raise AssertionError("oversized receipt reached JSON decode")

    monkeypatch.setattr(wing_migration, "_load_json", forbidden_decode)
    with pytest.raises(wing_migration.MigrationError) as caught:
        wing_migration._load_receipt(receipt_path)
    assert caught.value.code == "receipt_too_large"

    monkeypatch.delenv("WING_MIGRATION_INVENTORY_PATH", raising=False)
    assert wing_migration.main(["classify", "--receipt", str(receipt_path)]) == 2
    output = json.loads(capsys.readouterr().out)
    assert output["failed_predicate"] == "receipt_too_large"
    assert output["allowed_next_action"] == "inspect_private_evidence"


def test_compact_witnesses_bound_18300_row_receipt_payload():
    witnesses = [
        wing_migration._lance_row_witness(
            {
                "id": f"row-{index:05d}",
                "wing": "old-wing",
                "source_file": f"/owner/repository/file-{index:05d}.py",
                "source_hash": "a" * 32,
                "chunk_index": index,
                "ingest_mode": "file",
                "chunker_strategy": "regex_structural_v1",
                "type": "",
                "text": "private-payload-sentinel-" + "x" * 2048,
                "vector": [0.125] * 384,
                "unused_metadata": f"metadata-{index}",
            }
        )
        for index in range(18_300)
    ]
    expected = [dict(row, wing="new-wing") for row in witnesses]
    serialized = wing_migration._serialized_json(
        {"pre": {"lance_rows": witnesses}, "expected": {"lance_rows": expected}}
    )

    assert len(witnesses) == 18_300
    assert len(serialized) < 16 * 1024 * 1024
    assert b"private-payload-sentinel" not in serialized
    assert b'"vector"' not in serialized


def test_full_copy_provenance_is_lexical_and_prefix_safe(tmp_path, monkeypatch):
    inventory_path, _, inventory = full_copy_fixture(tmp_path, monkeypatch)
    real_resolve = Path.resolve

    def reject_original_resolution(path, *args, **kwargs):
        if str(path).startswith(inventory["logical_source_root"]):
            raise AssertionError("logical provenance reached filesystem resolution")
        return real_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", reject_original_resolution)
    admitted = wing_migration._load_inventory(inventory_path)

    assert wing_migration._path_scoped(
        f"{inventory['logical_source_root']}/app.py", Path(inventory["logical_source_root"])
    )
    assert wing_migration._path_scoped(
        "//owner-original//repository//app.py", Path(inventory["logical_source_root"])
    )
    assert not wing_migration._path_scoped(
        f"{inventory['logical_source_root']}-sibling/app.py",
        Path(inventory["logical_source_root"]),
    )
    assert admitted["logical_source_root"] == inventory["logical_source_root"]


def test_expected_state_groups_repeated_separators_without_rewriting_rows(tmp_path, monkeypatch):
    _, _, inventory = full_copy_fixture(tmp_path, monkeypatch)
    pre = wing_migration._capture(inventory)
    source = next(row for row in pre["lance_rows"] if row["wing"] == inventory["source_wing"])
    conflict = dict(source)
    conflict.update(
        {
            "id": "separator-collision",
            "wing": inventory["destination_wing"],
            "source_file": "//owner-original//repository//app.py",
        }
    )
    pre["lance_rows"].append(conflict)

    with pytest.raises(wing_migration.MigrationError) as caught:
        wing_migration._expected_state(inventory, pre, "2026-01-15T12:00:00+00:00")

    assert caught.value.code == "file_identity_collision"
    assert source["source_file"] == "/owner-original/repository/app.py"
    assert conflict["source_file"] == "//owner-original//repository//app.py"


def test_full_copy_rejects_dot_components_and_preimage_drift(tmp_path, monkeypatch):
    inventory_path, _, inventory = full_copy_fixture(tmp_path, monkeypatch)
    inventory["logical_source_root"] = f"{inventory['logical_source_root']}/../repository"
    rewrite_inventory(inventory_path, inventory)
    with pytest.raises(wing_migration.MigrationError) as dotted:
        wing_migration.qualify("full-copy")
    assert dotted.value.code == "logical_source_root_invalid"
    assert not (
        Path(inventory["evidence_root"])
        / f"full-copy-receipt-v{wing_migration.RECEIPT_VERSION}.json"
    ).exists()

    inventory_path, _, inventory = full_copy_fixture(tmp_path / "drift", monkeypatch)
    Path(inventory["project_root"], "app.py").write_text("changed after owner seal\n")
    with pytest.raises(wing_migration.MigrationError) as drifted:
        wing_migration.qualify("full-copy")
    assert drifted.value.code == "copy_preimage_mismatch"
    assert not (
        Path(inventory["evidence_root"])
        / f"full-copy-receipt-v{wing_migration.RECEIPT_VERSION}.json"
    ).exists()


def test_full_copy_requires_current_qualification_host(tmp_path, monkeypatch):
    inventory_path, _, inventory = full_copy_fixture(tmp_path, monkeypatch)
    inventory["authority"]["qualification_host"] = "different-host.example.invalid"
    rewrite_inventory(inventory_path, inventory)

    with pytest.raises(wing_migration.MigrationError) as caught:
        wing_migration.qualify("full-copy")

    assert caught.value.code == "qualification_host_mismatch"
    assert not (
        Path(inventory["evidence_root"])
        / f"full-copy-receipt-v{wing_migration.RECEIPT_VERSION}.json"
    ).exists()


def test_full_copy_inventory_binding_and_authority_fail_before_writes(tmp_path, monkeypatch):
    inventory_path, _, inventory = full_copy_fixture(tmp_path, monkeypatch)
    before = wing_migration._capture(wing_migration._load_inventory(inventory_path))
    inventory["authority"]["live_mutation"] = True
    rewrite_inventory(inventory_path, inventory)

    with pytest.raises(wing_migration.MigrationError) as caught:
        wing_migration.qualify("full-copy")

    assert caught.value.code == "full_copy_authority_invalid"
    assert (
        wing_migration._capture(
            {**inventory, "lance_state_format": wing_migration.LANCE_STATE_FORMAT}
        )
        == before
    )
    assert not (
        Path(inventory["evidence_root"])
        / f"full-copy-receipt-v{wing_migration.RECEIPT_VERSION}.json"
    ).exists()


def test_full_copy_refuses_legacy_deadline_authority_before_writes(tmp_path, monkeypatch):
    inventory_path, _, inventory = full_copy_fixture(tmp_path, monkeypatch)
    inventory["authority"]["retention_deadline"] = "legacy-owner-supplied-value"
    rewrite_inventory(inventory_path, inventory)

    with pytest.raises(wing_migration.MigrationError) as caught:
        wing_migration.qualify("full-copy")

    assert caught.value.code == "full_copy_authority_invalid"
    assert not (
        Path(inventory["evidence_root"])
        / f"full-copy-receipt-v{wing_migration.RECEIPT_VERSION}.json"
    ).exists()


def test_full_copy_requires_environment_selected_inventory(tmp_path, monkeypatch):
    inventory_path, _, _ = full_copy_fixture(tmp_path, monkeypatch)
    monkeypatch.delenv("WING_MIGRATION_INVENTORY_PATH")

    with pytest.raises(wing_migration.MigrationError) as missing:
        wing_migration.qualify("full-copy", str(inventory_path))
    assert missing.value.code == "full_copy_inventory_required"

    monkeypatch.setenv("WING_MIGRATION_INVENTORY_PATH", str(inventory_path))
    with pytest.raises(wing_migration.MigrationError) as mismatched:
        wing_migration.qualify("full-copy", str(tmp_path / "other.json"))
    assert mismatched.value.code == "full_copy_inventory_mismatch"


def test_full_copy_requires_private_inventory_permissions_before_writes(tmp_path, monkeypatch):
    inventory_path, _, inventory = full_copy_fixture(tmp_path, monkeypatch)
    os.chmod(inventory_path, 0o640)

    with pytest.raises(wing_migration.MigrationError) as caught:
        wing_migration.qualify("full-copy")

    assert caught.value.code == "inventory_permissions_invalid"
    assert not (
        Path(inventory["evidence_root"])
        / f"full-copy-receipt-v{wing_migration.RECEIPT_VERSION}.json"
    ).exists()


def test_full_copy_never_replaces_existing_or_aliased_report(tmp_path, monkeypatch):
    inventory_path, _, inventory = full_copy_fixture(tmp_path, monkeypatch)
    report_path = (
        Path(inventory["evidence_root"])
        / f"full-copy-qualification-v{wing_migration.RECEIPT_VERSION}.json"
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    retained = tmp_path / "retained-report.json"
    retained.write_text("retained\n")
    report_path.symlink_to(retained)

    with pytest.raises(wing_migration.MigrationError) as caught:
        wing_migration.qualify("full-copy")

    assert caught.value.code == "full_copy_evidence_exists"
    assert report_path.is_symlink()
    assert retained.read_text() == "retained\n"
    assert not (
        Path(inventory["evidence_root"])
        / f"full-copy-receipt-v{wing_migration.RECEIPT_VERSION}.json"
    ).exists()


def test_full_copy_never_replaces_existing_receipt(tmp_path, monkeypatch):
    _, _, inventory = full_copy_fixture(tmp_path, monkeypatch)
    receipt_path = (
        Path(inventory["evidence_root"])
        / f"full-copy-receipt-v{wing_migration.RECEIPT_VERSION}.json"
    )
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text("retained receipt\n")
    os.chmod(receipt_path, 0o600)

    with pytest.raises(wing_migration.MigrationError) as caught:
        wing_migration.qualify("full-copy")

    assert caught.value.code == "full_copy_evidence_exists"
    assert receipt_path.read_text() == "retained receipt\n"
    assert not (
        Path(inventory["evidence_root"])
        / f"full-copy-qualification-v{wing_migration.RECEIPT_VERSION}.json"
    ).exists()


def test_full_copy_receipt_actions_require_original_inventory_binding(tmp_path, monkeypatch):
    inventory_path, _, inventory = full_copy_fixture(tmp_path, monkeypatch)
    receipt_path = (
        Path(inventory["evidence_root"])
        / f"full-copy-receipt-v{wing_migration.RECEIPT_VERSION}.json"
    )
    receipt = wing_migration.inventory(str(inventory_path), str(receipt_path))
    receipt["unrelated_preimage"] = wing_migration._digest(
        wing_migration._unrelated_file_hashes(receipt["inventory"])
    )
    wing_migration._save_receipt(receipt)
    wing_migration.snapshot(str(receipt_path))

    with pytest.raises(wing_migration.MigrationError) as caught:
        wing_migration.apply(str(receipt_path))

    assert caught.value.code == "inventory_binding_required"
    assert wing_migration.classify(str(receipt_path)) == "original"


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (
            lambda inventory: inventory["runtime_authority"].__setitem__(
                "qualification_package_hashes", {"mempalace_code/__init__.py": "0" * 64}
            ),
            "runtime_package_hash_drift",
        ),
        (
            lambda inventory: inventory["copy_verification"].__setitem__("source_snapshot_id", ""),
            "copy_verification_invalid",
        ),
    ],
)
def test_full_copy_admission_refusal_preserves_complete_manifest(
    tmp_path, monkeypatch, mutate, code
):
    inventory_path, _, inventory = full_copy_fixture(tmp_path, monkeypatch)
    mutate(inventory)
    rewrite_inventory(inventory_path, inventory)
    evidence_root = Path(inventory["evidence_root"])
    receipt_path = evidence_root / f"full-copy-receipt-v{wing_migration.RECEIPT_VERSION}.json"
    report_path = evidence_root / f"full-copy-qualification-v{wing_migration.RECEIPT_VERSION}.json"
    before = filesystem_manifest(Path(inventory["fixture_root"]), receipt_path, report_path)

    with pytest.raises(wing_migration.MigrationError) as caught:
        wing_migration.qualify("full-copy")

    assert caught.value.code == code
    assert filesystem_manifest(Path(inventory["fixture_root"]), receipt_path, report_path) == before


def test_full_copy_runtime_validation_fails_before_artifacts_or_mutation(tmp_path, monkeypatch):
    inventory_path, _, inventory = full_copy_fixture(tmp_path, monkeypatch)
    evidence_root = Path(inventory["evidence_root"])
    receipt_path = evidence_root / f"full-copy-receipt-v{wing_migration.RECEIPT_VERSION}.json"
    lock = Path(inventory["lock"])
    lock_paths = (
        lock,
        lock.with_name(f"{lock.name}.metadata.lock"),
        lock.with_name(f"{lock.name}.owners.json"),
    )
    before = filesystem_manifest(Path(inventory["fixture_root"]), receipt_path, *lock_paths)

    def reject_runtime(_receipt):
        raise wing_migration.MigrationError("runtime_revalidation_failed", "runtime rejected")

    monkeypatch.setattr(wing_migration, "_probe_runtime_identity", reject_runtime)
    with pytest.raises(wing_migration.MigrationError) as caught:
        wing_migration.inventory(str(inventory_path), str(receipt_path))

    assert caught.value.code == "runtime_revalidation_failed"
    assert filesystem_manifest(Path(inventory["fixture_root"]), receipt_path, *lock_paths) == before


def test_full_copy_runtime_validation_repeats_under_fence(tmp_path, monkeypatch):
    inventory_path, _, inventory = full_copy_fixture(tmp_path, monkeypatch)
    receipt_path = (
        Path(inventory["evidence_root"])
        / f"full-copy-receipt-v{wing_migration.RECEIPT_VERSION}.json"
    )
    lock = Path(inventory["lock"])
    lock_paths = (
        lock,
        lock.with_name(f"{lock.name}.metadata.lock"),
        lock.with_name(f"{lock.name}.owners.json"),
    )
    before = filesystem_manifest(Path(inventory["fixture_root"]), receipt_path, *lock_paths)
    real_probe = wing_migration._probe_runtime_identity
    calls = 0

    def drift_between_fence_checks(receipt):
        nonlocal calls
        calls += 1
        observed = real_probe(receipt)
        if calls == 2:
            observed["runtime_prefix"] = "/private/runtime-drift"
        return observed

    monkeypatch.setattr(wing_migration, "_probe_runtime_identity", drift_between_fence_checks)
    with pytest.raises(wing_migration.MigrationError) as caught:
        wing_migration.inventory(str(inventory_path), str(receipt_path))

    assert caught.value.code == "runtime_provenance_drift"
    assert calls == 2
    assert filesystem_manifest(Path(inventory["fixture_root"]), receipt_path, *lock_paths) == before


@pytest.mark.parametrize("anchor_index", [0, 1])
def test_missing_lock_anchor_refuses_without_artifacts(tmp_path, anchor_index):
    inventory_path, receipt_path, inventory = fixture(tmp_path)
    lock_paths = wing_migration._lock_artifact_paths(Path(inventory["lock"]))
    lock_paths[anchor_index].unlink()
    before = filesystem_manifest(Path(inventory["fixture_root"]), receipt_path, *lock_paths)

    with pytest.raises(wing_migration.MigrationError) as caught:
        inventory_receipt(inventory_path, receipt_path)

    assert caught.value.code == "lock_anchor_invalid"
    assert filesystem_manifest(Path(inventory["fixture_root"]), receipt_path, *lock_paths) == before


@pytest.mark.parametrize("preexisting_lock_artifacts", [False, True])
def test_fenced_client_refusal_preserves_complete_lock_manifest(
    tmp_path, monkeypatch, preexisting_lock_artifacts
):
    inventory_path, receipt_path, inventory = fixture(tmp_path)
    lock = Path(inventory["lock"])
    lock_paths = (
        lock,
        lock.with_name(f"{lock.name}.metadata.lock"),
        lock.with_name(f"{lock.name}.owners.json"),
    )
    if preexisting_lock_artifacts:
        lock.write_bytes(b"retained lock evidence\n")
        lock_paths[1].write_bytes(b"retained metadata evidence\n")
        lock_paths[2].write_bytes(b"{}\n")
    before = filesystem_manifest(Path(inventory["fixture_root"]), receipt_path, *lock_paths)
    calls = 0

    def observe_clients(_inventory):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise wing_migration.MigrationError("fixture_client_active", "foreign client")

    monkeypatch.setattr(wing_migration, "_observe_fixture_clients", observe_clients)

    with pytest.raises(wing_migration.MigrationError, match="fixture_client_active"):
        inventory_receipt(inventory_path, receipt_path)

    assert calls == 2
    after = filesystem_manifest(Path(inventory["fixture_root"]), receipt_path, *lock_paths)
    assert after == before


def test_client_observation_scopes_timeout_to_active_targets(tmp_path, monkeypatch):
    _, _, inventory = fixture(tmp_path)
    snapshot = Path(inventory["snapshot_root"])
    snapshot.mkdir()
    retained = Path(inventory["fixture_root"]) / "retained-snapshot"
    retained.mkdir()
    inventory["retained_snapshot_roots"] = {str(retained): "historical-receipt.json"}
    external_kg = Path(inventory["kg_candidates"][1])
    external_sidecars = [Path(f"{external_kg}-wal"), Path(f"{external_kg}-shm")]
    for sidecar in external_sidecars:
        sidecar.write_bytes(b"sqlite sidecar")
    observed = {}

    def run(command, **kwargs):
        observed["command"] = command
        observed["timeout"] = kwargs["timeout"]
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="")

    monkeypatch.setattr(wing_migration.shutil, "which", lambda _name: "/usr/sbin/lsof")
    monkeypatch.setattr(wing_migration.subprocess, "run", run)

    wing_migration._observe_fixture_clients(inventory)

    assert observed["command"][:3] == ["/usr/sbin/lsof", "-Fpn", "+D"]
    for directory in sorted((Path(inventory["palace"]), Path(inventory["project_root"]), snapshot)):
        index = observed["command"].index(str(directory))
        assert observed["command"][index - 1] == "+D"
    assert inventory["configuration"] in observed["command"]
    assert inventory["marker"] in observed["command"]
    assert inventory["lock"] in observed["command"]
    assert all(str(sidecar) in observed["command"] for sidecar in external_sidecars)
    assert inventory["evidence_root"] not in observed["command"]
    assert inventory["runtime_root"] not in observed["command"]
    assert str(retained) not in observed["command"]
    assert observed["timeout"] == wing_migration.PROCESS_OBSERVATION_TIMEOUT_SECONDS == 60


def test_apply_refuses_process_holding_only_external_kg_sidecar(tmp_path):
    inventory_path, receipt_path, inventory = fixture(tmp_path)
    inventory_receipt(inventory_path, receipt_path)
    wing_migration.snapshot(str(receipt_path))
    external_wal = Path(f"{inventory['kg_candidates'][1]}-wal")
    external_wal.write_bytes(b"sqlite sidecar")
    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            (
                "import sys; "
                "handle = open(sys.argv[1], 'rb'); "
                "print('ready', flush=True); "
                "sys.stdin.buffer.read(1)"
            ),
            str(external_wal),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    assert holder.stdin is not None
    assert holder.stdout is not None
    assert holder.stdout.readline() == "ready\n"
    before = filesystem_manifest(Path(inventory["fixture_root"]))
    try:
        with pytest.raises(wing_migration.MigrationError) as caught:
            wing_migration.apply(str(receipt_path))
    finally:
        holder.stdin.write("x")
        holder.stdin.flush()
        holder.wait(timeout=5)

    assert caught.value.code == "fixture_client_active"
    assert filesystem_manifest(Path(inventory["fixture_root"])) == before


def test_failed_fence_cleanup_preserves_real_competing_lease(tmp_path, monkeypatch):
    inventory_path, receipt_path, inventory = fixture(tmp_path)
    lock = Path(inventory["lock"])
    calls = 0

    def observe_clients(_inventory):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise wing_migration.MigrationError("fixture_client_active", "foreign client")

    monkeypatch.setattr(wing_migration, "_observe_fixture_clients", observe_clients)
    original_cleanup = wing_migration._cleanup_failed_lock_artifacts
    competing = {}

    def interleave_cleanup(lock_object, paths, before):
        from mempalace_code.operation_lock import OperationLock, OperationLockedError

        competing_lock = OperationLock(lock)
        lease = competing_lock.acquire_shared("competing-cleanup-owner")
        competing["lease"] = lease
        try:
            owner = competing_lock.owner_details()
            assert owner is not None
            assert owner["operation"] == "competing-cleanup-owner"
            with pytest.raises(OperationLockedError):
                OperationLock(lock).acquire_exclusive("third-owner")
            original_cleanup(lock_object, paths, before)
            owner = competing_lock.owner_details()
            assert owner is not None
            assert owner["operation"] == "competing-cleanup-owner"
        finally:
            lease.release()

    monkeypatch.setattr(wing_migration, "_cleanup_failed_lock_artifacts", interleave_cleanup)

    with pytest.raises(wing_migration.MigrationError, match="fixture_client_active"):
        inventory_receipt(inventory_path, receipt_path)
    assert "lease" in competing


def test_failed_fence_cleanup_keeps_inode_opened_by_waiting_contender(tmp_path, monkeypatch):
    _, _, inventory = fixture(tmp_path)
    lock_path = Path(inventory["lock"])
    lock_paths = wing_migration._lock_artifact_paths(lock_path)
    absent: dict[Path, tuple[bool, bytes | None, int | None, int | None]] = {
        path: (False, None, None, None) for path in lock_paths
    }
    opened = threading.Event()
    resume = threading.Event()
    result = {}
    real_open = os.open

    def pausing_open(path, flags, mode=0o777):
        descriptor = real_open(path, flags, mode)
        if threading.current_thread().name == "lock-contender" and Path(path) == lock_path:
            opened.set()
            assert resume.wait(timeout=5)
        return descriptor

    monkeypatch.setattr(os, "open", pausing_open)

    def acquire_contending_lease():
        from mempalace_code.operation_lock import OperationLock

        result["lease"] = OperationLock(lock_path).acquire_shared("waiting-contender")

    contender = threading.Thread(target=acquire_contending_lease, name="lock-contender")
    contender.start()
    assert opened.wait(timeout=5)

    from mempalace_code.operation_lock import OperationLock, OperationLockedError

    lock = OperationLock(lock_path)
    wing_migration._cleanup_failed_lock_artifacts(lock, lock_paths, absent)
    resume.set()
    contender.join(timeout=5)
    assert not contender.is_alive()
    lease = result["lease"]
    try:
        assert os.fstat(lease.fd).st_ino == lock_path.stat().st_ino
        with pytest.raises(OperationLockedError):
            OperationLock(lock_path).acquire_exclusive("third-owner")
    finally:
        lease.release()
    with OperationLock(lock_path).acquire_exclusive("third-owner"):
        pass


def test_fenced_capacity_refusal_preserves_complete_artifact_manifest(tmp_path, monkeypatch):
    inventory_path, receipt_path, inventory = fixture(tmp_path)
    lock = Path(inventory["lock"])
    lock_paths = (
        lock,
        lock.with_name(f"{lock.name}.metadata.lock"),
        lock.with_name(f"{lock.name}.owners.json"),
    )
    before = filesystem_manifest(Path(inventory["fixture_root"]), receipt_path, *lock_paths)
    calls = 0

    def capacity(_inventory):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise wing_migration.MigrationError("insufficient_disk", "late refusal")

    monkeypatch.setattr(wing_migration, "_assert_recovery_capacity", capacity)

    with pytest.raises(wing_migration.MigrationError, match="insufficient_disk"):
        inventory_receipt(inventory_path, receipt_path)

    assert calls == 2
    after = filesystem_manifest(Path(inventory["fixture_root"]), receipt_path, *lock_paths)
    assert after == before


def test_full_copy_rejects_copied_symlink_without_following_it(tmp_path, monkeypatch):
    inventory_path, _, inventory = full_copy_fixture(tmp_path, monkeypatch)
    sentinel = tmp_path / "excluded-original-sentinel"
    sentinel.write_text("private sentinel\n")
    link = Path(inventory["project_root"]) / "copied-link"
    link.symlink_to(sentinel)
    inventory["copy_verification"]["copied_targets"] = [
        wing_migration._copied_target_state(Path(inventory["palace"])),
        wing_migration._copied_target_state(Path(inventory["project_root"])),
    ]
    rewrite_inventory(inventory_path, inventory)

    with pytest.raises(wing_migration.MigrationError) as caught:
        wing_migration.qualify("full-copy")

    assert caught.value.code == "fixture_symlink"
    assert sentinel.read_text() == "private sentinel\n"


def test_full_copy_symlink_guard_does_not_resolve_or_read_excluded_target(tmp_path, monkeypatch):
    inventory_path, _, inventory = full_copy_fixture(tmp_path, monkeypatch)
    sentinel = tmp_path / "excluded-original-sentinel"
    sentinel.write_text("private sentinel\n")
    link = Path(inventory["project_root"]) / "copied-link"
    link.symlink_to(sentinel)
    inventory["copy_verification"]["copied_targets"] = [
        wing_migration._copied_target_state(Path(inventory["palace"])),
        wing_migration._copied_target_state(Path(inventory["project_root"])),
    ]
    rewrite_inventory(inventory_path, inventory)
    real_resolve = Path.resolve
    real_read_bytes = Path.read_bytes

    def reject_sentinel_resolution(path, *args, **kwargs):
        if path in {link, sentinel}:
            raise AssertionError("excluded target was resolved")
        return real_resolve(path, *args, **kwargs)

    def reject_sentinel_read(path, *args, **kwargs):
        if path in {link, sentinel}:
            raise AssertionError("excluded target was read")
        return real_read_bytes(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", reject_sentinel_resolution)
    monkeypatch.setattr(Path, "read_bytes", reject_sentinel_read)

    with pytest.raises(wing_migration.MigrationError) as caught:
        wing_migration.qualify("full-copy")

    assert caught.value.code == "fixture_symlink"
    assert sentinel.read_text() == "private sentinel\n"


def test_external_kg_wal_symlink_refuses_before_target_read(tmp_path, monkeypatch):
    inventory_path, _, inventory = full_copy_fixture(tmp_path, monkeypatch)
    sentinel = tmp_path / "excluded-wal-sentinel"
    sentinel.write_text("private WAL sentinel\n")
    wal_path = Path(f"{inventory['kg_candidates'][1]}-wal")
    wal_path.unlink(missing_ok=True)
    wal_path.symlink_to(sentinel)
    real_read_bytes = Path.read_bytes

    def reject_excluded_read(path, *args, **kwargs):
        if path in {wal_path, sentinel}:
            raise AssertionError("excluded WAL target was read")
        return real_read_bytes(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_bytes", reject_excluded_read)
    receipt_path = Path(inventory["evidence_root"]) / "wal-symlink-receipt.json"
    with pytest.raises(wing_migration.MigrationError) as caught:
        wing_migration.inventory(str(inventory_path), str(receipt_path))

    assert caught.value.code == "fixture_symlink"
    assert sentinel.read_text() == "private WAL sentinel\n"


def test_fixture_authorization_symlink_refuses_before_target_read(tmp_path, monkeypatch):
    inventory_path, receipt_path, inventory = fixture(tmp_path)
    marker = Path(inventory["fixture_root"]) / wing_migration.FIXTURE_MARKER
    external = tmp_path / "external-fixture-marker.json"
    external.write_bytes(marker.read_bytes())
    marker.unlink()
    marker.symlink_to(external)
    real_read_text = Path.read_text

    def reject_excluded_read(path, *args, **kwargs):
        if path in {marker, external}:
            raise AssertionError("excluded fixture marker was read")
        return real_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", reject_excluded_read)
    with pytest.raises(wing_migration.MigrationError) as caught:
        inventory_receipt(inventory_path, receipt_path)

    assert caught.value.code == "fixture_symlink"


def test_symlink_chain_stops_before_access_below_symlink(tmp_path, monkeypatch):
    root = tmp_path / "trusted"
    root.mkdir()
    target = tmp_path / "excluded"
    target.mkdir()
    link = root / "linked"
    link.symlink_to(target, target_is_directory=True)
    beneath = link / "secret.txt"
    real_lstat = Path.lstat
    observed = []

    def guarded_lstat(path):
        observed.append(path)
        if path == beneath:
            raise AssertionError("accessed below a symlink")
        return real_lstat(path)

    monkeypatch.setattr(Path, "lstat", guarded_lstat)
    with pytest.raises(wing_migration.MigrationError) as caught:
        wing_migration._reject_symlink_chain(beneath, root)

    assert caught.value.code == "fixture_symlink"
    assert beneath not in observed


def test_runtime_identity_scopes_symlink_checks_to_owned_roots(tmp_path, monkeypatch):
    real_parent = tmp_path / "real"
    real_parent.mkdir()
    platform_alias = tmp_path / "platform-alias"
    platform_alias.symlink_to(real_parent, target_is_directory=True)
    prefix = platform_alias / "venv"
    metadata_file = Path("mempalace_code-1.14.1.dist-info/METADATA")
    metadata_path = prefix / "lib" / "python" / "site-packages" / metadata_file
    metadata_path.parent.mkdir(parents=True)
    metadata_path.write_text("Version: 1.14.1\n", encoding="utf-8")

    class Distribution:
        version = "1.14.1"
        files = (metadata_file,)

        @staticmethod
        def locate_file(path):
            return metadata_path.parents[1] / path

    monkeypatch.setattr(sys, "prefix", str(prefix))
    monkeypatch.setattr(
        wing_migration.importlib.metadata, "distribution", lambda _name: Distribution()
    )
    monkeypatch.setattr(wing_migration, "_model_cache_home", lambda: tmp_path / "hf-home")
    monkeypatch.setattr(wing_migration, "_seal_model_cache", lambda _path: {"files": {}})

    identity = wing_migration._runtime_identity()

    assert identity["distribution_origin"] == str(metadata_path.parent)


def test_runtime_identity_rejects_symlink_inside_runtime_prefix(tmp_path, monkeypatch):
    prefix = tmp_path / "venv"
    outside = tmp_path / "outside"
    outside.mkdir()
    site_packages = prefix / "lib" / "python" / "site-packages"
    site_packages.parent.mkdir(parents=True)
    site_packages.symlink_to(outside, target_is_directory=True)
    metadata_file = Path("mempalace_code-1.14.1.dist-info/METADATA")
    metadata_path = site_packages / metadata_file
    metadata_path.parent.mkdir()
    metadata_path.write_text("Version: 1.14.1\n", encoding="utf-8")

    class Distribution:
        version = "1.14.1"
        files = (metadata_file,)

        @staticmethod
        def locate_file(path):
            return site_packages / path

    monkeypatch.setattr(sys, "prefix", str(prefix))
    monkeypatch.setattr(
        wing_migration.importlib.metadata, "distribution", lambda _name: Distribution()
    )

    with pytest.raises(wing_migration.MigrationError) as caught:
        wing_migration._runtime_identity()

    assert caught.value.code == "fixture_symlink"


def test_descendant_apply_revalidates_parent_authority_and_baseline(tmp_path, monkeypatch):
    inventory_path, _, inventory = full_copy_fixture(tmp_path, monkeypatch)
    parent_path = Path(inventory["evidence_root"]) / "parent-receipt.json"
    parent = wing_migration.inventory(str(inventory_path), str(parent_path))
    wing_migration.snapshot(str(parent_path))
    parent = wing_migration._load_receipt(parent_path)
    trial_path, _ = wing_migration._create_full_copy_trial(parent, "parent-drift")
    Path(inventory["project_root"], "app.py").write_text("parent baseline changed\n")

    with pytest.raises(wing_migration.MigrationError) as caught:
        wing_migration.apply(str(trial_path))

    assert caught.value.code == "full_copy_unrelated_drift"
    assert wing_migration._load_receipt(trial_path)["phase"] == "snapshotted"


def test_descendant_apply_rechecks_parent_after_child_fence(tmp_path, monkeypatch):
    inventory_path, _, inventory = full_copy_fixture(tmp_path, monkeypatch)
    parent_path = Path(inventory["evidence_root"]) / "parent-receipt.json"
    parent = wing_migration.inventory(str(inventory_path), str(parent_path))
    wing_migration.snapshot(str(parent_path))
    parent = wing_migration._load_receipt(parent_path)
    trial_path, _ = wing_migration._create_full_copy_trial(parent, "parent-interleave")
    real_fence = wing_migration._fence
    calls = 0

    @contextmanager
    def interleaving_fence(current, **kwargs):
        nonlocal calls
        calls += 1
        with real_fence(current, **kwargs):
            if calls == 2:
                changed = wing_migration._load_receipt(parent_path)
                changed["phase"] = "parent-reordered"
                wing_migration._save_receipt(changed)
            yield

    monkeypatch.setattr(wing_migration, "_fence", interleaving_fence)
    with pytest.raises(wing_migration.MigrationError) as caught:
        wing_migration.apply(str(trial_path))

    assert caught.value.code == "parent_binding_invalid"
    assert wing_migration._load_receipt(trial_path)["phase"] == "snapshotted"


def test_descendant_apply_rechecks_parent_lance_bytes_after_child_fence(tmp_path, monkeypatch):
    inventory_path, _, inventory = full_copy_fixture(tmp_path, monkeypatch)
    parent_path = Path(inventory["evidence_root"]) / "parent-lance-receipt.json"
    parent = wing_migration.inventory(str(inventory_path), str(parent_path))
    wing_migration.snapshot(str(parent_path))
    parent = wing_migration._load_receipt(parent_path)
    trial_path, _ = wing_migration._create_full_copy_trial(parent, "parent-lance-interleave")
    real_fence = wing_migration._fence
    calls = 0

    @contextmanager
    def interleaving_fence(current, **kwargs):
        nonlocal calls
        calls += 1
        with real_fence(current, **kwargs):
            if calls == 2:
                lance_root = Path(inventory["palace"]) / "lance"
                (lance_root / "post-child-fence-drift.bin").write_bytes(b"drift")
            yield

    monkeypatch.setattr(wing_migration, "_fence", interleaving_fence)
    with pytest.raises(wing_migration.MigrationError) as caught:
        wing_migration.apply(str(trial_path))

    assert caught.value.code == "full_copy_baseline_drift"
    assert wing_migration._load_receipt(trial_path)["phase"] == "snapshotted"


def test_descendant_recovery_revalidates_parent_receipt_ordering(tmp_path, monkeypatch):
    inventory_path, _, inventory = full_copy_fixture(tmp_path, monkeypatch)
    parent_path = Path(inventory["evidence_root"]) / "parent-receipt.json"
    parent = wing_migration.inventory(str(inventory_path), str(parent_path))
    wing_migration.snapshot(str(parent_path))
    parent = wing_migration._load_receipt(parent_path)
    trial_path, _ = wing_migration._create_full_copy_trial(parent, "authority-drift")
    parent["phase"] = "reordered"
    wing_migration._save_receipt(parent)

    with pytest.raises(wing_migration.MigrationError) as caught:
        wing_migration.recover(str(trial_path))

    assert caught.value.code == "parent_binding_invalid"


def test_descendant_recovery_rechecks_parent_after_child_fence(tmp_path, monkeypatch):
    inventory_path, _, inventory = full_copy_fixture(tmp_path, monkeypatch)
    parent_path = Path(inventory["evidence_root"]) / "parent-receipt.json"
    parent = wing_migration.inventory(str(inventory_path), str(parent_path))
    wing_migration.snapshot(str(parent_path))
    parent = wing_migration._load_receipt(parent_path)
    trial_path, _ = wing_migration._create_full_copy_trial(parent, "recovery-interleave")
    real_fence = wing_migration._fence
    calls = 0

    @contextmanager
    def interleaving_fence(current, **kwargs):
        nonlocal calls
        calls += 1
        with real_fence(current, **kwargs):
            if calls == 2:
                changed = wing_migration._load_receipt(parent_path)
                changed["phase"] = "parent-reordered"
                wing_migration._save_receipt(changed)
            yield

    monkeypatch.setattr(wing_migration, "_fence", interleaving_fence)
    with pytest.raises(wing_migration.MigrationError) as caught:
        wing_migration.recover(str(trial_path))

    assert caught.value.code == "parent_binding_invalid"
    assert calls == 2
    assert wing_migration._load_receipt(trial_path)["phase"] == "snapshotted"


def test_descendant_copy_failure_retains_bound_recovery_receipt(tmp_path, monkeypatch):
    inventory_path, _, inventory = full_copy_fixture(tmp_path, monkeypatch)
    parent_path = Path(inventory["evidence_root"]) / "parent-receipt.json"
    parent = wing_migration.inventory(str(inventory_path), str(parent_path))
    wing_migration.snapshot(str(parent_path))
    parent = wing_migration._load_receipt(parent_path)

    def fail_copy(*_args, **_kwargs):
        raise OSError("copy interrupted")

    monkeypatch.setattr(wing_migration, "_copytree_without_sqlite", fail_copy)
    trial_receipt_path = wing_migration._full_copy_trial_receipt_path(parent, "copy-failure")

    with pytest.raises(OSError, match="copy interrupted"):
        wing_migration._create_full_copy_trial(parent, "copy-failure")

    trial = wing_migration._load_receipt(trial_receipt_path)
    assert trial["inventory"]["construction_phase"] == "copying"
    assert trial["inventory"]["fixture_id"] == "trial-copy-failure"
    assert trial["recovery_command"] == wing_migration._recovery_command(trial)
    assert str(trial_receipt_path) in trial["recovery_command"]
    assert "--inventory" not in trial["recovery_command"]

    assert wing_migration.recover(str(trial_receipt_path)) == {
        "state": "original",
        "restored": True,
    }
    assert wing_migration._load_receipt(trial_receipt_path)["phase"] == "recovered"
    wing_migration._assert_baseline_unchanged(wing_migration._load_receipt(parent_path))


def test_descendant_snapshot_refusal_recovers_without_construction_marker(tmp_path, monkeypatch):
    inventory_path, _, inventory = full_copy_fixture(tmp_path, monkeypatch)
    parent_path = Path(inventory["evidence_root"]) / "parent-receipt.json"
    parent = wing_migration.inventory(str(inventory_path), str(parent_path))
    wing_migration.snapshot(str(parent_path))
    parent = wing_migration._load_receipt(parent_path)
    trial_receipt_path = wing_migration._full_copy_trial_receipt_path(parent, "snapshot-refusal")

    def refuse_snapshot(_receipt_path):
        raise wing_migration.MigrationError("fixture_client_active", "foreign client")

    monkeypatch.setattr(wing_migration, "snapshot", refuse_snapshot)
    with pytest.raises(wing_migration.MigrationError) as caught:
        wing_migration._create_full_copy_trial(parent, "snapshot-refusal")

    assert caught.value.code == "fixture_client_active"
    trial = wing_migration._load_receipt(trial_receipt_path)
    assert trial["snapshot"] is None
    assert trial["phase"] == "inventoried"
    assert "construction_phase" not in trial["inventory"]

    assert wing_migration.recover(str(trial_receipt_path)) == {
        "state": "original",
        "restored": True,
    }
    recovered = wing_migration._load_receipt(trial_receipt_path)
    assert recovered["phase"] == "recovered"
    assert recovered["inventory"]["construction_phase"] == "recovered"
    wing_migration._assert_baseline_unchanged(wing_migration._load_receipt(parent_path))


def test_full_copy_copy_failure_reports_descendant_recovery(tmp_path, monkeypatch):
    _, _, inventory = full_copy_fixture(tmp_path, monkeypatch)
    report_path = (
        Path(inventory["evidence_root"])
        / f"full-copy-qualification-v{wing_migration.RECEIPT_VERSION}.json"
    )

    def fail_copy(*_args, **_kwargs):
        raise OSError("copy interrupted")

    monkeypatch.setattr(wing_migration, "_copytree_without_sqlite", fail_copy)

    with pytest.raises(wing_migration.MigrationError, match="full_copy_operation_failed"):
        wing_migration.qualify("full-copy")

    failure = json.loads(report_path.read_text())
    receipt_path = Path(failure["receipt"])
    receipt = wing_migration._load_receipt(receipt_path)
    assert receipt_path.name == "receipt.json"
    assert receipt["inventory"]["fixture_id"] == "trial-rehearsal"
    assert failure["recovery_command"] == receipt["recovery_command"]
    assert failure["failed_predicate"] == "full_copy_operation_failed"
    assert "--inventory" not in failure["recovery_command"]


def test_full_copy_failure_before_child_receipt_keeps_parent_recovery_target(tmp_path, monkeypatch):
    _, _, inventory = full_copy_fixture(tmp_path, monkeypatch)
    parent_path = (
        Path(inventory["evidence_root"])
        / f"full-copy-receipt-v{wing_migration.RECEIPT_VERSION}.json"
    )
    report_path = (
        Path(inventory["evidence_root"])
        / f"full-copy-qualification-v{wing_migration.RECEIPT_VERSION}.json"
    )

    def fail_before_receipt(*_args, **_kwargs):
        raise wing_migration.MigrationError("trial_evidence_exists", "retained trial")

    monkeypatch.setattr(wing_migration, "_create_full_copy_trial", fail_before_receipt)

    with pytest.raises(wing_migration.MigrationError) as caught:
        wing_migration.qualify("full-copy")

    assert caught.value.code == "trial_evidence_exists"
    failure = json.loads(report_path.read_text())
    assert failure["receipt"] == str(parent_path)
    assert failure["failed_predicate"] == "trial_evidence_exists"
    assert "--inventory" in failure["recovery_command"]


def test_full_copy_later_trial_failure_resets_recovery_target_to_parent(tmp_path, monkeypatch):
    _, _, inventory = full_copy_fixture(tmp_path, monkeypatch)
    parent_path = (
        Path(inventory["evidence_root"])
        / f"full-copy-receipt-v{wing_migration.RECEIPT_VERSION}.json"
    )
    report_path = (
        Path(inventory["evidence_root"])
        / f"full-copy-qualification-v{wing_migration.RECEIPT_VERSION}.json"
    )
    real_create = wing_migration._create_full_copy_trial
    calls = 0

    def fail_third_trial(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise wing_migration.MigrationError("trial_evidence_exists", "retained trial")
        return real_create(*args, **kwargs)

    monkeypatch.setattr(wing_migration, "_create_full_copy_trial", fail_third_trial)

    with pytest.raises(wing_migration.MigrationError) as caught:
        wing_migration.qualify("full-copy")

    assert caught.value.code == "trial_evidence_exists"
    assert calls == 3
    failure = json.loads(report_path.read_text())
    assert failure["receipt"] == str(parent_path)
    assert failure["failed_predicate"] == "trial_evidence_exists"
    assert "--inventory" in failure["recovery_command"]


def test_full_copy_parent_baseline_failure_reports_parent_recovery(tmp_path, monkeypatch):
    _, _, inventory = full_copy_fixture(tmp_path, monkeypatch)
    parent_path = (
        Path(inventory["evidence_root"])
        / f"full-copy-receipt-v{wing_migration.RECEIPT_VERSION}.json"
    )
    rehearsal_path = (
        Path(inventory["evidence_root"])
        / "trials"
        / f"v{wing_migration.RECEIPT_VERSION}"
        / "rehearsal"
        / "evidence"
        / "receipt.json"
    )
    report_path = (
        Path(inventory["evidence_root"])
        / f"full-copy-qualification-v{wing_migration.RECEIPT_VERSION}.json"
    )
    real_assert = wing_migration._assert_baseline_unchanged

    def fail_after_rehearsal_recovery(receipt):
        if (
            rehearsal_path.is_file()
            and wing_migration._load_receipt(rehearsal_path)["phase"] == "recovered"
        ):
            raise wing_migration.MigrationError("full_copy_baseline_drift", "baseline changed")
        real_assert(receipt)

    monkeypatch.setattr(wing_migration, "_assert_baseline_unchanged", fail_after_rehearsal_recovery)

    with pytest.raises(wing_migration.MigrationError) as caught:
        wing_migration.qualify("full-copy")

    assert caught.value.code == "full_copy_baseline_drift"
    failure = json.loads(report_path.read_text())
    assert failure["receipt"] == str(parent_path)
    assert failure["failed_predicate"] == "full_copy_baseline_drift"
    assert "--inventory" in failure["recovery_command"]


@pytest.mark.parametrize(
    "failed_predicate",
    ["runtime_source_baseline_timeout", "runtime_destination_probe_timeout"],
)
def test_full_copy_runtime_timeout_retains_predicate_and_recovers(
    tmp_path, monkeypatch, failed_predicate
):
    _, _, inventory = full_copy_fixture(tmp_path / failed_predicate, monkeypatch)
    report_path = (
        Path(inventory["evidence_root"])
        / f"full-copy-qualification-v{wing_migration.RECEIPT_VERSION}.json"
    )

    def timeout_probe(_receipt):
        raise wing_migration.MigrationError(failed_predicate, "bounded mine timeout")

    monkeypatch.setattr(wing_migration, "_runtime_probe", timeout_probe)

    with pytest.raises(wing_migration.MigrationError) as caught:
        wing_migration.qualify("full-copy")

    assert caught.value.code == failed_predicate
    failure = json.loads(report_path.read_text())
    assert failure["failed_predicate"] == failed_predicate
    assert failure["failure_detail"] == "bounded mine timeout"
    trial = wing_migration._load_receipt(failure["receipt"])
    assert trial["phase"] == "tiny_hashes"
    assert wing_migration._file_state(Path(trial["inventory"]["marker"])) == trial["pre"]["marker"]
    assert wing_migration.classify(failure["receipt"]) == "partial"
    assert wing_migration.recover(failure["receipt"]) == {"state": "original", "restored": True}
    restored = wing_migration._load_receipt(failure["receipt"])
    assert restored["phase"] == "recovered"
    assert wing_migration._capture(restored["inventory"]) == restored["pre"]


def test_full_copy_trial_preserves_external_wal_and_aliases(tmp_path, monkeypatch):
    inventory_path, _, inventory = full_copy_fixture(tmp_path, monkeypatch)
    external = Path(inventory["kg_candidates"][1])
    inventory["kg_candidates"].append(str(external))
    writer = sqlite3.connect(str(external))
    writer.execute("PRAGMA journal_mode=WAL")
    writer.execute(
        "INSERT INTO entities(id,name,type,properties) VALUES('external-wal','WAL','type','{}')"
    )
    writer.commit()
    inventory["copy_verification"]["source_preimage_sha256"] = wing_migration._digest(
        wing_migration._copy_preimage(inventory)
    )
    rewrite_inventory(inventory_path, inventory)
    parent_path = Path(inventory["evidence_root"]) / "parent-receipt.json"
    parent = wing_migration.inventory(str(inventory_path), str(parent_path))
    wing_migration.snapshot(str(parent_path))
    parent = wing_migration._load_receipt(parent_path)

    _, trial = wing_migration._create_full_copy_trial(parent, "wal-alias")
    writer.close()

    assert any(
        entity["id"] == "external-wal" for entity in trial["pre"]["kg"][1]["state"]["entities"]
    )
    assert trial["pre"]["kg"][2]["alias_of"] == 1


def test_runtime_package_drift_refuses_before_marker_activation(tmp_path, monkeypatch):
    inventory_path, receipt_path, inventory = fixture(tmp_path)
    inventory_receipt(inventory_path, receipt_path)
    wing_migration.snapshot(str(receipt_path))
    sealed = wing_migration._load_receipt(receipt_path)
    package_file = Path(sealed["runtime"]["module_origin"])
    package_file.write_bytes(package_file.read_bytes() + b"\n# drift\n")
    monkeypatch.setattr(wing_migration, "_runtime_probe", REAL_RUNTIME_PROBE)
    before = wing_migration._capture(sealed["inventory"])

    with pytest.raises(wing_migration.MigrationError) as caught:
        wing_migration.apply(str(receipt_path))

    assert caught.value.code == "runtime_package_hash_drift"
    assert wing_migration._capture(sealed["inventory"]) == before
    refused = wing_migration._load_receipt(receipt_path)
    assert refused["phase"] == "snapshotted"
    assert refused["writes"] == 0
    assert Path(inventory["marker"]).read_text().startswith("wing: old-wing")


def test_runtime_interpreter_symlink_refuses_before_subprocess(tmp_path, monkeypatch):
    inventory_path, receipt_path, _ = fixture(tmp_path)
    inventory_receipt(inventory_path, receipt_path)
    sealed = wing_migration._load_receipt(receipt_path)
    interpreter = Path(sealed["runtime"]["interpreter"])
    interpreter.unlink()
    interpreter.symlink_to(sys.executable)

    def reject_subprocess(*_args, **_kwargs):
        raise AssertionError("runtime subprocess started before path validation")

    monkeypatch.setattr(wing_migration.subprocess, "run", reject_subprocess)
    with pytest.raises(wing_migration.MigrationError) as caught:
        wing_migration._validate_runtime(sealed)

    assert caught.value.code == "fixture_symlink"


@pytest.mark.parametrize(
    ("qualification_mode", "expected_timeout"),
    [
        ("synthetic", wing_migration.SYNTHETIC_RUNTIME_MINE_TIMEOUT_SECONDS),
        ("full-copy", wing_migration.FULL_COPY_RUNTIME_MINE_TIMEOUT_SECONDS),
        ("full-copy-trial", wing_migration.FULL_COPY_RUNTIME_MINE_TIMEOUT_SECONDS),
    ],
)
def test_runtime_probe_selects_bounded_mine_timeout(
    tmp_path, monkeypatch, qualification_mode, expected_timeout
):
    inventory_path, receipt_path, _ = fixture(tmp_path)
    receipt = inventory_receipt(inventory_path, receipt_path)
    receipt["qualification_mode"] = qualification_mode
    observed_timeouts = []
    real_run = wing_migration._run_runtime_subprocess

    def timeout_run(current, command, **kwargs):
        if "mine" in command:
            observed_timeouts.append(kwargs["timeout"])
            raise subprocess.TimeoutExpired("mine", kwargs["timeout"])
        return real_run(current, command, **kwargs)

    monkeypatch.setattr(wing_migration, "_validate_runtime", lambda _receipt: None)
    monkeypatch.setattr(wing_migration, "_run_runtime_subprocess", timeout_run)

    with pytest.raises(wing_migration.MigrationError) as caught:
        REAL_RUNTIME_PROBE(receipt)

    assert caught.value.code == "runtime_source_baseline_timeout"
    assert observed_timeouts == [expected_timeout]


def test_runtime_probe_records_source_process_exit_without_materializing_rows(
    tmp_path, monkeypatch
):
    inventory_path, receipt_path, _ = fixture(tmp_path)
    receipt = inventory_receipt(inventory_path, receipt_path)

    def failed_mine(_receipt, command, **_kwargs):
        return subprocess.CompletedProcess(command, -9, stdout="", stderr="")

    monkeypatch.setattr(wing_migration, "_validate_runtime", lambda _receipt: None)
    monkeypatch.setattr(wing_migration, "_run_runtime_subprocess", failed_mine)
    monkeypatch.setattr(
        wing_migration,
        "_read_lance_rows",
        lambda *_args, **_kwargs: pytest.fail("runtime probe materialized complete rows"),
    )

    with pytest.raises(wing_migration.MigrationError) as caught:
        REAL_RUNTIME_PROBE(receipt)

    assert caught.value.code == "runtime_source_baseline_failed"
    assert json.loads(caught.value.detail) == {
        "expected_wing_reported": False,
        "returncode": -9,
        "stderr_tail": "",
        "stdout_tail": "",
    }


def test_runtime_probe_maps_destination_timeout(tmp_path, monkeypatch):
    inventory_path, receipt_path, _ = fixture(tmp_path)
    receipt = inventory_receipt(inventory_path, receipt_path)
    receipt["qualification_mode"] = "full-copy-trial"
    observed_timeouts = []
    mine_calls = 0
    real_run = wing_migration._run_runtime_subprocess

    def timeout_destination(current, command, **kwargs):
        nonlocal mine_calls
        if "mine" in command:
            mine_calls += 1
            observed_timeouts.append(kwargs["timeout"])
            if mine_calls == 2:
                raise subprocess.TimeoutExpired("mine", kwargs["timeout"])
        return real_run(current, command, **kwargs)

    monkeypatch.setattr(wing_migration, "_run_runtime_subprocess", timeout_destination)

    with pytest.raises(wing_migration.MigrationError) as caught:
        REAL_RUNTIME_PROBE(receipt)

    assert caught.value.code == "runtime_destination_probe_timeout"
    assert observed_timeouts == [
        wing_migration.FULL_COPY_RUNTIME_MINE_TIMEOUT_SECONDS,
        wing_migration.FULL_COPY_RUNTIME_MINE_TIMEOUT_SECONDS,
    ]


def test_real_runtime_forces_offline_and_preserves_external_cache(tmp_path, monkeypatch):
    source_home = wing_migration._model_cache_home()
    source_root = wing_migration._prepared_model_cache_root(source_home)
    external_home = tmp_path / "external-hf-home"
    external_root = external_home / wing_migration.MODEL_CACHE_RELATIVE
    shutil.copytree(source_root, external_root, symlinks=True)
    before = model_cache_state(external_root)
    observed_environments = []
    real_run = subprocess.run

    def observing_run(command, *args, **kwargs):
        environment = kwargs.get("env")
        if environment is not None:
            observed_environments.append(environment)
        return real_run(command, *args, **kwargs)

    monkeypatch.setenv("HF_HOME", str(external_home))
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    monkeypatch.delenv("TRANSFORMERS_OFFLINE", raising=False)
    monkeypatch.setattr(wing_migration, "_runtime_probe", REAL_RUNTIME_PROBE)
    monkeypatch.setattr(wing_migration.subprocess, "run", observing_run)
    monkeypatch.setattr(
        wing_migration,
        "_read_lance_rows",
        lambda *_args, **_kwargs: pytest.fail("runtime probe materialized complete rows"),
    )

    report = wing_migration.qualify("synthetic")

    assert report["status"] == "qualified"
    assert observed_environments
    assert all(environment["HF_HUB_OFFLINE"] == "1" for environment in observed_environments)
    assert all(environment["TRANSFORMERS_OFFLINE"] == "1" for environment in observed_environments)
    assert all(
        Path(environment["HF_HOME"]) != external_home for environment in observed_environments
    )
    assert model_cache_state(external_root) == before


def test_materialized_model_cache_is_independent_from_external_source(tmp_path):
    source_home = wing_migration._model_cache_home()
    source_root = wing_migration._prepared_model_cache_root(source_home)
    external_home = tmp_path / "external-hf-home"
    external_root = external_home / wing_migration.MODEL_CACHE_RELATIVE
    shutil.copytree(source_root, external_root, symlinks=True)
    before = model_cache_state(external_root)

    target_home = wing_migration._materialize_model_cache(
        external_home, tmp_path / "fixture-hf-home"
    )
    target_root = wing_migration._prepared_model_cache_root(target_home)
    tokenizer = next(target_root.rglob("tokenizer_config.json"))
    tokenizer.write_text('{"fixture": "changed"}\n', encoding="utf-8")

    assert model_cache_state(external_root) == before
    assert tokenizer.read_text(encoding="utf-8") == '{"fixture": "changed"}\n'


def test_missing_model_cache_refuses_before_receipt_or_migration_writes(tmp_path, monkeypatch):
    inventory_path, receipt_path, inventory = fixture(tmp_path)
    before = wing_migration._capture(inventory)
    missing_home = tmp_path / "missing-hf-home"
    monkeypatch.setenv("HF_HOME", str(missing_home))

    with pytest.raises(wing_migration.MigrationError) as caught:
        inventory_receipt(inventory_path, receipt_path)

    assert caught.value.code == "prepared_model_cache_required"
    assert not receipt_path.exists()
    assert not Path(inventory["runtime_root"]).exists()
    assert wing_migration._capture(inventory) == before


def test_configuration_drift_blocks_apply_and_recovery(tmp_path):
    inventory_path, receipt_path, inventory = fixture(tmp_path)
    receipt = inventory_receipt(inventory_path, receipt_path)
    wing_migration.snapshot(str(receipt_path))
    configuration = Path(inventory["configuration"])
    original = configuration.read_bytes()
    configuration.write_text('{"changed": true}\n', encoding="utf-8")
    with pytest.raises(wing_migration.MigrationError) as caught:
        wing_migration.apply(str(receipt_path))
    assert caught.value.code == "configuration_drift"

    configuration.write_bytes(original)
    with pytest.raises(wing_migration.InjectedStop):
        wing_migration.apply(str(receipt_path), stop_after="lance:1")
    configuration.write_text('{"changed": true}\n', encoding="utf-8")
    with pytest.raises(wing_migration.MigrationError) as caught:
        wing_migration.recover(str(receipt_path))
    assert caught.value.code == "configuration_drift"
    configuration.write_bytes(original)
    assert wing_migration.recover(str(receipt_path))["state"] == "original"
    assert wing_migration._capture(receipt["inventory"]) == receipt["pre"]


def test_duplicate_json_key_is_rejected(tmp_path):
    inventory_path, receipt_path, inventory = fixture(tmp_path)
    Path(inventory["tiny_hashes"]).write_text(
        '{"old-wing":{"x":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",'
        '"x":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}}'
    )
    with pytest.raises(wing_migration.MigrationError) as caught:
        inventory_receipt(inventory_path, receipt_path)
    assert caught.value.code == "duplicate_json_key"


def test_missing_derived_kg_candidate_is_rejected(tmp_path):
    inventory_path, receipt_path, inventory = fixture(tmp_path)
    inventory["kg_candidates"] = inventory["kg_candidates"][:1]
    rewrite_inventory(inventory_path, inventory)

    with pytest.raises(wing_migration.MigrationError) as caught:
        inventory_receipt(inventory_path, receipt_path)

    assert caught.value.code == "kg_inventory_incomplete"
    assert not receipt_path.exists()


def test_snapshot_corruption_refuses_before_apply_mutation(tmp_path):
    inventory_path, receipt_path, inventory = fixture(tmp_path)
    receipt = inventory_receipt(inventory_path, receipt_path)
    wing_migration.snapshot(str(receipt_path))
    before = wing_migration._capture(receipt["inventory"])
    sealed = wing_migration._load_receipt(receipt_path)
    backup = Path(sealed["snapshot"]["kg"][0]["backup"])
    backup.write_bytes(backup.read_bytes() + b"corrupt")

    with pytest.raises(wing_migration.MigrationError) as caught:
        wing_migration.apply(str(receipt_path), inventory_path=str(inventory_path))

    assert caught.value.code == "snapshot_corrupt"
    assert wing_migration._capture(receipt["inventory"]) == before


def test_snapshot_overlap_is_rejected(tmp_path):
    inventory_path, receipt_path, inventory = fixture(tmp_path)
    inventory["snapshot_root"] = str(Path(inventory["palace"]) / "snapshot")
    rewrite_inventory(inventory_path, inventory)

    with pytest.raises(wing_migration.MigrationError) as caught:
        inventory_receipt(inventory_path, receipt_path)

    assert caught.value.code == "target_overlap"


@pytest.mark.parametrize(
    "mutation",
    ["evidence_palace", "lock_snapshot", "runtime_project", "config_marker", "kg_config"],
)
def test_all_ownership_roots_must_be_disjoint(tmp_path, mutation):
    inventory_path, receipt_path, inventory = fixture(tmp_path)
    if mutation == "evidence_palace":
        inventory["evidence_root"] = inventory["palace"]
    elif mutation == "lock_snapshot":
        inventory["lock"] = str(Path(inventory["snapshot_root"]) / "operation.lock")
    elif mutation == "runtime_project":
        inventory["runtime_root"] = str(Path(inventory["project_root"]) / "runtime")
    elif mutation == "config_marker":
        inventory["configuration"] = inventory["marker"]
    else:
        inventory["configuration"] = inventory["kg_candidates"][1]
    rewrite_inventory(inventory_path, inventory)

    with pytest.raises(wing_migration.MigrationError) as caught:
        inventory_receipt(inventory_path, receipt_path)

    assert caught.value.code == "target_overlap"
    assert not receipt_path.exists()


def test_receipt_inside_palace_is_rejected_before_creation(tmp_path):
    inventory_path, _, inventory = fixture(tmp_path)
    receipt_path = Path(inventory["palace"]) / "receipt.json"

    with pytest.raises(wing_migration.MigrationError) as caught:
        inventory_receipt(inventory_path, receipt_path)

    assert caught.value.code in {"receipt_binding_invalid", "target_overlap"}
    assert not receipt_path.exists()


def test_containment_wrong_receipt_disk_and_writer_guards(tmp_path):
    inventory_path, receipt_path, inventory = fixture(tmp_path)
    original = dict(inventory)
    inventory["marker"] = str(tmp_path / "outside.yaml")
    rewrite_inventory(inventory_path, inventory)
    with pytest.raises(wing_migration.MigrationError, match="outside_fixture"):
        inventory_receipt(inventory_path, receipt_path)

    rewrite_inventory(inventory_path, original)
    from mempalace_code.operation_lock import OperationLock

    with OperationLock(original["lock"]).acquire_shared("fixture-writer"):
        with pytest.raises(wing_migration.MigrationError, match="writer_conflict"):
            inventory_receipt(inventory_path, receipt_path)

    original["required_free_bytes"] = 2**63
    rewrite_inventory(inventory_path, original)
    with pytest.raises(wing_migration.MigrationError, match="insufficient_disk"):
        inventory_receipt(inventory_path, receipt_path)


def test_recovery_capacity_excludes_retained_evidence_runtime_and_snapshots(tmp_path, monkeypatch):
    _, _, inventory = fixture(tmp_path)
    root = Path(inventory["fixture_root"])
    baseline = wing_migration._recovery_working_set_bytes(inventory)
    active = Path(inventory["project_root"]) / "active.bin"
    active.write_bytes(b"a" * 10)
    snapshot_file = Path(inventory["snapshot_root"]) / "current.bin"
    snapshot_file.parent.mkdir()
    snapshot_file.write_bytes(b"s" * 20)
    evidence_file = Path(inventory["evidence_root"]) / "retained.bin"
    evidence_file.write_bytes(b"e" * 100)
    runtime_file = Path(inventory["runtime_root"]) / "runtime.bin"
    runtime_file.parent.mkdir()
    runtime_file.write_bytes(b"r" * 100)
    retained_root = root / "retained-snapshot"
    retained_root.mkdir()
    (retained_root / "historical.bin").write_bytes(b"h" * 100)
    inventory["retained_snapshot_roots"] = {str(retained_root): "historical-receipt.json"}

    working_set = wing_migration._recovery_working_set_bytes(inventory)

    assert working_set == baseline + 30
    monkeypatch.setattr(
        wing_migration.shutil,
        "disk_usage",
        lambda _path: type("Usage", (), {"free": working_set * 2 + 1024 * 1024})(),
    )
    wing_migration._assert_recovery_capacity(inventory)


def test_stale_and_wrong_target_receipts_are_rejected(tmp_path):
    inventory_path, receipt_path, _ = fixture(tmp_path)
    inventory_receipt(inventory_path, receipt_path)
    copied = receipt_path.with_name("copied-receipt.json")
    copied.write_bytes(receipt_path.read_bytes())
    os.chmod(copied, 0o600)
    with pytest.raises(wing_migration.MigrationError, match="wrong_target_receipt"):
        wing_migration.classify(str(copied))

    value = json.loads(receipt_path.read_text())
    value["phase"] = "forged"
    receipt_path.write_text(json.dumps(value))
    with pytest.raises(wing_migration.MigrationError, match="receipt_seal_invalid"):
        wing_migration.classify(str(receipt_path))


def test_absent_and_aliased_kg_candidates_have_explicit_proof(tmp_path):
    inventory_path, receipt_path, inventory = fixture(tmp_path)
    absent = Path(inventory["fixture_root"]) / "absent.sqlite3"
    inventory["kg_candidates"].append(str(absent))
    inventory["kg_candidates"].append(inventory["kg_candidates"][0])
    rewrite_inventory(inventory_path, inventory)
    receipt = inventory_receipt(inventory_path, receipt_path)

    assert receipt["pre"]["kg"][2]["state"] == {
        "exists": False,
        "entities": [],
        "triples": [],
    }
    assert receipt["pre"]["kg"][3]["alias_of"] == 0
    assert receipt["expected"]["kg_eligible"][str(absent)] == []


def test_cli_qualification_and_authority_refusals(tmp_path):
    qualified = subprocess.run(
        [sys.executable, str(SCRIPT), "qualify", "--mode", "synthetic"],
        text=True,
        capture_output=True,
        check=False,
        timeout=90,
    )
    assert qualified.returncode == 0, qualified.stderr + qualified.stdout
    report = json.loads(qualified.stdout)
    assert report["status"] == "qualified"
    assert report["synthetic_only"] is True
    assert all(report["predicates"].values())
    assert report["runtime"]["predicates"]["zero_drawer_writes"] is True
    assert report["runtime"]["predicates"]["source_baseline_real_mine"] is True
    assert report["runtime"]["predicates"]["resolver_destination"] is True
    assert report["runtime"]["identity"]["isolated_non_editable"] is True
    assert report["runtime"]["identity"]["package_hashes"]
    assert "--inventory" in report["recovery_command"]

    missing_inventory_environment = dict(os.environ)
    missing_inventory_environment.pop("WING_MIGRATION_INVENTORY_PATH", None)
    full_copy = subprocess.run(
        [sys.executable, str(SCRIPT), "qualify", "--mode", "full-copy"],
        env=missing_inventory_environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert full_copy.returncode == 2
    assert json.loads(full_copy.stdout)["failed_predicate"] == "full_copy_inventory_required"

    live = subprocess.run(
        [sys.executable, str(SCRIPT), "qualify", "--mode", "live"],
        text=True,
        capture_output=True,
        check=False,
    )
    assert live.returncode == 2
    assert json.loads(live.stdout)["failed_predicate"] == "live_authority_required"


def test_cli_full_copy_malformed_inventory_is_sanitized_and_artifact_free(tmp_path):
    inventory_path = tmp_path / "private-inventory.json"
    sentinel = "private-path-sentinel"
    inventory_path.write_text(f'{{"{sentinel}":')
    os.chmod(inventory_path, 0o600)
    environment = dict(os.environ)
    environment["WING_MIGRATION_INVENTORY_PATH"] = str(inventory_path)

    refused = subprocess.run(
        [sys.executable, str(SCRIPT), "qualify", "--mode", "full-copy"],
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    assert refused.returncode == 2
    output = json.loads(refused.stdout)
    assert output["failed_predicate"] == "invalid_json"
    assert output["allowed_next_action"] == "inspect_private_evidence"
    assert sentinel not in refused.stdout
    assert refused.stderr == ""
    assert sorted(tmp_path.iterdir()) == [inventory_path]


@pytest.mark.parametrize(
    "receipt_name",
    ["missing-receipt-sentinel.json", "malformed-receipt.json", "sealed-incomplete.json"],
)
def test_cli_classify_receipt_failures_never_echo_private_details(tmp_path, receipt_name):
    sentinel = "private-classify-path-and-content-sentinel"
    receipt_path = tmp_path / receipt_name
    if "malformed" in receipt_name:
        receipt_path.write_text(f'{{"private": "{sentinel}"', encoding="utf-8")
        os.chmod(receipt_path, 0o600)
    elif "sealed" in receipt_name:
        receipt = {
            "version": wing_migration.RECEIPT_VERSION,
            "receipt_path": str(receipt_path),
            "qualification_mode": "full-copy",
            "private": sentinel,
        }
        receipt["seal"] = wing_migration._digest(receipt)
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        os.chmod(receipt_path, 0o600)

    refused = subprocess.run(
        [sys.executable, str(SCRIPT), "classify", "--receipt", str(receipt_path)],
        text=True,
        capture_output=True,
        check=False,
    )

    assert refused.returncode == 2
    assert sentinel not in refused.stdout
    assert str(receipt_path) not in refused.stdout
    assert str(receipt_path) not in refused.stderr
    output = json.loads(refused.stdout)
    assert "recovery_command" in output
    if "sealed" in receipt_name:
        assert output["failed_predicate"] == "operation_failed"
        assert output["allowed_next_action"] == "inspect_private_evidence"


def test_main_full_copy_success_outputs_are_path_and_content_sanitized(monkeypatch, capsys):
    sentinel = "/private/full-copy-path-sentinel"
    monkeypatch.setattr(wing_migration, "_arguments_target_full_copy", lambda _args: True)
    monkeypatch.setattr(
        wing_migration,
        "inventory",
        lambda *_args, **_kwargs: {"receipt_path": sentinel, "private": sentinel},
    )
    monkeypatch.setattr(
        wing_migration,
        "snapshot",
        lambda *_args, **_kwargs: {"snapshot": {"root": sentinel}, "private": sentinel},
    )
    monkeypatch.setattr(
        wing_migration,
        "apply",
        lambda *_args, **_kwargs: {"state": "merged", "writes": 99, "private": sentinel},
    )
    monkeypatch.setattr(wing_migration, "classify", lambda *_args, **_kwargs: "merged")
    monkeypatch.setattr(
        wing_migration,
        "recover",
        lambda *_args, **_kwargs: {"state": "original", "private": sentinel},
    )
    monkeypatch.setattr(
        wing_migration,
        "qualify",
        lambda *_args, **_kwargs: {"status": "qualified", "private": sentinel},
    )

    commands = [
        ["inventory", "--inventory", sentinel, "--receipt", sentinel],
        ["snapshot", "--receipt", sentinel],
        ["apply", "--inventory", sentinel, "--receipt", sentinel],
        ["classify", "--receipt", sentinel],
        ["recover", "--receipt", sentinel],
        ["qualify", "--mode", "full-copy"],
    ]
    for command in commands:
        assert wing_migration.main(command) == 0
        output = capsys.readouterr()
        assert sentinel not in output.out
        assert output.err == ""
        public = json.loads(output.out)
        assert public["authority"] == "owner-authorized isolated full copy only"
        assert public["allowed_next_action"]


def test_runtime_probe_measurement_mutation_refuses_before_qualification_success(
    tmp_path, monkeypatch
):
    inventory_path, receipt_path, _ = fixture(tmp_path)
    inventory_receipt(inventory_path, receipt_path)
    wing_migration.snapshot(str(receipt_path))

    def mutate_real_probe(receipt):
        proof = REAL_RUNTIME_PROBE(receipt)
        proof["measurements"]["destination_filed_drawers"] = 1
        return proof

    monkeypatch.setattr(wing_migration, "_runtime_probe", mutate_real_probe)
    with pytest.raises(wing_migration.MigrationError) as caught:
        wing_migration.apply(str(receipt_path))
    assert caught.value.code == "runtime_measurements_inconsistent"


def test_runtime_probe_uses_bounded_project_instead_of_copying_source(tmp_path, monkeypatch):
    inventory_path, receipt_path, inventory = fixture(tmp_path)
    inventory_receipt(inventory_path, receipt_path)
    wing_migration.snapshot(str(receipt_path))
    (Path(inventory["project_root"]) / "large-unrelated.bin").write_bytes(b"x" * 1024)

    def refuse_source_copy(*_args, **_kwargs):
        raise AssertionError("runtime proof must not copy the source project")

    monkeypatch.setattr(wing_migration.shutil, "copytree", refuse_source_copy)

    proof = REAL_RUNTIME_PROBE(wing_migration._load_receipt(receipt_path))

    assert proof["predicates"]["source_baseline_real_mine"] is True


def test_apply_clears_live_maintenance_before_releasing_fence(tmp_path, monkeypatch):
    inventory_path, receipt_path, _ = fixture(tmp_path)
    inventory_receipt(inventory_path, receipt_path)
    wing_migration.snapshot(str(receipt_path))
    real_fence = wing_migration._fence
    fence_active = False
    cleared = False

    @contextmanager
    def observed_fence(*args, **kwargs):
        nonlocal fence_active
        with real_fence(*args, **kwargs):
            fence_active = True
            try:
                yield
            finally:
                fence_active = False

    def observed_clear(_receipt):
        nonlocal cleared
        assert fence_active
        cleared = True

    monkeypatch.setattr(wing_migration, "_fence", observed_fence)
    monkeypatch.setattr(wing_migration, "_clear_live_maintenance", observed_clear)

    wing_migration.apply(str(receipt_path))

    assert cleared


def test_runner_is_installed_with_compatible_repository_wrapper():
    root = SCRIPT.parents[1]
    cli = (root / "mempalace_code" / "cli.py").read_text()
    mcp = (root / "mempalace_code" / "mcp_server.py").read_text()
    wrapper = (root / "scripts" / "wing_migration.py").read_text()

    assert '"wing-migration": cmd_wing_migration' in cli
    assert "from mempalace_code.wing_migration import main" in wrapper
    assert "wing_migration" not in mcp
    assert SCRIPT.parent.name == "mempalace_code"


def test_live_identity_allows_bounded_file_replacement_but_not_root_replacement(tmp_path):
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    palace = tmp_path / "palace"
    project = tmp_path / "project"
    palace.mkdir()
    project.mkdir()
    configuration = tmp_path / "config.json"
    lock = tmp_path / "operation.lock"
    marker = project / "mempalace.yaml"
    tiny = palace / "tiny.json"
    kg = tmp_path / "kg.sqlite3"
    recovery_runner = tmp_path / "runner.py"
    authority_path = tmp_path / "authority.json"
    for path in (configuration, lock, marker, tiny, kg):
        path.write_text("{}", encoding="utf-8")
    wing_migration._atomic_json(authority_path, {"approved": True})
    shutil.copy2(SCRIPT, recovery_runner)
    inventory = {
        "qualification_mode": "live",
        "fixture_root": str(evidence),
        "fixture_root_identity": wing_migration._path_identity(evidence),
        "approved_host": socket.gethostname(),
        "palace": str(palace),
        "authority_path": str(authority_path),
        "live_authority_seal": wing_migration._digest({"approved": True}),
        "live_target_identities": {
            str(path): wing_migration._path_identity(path)
            for path in (palace, project, configuration, lock)
        },
        "live_mutable_paths": [str(path) for path in (marker, tiny, kg)],
        "recovery_runner": str(recovery_runner),
        "recovery_runner_sha256": wing_migration._file_digest(recovery_runner),
    }

    marker.replace(marker.with_suffix(".old"))
    marker.write_text("wing: destination\n", encoding="utf-8")
    wing_migration._check_fixture_identity(inventory)

    outside_lance = tmp_path / "outside-lance"
    outside_lance.mkdir()
    (palace / "lance").symlink_to(outside_lance, target_is_directory=True)
    with pytest.raises(wing_migration.MigrationError) as escaped:
        wing_migration._check_fixture_identity(inventory)
    assert escaped.value.code == "fixture_symlink"
    (palace / "lance").unlink()

    palace.rename(tmp_path / "old-palace")
    palace.mkdir()
    with pytest.raises(wing_migration.MigrationError) as caught:
        wing_migration._check_fixture_identity(inventory)
    assert caught.value.code == "live_target_drift"


def test_runtime_seal_accepts_only_the_exact_interpreter_symlink(tmp_path):
    inventory_path, receipt_path, _ = fixture(tmp_path)
    receipt = inventory_receipt(inventory_path, receipt_path)
    target = Path(receipt["runtime"]["interpreter"])
    launcher = tmp_path / "installed-python"
    launcher.symlink_to(target)
    receipt["runtime"]["interpreter"] = str(launcher)
    receipt["runtime"]["interpreter_link"] = {
        "value": os.readlink(launcher),
        "target": str(target.resolve(strict=True)),
        "target_sha256": wing_migration._file_digest(target.resolve(strict=True)),
    }
    wing_migration._assert_runtime_files_unchanged(receipt)

    launcher.unlink()
    launcher.symlink_to("/bin/false")
    with pytest.raises(wing_migration.MigrationError) as caught:
        wing_migration._assert_runtime_files_unchanged(receipt)
    assert caught.value.code == "runtime_package_hash_drift"


def test_model_cache_seal_allows_atomic_same_byte_normalization(tmp_path):
    cache_home = tmp_path / "hf-home"
    cache_root = cache_home / wing_migration.MODEL_CACHE_RELATIVE
    cache_root.mkdir(parents=True)
    artifact = cache_root / "tokenizer_config.json"
    artifact.write_text('{"max_length": 512}\n', encoding="utf-8")
    sealed = wing_migration._seal_model_cache_files(cache_home)

    replacement = artifact.with_suffix(".tmp")
    replacement.write_bytes(artifact.read_bytes())
    replacement.replace(artifact)

    assert wing_migration._seal_model_cache_files(cache_home) == sealed
    artifact.write_text('{"max_length": 256}\n', encoding="utf-8")
    assert wing_migration._seal_model_cache_files(cache_home) != sealed


def test_live_runtime_recovery_owns_only_destination_lance_and_tiny_delta(tmp_path):
    inventory_path, receipt_path, _ = fixture(tmp_path)
    receipt = inventory_receipt(inventory_path, receipt_path)
    receipt["qualification_mode"] = "live"
    receipt["phase"] = "runtime_activating"
    observed = copy.deepcopy(wing_migration._expanded_expected_state(receipt))
    destination = receipt["inventory"]["destination_wing"]
    destination_index = next(
        index for index, row in enumerate(observed["lance_rows"]) if row["wing"] == destination
    )
    observed["lance_rows"].pop(destination_index)
    observed["kg"][0]["state"]["entities"].clear()
    destination_tiny = wing_migration._decode_json_state(
        observed["tiny_hashes"], "destination runtime tiny hashes"
    )
    destination_tiny[destination] = {"/project/new.py": "runtime-owned"}
    observed["tiny_hashes"] = wing_migration._encode_file_state(destination_tiny)

    assert wing_migration._live_runtime_recovery_owned(receipt, observed) is True

    destination_owned = copy.deepcopy(observed)
    unrelated = next(row for row in observed["lance_rows"] if row["wing"] != destination)
    unrelated["source_hash"] = "runtime escaped its destination wing"
    assert wing_migration._live_runtime_recovery_owned(receipt, observed) is False

    unrelated_tiny = wing_migration._decode_json_state(
        destination_owned["tiny_hashes"], "unrelated runtime tiny hashes"
    )
    unrelated_tiny["unrelated-wing"] = {"/outside/project.py": "escaped"}
    destination_owned["tiny_hashes"] = wing_migration._encode_file_state(unrelated_tiny)
    assert wing_migration._live_runtime_recovery_owned(receipt, destination_owned) is False


def test_live_runtime_noop_uses_live_timeout(monkeypatch, tmp_path):
    receipt = {
        "qualification_mode": "live",
        "inventory": {
            "palace": str(tmp_path / "palace"),
            "project_root": str(tmp_path / "project"),
            "fixture_root": str(tmp_path),
            "destination_wing": "new-wing",
        },
        "runtime": {"interpreter": sys.executable},
    }
    observed_timeout = None

    def completed(_receipt, _command, **kwargs):
        nonlocal observed_timeout
        observed_timeout = kwargs["timeout"]
        return subprocess.CompletedProcess(
            args=[], returncode=0, stdout="Wing:    new-wing\nDrawers filed: 0\n", stderr=""
        )

    monkeypatch.setattr(wing_migration, "_validate_runtime", lambda _receipt: None)
    monkeypatch.setattr(wing_migration, "_run_runtime_subprocess", completed)

    wing_migration._runtime_live_noop(receipt)

    assert observed_timeout == wing_migration.FULL_COPY_RUNTIME_MINE_TIMEOUT_SECONDS


def test_live_process_inventory_matches_argv_identity_only(monkeypatch):
    class Observed:
        returncode = 0
        stdout = "\n".join(
            (
                "101 501 /bin/zsh -c echo mempalace-code-mcp",
                "102 501 /tool/bin/python /Users/test/.local/bin/mempalace-code-mcp --tools=search",
                "103 501 editor note:-m mempalace_code.mcp_server",
                "104 501 /tool/bin/python -m mempalace_code.mcp_server",
                "105 501 cat /tmp/mempalace-code-mcp",
                "106 501 python worker.py -m mempalace_code.mcp_server",
            )
        )

    monkeypatch.setattr(wing_migration.os, "getuid", lambda: 501)
    monkeypatch.setattr(wing_migration.subprocess, "run", lambda *_args, **_kwargs: Observed())
    assert set(wing_migration._live_processes()) == {102, 104}


def test_live_unsnapshotted_receipt_recovers_zero_write_state(tmp_path, monkeypatch):
    inventory_path, receipt_path, _ = fixture(tmp_path)
    receipt = inventory_receipt(inventory_path, receipt_path)
    inventory = receipt["inventory"]
    authority_path = tmp_path / "authority.json"
    wing_migration._atomic_json(authority_path, {"approved": True})
    recovery_runner = tmp_path / "runner.py"
    shutil.copy2(SCRIPT, recovery_runner)
    inventory.update(
        {
            "qualification_mode": "live",
            "approved_host": socket.gethostname(),
            "authority_path": str(authority_path),
            "live_authority_seal": wing_migration._digest({"approved": True}),
            "live_target_identities": {
                inventory["palace"]: wing_migration._path_identity(Path(inventory["palace"])),
                inventory["project_root"]: wing_migration._path_identity(
                    Path(inventory["project_root"])
                ),
                inventory["configuration"]: wing_migration._path_identity(
                    Path(inventory["configuration"])
                ),
                inventory["lock"]: wing_migration._path_identity(Path(inventory["lock"])),
            },
            "live_mutable_paths": [
                inventory["marker"],
                inventory["tiny_hashes"],
                *inventory["kg_candidates"],
            ],
            "maintenance_marker": str(tmp_path / "live-wing-migration.json"),
            "maintenance_receipt_path": str(receipt_path),
            "recovery_runner": str(recovery_runner),
            "recovery_runner_sha256": wing_migration._file_digest(recovery_runner),
        }
    )
    receipt["qualification_mode"] = "live"
    wing_migration._save_receipt(receipt)
    wing_migration._atomic_json(
        Path(inventory["maintenance_marker"]),
        {
            "approved_host": socket.gethostname(),
            "receipt_path": str(receipt_path),
            "phase": "receipt",
        },
    )
    monkeypatch.setattr(wing_migration, "_observe_live_clients", lambda _inventory: None)

    assert wing_migration.recover(str(receipt_path)) == {
        "state": "original",
        "restored": False,
    }
    assert not Path(inventory["maintenance_marker"]).exists()
    with pytest.raises(wing_migration.MigrationError) as replayed:
        wing_migration.recover(str(receipt_path))
    assert replayed.value.code == "live_maintenance_required"


def test_live_admission_recovery_clears_marker_without_receipt(tmp_path, monkeypatch):
    state = tmp_path / ".mempalace"
    state.mkdir()
    lock = state / "operation.lock"
    lock.write_bytes(b"")
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / "home").mkdir()
    authority_path = state / "authority.json"
    authority = {
        "approved_host": socket.gethostname(),
        "lock": str(lock),
        "evidence_root": str(evidence),
    }
    maintenance = state / wing_migration.LIVE_MAINTENANCE_NAME
    receipt_path = evidence / "receipt.json"
    wing_migration._atomic_json(
        maintenance,
        {
            "approved_host": socket.gethostname(),
            "receipt_path": str(receipt_path),
            "phase": "admission",
        },
    )
    monkeypatch.setattr(
        wing_migration,
        "_validate_live_authority",
        lambda path, allow_existing_evidence=False: (authority, authority_path),
    )
    monkeypatch.setattr(wing_migration, "_stop_live_mcp_clients", lambda: [])

    assert wing_migration.live_recover(str(authority_path)) == {
        "state": "original",
        "restored": False,
        "admission_only": True,
    }
    assert not maintenance.exists()
    assert not evidence.exists()


def test_live_runtime_normalization_preserves_already_restored_components(tmp_path):
    inventory_path, receipt_path, _ = fixture(tmp_path)
    inventory_receipt(inventory_path, receipt_path)
    wing_migration.snapshot(str(receipt_path))
    wing_migration.apply(str(receipt_path))
    receipt = wing_migration._load_receipt(receipt_path)
    receipt["qualification_mode"] = "live"
    receipt["phase"] = "marker"
    expected = wing_migration._expanded_expected_state(receipt)
    observed = copy.deepcopy(expected)
    observed["lance_rows"] = copy.deepcopy(receipt["pre"]["lance_rows"])
    tiny = wing_migration._decode_json_state(observed["tiny_hashes"], "test")
    observed["tiny_hashes"] = {
        "exists": True,
        "bytes": base64.b64encode(json.dumps(tiny, sort_keys=True).encode()).decode(),
    }
    observed["kg"][0] = copy.deepcopy(receipt["pre"]["kg"][0])
    eligible_path = next(path for path, ids in receipt["expected"]["kg_eligible"].items() if ids)
    eligible_index = next(
        index
        for index, candidate in enumerate(observed["kg"])
        if candidate["path"] == eligible_path
    )
    eligible_id = receipt["expected"]["kg_eligible"][eligible_path][0]
    triple = next(
        row
        for row in observed["kg"][eligible_index]["state"]["triples"]
        if row["id"] == eligible_id
    )
    triple["valid_to"] = "2026-09-11T00:00:00+00:00"

    normalized = wing_migration._normalize_live_runtime_state(receipt, observed)
    assert normalized is not None
    assert normalized["kg"][0] == receipt["pre"]["kg"][0]
    assert wing_migration._classify_observed(receipt, normalized) == "partial"


def test_main_routes_explicit_live_authority(monkeypatch, capsys):
    monkeypatch.setattr(
        wing_migration,
        "live_run",
        lambda authority: {"state": "merged", "authority": authority},
    )
    assert wing_migration.main(["live-run", "--authority", "/private/authority.json"]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "authority": "/private/authority.json",
        "state": "merged",
    }


def test_runbook_records_full_copy_private_recovery_and_live_gates():
    runbook = (SCRIPT.parents[1] / "docs" / "operations" / "wing-migration.md").read_text()
    normalized = " ".join(runbook.split())

    assert "WING_MIGRATION_INVENTORY_PATH" in runbook
    assert "source_preimage_sha256" in runbook
    assert "non-hardlinked descendant copy" in runbook
    assert "Retain this evidence until verified recovery or owner disposition" in runbook
    assert "one exact recovery command" in normalized
    assert "Full-copy qualification alone grants no live authority" in runbook
    assert "live-run --authority" in runbook
