"""
test_watcher_resource_bounds.py — Watcher resource-boundary tests (AC-5).

Verifies that:
  - optimize_store threads kg_path through to store.safe_optimize.
  - LanceStore.safe_optimize passes kg_path to create_backup when backup_first=True.
  - _optimize_once accepts and threads the kg_path argument to optimize_store.
  - Pre-optimize backups carry the palace-local KG, not the global default.
"""

import os
import tarfile
from typing import cast
from unittest.mock import patch

from mempalace_code.knowledge_graph import palace_kg_path
from mempalace_code.storage import LanceStore, OptimizeResult, optimize_store

# ─── optimize_store kg_path threading ──────────────────────────────────────────


class TestOptimizeStoreKgPath:
    def test_optimize_store_passes_kg_path_to_safe_optimize(self, tmp_dir):
        """optimize_store must forward kg_path to LanceStore.safe_optimize."""
        palace_path = os.path.join(tmp_dir, "palace")
        local_kg_path = palace_kg_path(palace_path)

        from mempalace_code.storage import open_store

        store = cast("LanceStore", open_store(palace_path, create=True))

        captured = []

        def spy(pp, backup_first=False, kg_path=None):
            captured.append({"pp": pp, "backup_first": backup_first, "kg_path": kg_path})
            return True

        with patch.object(store, "safe_optimize", side_effect=spy):
            result = optimize_store(store, palace_path, backup_first=True, kg_path=local_kg_path)

        assert captured, "safe_optimize must have been called"
        assert captured[0]["kg_path"] == local_kg_path, (
            f"optimize_store must pass kg_path through, got: {captured[0]}"
        )
        assert result.ok

    def test_optimize_store_accepts_none_kg_path(self, tmp_dir):
        """optimize_store with kg_path=None must still call safe_optimize with kg_path=None."""
        palace_path = os.path.join(tmp_dir, "palace")

        from mempalace_code.storage import open_store

        store = cast("LanceStore", open_store(palace_path, create=True))

        captured = []

        def spy(pp, backup_first=False, kg_path=None):
            captured.append({"kg_path": kg_path})
            return True

        with patch.object(store, "safe_optimize", side_effect=spy):
            result = optimize_store(store, palace_path, backup_first=False, kg_path=None)

        assert captured
        assert captured[0]["kg_path"] is None
        assert result.ok

    def test_optimize_store_falls_back_for_unsupported_store(self, tmp_dir):
        """optimize_store calls store.optimize() for stores without safe_optimize protocol."""

        class MinimalStore:
            def optimize(self):
                self._optimized = True

        ms = MinimalStore()
        result = optimize_store(ms, os.path.join(tmp_dir, "pal"))
        assert hasattr(ms, "_optimized")
        assert ms._optimized
        assert result.ok
        assert not result.supported


# ─── LanceStore.safe_optimize kg_path threading ────────────────────────────────


class TestLanceSafeOptimizeKgPath:
    def test_safe_optimize_passes_kg_path_to_backup(self, tmp_dir):
        """LanceStore.safe_optimize must pass kg_path to create_backup when backup_first=True."""
        palace_path = os.path.join(tmp_dir, "palace")
        local_kg_path = palace_kg_path(palace_path)

        from mempalace_code.storage import open_store

        store = cast("LanceStore", open_store(palace_path, create=True))

        backup_calls = []

        def fake_create_backup(pp, out_path=None, kind="manual", kg_path=None, **kw):
            backup_calls.append({"palace_path": pp, "kg_path": kg_path, "kind": kind})
            archive_path = os.path.join(tmp_dir, "fake_backup.tar.gz")
            with tarfile.open(archive_path, "w:gz"):
                pass
            return {}, archive_path

        with patch("mempalace_code.backup.create_backup", side_effect=fake_create_backup):
            store.safe_optimize(palace_path, backup_first=True, kg_path=local_kg_path)

        assert backup_calls, "create_backup must have been called"
        assert backup_calls[0]["kg_path"] == local_kg_path, (
            f"create_backup must receive palace-local kg_path, got: {backup_calls[0]}"
        )

    def test_safe_optimize_without_backup_skips_create_backup(self, tmp_dir):
        """LanceStore.safe_optimize with backup_first=False must not call create_backup."""
        palace_path = os.path.join(tmp_dir, "palace")

        from mempalace_code.storage import open_store

        store = cast("LanceStore", open_store(palace_path, create=True))

        backup_calls = []

        def spy_create_backup(*args, **kwargs):
            backup_calls.append(1)

        with patch("mempalace_code.backup.create_backup", side_effect=spy_create_backup):
            store.safe_optimize(palace_path, backup_first=False, kg_path="/any/path.db")

        assert not backup_calls, "create_backup must not be called when backup_first=False"


# ─── palace_kg_path() contract ─────────────────────────────────────────────────


class TestPalaceKgPath:
    def test_returns_sqlite3_under_palace(self, tmp_dir):
        """palace_kg_path must return <palace>/knowledge_graph.sqlite3."""
        palace = os.path.join(tmp_dir, "my_palace")
        expected = os.path.join(palace, "knowledge_graph.sqlite3")
        assert palace_kg_path(palace) == expected

    def test_does_not_create_the_file(self, tmp_dir):
        """Calling palace_kg_path must not create the file or directory."""
        palace = os.path.join(tmp_dir, "palace_fresh")
        _ = palace_kg_path(palace)
        assert not os.path.exists(os.path.join(palace, "knowledge_graph.sqlite3"))


# ─── watcher _optimize_once kg_path threading ──────────────────────────────────


class TestOptimizeOnce:
    def test_optimize_once_threads_kg_path(self, tmp_dir):
        """_optimize_once must pass kg_path to optimize_store."""
        palace_path = os.path.join(tmp_dir, "palace")
        local_kg_path = palace_kg_path(palace_path)

        from mempalace_code.storage import open_store

        store = open_store(palace_path, create=True)

        optimize_calls = []

        def fake_optimize_store(s, pp, backup_first=False, kg_path=None):
            optimize_calls.append({"pp": pp, "backup_first": backup_first, "kg_path": kg_path})
            return OptimizeResult(ok=True, supported=True)

        def fake_open_store(pp, create=True):
            return store

        with patch("mempalace_code.watcher.optimize_store", side_effect=fake_optimize_store):
            from mempalace_code.watcher import _optimize_once

            _optimize_once(palace_path, fake_open_store, kg_path=local_kg_path)

        assert optimize_calls, "_optimize_once must call optimize_store"
        assert optimize_calls[0]["kg_path"] == local_kg_path, (
            f"optimize_store must receive palace-local kg_path, got: {optimize_calls[0]}"
        )

    def test_optimize_once_with_none_kg_path_is_accepted(self, tmp_dir):
        """_optimize_once with kg_path=None must not error."""
        palace_path = os.path.join(tmp_dir, "palace")

        from mempalace_code.storage import open_store

        store = open_store(palace_path, create=True)

        optimize_calls = []

        def fake_optimize_store(s, pp, backup_first=False, kg_path=None):
            optimize_calls.append(kg_path)
            return OptimizeResult(ok=True, supported=True)

        def fake_open_store(pp, create=True):
            return store

        with patch("mempalace_code.watcher.optimize_store", side_effect=fake_optimize_store):
            from mempalace_code.watcher import _optimize_once

            _optimize_once(palace_path, fake_open_store, kg_path=None)

        assert optimize_calls
        assert optimize_calls[0] is None

    def test_optimize_once_uses_supplied_lifecycle_store(self, tmp_dir):
        """Watcher optimization uses its active store so its table handle is refreshed."""
        palace_path = os.path.join(tmp_dir, "palace")
        lifecycle_store = object()
        optimize_calls = []
        opened = []

        def fake_optimize_store(store, *args, **kwargs):
            optimize_calls.append(store)
            return OptimizeResult(ok=True, supported=True)

        def fake_open_store(*args, **kwargs):
            opened.append((args, kwargs))
            raise AssertionError("must not open a second store when a lifecycle store is supplied")

        with patch("mempalace_code.watcher.optimize_store", side_effect=fake_optimize_store):
            from mempalace_code.watcher import _optimize_once

            result = _optimize_once(palace_path, fake_open_store, store=lifecycle_store)

        assert result == "completed"
        assert optimize_calls == [lifecycle_store]
        assert not opened
