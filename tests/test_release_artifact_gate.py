"""Tests for scripts/release_artifact_gate.py — artifact member inspection."""

from __future__ import annotations

import importlib.util
import io
import stat
import sys
import tarfile
import warnings
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]  # reason: script path always has a spec
    sys.modules[name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]  # reason: script path always has a loader
    return mod


rag = _load_module("release_artifact_gate", ROOT / "scripts" / "release_artifact_gate.py")

_REQUIRED_AGENT_PLUGIN_MEMBERS = list(rag.AGENT_PLUGIN_REQUIRED_MEMBERS)

WHEEL_NAME = "mempalace_code-1.0.0-py3-none-any.whl"
SDIST_NAME = "mempalace_code-1.0.0.tar.gz"
DIST_INFO_ROOT = "mempalace_code-1.0.0.dist-info"
GENERATED_DIST_INFO = sorted(rag.GENERATED_DIST_INFO_MEMBERS)


# ── Fixture helpers ────────────────────────────────────────────────────────────


def _plugin_json_content(version: str = "1.0.0") -> str:
    return __import__("json").dumps({"version": version})


def _make_wheel(
    dist_dir: Path,
    members: list[str],
    *,
    plugin_json_version: str | None = "1.0.0",
    dist_info: list[str] | None = None,
    filename: str = WHEEL_NAME,
) -> Path:
    """Create a minimal .whl (zip) archive with the given member names.

    `members` is the package side. The generated `.dist-info` side defaults to
    exactly the set a real build writes, because the gate requires that set to be
    complete; pass `dist_info` to model a wheel whose metadata deviates.
    """
    wheel_path = dist_dir / filename
    generated = GENERATED_DIST_INFO if dist_info is None else dist_info
    with zipfile.ZipFile(wheel_path, "w") as zf:
        for member in members:
            if member == rag.PLUGIN_JSON_MEMBER and plugin_json_version is not None:
                zf.writestr(member, _plugin_json_content(plugin_json_version))
            else:
                zf.writestr(member, "placeholder content")
        for member in generated:
            zf.writestr(f"{DIST_INFO_ROOT}/{member}", "placeholder content")
    return wheel_path


def _make_sdist(
    dist_dir: Path, members: list[str], *, plugin_json_version: str | None = "1.0.0"
) -> Path:
    """Create a minimal .tar.gz archive with the given member names (sdist-style)."""
    sdist_path = dist_dir / SDIST_NAME
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for member in members:
            if member == rag.PLUGIN_JSON_MEMBER and plugin_json_version is not None:
                content = _plugin_json_content(plugin_json_version).encode("utf-8")
            else:
                content = b"placeholder content"
            info = tarfile.TarInfo(name=f"mempalace_code-1.0.0/{member}")
            info.size = len(content)
            tf.addfile(info, io.BytesIO(content))
    sdist_path.write_bytes(buf.getvalue())
    return sdist_path


def _make_raw_sdist(
    dist_dir: Path, entries: list[tarfile.TarInfo], *, filename: str = SDIST_NAME
) -> Path:
    """Create an sdist whose exact tar entries — including kind — the caller sets."""
    sdist_path = dist_dir / filename
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for info in entries:
            if info.isfile():
                tf.addfile(info, io.BytesIO(b"placeholder content"))
            else:
                tf.addfile(info)
    sdist_path.write_bytes(buf.getvalue())
    return sdist_path


def _tar_file(name: str) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name=name)
    info.size = len(b"placeholder content")
    return info


def _zip_entry(name: str, *, mode: int = 0o100644) -> zipfile.ZipInfo:
    """A zip entry whose unix mode — file-type bits included — the caller sets."""
    info = zipfile.ZipInfo(filename=name)
    info.external_attr = mode << 16
    return info


def _make_raw_wheel(
    dist_dir: Path, entries: list[zipfile.ZipInfo], *, filename: str = WHEEL_NAME
) -> Path:
    """Create a wheel whose exact zip entries — including unix mode — the caller sets."""
    wheel_path = dist_dir / filename
    with warnings.catch_warnings():
        # Repeated names are the point of one of the fixtures below.
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(wheel_path, "w") as zf:
            for info in entries:
                if info.filename == rag.PLUGIN_JSON_MEMBER:
                    zf.writestr(info, _plugin_json_content())
                else:
                    zf.writestr(info, "placeholder content")
    return wheel_path


def _canonical_wheel_entries(extra: list[str]) -> list[zipfile.ZipInfo]:
    """The entries a passing wheel holds, plus whatever shape a test is adding."""
    return [
        _zip_entry("mempalace_code/__init__.py"),
        *(_zip_entry(member) for member in _REQUIRED_AGENT_PLUGIN_MEMBERS),
        *(_zip_entry(f"{DIST_INFO_ROOT}/{member}") for member in GENERATED_DIST_INFO),
        *(_zip_entry(name) for name in extra),
    ]


# ── Clean artifact tests ───────────────────────────────────────────────────────


def test_clean_wheel_passes_member_check(tmp_path):
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    _make_wheel(dist_dir, ["mempalace_code/__init__.py", *_REQUIRED_AGENT_PLUGIN_MEMBERS])
    result = rag.inspect_dist(dist_dir, require_wheel=True, run_twine=False)
    wheel_row = next(r for r in result["rows"] if r["check"] == "wheel-members")
    plugin_row = next(r for r in result["rows"] if r["check"] == "wheel-agent-plugin-members")
    assert wheel_row["status"] == "pass"
    assert plugin_row["status"] == "pass"
    assert result["wheel_found"] is not None


def test_clean_sdist_passes_member_check(tmp_path):
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    _make_sdist(
        dist_dir,
        [
            "mempalace_code/__init__.py",
            "pyproject.toml",
            "README.md",
            *_REQUIRED_AGENT_PLUGIN_MEMBERS,
        ],
    )
    result = rag.inspect_dist(dist_dir, require_sdist=True, run_twine=False)
    sdist_row = next(r for r in result["rows"] if r["check"] == "sdist-members")
    plugin_row = next(r for r in result["rows"] if r["check"] == "sdist-agent-plugin-members")
    assert sdist_row["status"] == "pass"
    assert plugin_row["status"] == "pass"
    assert result["sdist_found"] is not None


def test_clean_wheel_and_sdist_both_pass(tmp_path):
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    _make_wheel(dist_dir, ["mempalace_code/__init__.py", *_REQUIRED_AGENT_PLUGIN_MEMBERS])
    _make_sdist(dist_dir, ["mempalace_code/__init__.py", *_REQUIRED_AGENT_PLUGIN_MEMBERS])
    result = rag.inspect_dist(dist_dir, require_wheel=True, require_sdist=True, run_twine=False)
    assert result["ok"] is True
    assert result["wheel_found"] is not None
    assert result["sdist_found"] is not None


def test_agent_plugin_required_members_are_checked(tmp_path):
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    _make_wheel(dist_dir, ["mempalace_code/__init__.py", *_REQUIRED_AGENT_PLUGIN_MEMBERS])
    _make_sdist(dist_dir, ["mempalace_code/__init__.py", *_REQUIRED_AGENT_PLUGIN_MEMBERS])

    result = rag.inspect_dist(dist_dir, require_wheel=True, require_sdist=True, run_twine=False)

    wheel_row = next(r for r in result["rows"] if r["check"] == "wheel-agent-plugin-members")
    sdist_row = next(r for r in result["rows"] if r["check"] == "sdist-agent-plugin-members")
    assert wheel_row["status"] == "pass"
    assert sdist_row["status"] == "pass"
    assert result["ok"] is True


def test_missing_agent_plugin_member_fails_artifact_gate(tmp_path):
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    missing = "mempalace_code/agent_plugin/mcp.json"
    incomplete = [m for m in _REQUIRED_AGENT_PLUGIN_MEMBERS if m != missing]
    _make_wheel(dist_dir, ["mempalace_code/__init__.py", *incomplete])
    _make_sdist(dist_dir, ["mempalace_code/__init__.py", *incomplete])

    result = rag.inspect_dist(dist_dir, require_wheel=True, require_sdist=True, run_twine=False)

    wheel_row = next(r for r in result["rows"] if r["check"] == "wheel-agent-plugin-members")
    sdist_row = next(r for r in result["rows"] if r["check"] == "sdist-agent-plugin-members")
    assert wheel_row["status"] == "fail"
    assert sdist_row["status"] == "fail"
    assert missing in wheel_row["detail"]
    assert missing in sdist_row["detail"]
    assert result["ok"] is False


# ── plugin.json version binding ────────────────────────────────────────────────


def test_wheel_plugin_json_version_matches_filename_passes(tmp_path):
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    _make_wheel(
        dist_dir,
        ["mempalace_code/__init__.py", *_REQUIRED_AGENT_PLUGIN_MEMBERS],
        plugin_json_version="1.0.0",
    )
    result = rag.inspect_dist(dist_dir, require_wheel=True, run_twine=False)
    version_row = next(r for r in result["rows"] if r["check"] == "wheel-agent-plugin-version")
    assert version_row["status"] == "pass"
    assert result["ok"] is True


def test_wheel_plugin_json_stale_version_fails(tmp_path):
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    _make_wheel(
        dist_dir,
        ["mempalace_code/__init__.py", *_REQUIRED_AGENT_PLUGIN_MEMBERS],
        plugin_json_version="0.9.0",
    )
    result = rag.inspect_dist(dist_dir, require_wheel=True, run_twine=False)
    version_row = next(r for r in result["rows"] if r["check"] == "wheel-agent-plugin-version")
    assert version_row["status"] == "fail"
    assert "0.9.0" in version_row["detail"]
    assert "1.0.0" in version_row["detail"]
    assert result["ok"] is False


def test_sdist_plugin_json_version_matches_filename_passes(tmp_path):
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    _make_sdist(
        dist_dir,
        ["mempalace_code/__init__.py", *_REQUIRED_AGENT_PLUGIN_MEMBERS],
        plugin_json_version="1.0.0",
    )
    result = rag.inspect_dist(dist_dir, require_sdist=True, run_twine=False)
    version_row = next(r for r in result["rows"] if r["check"] == "sdist-agent-plugin-version")
    assert version_row["status"] == "pass"
    assert result["ok"] is True


def test_sdist_plugin_json_stale_version_fails(tmp_path):
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    _make_sdist(
        dist_dir,
        ["mempalace_code/__init__.py", *_REQUIRED_AGENT_PLUGIN_MEMBERS],
        plugin_json_version="0.9.0",
    )
    result = rag.inspect_dist(dist_dir, require_sdist=True, run_twine=False)
    version_row = next(r for r in result["rows"] if r["check"] == "sdist-agent-plugin-version")
    assert version_row["status"] == "fail"
    assert "0.9.0" in version_row["detail"]
    assert "1.0.0" in version_row["detail"]
    assert result["ok"] is False


def test_wheel_plugin_json_missing_version_field_fails(tmp_path):
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    wheel_path = dist_dir / "mempalace_code-1.0.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel_path, "w") as zf:
        zf.writestr("mempalace_code/__init__.py", "placeholder content")
        for member in _REQUIRED_AGENT_PLUGIN_MEMBERS:
            if member == rag.PLUGIN_JSON_MEMBER:
                zf.writestr(member, "{}")
            else:
                zf.writestr(member, "placeholder content")

    result = rag.inspect_dist(dist_dir, require_wheel=True, run_twine=False)
    version_row = next(r for r in result["rows"] if r["check"] == "wheel-agent-plugin-version")
    assert version_row["status"] == "fail"
    assert "version" in version_row["detail"]
    assert result["ok"] is False


# ── Forbidden member rejection ─────────────────────────────────────────────────


def test_wheel_with_codex_local_fails(tmp_path):
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    _make_wheel(
        dist_dir,
        [
            "mempalace_code/__init__.py",
            ".codex-local/LESSONS.md",
        ],
    )
    result = rag.inspect_dist(dist_dir, run_twine=False)
    member_row = next(r for r in result["rows"] if r["check"] == "wheel-members")
    assert member_row["status"] == "fail"
    assert ".codex-local" in member_row["detail"]
    assert result["ok"] is False


def test_sdist_with_codex_config_fails(tmp_path):
    """`.codex/config.toml` carries absolute local paths and must never ship.

    This is a synthetic archive: it proves the gate rejects the member if it
    ever reaches a distribution. That the Hatch sdist exclude keeps it out of a
    real build is a separate fact, proven by building with the ignored file
    present — not by this test.
    """
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    _make_sdist(
        dist_dir,
        [
            "mempalace_code/__init__.py",
            ".codex/config.toml",
        ],
    )
    result = rag.inspect_dist(dist_dir, run_twine=False)
    sdist_row = next(r for r in result["rows"] if r["check"] == "sdist-members")
    assert sdist_row["status"] == "fail"
    assert ".codex/config.toml" in sdist_row["detail"]
    assert result["ok"] is False


def test_sdist_with_repository_only_codex_review_script_has_bounded_diagnostic(tmp_path):
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    _make_sdist(
        dist_dir,
        [
            "mempalace_code/__init__.py",
            "scripts/codex-review.sh",
        ],
    )

    result = rag.inspect_dist(dist_dir, run_twine=False)

    sdist_row = next(r for r in result["rows"] if r["check"] == "sdist-members")
    assert sdist_row == {
        "check": "sdist-members",
        "status": "fail",
        "detail": ("rejected members: ['sdist:mempalace_code-1.0.0/scripts/codex-review.sh']"),
    }
    assert result["ok"] is False


def test_sdist_with_untracked_member_fails_without_a_named_prefix(tmp_path):
    """Any member git does not track is rejected, prefix list or not.

    `.git/info/exclude` hides files from git status while build backends still
    package them, so the next leak will not be a prefix anyone listed. The
    tracked-inventory rule is what closes that class.
    """
    assert not any(".private-agent/".startswith(prefix) for prefix in rag.FORBIDDEN_MEMBER_PREFIXES)
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    _make_sdist(
        dist_dir,
        [
            "mempalace_code/__init__.py",
            ".private-agent/config.toml",
        ],
    )
    result = rag.inspect_dist(dist_dir, run_twine=False)
    sdist_row = next(r for r in result["rows"] if r["check"] == "sdist-members")
    assert sdist_row["status"] == "fail"
    assert ".private-agent/config.toml" in sdist_row["detail"]
    assert result["ok"] is False


# ── Archive shape: roots, kinds, duplicates, generated members ────────────────


def test_sdist_pkg_info_under_the_canonical_root_is_allowed(tmp_path):
    """PKG-INFO is the one member the backend generates, and only at the root."""
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    _make_sdist(dist_dir, ["PKG-INFO", "mempalace_code/__init__.py"])
    result = rag.inspect_dist(dist_dir, run_twine=False)
    sdist_row = next(r for r in result["rows"] if r["check"] == "sdist-members")
    assert sdist_row["status"] == "pass"


def test_sdist_outside_the_filename_root_fails(tmp_path):
    """Members must live under the one root the sdist filename implies.

    A rootless PKG-INFO and a second, spoofed root both extract somewhere the
    reader did not ask for, so neither is a shape this project ever publishes.
    """
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    _make_raw_sdist(
        dist_dir,
        [
            _tar_file("mempalace_code-1.0.0/mempalace_code/__init__.py"),
            _tar_file("PKG-INFO"),
            _tar_file("mempalace_code-9.9.9/pyproject.toml"),
        ],
    )
    result = rag.inspect_dist(dist_dir, run_twine=False)
    sdist_row = next(r for r in result["rows"] if r["check"] == "sdist-members")
    assert sdist_row["status"] == "fail"
    assert "sdist-foreign-root:PKG-INFO" in sdist_row["detail"]
    assert "sdist-foreign-root:mempalace_code-9.9.9/pyproject.toml" in sdist_row["detail"]
    assert result["ok"] is False


def test_sdist_duplicate_member_path_fails(tmp_path):
    """Two entries for one path mean the inspected bytes are not the extracted ones."""
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    _make_raw_sdist(
        dist_dir,
        [
            _tar_file("mempalace_code-1.0.0/mempalace_code/__init__.py"),
            _tar_file("mempalace_code-1.0.0/mempalace_code/__init__.py"),
        ],
    )
    result = rag.inspect_dist(dist_dir, run_twine=False)
    sdist_row = next(r for r in result["rows"] if r["check"] == "sdist-members")
    assert sdist_row["status"] == "fail"
    assert "sdist-duplicate:" in sdist_row["detail"]
    assert result["ok"] is False


def test_sdist_symlink_member_fails(tmp_path):
    """A symlink member resolves outside the archive on extraction."""
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    link = tarfile.TarInfo(name="mempalace_code-1.0.0/README.md")
    link.type = tarfile.SYMTYPE
    link.linkname = "../../../etc/passwd"
    _make_raw_sdist(
        dist_dir,
        [_tar_file("mempalace_code-1.0.0/mempalace_code/__init__.py"), link],
    )
    result = rag.inspect_dist(dist_dir, run_twine=False)
    sdist_row = next(r for r in result["rows"] if r["check"] == "sdist-members")
    assert sdist_row["status"] == "fail"
    assert "sdist-non-regular:mempalace_code-1.0.0/README.md" in sdist_row["detail"]
    assert result["ok"] is False


def test_wheel_with_untracked_package_file_fails(tmp_path):
    """The ignored-file class reaches the wheel too, inside the package directory.

    `.git/info/exclude` hides a file from git while the backend still packages
    it, and a file under `mempalace_code/` passes every prefix rule there is.
    """
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    _make_wheel(
        dist_dir,
        [
            "mempalace_code/__init__.py",
            "mempalace_code/_local_operator_notes.py",
            *_REQUIRED_AGENT_PLUGIN_MEMBERS,
        ],
    )
    result = rag.inspect_dist(dist_dir, run_twine=False)
    wheel_row = next(r for r in result["rows"] if r["check"] == "wheel-members")
    assert wheel_row["status"] == "fail"
    assert "wheel-untracked:mempalace_code/_local_operator_notes.py" in wheel_row["detail"]
    assert result["ok"] is False


def test_wheel_unexpected_generated_and_foreign_root_members_fail(tmp_path):
    """Outside the package, only the exact generated `.dist-info` set may ship."""
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    _make_wheel(
        dist_dir,
        [
            "mempalace_code/__init__.py",
            "mempalace_code-1.0.0.data/scripts/postinstall.sh",
            *_REQUIRED_AGENT_PLUGIN_MEMBERS,
        ],
        dist_info=[*GENERATED_DIST_INFO, "OPERATOR-NOTES.txt"],
    )
    result = rag.inspect_dist(dist_dir, run_twine=False)
    wheel_row = next(r for r in result["rows"] if r["check"] == "wheel-members")
    assert wheel_row["status"] == "fail"
    detail = wheel_row["detail"]
    assert "wheel-unexpected-dist-info:mempalace_code-1.0.0.dist-info/OPERATOR-NOTES.txt" in detail
    assert "wheel-foreign-root:mempalace_code-1.0.0.data/scripts/postinstall.sh" in detail
    assert result["ok"] is False


@pytest.mark.parametrize("dropped", GENERATED_DIST_INFO)
def test_wheel_missing_any_generated_dist_info_member_fails(tmp_path, dropped: str):
    """The generated set is an equality, not a ceiling.

    A wheel that quietly loses `licenses/LICENSE`, `RECORD` or `entry_points.txt`
    satisfies every "nothing extra shipped" rule while being unusable or
    unlicensed on the reader's side.
    """
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    _make_wheel(
        dist_dir,
        ["mempalace_code/__init__.py", *_REQUIRED_AGENT_PLUGIN_MEMBERS],
        dist_info=[m for m in GENERATED_DIST_INFO if m != dropped],
    )
    result = rag.inspect_dist(dist_dir, run_twine=False)
    wheel_row = next(r for r in result["rows"] if r["check"] == "wheel-members")
    assert wheel_row["status"] == "fail"
    assert f"wheel-missing-dist-info:{DIST_INFO_ROOT}/{dropped}" in wheel_row["detail"]
    assert result["ok"] is False


def test_wheel_fifo_member_under_a_tracked_name_fails(tmp_path):
    """Mode bits, not the name, decide whether a member is a file.

    A FIFO named `mempalace_code/__init__.py` is tracked, safely named, unique
    and under the package root — it satisfies every rule except its own type,
    and extracting it puts a pipe where the module should be. Checking only for
    symlink bits let every other non-regular type through.
    """
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    entries = _canonical_wheel_entries([])
    entries[0] = _zip_entry("mempalace_code/__init__.py", mode=stat.S_IFIFO | 0o644)
    _make_raw_wheel(dist_dir, entries)

    result = rag.inspect_dist(dist_dir, run_twine=False)

    wheel_row = next(r for r in result["rows"] if r["check"] == "wheel-members")
    assert wheel_row["status"] == "fail"
    assert "wheel-non-regular:mempalace_code/__init__.py" in wheel_row["detail"]
    assert result["ok"] is False


@pytest.mark.parametrize(
    ("mode", "label"),
    [
        (stat.S_IFCHR | 0o644, "character device"),
        (stat.S_IFBLK | 0o644, "block device"),
        (stat.S_IFSOCK | 0o644, "socket"),
        (stat.S_IFLNK | 0o777, "symlink"),
        (stat.S_IFDIR | 0o755, "directory-shaped mode"),
    ],
)
def test_wheel_rejects_every_non_regular_member_type(tmp_path, mode: int, label: str):
    """Each of these extracts as something other than the file its name promises."""
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    # No trailing slash, so the directory-shaped case is a mode claim rather than
    # the ordinary directory entry the check reports separately.
    _make_raw_wheel(
        dist_dir, _canonical_wheel_entries([]) + [_zip_entry("mempalace_code/x", mode=mode)]
    )

    result = rag.inspect_dist(dist_dir, run_twine=False)

    wheel_row = next(r for r in result["rows"] if r["check"] == "wheel-members")
    assert wheel_row["status"] == "fail", label
    assert "wheel-non-regular:mempalace_code/x" in wheel_row["detail"], label
    assert result["ok"] is False


def test_wheel_written_the_way_a_real_build_writes_it_passes(tmp_path):
    """A real Hatch wheel mixes both encodings, so both have to count as regular.

    Measured on a real `python -m build`: the 92 package members carry S_IFREG
    and the 6 generated `.dist-info` members carry bare permissions with no
    file-type bits. Treating a missing type as non-regular would reject every
    wheel this project has ever built.
    """
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    entries = [
        _zip_entry(entry.filename, mode=0o644 if DIST_INFO_ROOT in entry.filename else 0o100644)
        for entry in _canonical_wheel_entries([])
    ]
    _make_raw_wheel(dist_dir, entries)

    result = rag.inspect_dist(dist_dir, require_wheel=True, run_twine=False)

    wheel_row = next(r for r in result["rows"] if r["check"] == "wheel-members")
    assert wheel_row["status"] == "pass"
    assert result["ok"] is True


# ── Shape diagnostics that only an operator sees ──────────────────────────────


@pytest.mark.parametrize(
    ("extra", "filename", "expected"),
    [
        (["mempalace_code/subpkg/"], WHEEL_NAME, "wheel-directory-entry:mempalace_code/subpkg/"),
        (
            ["mempalace_code/../escape.py"],
            WHEEL_NAME,
            "wheel-unsafe-path:mempalace_code/../escape.py",
        ),
        (["/etc/passwd"], WHEEL_NAME, "wheel-unsafe-path:/etc/passwd"),
        (["mempalace_code/__init__.py"], WHEEL_NAME, "wheel-duplicate:mempalace_code/__init__.py"),
        ([], "mempalace_code.whl", "wheel-unparsable-filename:mempalace_code.whl"),
    ],
    ids=["directory-entry", "escaping-path", "absolute-path", "duplicate", "unparsable-filename"],
)
def test_wheel_shape_diagnostics_are_reported(
    tmp_path, extra: list[str], filename: str, expected: str
):
    """Each rejection carries its own diagnostic, so an operator sees what broke."""
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    _make_raw_wheel(dist_dir, _canonical_wheel_entries(extra), filename=filename)

    result = rag.inspect_dist(dist_dir, run_twine=False)

    wheel_row = next(r for r in result["rows"] if r["check"] == "wheel-members")
    assert wheel_row["status"] == "fail"
    assert expected in wheel_row["detail"]
    assert result["ok"] is False


@pytest.mark.parametrize(
    ("names", "filename", "expected"),
    [
        (
            ["mempalace_code-1.0.0/../etc/passwd"],
            SDIST_NAME,
            "sdist-unsafe-path:mempalace_code-1.0.0/../etc/passwd",
        ),
        (["/etc/passwd"], SDIST_NAME, "sdist-unsafe-path:/etc/passwd"),
        ([], "archive.tar.gz", "sdist-unparsable-filename:archive.tar.gz"),
    ],
    ids=["escaping-path", "absolute-path", "unparsable-filename"],
)
def test_sdist_shape_diagnostics_are_reported(
    tmp_path, names: list[str], filename: str, expected: str
):
    """Same for the sdist: a rejection an operator cannot read is a rejection twice."""
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    _make_raw_sdist(
        dist_dir,
        [
            _tar_file("mempalace_code-1.0.0/mempalace_code/__init__.py"),
            *(_tar_file(n) for n in names),
        ],
        filename=filename,
    )

    result = rag.inspect_dist(dist_dir, run_twine=False)

    sdist_row = next(r for r in result["rows"] if r["check"] == "sdist-members")
    assert sdist_row["status"] == "fail"
    assert expected in sdist_row["detail"]
    assert result["ok"] is False


# ── Fail-closed inventory and ambiguous dist directories ──────────────────────


def test_both_archives_fail_closed_when_the_tracked_inventory_is_unavailable(tmp_path, monkeypatch):
    """No inventory means the tracked rule cannot be evaluated, so nothing passes."""
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    _make_wheel(dist_dir, ["mempalace_code/__init__.py", *_REQUIRED_AGENT_PLUGIN_MEMBERS])
    _make_sdist(dist_dir, ["mempalace_code/__init__.py", *_REQUIRED_AGENT_PLUGIN_MEMBERS])
    monkeypatch.setattr(
        rag, "tracked_repository_paths", lambda *_a, **_k: (frozenset(), "git ls-files exited 128")
    )

    result = rag.inspect_dist(dist_dir, require_wheel=True, require_sdist=True, run_twine=False)

    for check in ("wheel-members", "sdist-members"):
        row = next(r for r in result["rows"] if r["check"] == check)
        assert row["status"] == "fail"
        assert "tracked-source-inventory-unavailable" in row["detail"]
    assert result["ok"] is False


def test_inventory_diagnostic_never_echoes_a_local_path(tmp_path):
    """git writes absolute paths to stderr; the diagnostic must not carry them."""
    paths, error = rag.tracked_repository_paths(tmp_path)
    assert paths == frozenset()
    assert error is not None
    assert str(tmp_path) not in error


def test_two_wheels_in_dist_fail_instead_of_inspecting_one(tmp_path, monkeypatch):
    """A stale dist/ holding two builds must not pass on whichever sorts first."""
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    _make_wheel(dist_dir, ["mempalace_code/__init__.py", *_REQUIRED_AGENT_PLUGIN_MEMBERS])
    stale = dist_dir / "mempalace_code-0.9.0-py3-none-any.whl"
    stale.write_bytes((dist_dir / "mempalace_code-1.0.0-py3-none-any.whl").read_bytes())
    _make_sdist(dist_dir, ["mempalace_code/__init__.py", *_REQUIRED_AGENT_PLUGIN_MEMBERS])
    monkeypatch.setattr(rag, "_run_twine_check", lambda _d: (True, "PASSED"))

    result = rag.inspect_dist(dist_dir, require_wheel=True, require_sdist=True)

    wheel_row = next(r for r in result["rows"] if r["check"] == "wheel-present")
    assert wheel_row["status"] == "fail"
    assert "found" in wheel_row["detail"]
    assert result["ok"] is False
    # No wheel was chosen, so no wheel member row claims a verdict.
    assert not any(r["check"] == "wheel-members" for r in result["rows"])


def test_two_sdists_in_dist_fail_even_when_the_type_is_not_required(tmp_path):
    """Ambiguity is reported whether or not the caller asked for the type."""
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    _make_sdist(dist_dir, ["mempalace_code/__init__.py", *_REQUIRED_AGENT_PLUGIN_MEMBERS])
    stale = dist_dir / "mempalace_code-0.9.0.tar.gz"
    stale.write_bytes((dist_dir / "mempalace_code-1.0.0.tar.gz").read_bytes())

    result = rag.inspect_dist(dist_dir, run_twine=False)

    sdist_row = next(r for r in result["rows"] if r["check"] == "sdist-present")
    assert sdist_row["status"] == "fail"
    assert result["ok"] is False


# ── Build configuration contract ──────────────────────────────────────────────


def test_pyproject_excludes_codex_from_the_sdist():
    """The gate catches the leak; this exclude is what stops it being built.

    `.codex/` is ignored through `.git/info/exclude`, which hatchling does not
    read, so without this entry the directory is packaged despite git treating
    it as absent.
    """
    import tomllib

    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    exclude = config["tool"]["hatch"]["build"]["targets"]["sdist"]["exclude"]
    assert ".codex/" in exclude


def test_pyproject_excludes_repository_only_release_configuration_from_the_sdist():
    import tomllib

    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    exclude = config["tool"]["hatch"]["build"]["targets"]["sdist"]["exclude"]
    assert ".claude/**" in exclude
    assert "/.gitleaksignore" in exclude
    assert exclude.count("scripts/codex-review.sh") == 1
    for repository_only_path in (
        ".playwright-mcp/",
        "docs/BACKLOG.yaml",
        "docs/BACKLOG-archived.yaml",
        "docs/task-evidence/",
    ):
        assert exclude.count(repository_only_path) == 1
    assert "docs/" not in exclude
    assert "docs/quality/" not in exclude


def test_wheel_with_tasks_dir_fails(tmp_path):
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    _make_wheel(
        dist_dir,
        [
            "mempalace_code/__init__.py",
            ".tasks/TASK-demo/raw.txt",
        ],
    )
    result = rag.inspect_dist(dist_dir, run_twine=False)
    member_row = next(r for r in result["rows"] if r["check"] == "wheel-members")
    assert member_row["status"] == "fail"
    assert result["ok"] is False


def test_sdist_with_protocols_dir_fails(tmp_path):
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    _make_sdist(
        dist_dir,
        [
            "mempalace_code/__init__.py",
            ".protocols/some-protocol.md",
        ],
    )
    result = rag.inspect_dist(dist_dir, run_twine=False)
    sdist_row = next(r for r in result["rows"] if r["check"] == "sdist-members")
    assert sdist_row["status"] == "fail"
    assert result["ok"] is False


def test_sdist_with_docs_audits_fails(tmp_path):
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    _make_sdist(
        dist_dir,
        [
            "mempalace_code/__init__.py",
            "docs/audits/internal-audit.md",
        ],
    )
    result = rag.inspect_dist(dist_dir, run_twine=False)
    sdist_row = next(r for r in result["rows"] if r["check"] == "sdist-members")
    assert sdist_row["status"] == "fail"
    assert result["ok"] is False


@pytest.mark.parametrize(
    "internal_member",
    [
        ".claude/skills/release/SKILL.md",
        ".github/workflows/ci.yml",
        "docs/dependency-upgrade-reports/internal.json",
        "docs/plans/internal-plan.md",
    ],
)
def test_sdist_with_internal_repository_surface_fails(tmp_path, internal_member):
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    _make_sdist(dist_dir, ["mempalace_code/__init__.py", internal_member])

    result = rag.inspect_dist(dist_dir, run_twine=False)

    sdist_row = next(r for r in result["rows"] if r["check"] == "sdist-members")
    assert sdist_row["status"] == "fail"
    assert result["ok"] is False


def test_sdist_with_verify_state_fails(tmp_path):
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    _make_sdist(
        dist_dir,
        [
            "mempalace_code/__init__.py",
            ".verify-state",
        ],
    )
    result = rag.inspect_dist(dist_dir, run_twine=False)
    sdist_row = next(r for r in result["rows"] if r["check"] == "sdist-members")
    assert sdist_row["status"] == "fail"
    assert result["ok"] is False


def test_wheel_with_pycache_fails(tmp_path):
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    _make_wheel(
        dist_dir,
        [
            "mempalace_code/__init__.py",
            "__pycache__/module.cpython-311.pyc",
        ],
    )
    result = rag.inspect_dist(dist_dir, run_twine=False)
    member_row = next(r for r in result["rows"] if r["check"] == "wheel-members")
    assert member_row["status"] == "fail"
    assert result["ok"] is False


# ── Missing distribution file tests ───────────────────────────────────────────


def test_missing_wheel_fails_when_required(tmp_path):
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    _make_sdist(dist_dir, ["mempalace_code/__init__.py"])
    result = rag.inspect_dist(dist_dir, require_wheel=True, run_twine=False)
    wheel_row = next(r for r in result["rows"] if r["check"] == "wheel-present")
    assert wheel_row["status"] == "fail"
    assert result["ok"] is False


def test_missing_sdist_fails_when_required(tmp_path):
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    _make_wheel(dist_dir, ["mempalace_code/__init__.py", *_REQUIRED_AGENT_PLUGIN_MEMBERS])
    result = rag.inspect_dist(dist_dir, require_sdist=True, run_twine=False)
    sdist_row = next(r for r in result["rows"] if r["check"] == "sdist-present")
    assert sdist_row["status"] == "fail"
    assert result["ok"] is False


def test_missing_both_no_require_is_ok_with_no_twine(tmp_path):
    """When neither require_wheel nor require_sdist, an empty dist dir is ok (no files = no checks)."""
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    result = rag.inspect_dist(dist_dir, run_twine=False)
    assert result["ok"] is True
    assert result["wheel_found"] is None
    assert result["sdist_found"] is None


# ── Twine failure reporting ────────────────────────────────────────────────────


def test_twine_check_failure_sets_ok_false(tmp_path, monkeypatch):
    """When twine check fails, ok is False and detail captures the failure."""
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    _make_wheel(dist_dir, ["mempalace_code/__init__.py"])

    monkeypatch.setattr(rag, "_run_twine_check", lambda _d: (False, "FAIL bad metadata"))
    result = rag.inspect_dist(dist_dir, run_twine=True)
    twine_row = next(r for r in result["rows"] if r["check"] == "twine-check")
    assert twine_row["status"] == "fail"
    assert "bad metadata" in twine_row["detail"]
    assert result["ok"] is False


def test_twine_check_pass_sets_ok_true(tmp_path, monkeypatch):
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    _make_wheel(dist_dir, ["mempalace_code/__init__.py", *_REQUIRED_AGENT_PLUGIN_MEMBERS])
    _make_sdist(dist_dir, ["mempalace_code/__init__.py", *_REQUIRED_AGENT_PLUGIN_MEMBERS])

    monkeypatch.setattr(rag, "_run_twine_check", lambda _d: (True, "PASSED"))
    result = rag.inspect_dist(dist_dir, require_wheel=True, require_sdist=True, run_twine=True)
    twine_row = next(r for r in result["rows"] if r["check"] == "twine-check")
    assert twine_row["status"] == "pass"
    assert result["ok"] is True


# ── CLI main() ────────────────────────────────────────────────────────────────


def test_main_missing_dist_dir_exits_1(tmp_path):
    rc = rag.main(["--dist", str(tmp_path / "no-such-dir")])
    assert rc == 1


def test_main_clean_artifacts_exits_0(tmp_path, monkeypatch):
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    _make_wheel(dist_dir, ["mempalace_code/__init__.py", *_REQUIRED_AGENT_PLUGIN_MEMBERS])
    _make_sdist(dist_dir, ["mempalace_code/__init__.py", *_REQUIRED_AGENT_PLUGIN_MEMBERS])
    monkeypatch.setattr(rag, "_run_twine_check", lambda _d: (True, "PASSED"))

    rc = rag.main(
        [
            "--dist",
            str(dist_dir),
            "--require-wheel",
            "--require-sdist",
        ]
    )
    assert rc == 0


def test_main_forbidden_member_exits_1(tmp_path, monkeypatch):
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    _make_wheel(dist_dir, [".tasks/TASK-leak/raw.txt"])
    monkeypatch.setattr(rag, "_run_twine_check", lambda _d: (True, "PASSED"))

    rc = rag.main(["--dist", str(dist_dir)])
    assert rc == 1


def test_main_json_output(tmp_path, capsys, monkeypatch):
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    _make_wheel(dist_dir, ["mempalace_code/__init__.py", *_REQUIRED_AGENT_PLUGIN_MEMBERS])
    monkeypatch.setattr(rag, "_run_twine_check", lambda _d: (True, "PASSED"))

    rc = rag.main(["--dist", str(dist_dir), "--json"])
    assert rc == 0
    import json as _json

    out = capsys.readouterr().out
    data = _json.loads(out)
    assert "ok" in data
    assert "rows" in data
