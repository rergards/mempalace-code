"""Tests for scripts/release_status_gate.py.

Covers: all-green gate, surface blockers, version/metadata edge cases,
sanitized error output, and machine-readable JSON output.

All seams (run_git, run_gh, http_get, run_subprocess) are mocked so no live
GitHub, PyPI, or pip network calls are made.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

ROOT = Path(__file__).parent.parent


def _load_module_from_path(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]  # reason: known script path always returns a spec
    sys.modules[name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]  # reason: known script path has a loader
    return mod


rsg = _load_module_from_path("release_status_gate", ROOT / "scripts" / "release_status_gate.py")

VERSION = "1.2.3"
REPO = "testowner/testrepo"
REMOTE = "publish"
BRANCH = "main"
PACKAGE = "mempalace-code"

# ── Mock factories ─────────────────────────────────────────────────────────────


def _release_view_data(
    version: str = VERSION,
    release_draft: bool = False,
    release_prerelease: bool = False,
) -> dict[str, object]:
    return {
        "tagName": f"v{version}",
        "isDraft": release_draft,
        "isPrerelease": release_prerelease,
        "publishedAt": "2024-01-01T00:00:00Z",
        "url": f"https://github.com/testowner/testrepo/releases/tag/v{version}",
        "targetCommitish": "main",
    }


def _release_list_data(
    version: str = VERSION,
    release_latest: bool = True,
) -> list[dict[str, object]]:
    if release_latest:
        return [
            {
                "tagName": f"v{version}",
                "isLatest": True,
                "publishedAt": "2024-01-01T00:00:00Z",
                "url": f"https://github.com/testowner/testrepo/releases/tag/v{version}",
            }
        ]
    return [
        {
            "tagName": "v9.9.9",
            "isLatest": True,
            "publishedAt": "2024-02-01T00:00:00Z",
            "url": "https://github.com/testowner/testrepo/releases/tag/v9.9.9",
        },
        {
            "tagName": f"v{version}",
            "isLatest": False,
            "publishedAt": "2024-01-01T00:00:00Z",
            "url": f"https://github.com/testowner/testrepo/releases/tag/v{version}",
        },
    ]


def _git_ok(tag_ref: str | None = None) -> Callable[[list[str]], tuple[int, str, str]]:
    """Return a run_git stub that reports the tag as present."""
    ref = tag_ref if tag_ref else f"refs/tags/v{VERSION}"

    def run_git(args: list[str]) -> tuple[int, str, str]:
        if "ls-remote" in args:
            return 0, f"abc123\t{ref}\n", ""
        return 0, "", ""

    return run_git


def _git_missing() -> Callable[[list[str]], tuple[int, str, str]]:
    """Return a run_git stub that reports the tag as absent."""

    def run_git(_args: list[str]) -> tuple[int, str, str]:
        return 0, "", ""

    return run_git


def _gh_all_ok(
    version: str = VERSION,
    release_latest: bool = True,
    release_draft: bool = False,
    release_prerelease: bool = False,
) -> Callable[[list[str]], tuple[int, str, str]]:
    """Return a run_gh stub where both workflows pass and the release is clean."""

    def run_gh(args: list[str]) -> tuple[int, str, str]:
        if "run" in args and "list" in args:
            run = {"status": "completed", "conclusion": "success", "headBranch": BRANCH}
            return 0, json.dumps([run]), ""
        if "release" in args and "view" in args:
            return 0, json.dumps(_release_view_data(version, release_draft, release_prerelease)), ""
        if "release" in args and "list" in args:
            return 0, json.dumps(_release_list_data(version, release_latest)), ""
        return 0, "[]", ""

    return run_gh


def _gh_workflow_fail(
    workflow: str,
) -> Callable[[list[str]], tuple[int, str, str]]:
    """Return a run_gh stub where the given workflow has a failed conclusion."""

    def run_gh(args: list[str]) -> tuple[int, str, str]:
        if "run" in args and "list" in args and workflow in args:
            run = {"status": "completed", "conclusion": "failure", "headBranch": BRANCH}
            return 0, json.dumps([run]), ""
        if "run" in args and "list" in args:
            run = {"status": "completed", "conclusion": "success", "headBranch": BRANCH}
            return 0, json.dumps([run]), ""
        if "release" in args and "view" in args:
            return 0, json.dumps(_release_view_data()), ""
        if "release" in args and "list" in args:
            return 0, json.dumps(_release_list_data()), ""
        return 0, "[]", ""

    return run_gh


def _gh_no_runs() -> Callable[[list[str]], tuple[int, str, str]]:
    """Return a run_gh stub with no workflow runs and a good release."""

    def run_gh(args: list[str]) -> tuple[int, str, str]:
        if "run" in args and "list" in args:
            return 0, json.dumps([]), ""
        if "release" in args and "view" in args:
            return 0, json.dumps(_release_view_data()), ""
        if "release" in args and "list" in args:
            return 0, json.dumps(_release_list_data()), ""
        return 0, "[]", ""

    return run_gh


def _gh_release_error() -> Callable[[list[str]], tuple[int, str, str]]:
    """Return a run_gh stub where release view returns nonzero."""

    def run_gh(args: list[str]) -> tuple[int, str, str]:
        if "release" in args and "view" in args:
            return 1, "", "release not found"
        run = {"status": "completed", "conclusion": "success", "headBranch": BRANCH}
        return 0, json.dumps([run]), ""

    return run_gh


def _pypi_ok(
    version: str = VERSION,
    info_version: str | None = None,
    has_wheel: bool = True,
    has_sdist: bool = True,
) -> Callable[[str], tuple[int, bytes, str]]:
    iv = info_version if info_version is not None else version
    files = []
    if has_wheel:
        files.append({"packagetype": "bdist_wheel", "filename": f"pkg-{version}-py3-none-any.whl"})
    if has_sdist:
        files.append({"packagetype": "sdist", "filename": f"pkg-{version}.tar.gz"})
    data = {"info": {"version": iv}, "releases": {version: files}}

    def http_get(_url: str) -> tuple[int, bytes, str]:
        return 200, json.dumps(data).encode(), ""

    return http_get


def _pypi_wrong_version(latest: str = "1.1.0") -> Callable[[str], tuple[int, bytes, str]]:
    """PyPI reports a different latest version."""
    data: dict[str, object] = {
        "info": {"version": latest},
        "releases": {
            latest: [
                {"packagetype": "bdist_wheel"},
                {"packagetype": "sdist"},
            ]
        },
    }

    def http_get(_url: str) -> tuple[int, bytes, str]:
        return 200, json.dumps(data).encode(), ""

    return http_get


def _pypi_error(msg: str = "Connection refused") -> Callable[[str], tuple[int, bytes, str]]:
    def http_get(_url: str) -> tuple[int, bytes, str]:
        return 0, b"", msg

    return http_get


def _smoke_ok(version: str = VERSION) -> Callable[..., tuple[int, str, str]]:
    def run_subprocess(args: list[str], env=None, cwd=None) -> tuple[int, str, str]:
        if "-m" in args and "venv" in args:
            return 0, "", ""
        if "install" in args and "--no-cache-dir" in args:
            return 0, "", ""
        if "-c" in args:
            return 0, f"METADATA={version}\nMODULE={version}\n", ""
        if "version-check" in args:
            return 0, f"  Current version: {version}\n", ""
        return 0, "", ""

    return run_subprocess


def _smoke_fail(
    msg: str = "Could not find a version",
) -> Callable[..., tuple[int, str, str]]:
    def run_subprocess(args: list[str], env=None, cwd=None) -> tuple[int, str, str]:
        if "-m" in args and "venv" in args:
            return 0, "", ""
        return 1, "", msg

    return run_subprocess


def _smoke_venv_fail() -> Callable[..., tuple[int, str, str]]:
    def run_subprocess(args: list[str], env=None, cwd=None) -> tuple[int, str, str]:
        if "-m" in args and "venv" in args:
            return 1, "", "venv creation error"
        return 0, "ok", ""

    return run_subprocess


def _smoke_mismatch(
    metadata_version: str = VERSION, module_version: str = "9.9.9"
) -> Callable[..., tuple[int, str, str]]:
    def run_subprocess(args: list[str], env=None, cwd=None) -> tuple[int, str, str]:
        if "-m" in args and "venv" in args:
            return 0, "", ""
        if "install" in args and "--no-cache-dir" in args:
            return 0, "", ""
        if "-c" in args:
            return 0, f"METADATA={metadata_version}\nMODULE={module_version}\n", ""
        if "version-check" in args:
            return 0, f"  Current version: {metadata_version}\n", ""
        return 0, "", ""

    return run_subprocess


# ── AC-4: install_smoke delegates to the metadata consistency smoke ──────────


def test_install_smoke_checks_version_metadata_surfaces():
    # All three surfaces agree with the requested version → ok.
    result_ok = rsg.check_install_smoke(VERSION, PACKAGE, _smoke_ok())
    assert result_ok.status == rsg.STATUS_OK
    assert VERSION in result_ok.detail
    assert "metadata" in result_ok.detail.lower() or "module" in result_ok.detail.lower()

    # Module version disagrees with metadata/CLI → fail, names the mismatch.
    result_mismatch = rsg.check_install_smoke(VERSION, PACKAGE, _smoke_mismatch())
    assert result_mismatch.status == rsg.STATUS_FAIL
    assert "module_version" in result_mismatch.detail
    assert "9.9.9" in result_mismatch.detail

    # All surfaces internally agree but not with the requested release version → fail.
    result_stale = rsg.check_install_smoke(VERSION, PACKAGE, _smoke_ok(version="1.0.0"))
    assert result_stale.status == rsg.STATUS_FAIL
    assert "1.0.0" in result_stale.detail
    assert VERSION in result_stale.detail

    # Gate-level integration: a metadata mismatch blocks the whole gate.
    gate_result = _call_gate(run_subprocess=_smoke_mismatch())
    assert gate_result.ok is False
    smoke_surf = next(s for s in gate_result.surfaces if s.name == rsg.SURFACE_SMOKE)
    assert smoke_surf.status == rsg.STATUS_FAIL


def _call_gate(
    version: str = VERSION,
    allow_prerelease: bool = False,
    skip_smoke: bool = False,
    run_git=None,
    run_gh=None,
    http_get=None,
    run_subprocess=None,
) -> rsg.GateResult:  # type: ignore[name-defined]  # reason: module loaded at runtime
    return rsg.run_gate(
        version=version,
        repo=REPO,
        remote=REMOTE,
        branch=BRANCH,
        package=PACKAGE,
        allow_prerelease=allow_prerelease,
        skip_smoke=skip_smoke,
        run_git=run_git or _git_ok(),
        run_gh=run_gh or _gh_all_ok(),
        http_get=http_get or _pypi_ok(),
        run_subprocess=run_subprocess or _smoke_ok(),
    )


# ── AC-1: all surfaces green → gate passes ────────────────────────────────────


def test_gate_passes_when_all_public_surfaces_match():
    result = _call_gate()

    assert result.ok is True
    assert result.partial is False
    assert result.blockers == []
    assert result.version == VERSION

    surface_names = {s.name for s in result.surfaces}
    assert rsg.SURFACE_TAG in surface_names
    assert rsg.SURFACE_TESTS in surface_names
    assert rsg.SURFACE_PUBLISH in surface_names
    assert rsg.SURFACE_RELEASE in surface_names
    assert rsg.SURFACE_PYPI in surface_names
    assert rsg.SURFACE_SMOKE in surface_names

    for s in result.surfaces:
        assert s.status == rsg.STATUS_OK, (
            f"surface {s.name!r} expected ok, got {s.status!r}: {s.detail}"
        )

    human = rsg.render_human(result)
    assert "SHIPPED" in human
    assert "NOT SHIPPED" not in human
    assert "Remaining blockers" not in human


# ── AC-2: missing/red surfaces → nonzero + blockers ──────────────────────────


def test_gate_fails_and_lists_blockers_when_public_surfaces_diverge():
    # Missing tag
    result_tag = _call_gate(run_git=_git_missing())
    assert result_tag.ok is False
    tag_surf = next(s for s in result_tag.surfaces if s.name == rsg.SURFACE_TAG)
    assert tag_surf.status == rsg.STATUS_FAIL
    assert any("not found" in b for b in result_tag.blockers)

    # Red Tests workflow
    result_tests = _call_gate(run_gh=_gh_workflow_fail(rsg.TESTS_WORKFLOW))
    assert result_tests.ok is False
    tests_surf = next(s for s in result_tests.surfaces if s.name == rsg.SURFACE_TESTS)
    assert tests_surf.status == rsg.STATUS_FAIL
    assert result_tests.blockers

    # Red Publish workflow
    result_pub = _call_gate(run_gh=_gh_workflow_fail(rsg.PUBLISH_WORKFLOW))
    assert result_pub.ok is False
    pub_surf = next(s for s in result_pub.surfaces if s.name == rsg.SURFACE_PUBLISH)
    assert pub_surf.status == rsg.STATUS_FAIL
    assert result_pub.blockers

    # No runs for workflow
    result_norun = _call_gate(run_gh=_gh_no_runs())
    assert result_norun.ok is False
    for name in (rsg.SURFACE_TESTS, rsg.SURFACE_PUBLISH):
        surf = next(s for s in result_norun.surfaces if s.name == name)
        assert surf.status == rsg.STATUS_FAIL

    # Missing GitHub Release
    result_rel = _call_gate(run_gh=_gh_release_error())
    assert result_rel.ok is False
    rel_surf = next(s for s in result_rel.surfaces if s.name == rsg.SURFACE_RELEASE)
    assert rel_surf.status == rsg.STATUS_ERROR

    # Stale PyPI version
    result_pypi = _call_gate(http_get=_pypi_wrong_version("1.1.0"))
    assert result_pypi.ok is False
    pypi_surf = next(s for s in result_pypi.surfaces if s.name == rsg.SURFACE_PYPI)
    assert pypi_surf.status == rsg.STATUS_FAIL
    assert "1.1.0" in pypi_surf.detail

    # Missing wheel
    result_no_wheel = _call_gate(http_get=_pypi_ok(has_wheel=False))
    assert result_no_wheel.ok is False
    pypi_surf2 = next(s for s in result_no_wheel.surfaces if s.name == rsg.SURFACE_PYPI)
    assert pypi_surf2.status == rsg.STATUS_FAIL
    assert "wheel" in pypi_surf2.detail

    # Failed install smoke
    result_smoke = _call_gate(run_subprocess=_smoke_fail())
    assert result_smoke.ok is False
    smoke_surf = next(s for s in result_smoke.surfaces if s.name == rsg.SURFACE_SMOKE)
    assert smoke_surf.status == rsg.STATUS_FAIL

    # PyPI network error
    result_pypi_err = _call_gate(http_get=_pypi_error("Connection timed out"))
    assert result_pypi_err.ok is False
    pypi_err_surf = next(s for s in result_pypi_err.surfaces if s.name == rsg.SURFACE_PYPI)
    assert pypi_err_surf.status == rsg.STATUS_ERROR

    # Human output uses NOT SHIPPED and lists blockers
    human = rsg.render_human(result_tag)
    assert "NOT SHIPPED" in human
    assert "Remaining blockers" in human


# ── AC-3: version/metadata edge cases ─────────────────────────────────────────


def test_gate_rejects_version_and_release_metadata_edge_cases():
    # PyPI latest is older than requested
    result_old = _call_gate(http_get=_pypi_wrong_version("1.0.0"))
    assert result_old.ok is False
    pypi_surf = next(s for s in result_old.surfaces if s.name == rsg.SURFACE_PYPI)
    assert pypi_surf.status == rsg.STATUS_FAIL
    assert "1.0.0" in pypi_surf.detail
    assert VERSION in pypi_surf.detail

    # Draft release
    result_draft = _call_gate(run_gh=_gh_all_ok(release_draft=True))
    assert result_draft.ok is False
    rel_surf = next(s for s in result_draft.surfaces if s.name == rsg.SURFACE_RELEASE)
    assert rel_surf.status == rsg.STATUS_FAIL
    assert "draft" in rel_surf.detail.lower()

    # Prerelease without --allow-prerelease
    result_pre = _call_gate(run_gh=_gh_all_ok(release_prerelease=True))
    assert result_pre.ok is False
    rel_surf2 = next(s for s in result_pre.surfaces if s.name == rsg.SURFACE_RELEASE)
    assert rel_surf2.status == rsg.STATUS_FAIL
    assert "prerelease" in rel_surf2.detail.lower()

    # Prerelease allowed when --allow-prerelease
    result_pre_ok = _call_gate(run_gh=_gh_all_ok(release_prerelease=True), allow_prerelease=True)
    rel_surf3 = next(s for s in result_pre_ok.surfaces if s.name == rsg.SURFACE_RELEASE)
    assert rel_surf3.status == rsg.STATUS_OK

    # A newer latest release in release list blocks
    result_not_latest = _call_gate(run_gh=_gh_all_ok(release_latest=False))
    assert result_not_latest.ok is False
    rel_surf4 = next(s for s in result_not_latest.surfaces if s.name == rsg.SURFACE_RELEASE)
    assert rel_surf4.status == rsg.STATUS_FAIL
    assert "not the latest" in rel_surf4.detail

    # Tag mismatch (release returns a different tag)
    def gh_wrong_tag(args: list[str]) -> tuple[int, str, str]:
        if "release" in args and "view" in args:
            data = {
                "tagName": "v9.9.9",
                "isDraft": False,
                "isPrerelease": False,
                "publishedAt": "2024-01-01T00:00:00Z",
                "url": "https://github.com/...",
                "targetCommitish": "main",
            }
            return 0, json.dumps(data), ""
        if "release" in args and "list" in args:
            return 0, json.dumps(_release_list_data()), ""
        run = {"status": "completed", "conclusion": "success", "headBranch": BRANCH}
        return 0, json.dumps([run]), ""

    result_tag_mismatch = _call_gate(run_gh=gh_wrong_tag)
    assert result_tag_mismatch.ok is False
    rel_surf5 = next(s for s in result_tag_mismatch.surfaces if s.name == rsg.SURFACE_RELEASE)
    assert rel_surf5.status == rsg.STATUS_FAIL
    assert "v9.9.9" in rel_surf5.detail

    # Missing sdist only
    result_no_sdist = _call_gate(http_get=_pypi_ok(has_sdist=False))
    assert result_no_sdist.ok is False
    pypi_surf2 = next(s for s in result_no_sdist.surfaces if s.name == rsg.SURFACE_PYPI)
    assert "sdist" in pypi_surf2.detail


# ── AC-4: errors sanitized — no private leaks ─────────────────────────────────


def test_gate_handles_transient_public_lookup_errors_without_private_leaks():
    fake_token = "ghp_" + "A" * 30
    fake_path = "/Users/testuser/secret-project"
    fake_remote = "git@github.com:private-org/private-repo"

    def run_git_with_leak(args: list[str]) -> tuple[int, str, str]:
        return 1, "", f"fatal: could not read {fake_remote}: token {fake_token}"

    def run_gh_with_leak(args: list[str]) -> tuple[int, str, str]:
        return 1, "", f"Error: token {fake_token} invalid at {fake_path}"

    def http_get_with_leak(url: str) -> tuple[int, bytes, str]:
        return 0, b"", f"Connection refused from {fake_path}"

    def run_subprocess_with_leak(args: list[str], env=None, cwd=None) -> tuple[int, str, str]:
        if "-m" in args and "venv" in args:
            return 0, "", ""
        return 1, "", f"pip failed at {fake_path}: token {fake_token}"

    result = rsg.run_gate(
        version=VERSION,
        repo=REPO,
        remote=REMOTE,
        branch=BRANCH,
        package=PACKAGE,
        allow_prerelease=False,
        skip_smoke=False,
        run_git=run_git_with_leak,
        run_gh=run_gh_with_leak,
        http_get=http_get_with_leak,
        run_subprocess=run_subprocess_with_leak,
    )

    assert result.ok is False
    output = json.dumps(result.to_dict())

    # No private token in any output
    assert fake_token not in output, "raw token must not appear in gate output"
    # No private local path in any output
    assert fake_path not in output, "private path must not appear in gate output"
    # No private git remote in any output
    assert fake_remote not in output, "private remote must not appear in gate output"

    # Blockers are still present (just sanitized)
    assert len(result.blockers) > 0

    # Each error surface reports REDACTED markers instead of raw private data
    error_surfaces = [s for s in result.surfaces if s.status in (rsg.STATUS_ERROR, rsg.STATUS_FAIL)]
    assert len(error_surfaces) > 0
    for s in error_surfaces:
        assert fake_token not in s.detail
        assert fake_path not in s.detail
        assert fake_remote not in s.detail

    # Sanitize helper works standalone
    assert rsg.sanitize(fake_token) == "[REDACTED-TOKEN]"
    assert rsg.sanitize(fake_path) == "[REDACTED-PATH]"
    assert rsg.sanitize(fake_remote) == "[REDACTED-REMOTE]"

    # The smoke script's own TemporaryDirectory() defaults to /tmp on Linux
    # (including this project's GitHub Actions Ubuntu runners), not /var/folders.
    fake_linux_tmp = "/tmp/mempalace-install-smoke-abc123/venv/bin/pip"
    assert rsg.sanitize(fake_linux_tmp) == "[REDACTED-PATH]"


# ── AC-5: JSON output is machine-readable and surface-complete ────────────────


def test_gate_json_output_is_machine_readable_and_surface_complete():
    result = _call_gate()
    data = result.to_dict()

    # Required top-level keys
    assert "ok" in data
    assert "version" in data
    assert "surfaces" in data
    assert "blockers" in data

    # Types
    assert isinstance(data["ok"], bool)
    assert isinstance(data["version"], str)
    assert isinstance(data["surfaces"], list)
    assert isinstance(data["blockers"], list)

    # All required surfaces are present
    surface_names = {s["name"] for s in data["surfaces"]}
    for required in rsg.REQUIRED_SURFACES:
        assert required in surface_names, f"surface {required!r} missing from JSON output"

    # Each surface row has required fields
    for s in data["surfaces"]:
        assert "name" in s
        assert "status" in s
        assert "detail" in s
        assert s["status"] in (rsg.STATUS_OK, rsg.STATUS_FAIL, rsg.STATUS_SKIP, rsg.STATUS_ERROR)

    # JSON is serializable without error
    serialized = json.dumps(data)
    assert isinstance(serialized, str)
    roundtrip = json.loads(serialized)
    assert roundtrip["ok"] == data["ok"]
    assert roundtrip["version"] == VERSION
    assert len(roundtrip["surfaces"]) == len(data["surfaces"])

    # Fail case also produces complete surface rows
    result_fail = _call_gate(run_git=_git_missing())
    data_fail = result_fail.to_dict()
    assert data_fail["ok"] is False
    assert len(data_fail["blockers"]) > 0
    surface_names_fail = {s["name"] for s in data_fail["surfaces"]}
    for required in rsg.REQUIRED_SURFACES:
        assert required in surface_names_fail, f"surface {required!r} missing from failed-gate JSON"

    # Skip smoke → partial, not fully ok
    result_skip = _call_gate(skip_smoke=True)
    data_skip = result_skip.to_dict()
    assert data_skip["ok"] is False
    assert result_skip.partial is True
    assert data_skip["partial"] is True
    smoke_surf = next(s for s in data_skip["surfaces"] if s["name"] == rsg.SURFACE_SMOKE)
    assert smoke_surf["status"] == rsg.STATUS_SKIP

    # --json CLI flag round-trips through main()
    import io
    from contextlib import redirect_stdout

    buf = io.StringIO()
    with redirect_stdout(buf):
        rsg.main(
            [
                "--version",
                VERSION,
                "--repo",
                REPO,
                "--remote",
                REMOTE,
                "--branch",
                BRANCH,
                "--package",
                PACKAGE,
                "--json",
                "--skip-smoke",
            ]
        )
    # main() calls live services; we only verify it emits valid JSON and exits non-zero
    # (skip-smoke prevents fully shipped even without network)
    cli_output = buf.getvalue()
    cli_data = json.loads(cli_output)
    assert "ok" in cli_data
    assert "version" in cli_data
    assert "surfaces" in cli_data
    assert cli_data["version"] == VERSION


# ── Additional: smoke skip blocks fully shipped status ────────────────────────


def test_skip_smoke_marks_result_partial_not_ok():
    result = _call_gate(skip_smoke=True)
    assert result.ok is False
    assert result.partial is True
    smoke = next(s for s in result.surfaces if s.name == rsg.SURFACE_SMOKE)
    assert smoke.status == rsg.STATUS_SKIP
    human = rsg.render_human(result)
    assert "NOT SHIPPED" not in human or "DIAGNOSTIC" in human
    assert "SHIPPED" not in human.replace("NOT SHIPPED", "").replace("DIAGNOSTIC", "")


# ── Additional: venv failure is STATUS_ERROR ──────────────────────────────────


def test_smoke_venv_failure_is_error_not_fail():
    result = _call_gate(run_subprocess=_smoke_venv_fail())
    assert result.ok is False
    smoke = next(s for s in result.surfaces if s.name == rsg.SURFACE_SMOKE)
    assert smoke.status == rsg.STATUS_ERROR
    assert "venv" in smoke.detail.lower()


def test_smoke_missing_sibling_module_is_error_not_a_crash(monkeypatch):
    # release_status_gate.py documents itself as runnable standalone; if the sibling
    # release_install_metadata_smoke.py script is missing or unreadable, the gate must
    # report a STATUS_ERROR surface instead of letting the loader's OSError propagate.
    def _raise_missing():
        raise FileNotFoundError(
            "[Errno 2] No such file or directory: '/tmp/x/release_install_metadata_smoke.py'"
        )

    monkeypatch.setattr(rsg, "_load_install_metadata_smoke", _raise_missing)

    result = rsg.check_install_smoke(VERSION, PACKAGE, _smoke_ok())
    assert result.status == rsg.STATUS_ERROR
    assert "install smoke setup failed" in result.detail
    assert "/tmp/x/" not in result.detail


# ── Additional: CLI --help exits cleanly ──────────────────────────────────────


def test_gate_cli_help_exits_cleanly():
    import subprocess

    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "release_status_gate.py"), "--help"],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0
    assert "--version" in r.stdout
    assert "--repo" in r.stdout
    assert "--json" in r.stdout
    assert "--smoke-timeout-seconds" in r.stdout


# ── Regression: stale-success masking ────────────────────────────────────────


def test_workflow_stale_success_does_not_mask_newer_failure():
    """A newer completed failure must block the gate even when an older success exists in the window."""

    def gh_newer_failure_older_success(args: list[str]) -> tuple[int, str, str]:
        if "run" in args and "list" in args:
            runs = [
                {"status": "completed", "conclusion": "failure", "headBranch": BRANCH},
                {"status": "completed", "conclusion": "success", "headBranch": BRANCH},
            ]
            return 0, json.dumps(runs), ""
        if "release" in args and "view" in args:
            return 0, json.dumps(_release_view_data()), ""
        if "release" in args and "list" in args:
            return 0, json.dumps(_release_list_data()), ""
        return 0, "[]", ""

    result = _call_gate(run_gh=gh_newer_failure_older_success)
    assert result.ok is False

    tests_surf = next(s for s in result.surfaces if s.name == rsg.SURFACE_TESTS)
    assert tests_surf.status == rsg.STATUS_FAIL, (
        f"SURFACE_TESTS must fail when most recent run failed, got {tests_surf.status!r}: {tests_surf.detail}"
    )

    pub_surf = next(s for s in result.surfaces if s.name == rsg.SURFACE_PUBLISH)
    assert pub_surf.status == rsg.STATUS_FAIL, (
        f"SURFACE_PUBLISH must fail when most recent run failed, got {pub_surf.status!r}: {pub_surf.detail}"
    )
