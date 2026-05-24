"""
test_layers.py — No-embedder regression tests for Layer1/Layer2/MemoryStack read paths.

Covers VER-1 (wake_up, recall, status, CLI smoke) and VER-4 (missing and empty palace
boundaries) from the CLI-LAYERS-GRAPH-READONLY-NO-EMBEDDER plan.
"""

import os
import subprocess
import sys

from mempalace_code.layers import MemoryStack
from mempalace_code.storage import LanceStore, open_store

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MODEL_LOADING_MARKERS = (
    "Loading embedding model",
    "Loading weights",
    "huggingface",
    "sentence-transformers",
)


def _assert_no_model_output(text: str) -> None:
    for marker in _MODEL_LOADING_MARKERS:
        assert marker.lower() not in text.lower(), (
            f"Model-loading marker {marker!r} detected in output: {text!r}"
        )


def _seed_palace(palace_path: str) -> None:
    """Seed a palace with a small set of drawers using the active test embedder."""
    store = open_store(palace_path, create=True)
    store.add(
        ids=["drawer_alpha_backend_001", "drawer_alpha_backend_002", "drawer_beta_planning_003"],
        documents=[
            "The authentication module uses JWT tokens for session management.",
            "Database migrations are handled by Alembic with PostgreSQL.",
            "Sprint planning: migrate auth to passkeys by Q3.",
        ],
        metadatas=[
            {
                "wing": "alpha",
                "room": "backend",
                "source_file": "auth.py",
                "chunk_index": 0,
                "added_by": "miner",
                "filed_at": "2026-01-01T00:00:00",
            },
            {
                "wing": "alpha",
                "room": "backend",
                "source_file": "db.py",
                "chunk_index": 0,
                "added_by": "miner",
                "filed_at": "2026-01-02T00:00:00",
            },
            {
                "wing": "beta",
                "room": "planning",
                "source_file": "sprint.md",
                "chunk_index": 0,
                "added_by": "miner",
                "filed_at": "2026-01-03T00:00:00",
            },
        ],
    )


def _guard_embedder(monkeypatch) -> None:
    """Patch LanceStore._get_embedder to raise — proves no embedder is initialized."""

    def _raise(_self):  # noqa: N805
        raise RuntimeError("embedder must not be called during read-only operation")

    monkeypatch.setattr(LanceStore, "_get_embedder", _raise)


# ---------------------------------------------------------------------------
# VER-1 / AC-1: populated palace wake-up, recall, status avoid embedder startup
# ---------------------------------------------------------------------------


class TestWakeUpRecallNoEmbedder:
    """VER-1/AC-1: wake_up and recall work on a populated palace without embedder startup."""

    def test_wake_up_recall_no_embedder(self, monkeypatch, palace_path):
        """Populated palace wake_up and recall succeed when embedder is guarded to raise."""
        _seed_palace(palace_path)
        _guard_embedder(monkeypatch)

        stack = MemoryStack(palace_path=palace_path)

        text = stack.wake_up()
        assert "L1 — ESSENTIAL STORY" in text
        assert any(
            kw in text
            for kw in ("JWT", "Alembic", "passkeys", "authentication", "migration", "sprint")
        ), f"Expected seeded content in wake_up output; got: {text!r}"

    def test_recall_wing_filter_no_embedder(self, monkeypatch, palace_path):
        """Recall with wing filter returns drawers without embedder startup."""
        _seed_palace(palace_path)
        _guard_embedder(monkeypatch)

        stack = MemoryStack(palace_path=palace_path)
        text = stack.recall(wing="alpha")

        assert "L2 — ON-DEMAND" in text
        assert "2 drawers" in text

    def test_recall_no_filter_no_embedder(self, monkeypatch, palace_path):
        """Recall with no filter returns all drawers without embedder startup."""
        _seed_palace(palace_path)
        _guard_embedder(monkeypatch)

        stack = MemoryStack(palace_path=palace_path)
        text = stack.recall()

        assert "L2 — ON-DEMAND" in text
        assert "3 drawers" in text


class TestLayerStatusNoEmbedder:
    """VER-1/AC-1: MemoryStack.status() returns correct drawer count without embedder startup."""

    def test_layer_status_no_embedder(self, monkeypatch, palace_path):
        """Status on a populated palace returns correct count without embedder startup."""
        _seed_palace(palace_path)
        _guard_embedder(monkeypatch)

        stack = MemoryStack(palace_path=palace_path)
        status = stack.status()

        assert status["total_drawers"] == 3
        assert status["palace_path"] == palace_path
        assert "L0_identity" in status
        assert "L1_essential" in status
        assert "L2_on_demand" in status
        assert "L3_deep_search" in status


# ---------------------------------------------------------------------------
# VER-1 / AC-1: real CLI subprocess smoke — no model-loading output
# ---------------------------------------------------------------------------


class TestWakeupCliSmokeNoModelOutput:
    """VER-1/AC-1: Real CLI subprocess wake-up emits no model-loading output."""

    def test_wakeup_cli_smoke_no_model_output(self, palace_path):
        """CLI wake-up on a seeded palace exits 0 and produces no model-loading markers.

        The subprocess inherits a fresh HOME (no model cache) and HF_HUB_OFFLINE=1,
        so any accidental embedder startup would fail and surface as a non-zero exit
        or missing 'L1 — ESSENTIAL STORY' in stdout.
        """
        _seed_palace(palace_path)  # seeds using deterministic test embedder

        env = os.environ.copy()
        env["HF_HUB_OFFLINE"] = "1"
        env["TRANSFORMERS_OFFLINE"] = "1"

        result = subprocess.run(
            [sys.executable, "-m", "mempalace_code.layers", "wake-up", f"--palace={palace_path}"],
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )

        assert result.returncode == 0, (
            f"CLI exited {result.returncode}.\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
        combined = result.stdout + result.stderr
        _assert_no_model_output(combined)
        assert "L1 — ESSENTIAL STORY" in result.stdout, (
            f"Expected seeded content in CLI stdout; got: {result.stdout!r}"
        )


# ---------------------------------------------------------------------------
# VER-4 / AC-3: missing palace — no directory created, embedder not called
# ---------------------------------------------------------------------------


class TestMissingPalaceNoEmbedder:
    """VER-4/AC-3: wake-up/recall/status on a missing palace do not create the directory."""

    def test_missing_palace_no_embedder_directory_not_created(self, monkeypatch, tmp_dir):
        """read-only wake_up on a missing palace must not create the palace directory."""
        missing = os.path.join(tmp_dir, "does_not_exist")
        _guard_embedder(monkeypatch)

        stack = MemoryStack(palace_path=missing)
        _ = stack.wake_up()

        assert not os.path.exists(missing), (
            "Read-only wake_up must not create the missing palace directory"
        )

    def test_missing_palace_no_embedder_wakeup_returns_message(self, monkeypatch, tmp_dir):
        """wake_up on a missing palace returns a user-visible L1 message, not an exception."""
        missing = os.path.join(tmp_dir, "does_not_exist")
        _guard_embedder(monkeypatch)

        stack = MemoryStack(palace_path=missing)
        text = stack.wake_up()

        assert isinstance(text, str)
        assert len(text) > 0
        assert "L1 —" in text

    def test_missing_palace_no_embedder_recall_no_crash(self, monkeypatch, tmp_dir):
        """recall() on a missing palace returns a string without crashing or creating dirs."""
        missing = os.path.join(tmp_dir, "does_not_exist")
        _guard_embedder(monkeypatch)

        stack = MemoryStack(palace_path=missing)
        text = stack.recall()

        assert isinstance(text, str)
        assert len(text) > 0
        assert not os.path.exists(missing)

    def test_missing_palace_no_embedder_status_zero_drawers(self, monkeypatch, tmp_dir):
        """status() on a missing palace returns 0 drawers without creating the directory."""
        missing = os.path.join(tmp_dir, "does_not_exist")
        _guard_embedder(monkeypatch)

        stack = MemoryStack(palace_path=missing)
        status = stack.status()

        assert status["total_drawers"] == 0
        assert not os.path.exists(missing)


# ---------------------------------------------------------------------------
# VER-4 / AC-4: empty (initialized) palace — zero counts, embedder not called
# ---------------------------------------------------------------------------


class TestEmptyPalaceNoEmbedder:
    """VER-4/AC-4: wake-up/recall/status on an initialized empty palace return zero counts."""

    def test_empty_palace_no_embedder_wakeup(self, monkeypatch, palace_path):
        """Initialized empty palace returns 'no memories' message without embedder startup."""
        open_store(palace_path, create=True)  # initialize empty LanceDB table
        _guard_embedder(monkeypatch)

        stack = MemoryStack(palace_path=palace_path)
        text = stack.wake_up()

        assert "L1 — No memories yet." in text

    def test_empty_palace_no_embedder_recall(self, monkeypatch, palace_path):
        """Recall on an empty palace returns a 'No drawers found' message without embedder startup."""
        open_store(palace_path, create=True)
        _guard_embedder(monkeypatch)

        stack = MemoryStack(palace_path=palace_path)
        text = stack.recall()

        assert isinstance(text, str)
        assert len(text) > 0
        assert "No drawers found" in text, (
            f"Expected 'No drawers found' in recall output for empty palace; got: {text!r}"
        )

    def test_empty_palace_no_embedder_status_zero_drawers(self, monkeypatch, palace_path):
        """status() on an empty palace returns 0 drawers without embedder startup."""
        open_store(palace_path, create=True)
        _guard_embedder(monkeypatch)

        stack = MemoryStack(palace_path=palace_path)
        status = stack.status()

        assert status["total_drawers"] == 0
