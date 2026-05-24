"""
test_reader.py — Tests for the shared reader.py helpers.

Covers:
  - Single overlapping chunk returns only requested lines (AC-3)
  - Multi-chunk range spanning chunk boundary (AC-3)
  - source_file not in palace returns not_found (AC-4)
  - Range outside all stored chunks returns stale_pointer (AC-5)
  - Invalid range (start > end, start < 1) returns invalid_range (AC-5)
  - Legacy rows with line_start=0 are not treated as overlapping (AC-6)
"""

import pytest

from mempalace_code.reader import (
    _ends_with_components,
    _lines_from_chunk,
    _macos_var_aliases,
    _overlaps,
    _validate_range,
    read_slice,
)
from mempalace_code.storage import open_store

# ─── Unit tests for helpers ───────────────────────────────────────────────────


class TestValidateRange:
    def test_valid_range_returns_ints(self):
        result = _validate_range(5, 10)
        assert result == (5, 10)

    def test_start_equals_end_valid(self):
        result = _validate_range(7, 7)
        assert result == (7, 7)

    def test_start_greater_than_end_error(self):
        result = _validate_range(10, 5)
        assert isinstance(result, dict)
        assert result["error"] == "invalid_range"
        assert "start" in result["detail"]

    def test_zero_start_error(self):
        result = _validate_range(0, 5)
        assert isinstance(result, dict)
        assert result["error"] == "invalid_range"

    def test_negative_start_error(self):
        result = _validate_range(-1, 5)
        assert isinstance(result, dict)
        assert result["error"] == "invalid_range"

    def test_non_integer_error(self):
        result = _validate_range("abc", 5)
        assert isinstance(result, dict)
        assert result["error"] == "invalid_range"

    def test_none_error(self):
        result = _validate_range(None, 5)
        assert isinstance(result, dict)
        assert result["error"] == "invalid_range"


class TestOverlaps:
    def test_exact_match(self):
        assert _overlaps(5, 10, 5, 10) is True

    def test_chunk_fully_inside_request(self):
        assert _overlaps(5, 8, 3, 12) is True

    def test_request_inside_chunk(self):
        assert _overlaps(1, 20, 5, 10) is True

    def test_chunk_before_request(self):
        assert _overlaps(1, 4, 5, 10) is False

    def test_chunk_after_request(self):
        assert _overlaps(11, 20, 5, 10) is False

    def test_adjacent_no_overlap(self):
        assert _overlaps(1, 4, 5, 10) is False
        assert _overlaps(11, 20, 5, 10) is False

    def test_partial_overlap_start(self):
        assert _overlaps(3, 7, 5, 10) is True

    def test_partial_overlap_end(self):
        assert _overlaps(8, 15, 5, 10) is True

    def test_zero_chunk_start_not_overlapping(self):
        """Legacy rows (line_start=0) must not be considered overlapping."""
        assert _overlaps(0, 10, 1, 5) is False

    def test_zero_chunk_end_not_overlapping(self):
        assert _overlaps(1, 0, 1, 5) is False


class TestLinesFromChunk:
    def test_returns_only_requested_lines(self):
        text = "line A\nline B\nline C\nline D\nline E"
        result = list(_lines_from_chunk(text, chunk_line_start=1, req_start=2, req_end=4))
        assert result == [(2, "line B"), (3, "line C"), (4, "line D")]

    def test_full_chunk_returned(self):
        text = "line 1\nline 2\nline 3"
        result = list(_lines_from_chunk(text, chunk_line_start=10, req_start=10, req_end=12))
        assert result == [(10, "line 1"), (11, "line 2"), (12, "line 3")]

    def test_no_lines_before_request(self):
        text = "line A\nline B\nline C"
        result = list(_lines_from_chunk(text, chunk_line_start=1, req_start=3, req_end=5))
        # Only line at position 3 is in range (chunk has lines 1,2,3)
        assert result == [(3, "line C")]

    def test_empty_text(self):
        result = list(_lines_from_chunk("", chunk_line_start=1, req_start=1, req_end=1))
        assert result == [(1, "")]


# ─── Integration tests for read_slice ────────────────────────────────────────


@pytest.fixture
def sliceable_store(palace_path):
    """Store with two ordered chunks covering lines 1-5 and 6-10."""
    store = open_store(palace_path, create=True)
    store.add(
        ids=["chunk0", "chunk1"],
        documents=[
            "line A\nline B\nline C\nline D\nline E",
            "line F\nline G\nline H\nline I\nline J",
        ],
        metadatas=[
            {
                "wing": "proj",
                "room": "backend",
                "source_file": "/src/sliceable.py",
                "chunk_index": 0,
                "added_by": "miner",
                "filed_at": "2026-01-01T00:00:00",
                "line_start": 1,
                "line_end": 5,
            },
            {
                "wing": "proj",
                "room": "backend",
                "source_file": "/src/sliceable.py",
                "chunk_index": 1,
                "added_by": "miner",
                "filed_at": "2026-01-01T00:00:00",
                "line_start": 6,
                "line_end": 10,
            },
        ],
    )
    return store


class TestReadSlice:
    def test_single_chunk_exact_range(self, palace_path, sliceable_store):
        """read_slice: returns only lines 2-4 from first chunk."""
        result = read_slice(sliceable_store, "/src/sliceable.py", 2, 4)
        assert "error" not in result
        assert result["start"] == 2
        assert result["end"] == 4
        assert [e["line"] for e in result["lines"]] == [2, 3, 4]
        assert result["lines"][0]["text"] == "line B"
        assert result["lines"][2]["text"] == "line D"

    def test_multi_chunk_spanning_boundary(self, palace_path, sliceable_store):
        """read_slice: spans chunk boundary [4, 7] and returns lines from both chunks (AC-3)."""
        result = read_slice(sliceable_store, "/src/sliceable.py", 4, 7)
        assert "error" not in result
        line_nos = [e["line"] for e in result["lines"]]
        assert line_nos == [4, 5, 6, 7]
        texts = [e["text"] for e in result["lines"]]
        assert texts == ["line D", "line E", "line F", "line G"]

    def test_not_found_missing_source(self, palace_path, sliceable_store):
        """read_slice: not_found when source_file has no chunks in palace (AC-4)."""
        result = read_slice(sliceable_store, "/nonexistent/file.py", 1, 5)
        assert result["error"] == "not_found"
        assert result["source_file"] == "/nonexistent/file.py"

    def test_stale_pointer_range_outside_chunks(self, palace_path, sliceable_store):
        """read_slice: stale_pointer when range [100, 200] doesn't overlap any chunk (AC-5)."""
        result = read_slice(sliceable_store, "/src/sliceable.py", 100, 200)
        assert result["error"] == "stale_pointer"
        assert "100" in result["detail"] or "200" in result["detail"]

    def test_invalid_range_start_greater_than_end(self, palace_path, sliceable_store):
        """read_slice: invalid_range when start > end (AC-5)."""
        result = read_slice(sliceable_store, "/src/sliceable.py", 10, 5)
        assert result["error"] == "invalid_range"

    def test_invalid_range_zero_start(self, palace_path, sliceable_store):
        """read_slice: invalid_range when start < 1 (AC-5)."""
        result = read_slice(sliceable_store, "/src/sliceable.py", 0, 5)
        assert result["error"] == "invalid_range"

    def test_legacy_chunks_ignored_in_overlap(self, palace_path):
        """read_slice: legacy rows (line_start=0) do not satisfy overlap; stale_pointer returned."""
        store = open_store(palace_path, create=True)
        store.add(
            ids=["legacy_only"],
            documents=["some legacy content that spans many lines"],
            metadatas=[
                {
                    "wing": "proj",
                    "room": "backend",
                    "source_file": "/src/legacy.py",
                    "chunk_index": 0,
                    "added_by": "miner",
                    "filed_at": "2026-01-01T00:00:00",
                    # line_start/line_end absent → defaults to 0
                }
            ],
        )
        result = read_slice(store, "/src/legacy.py", 1, 5)
        assert result["error"] == "stale_pointer", (
            "Legacy rows with line_start=0 must not be treated as overlapping"
        )

    def test_lines_are_ordered(self, palace_path, sliceable_store):
        """read_slice: output lines are always sorted by line number."""
        result = read_slice(sliceable_store, "/src/sliceable.py", 1, 10)
        line_nos = [e["line"] for e in result["lines"]]
        assert line_nos == sorted(line_nos)

    def test_no_duplicate_lines(self, palace_path, sliceable_store):
        """read_slice: no duplicate line numbers even when chunks share boundary lines."""
        result = read_slice(sliceable_store, "/src/sliceable.py", 1, 10)
        line_nos = [e["line"] for e in result["lines"]]
        assert len(line_nos) == len(set(line_nos))

    def test_wing_filter_restricts_to_matching_wing(self, palace_path):
        """read_slice: wing filter returns not_found when no chunk in that wing (AC-3)."""
        store = open_store(palace_path, create=True)
        store.add(
            ids=["wf_chunk0"],
            documents=["def foo(): return True"],
            metadatas=[
                {
                    "wing": "proj_a",
                    "room": "backend",
                    "source_file": "/src/foo.py",
                    "chunk_index": 0,
                    "added_by": "miner",
                    "filed_at": "2026-01-01T00:00:00",
                    "line_start": 1,
                    "line_end": 1,
                }
            ],
        )
        # Correct wing finds the chunk
        result_ok = read_slice(store, "/src/foo.py", 1, 1, wing="proj_a")
        assert "error" not in result_ok
        assert result_ok["lines"][0]["text"] == "def foo(): return True"

        # Wrong wing returns not_found (chunk exists but not in proj_b)
        result_miss = read_slice(store, "/src/foo.py", 1, 1, wing="proj_b")
        assert result_miss["error"] == "not_found"


# ─── Unit tests for path resolution helpers ──────────────────────────────────


class TestMacosVarAliases:
    def test_var_path_gets_private_alias(self):
        aliases = _macos_var_aliases("/var/folders/tmp/auth.py")
        assert "/var/folders/tmp/auth.py" in aliases
        assert "/private/var/folders/tmp/auth.py" in aliases

    def test_private_var_path_gets_var_alias(self):
        aliases = _macos_var_aliases("/private/var/folders/tmp/auth.py")
        assert "/private/var/folders/tmp/auth.py" in aliases
        assert "/var/folders/tmp/auth.py" in aliases

    def test_non_var_path_returns_singleton(self):
        aliases = _macos_var_aliases("/project/src/auth.py")
        assert aliases == {"/project/src/auth.py"}

    def test_basename_only_returns_singleton(self):
        aliases = _macos_var_aliases("auth.py")
        assert aliases == {"auth.py"}


class TestEndsWithComponents:
    def test_basename_matches_last_component(self):
        assert _ends_with_components("/project/src/auth.py", "auth.py") is True

    def test_suffix_matches_last_two_components(self):
        assert _ends_with_components("/project/src/auth.py", "src/auth.py") is True

    def test_full_path_match(self):
        assert _ends_with_components("/project/src/auth.py", "/project/src/auth.py") is True

    def test_substring_basename_does_not_match(self):
        """'auth.py' must not match 'my_auth.py'."""
        assert _ends_with_components("/project/src/my_auth.py", "auth.py") is False

    def test_wrong_parent_does_not_match(self):
        assert _ends_with_components("/project/web/auth.py", "src/auth.py") is False

    def test_query_longer_than_stored_returns_false(self):
        assert _ends_with_components("auth.py", "src/auth.py") is False

    def test_empty_query_returns_false(self):
        assert _ends_with_components("/project/src/auth.py", "") is False


# ─── Integration tests for source_file_resolution ────────────────────────────


@pytest.fixture
def multi_source_store(palace_path):
    """Store with three source files sharing a basename to test disambiguation."""
    store = open_store(palace_path, create=True)
    store.add(
        ids=["ms_chunk_src", "ms_chunk_web", "ms_chunk_login"],
        documents=[
            "def authenticate(): pass",
            "class AuthController: pass",
            "def login(): pass",
        ],
        metadatas=[
            {
                "wing": "proj",
                "room": "backend",
                "source_file": "/project/src/auth.py",
                "chunk_index": 0,
                "added_by": "miner",
                "filed_at": "2026-01-01T00:00:00",
                "line_start": 1,
                "line_end": 1,
            },
            {
                "wing": "proj",
                "room": "backend",
                "source_file": "/project/web/auth.py",
                "chunk_index": 0,
                "added_by": "miner",
                "filed_at": "2026-01-01T00:00:00",
                "line_start": 1,
                "line_end": 1,
            },
            {
                "wing": "proj",
                "room": "backend",
                "source_file": "/project/src/login.py",
                "chunk_index": 0,
                "added_by": "miner",
                "filed_at": "2026-01-01T00:00:00",
                "line_start": 1,
                "line_end": 1,
            },
        ],
    )
    return store


@pytest.fixture
def macos_store(palace_path):
    """Store with a /private/var/... source_file to test macOS alias resolution."""
    store = open_store(palace_path, create=True)
    store.add(
        ids=["macos_chunk"],
        documents=["def authenticate(): pass"],
        metadatas=[
            {
                "wing": "proj",
                "room": "backend",
                "source_file": "/private/var/folders/tmp/project/auth.py",
                "chunk_index": 0,
                "added_by": "miner",
                "filed_at": "2026-01-01T00:00:00",
                "line_start": 1,
                "line_end": 1,
            }
        ],
    )
    return store


class TestSourceFileResolution:
    """read_slice: source_file resolution — exact, suffix, alias, ambiguous, and missing cases."""

    def test_source_file_resolution_exact_match(self, palace_path, multi_source_store):
        """Exact stored path resolves immediately without suffix matching (AC-2, INV-2)."""
        result = read_slice(multi_source_store, "/project/src/auth.py", 1, 1, wing="proj")
        assert "error" not in result
        assert result["source_file"] == "/project/src/auth.py"
        assert result["lines"][0]["text"] == "def authenticate(): pass"

    def test_source_file_resolution_unique_basename(self, palace_path, multi_source_store):
        """Unique basename resolves to the single matching stored path (AC-2)."""
        result = read_slice(multi_source_store, "login.py", 1, 1, wing="proj")
        assert "error" not in result
        assert result["source_file"] == "/project/src/login.py"
        assert result["lines"][0]["text"] == "def login(): pass"

    def test_source_file_resolution_unique_suffix(self, palace_path, multi_source_store):
        """Unique project-relative suffix resolves to the single matching stored path (AC-3)."""
        result = read_slice(multi_source_store, "src/auth.py", 1, 1, wing="proj")
        assert "error" not in result
        assert result["source_file"] == "/project/src/auth.py"
        assert result["lines"][0]["text"] == "def authenticate(): pass"

    def test_source_file_resolution_ambiguous_basename(self, palace_path, multi_source_store):
        """Ambiguous basename returns ambiguous_source with all candidate paths (AC-4)."""
        result = read_slice(multi_source_store, "auth.py", 1, 1, wing="proj")
        assert result["error"] == "ambiguous_source"
        assert result["source_file"] == "auth.py"
        candidates = result["candidates"]
        assert "/project/src/auth.py" in candidates
        assert "/project/web/auth.py" in candidates
        # No drawer content must be included in the error payload
        assert "lines" not in result

    def test_source_file_resolution_missing_returns_not_found(
        self, palace_path, multi_source_store
    ):
        """Unknown source returns not_found without broadening to file_context (AC-6)."""
        result = read_slice(multi_source_store, "missing.py", 1, 1, wing="proj")
        assert result["error"] == "not_found"
        assert "lines" not in result

    def test_source_file_resolution_macos_var_alias(self, palace_path, macos_store):
        """'/var/...' spelling resolves to the stored '/private/var/...' canonical path (AC-5)."""
        result = read_slice(macos_store, "/var/folders/tmp/project/auth.py", 1, 1, wing="proj")
        assert "error" not in result
        assert result["source_file"] == "/private/var/folders/tmp/project/auth.py"
        assert result["lines"][0]["text"] == "def authenticate(): pass"

    def test_source_file_resolution_wing_scopes_candidates(self, palace_path):
        """Wing filter restricts candidate discovery — cross-wing basename is not resolved (INV-3)."""
        store = open_store(palace_path, create=True)
        store.add(
            ids=["wsc_proj_a", "wsc_proj_b"],
            documents=["def alpha(): pass", "def beta(): pass"],
            metadatas=[
                {
                    "wing": "proj_a",
                    "room": "backend",
                    "source_file": "/a/auth.py",
                    "chunk_index": 0,
                    "added_by": "miner",
                    "filed_at": "2026-01-01T00:00:00",
                    "line_start": 1,
                    "line_end": 1,
                },
                {
                    "wing": "proj_b",
                    "room": "backend",
                    "source_file": "/b/auth.py",
                    "chunk_index": 0,
                    "added_by": "miner",
                    "filed_at": "2026-01-01T00:00:00",
                    "line_start": 1,
                    "line_end": 1,
                },
            ],
        )
        # With wing=proj_a, 'auth.py' is unique in that wing → resolves
        result_a = read_slice(store, "auth.py", 1, 1, wing="proj_a")
        assert "error" not in result_a
        assert result_a["source_file"] == "/a/auth.py"

        # With wing=proj_b, 'auth.py' is unique in that wing → resolves
        result_b = read_slice(store, "auth.py", 1, 1, wing="proj_b")
        assert "error" not in result_b
        assert result_b["source_file"] == "/b/auth.py"

    def test_source_file_resolution_exact_preferred_over_suffix(self, palace_path):
        """Exact match wins even when a suffix match also exists (INV-2)."""
        store = open_store(palace_path, create=True)
        store.add(
            ids=["ep_exact", "ep_long"],
            documents=["def exact(): pass", "def other(): pass"],
            metadatas=[
                {
                    "wing": "proj",
                    "room": "backend",
                    "source_file": "auth.py",
                    "chunk_index": 0,
                    "added_by": "miner",
                    "filed_at": "2026-01-01T00:00:00",
                    "line_start": 1,
                    "line_end": 1,
                },
                {
                    "wing": "proj",
                    "room": "backend",
                    "source_file": "/project/src/auth.py",
                    "chunk_index": 0,
                    "added_by": "miner",
                    "filed_at": "2026-01-01T00:00:00",
                    "line_start": 1,
                    "line_end": 1,
                },
            ],
        )
        # Input matches exactly one stored path — exact wins, no ambiguity
        result = read_slice(store, "auth.py", 1, 1, wing="proj")
        assert "error" not in result
        assert result["source_file"] == "auth.py"
        assert result["lines"][0]["text"] == "def exact(): pass"
