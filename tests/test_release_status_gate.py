"""Tests for scripts/release_status_gate.py.

Covers: all-green gate, surface blockers, version/metadata edge cases,
sanitized error output, and machine-readable JSON output.

All seams (run_git, run_gh, http_get, run_subprocess) are mocked so no live
GitHub, PyPI, or pip network calls are made.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

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
SHA = "a" * 40
PUBLISH_RUN_ID = 4242
RELEASE_JOB_ID = 4343

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


def _branch_rules_payload(
    rule_types: tuple[str, ...] | None = None,
    contexts: tuple[str, ...] = ("release-required",),
) -> list[dict[str, object]]:
    """Shape of GET /repos/{repo}/rules/branches/{branch}: effective rules."""
    if rule_types is None:
        rule_types = ("deletion", "non_fast_forward", "required_status_checks")
    rules: list[dict[str, object]] = [
        {"type": rule_type} for rule_type in rule_types if rule_type != "required_status_checks"
    ]
    if "required_status_checks" in rule_types:
        rules.append(
            {
                "type": "required_status_checks",
                "parameters": {
                    "required_status_checks": [{"context": context} for context in contexts]
                },
            }
        )
    return rules


def _tag_ruleset_summaries() -> list[dict[str, object]]:
    """Shape of GET /repos/{repo}/rulesets: summaries carry no rules/conditions."""
    return [
        {"id": 11, "name": "public-v-tags-restricted", "target": "tag", "enforcement": "active"}
    ]


def _tag_ruleset_detail() -> dict[str, object]:
    """Shape of GET /repos/{repo}/rulesets/{id}: full rules and conditions."""
    return {
        "id": 11,
        "name": "public-v-tags-restricted",
        "target": "tag",
        "enforcement": "active",
        "conditions": {"ref_name": {"include": ["refs/tags/v*"], "exclude": []}},
        "rules": [{"type": "creation"}, {"type": "update"}, {"type": "deletion"}],
        "bypass_actors": [{"actor_type": "RepositoryRole", "bypass_mode": "always"}],
    }


def _fresh_audit_run() -> dict[str, object]:
    """A successful Dependency Audit run stamped relative to now, never to a date.

    A hardcoded date would silently age past the freshness window and turn this
    fixture into a time bomb.
    """
    stamp = datetime.now(UTC) - timedelta(hours=1)
    return {
        "status": "completed",
        "conclusion": "success",
        "event": "schedule",
        "updatedAt": stamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def _git_ok(tag_ref: str | None = None) -> Callable[[list[str]], tuple[int, str, str]]:
    """Return a run_git stub that reports the tag as present."""
    ref = tag_ref if tag_ref else f"refs/tags/v{VERSION}"

    def run_git(args: list[str]) -> tuple[int, str, str]:
        if args[:3] == ["ls-remote", "--tags", "--refs"]:
            return 0, f"{SHA}\t{ref}\n", ""
        if args[:2] == ["ls-remote", "--tags"]:
            return 0, f"{SHA}\t{ref}\n", ""
        return 0, "", ""

    return run_git


def _git_annotated_tag(peeled_sha: str) -> Callable[[list[str]], tuple[int, str, str]]:
    """run_git stub for an annotated tag whose tag object differs from its commit.

    `ls-remote --tags <remote> <ref> <ref>^{}` reports both lines; only the peeled
    one is the published commit. `--refs` suppresses peeled refs, matching git.
    """
    ref = f"refs/tags/v{VERSION}"
    tag_object_sha = "c" * 40

    def run_git(args: list[str]) -> tuple[int, str, str]:
        if args[:3] == ["ls-remote", "--tags", "--refs"]:
            return 0, f"{tag_object_sha}\t{ref}\n", ""
        if args[:2] == ["ls-remote", "--tags"]:
            return 0, f"{tag_object_sha}\t{ref}\n{peeled_sha}\t{ref}^{{}}\n", ""
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
        if args and args[0] == "api" and "check-runs" in args[1]:
            data = {
                "check_runs": [
                    {
                        "name": "release-required",
                        "head_sha": SHA,
                        "status": "completed",
                        "conclusion": "success",
                    }
                ]
            }
            return 0, json.dumps(data), ""
        if args and args[0] == "api" and "/rules/branches/" in args[1]:
            return 0, json.dumps(_branch_rules_payload()), ""
        if args and args[0] == "api" and "/rulesets/" in args[1]:
            return 0, json.dumps(_tag_ruleset_detail()), ""
        if args and args[0] == "api" and "/rulesets" in args[1]:
            return 0, json.dumps(_tag_ruleset_summaries()), ""
        if "run" in args and "list" in args:
            if "Dependency Audit" in args:
                return 0, json.dumps([_fresh_audit_run()]), ""
            run = {
                "status": "completed",
                "conclusion": "success",
                "headBranch": f"v{version}" if rsg.PUBLISH_WORKFLOW in args else BRANCH,
                "headSha": SHA,
                "event": "push",
                "databaseId": PUBLISH_RUN_ID,
                "createdAt": "2026-01-01T00:00:00Z",
            }
            return 0, json.dumps([run]), ""
        if "run" in args and "view" in args:
            jobs = [
                {
                    "name": name,
                    "status": "completed",
                    "conclusion": "success",
                    "databaseId": job_id,
                }
                for name, job_id in (
                    ("build", 4141),
                    ("publish", 4242),
                    ("github-release", RELEASE_JOB_ID),
                )
            ]
            return 0, json.dumps({"jobs": jobs}), ""
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
            run = {
                "status": "completed",
                "conclusion": "failure",
                "headBranch": BRANCH,
                "headSha": SHA,
            }
            return 0, json.dumps([run]), ""
        return _gh_all_ok()(args)

    return run_gh


def _gh_no_runs() -> Callable[[list[str]], tuple[int, str, str]]:
    """Return a run_gh stub with no workflow runs and a good release."""

    def run_gh(args: list[str]) -> tuple[int, str, str]:
        if "run" in args and "list" in args:
            if "Dependency Audit" in args:
                return _gh_all_ok()(args)
            return 0, json.dumps([]), ""
        return _gh_all_ok()(args)

    return run_gh


def _gh_release_error() -> Callable[[list[str]], tuple[int, str, str]]:
    """Return a run_gh stub where release view returns nonzero."""

    def run_gh(args: list[str]) -> tuple[int, str, str]:
        if "release" in args and "view" in args:
            return 1, "", "release not found"
        return _gh_all_ok()(args)

    return run_gh


def _gh_partial_publication(
    *,
    release_status: str = "failure",
    publish_status: str = "success",
    run_status: str = "completed",
    duplicate_release_job: bool = False,
) -> Callable[[list[str]], tuple[int, str, str]]:
    """Exact tag run where PyPI succeeded and GitHub Release did not."""

    def run_gh(args: list[str]) -> tuple[int, str, str]:
        if "run" in args and "list" in args and rsg.PUBLISH_WORKFLOW in args:
            run = {
                "status": run_status,
                "conclusion": "failure" if release_status == "failure" else "success",
                "headBranch": f"v{VERSION}",
                "headSha": SHA,
                "event": "push",
                "databaseId": PUBLISH_RUN_ID,
                "createdAt": "2026-02-01T00:00:00Z",
            }
            return 0, json.dumps([run]), ""
        if "run" in args and "view" in args:
            jobs = [
                {
                    "name": "github-release",
                    "status": "completed",
                    "conclusion": release_status,
                    "databaseId": RELEASE_JOB_ID,
                },
                {
                    "name": "build",
                    "status": "completed",
                    "conclusion": "success",
                    "databaseId": 4141,
                },
                {
                    "name": "publish",
                    "status": "completed",
                    "conclusion": publish_status,
                    "databaseId": 4242,
                },
            ]
            if duplicate_release_job:
                jobs.append(dict(jobs[0], databaseId=9999))
            return 0, json.dumps({"jobs": jobs}), ""
        if "release" in args and "view" in args:
            return 1, "", "release not found"
        if "release" in args and "list" in args:
            return 0, "[]", ""
        return _gh_all_ok()(args)

    return run_gh


def _pypi_ok(
    version: str = VERSION,
    info_version: str | None = None,
    has_wheel: bool = True,
    has_sdist: bool = True,
    extra_wheel: bool = False,
    provenance_repository: str = REPO,
    provenance_workflow: str = "publish.yml",
    provenance_environment: str | None = "release",
) -> Callable[[str], tuple[int, bytes, str]]:
    iv = info_version if info_version is not None else version
    files: list[dict[str, object]] = []

    def add_file(filename: str, package_type: str) -> None:
        content = filename.encode()
        files.append(
            {
                "packagetype": package_type,
                "filename": filename,
                "digests": {"sha256": hashlib.sha256(content).hexdigest()},
                "url": f"https://files.pythonhosted.org/packages/test/{filename}",
            }
        )

    if has_wheel:
        add_file(f"pkg-{version}-py3-none-any.whl", "bdist_wheel")
    if extra_wheel:
        add_file(f"pkg-{version}-py3-none-manylinux_x86_64.whl", "bdist_wheel")
    if has_sdist:
        add_file(f"pkg-{version}.tar.gz", "sdist")
    data = {"info": {"version": iv}, "releases": {version: files}}
    provenance = {
        "version": 1,
        "attestation_bundles": [
            {
                "publisher": {
                    "kind": "GitHub",
                    "repository": provenance_repository,
                    "workflow": provenance_workflow,
                    "environment": provenance_environment,
                },
                "attestations": [{"version": 1}],
            }
        ],
    }

    def http_get(url: str) -> tuple[int, bytes, str]:
        if url == rsg.PYPI_JSON_URL.format(package=PACKAGE):
            return 200, json.dumps(data).encode(), ""
        if url.startswith("https://files.pythonhosted.org/"):
            return 200, Path(url).name.encode(), ""
        if url.startswith("https://pypi.org/integrity/"):
            return 200, json.dumps(provenance).encode(), ""
        return 404, b"", "not found"

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


_AGENT_PLUGIN_FIXTURE_ROOT: Path | None = None


def _write_agent_plugin_fixture(plugin_root: Path) -> None:
    (plugin_root / "skills" / "mempalace").mkdir(parents=True)
    (plugin_root / "schemas" / "1.0.0").mkdir(parents=True)
    (plugin_root / "plugin.json").write_text(
        json.dumps(
            {
                "$schema": "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json",
                "name": "mempalace-code",
                "version": VERSION,
            }
        ),
        encoding="utf-8",
    )
    (plugin_root / "mcp.json").write_text(
        json.dumps(
            {
                "$schema": "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json",
                "mcpServers": {
                    "mempalace-code": {
                        "type": "stdio",
                        "command": "mempalace-code-mcp",
                        "args": ["--profile=minimal"],
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    (plugin_root / "skills" / "mempalace" / "SKILL.md").write_text(
        "---\nname: mempalace\ndescription: Minimal memory.\n---\n", encoding="utf-8"
    )
    (plugin_root / "schemas" / "1.0.0" / "plugin.schema.json").write_text(
        json.dumps({"$id": "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"}),
        encoding="utf-8",
    )
    (plugin_root / "schemas" / "1.0.0" / "mcp.schema.json").write_text(
        json.dumps({"$id": "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json"}),
        encoding="utf-8",
    )
    (plugin_root / "schemas" / "SCHEMA-NOTICE.md").write_text(
        "Apache License 2.0\n", encoding="utf-8"
    )


def _agent_plugin_fixture_root() -> Path:
    if _AGENT_PLUGIN_FIXTURE_ROOT is None:
        raise RuntimeError(
            "_agent_plugin_fixture_root() called outside a test — the "
            "_agent_plugin_fixture_root_cache autouse fixture must be active"
        )
    return _AGENT_PLUGIN_FIXTURE_ROOT


@pytest.fixture(scope="module", autouse=True)
def _agent_plugin_fixture_root_cache(tmp_path_factory: pytest.TempPathFactory):
    """Populate the module-cached fixture root under pytest-owned tmp_path_factory storage.

    Replaces a raw tempfile.mkdtemp() that was never cleaned up: pytest prunes
    tmp_path_factory's base temp directory across sessions, so this stays isolated
    per test run without leaking directories on disk.
    """
    global _AGENT_PLUGIN_FIXTURE_ROOT
    root = tmp_path_factory.mktemp("agent-plugin-fixture") / "agent_plugin"
    _write_agent_plugin_fixture(root)
    _AGENT_PLUGIN_FIXTURE_ROOT = root
    try:
        yield
    finally:
        _AGENT_PLUGIN_FIXTURE_ROOT = None


def _agent_plugin_mcp_responses() -> str:
    tools = [
        {"name": name}
        for name in (
            "mempalace_status",
            "mempalace_search",
            "mempalace_check_duplicate",
            "mempalace_add_drawer",
        )
    ]
    responses = [
        {"jsonrpc": "2.0", "id": 1, "result": {"serverInfo": {"name": "mempalace-code"}}},
        {"jsonrpc": "2.0", "id": 2, "result": {"tools": tools}},
    ]
    return "\n".join(json.dumps(r) for r in responses) + "\n"


def _alias_probe_response(args: list[str], version: str) -> tuple[int, str, str] | None:
    if args and Path(args[0]).name == "mempalace-code-alias":
        alias_dir = Path(args[0]).parent
        (alias_dir / "mempalace").symlink_to(alias_dir / "mempalace-code")
        return 0, "Alias ready\n", ""
    if "install-alias" in args:
        alias_dir = (
            Path(args[args.index("--target-dir") + 1])
            if "--target-dir" in args
            else Path(args[0]).parent
        )
        alias_path = alias_dir / "mempalace"
        alias_path.symlink_to(Path(args[0]))
        return 0, "Alias ready\n", ""
    if args and Path(args[0]).name == "mempalace" and "version-check" in args:
        return 0, f"  Current version: {version}\n", ""
    return None


def _smoke_ok(
    version: str = VERSION, *, include_alias: bool = True
) -> Callable[..., tuple[int, str, str]]:
    def run_subprocess(
        args: list[str], env=None, cwd=None, input_text=None, timeout_seconds=None
    ) -> tuple[int, str, str]:
        if include_alias:
            alias_response = _alias_probe_response(args, version)
            if alias_response is not None:
                return alias_response
        if "-m" in args and "venv" in args:
            return 0, "", ""
        if "install" in args and "--no-cache-dir" in args:
            return 0, "", ""
        if "agent-plugin" in args and "path" in args:
            return 0, json.dumps({"path": str(_agent_plugin_fixture_root())}), ""
        if args and args[0] == "mempalace-code-mcp":
            return 0, _agent_plugin_mcp_responses(), ""
        if args and Path(args[0]).name == "pypi-attestations":
            return 0, "", f"OK: {args[3]}\n"
        if "-c" in args:
            if any("RUNTIME-NO-CHROMADB" in str(a) for a in args):
                return 0, "usage: mempalace-code\nmigrate-storage\nRUNTIME-NO-CHROMADB=ok\n", ""
            return 0, f"METADATA={version}\nMODULE={version}\n", ""
        if "version-check" in args:
            return 0, f"  Current version: {version}\n", ""
        return 0, "", ""

    return run_subprocess


def _smoke_fail(
    msg: str = "Could not find a version",
) -> Callable[..., tuple[int, str, str]]:
    def run_subprocess(
        args: list[str], env=None, cwd=None, input_text=None, timeout_seconds=None
    ) -> tuple[int, str, str]:
        if "-m" in args and "venv" in args:
            return 0, "", ""
        return 1, "", msg

    return run_subprocess


def _smoke_venv_fail() -> Callable[..., tuple[int, str, str]]:
    def run_subprocess(
        args: list[str], env=None, cwd=None, input_text=None, timeout_seconds=None
    ) -> tuple[int, str, str]:
        if "-m" in args and "venv" in args:
            return 1, "", "venv creation error"
        return 0, "ok", ""

    return run_subprocess


def _smoke_mismatch(
    metadata_version: str = VERSION, module_version: str = "9.9.9"
) -> Callable[..., tuple[int, str, str]]:
    def run_subprocess(
        args: list[str], env=None, cwd=None, input_text=None, timeout_seconds=None
    ) -> tuple[int, str, str]:
        alias_response = _alias_probe_response(args, metadata_version)
        if alias_response is not None:
            return alias_response
        if "-m" in args and "venv" in args:
            return 0, "", ""
        if "install" in args and "--no-cache-dir" in args:
            return 0, "", ""
        if "agent-plugin" in args and "path" in args:
            return 0, json.dumps({"path": str(_agent_plugin_fixture_root())}), ""
        if args and args[0] == "mempalace-code-mcp":
            return 0, _agent_plugin_mcp_responses(), ""
        if args and Path(args[0]).name == "pypi-attestations":
            return 0, "", f"OK: {args[3]}\n"
        if "-c" in args:
            if any("RUNTIME-NO-CHROMADB" in str(a) for a in args):
                return 0, "usage: mempalace-code\nmigrate-storage\nRUNTIME-NO-CHROMADB=ok\n", ""
            return 0, f"METADATA={metadata_version}\nMODULE={module_version}\n", ""
        if "version-check" in args:
            return 0, f"  Current version: {metadata_version}\n", ""
        return 0, "", ""

    return run_subprocess


# ── AC-4: install_smoke delegates to the metadata consistency smoke ──────────


def test_install_smoke_checks_version_metadata_surfaces():
    # All versioned surfaces agree with the requested version and alias provenance → ok.
    result_ok = rsg.check_install_smoke(VERSION, PACKAGE, _smoke_ok())
    assert result_ok.status == rsg.STATUS_OK
    assert VERSION in result_ok.detail
    assert "metadata" in result_ok.detail.lower() or "module" in result_ok.detail.lower()
    assert "alias provenance" in result_ok.detail

    result_missing_alias = rsg.check_install_smoke(VERSION, PACKAGE, _smoke_ok(include_alias=False))
    assert result_missing_alias.status == rsg.STATUS_FAIL
    assert "alias_provenance" in result_missing_alias.detail

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
    expect_sha: str | None = SHA,
    run_git=None,
    run_gh=None,
    http_get=None,
    run_subprocess=None,
    repo: str = REPO,
) -> rsg.GateResult:  # type: ignore[name-defined]  # reason: module loaded at runtime
    return rsg.run_gate(
        version=version,
        repo=repo,
        remote=REMOTE,
        branch=BRANCH,
        package=PACKAGE,
        allow_prerelease=allow_prerelease,
        skip_smoke=skip_smoke,
        expect_sha=expect_sha,
        required_check_name="release-required",
        audit_max_age_hours=168,
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
    assert rsg.SURFACE_PYPI_PROVENANCE in surface_names
    assert rsg.SURFACE_SMOKE in surface_names

    for s in result.surfaces:
        assert s.status == rsg.STATUS_OK, (
            f"surface {s.name!r} expected ok, got {s.status!r}: {s.detail}"
        )

    human = rsg.render_human(result)
    assert "SHIPPED" in human
    assert "NOT SHIPPED" not in human
    assert "Remaining blockers" not in human


def test_provenance_verifies_every_exact_version_file_with_locked_uv_environment():
    http_get = _pypi_ok(extra_wheel=True)
    distributions, inventory = rsg.fetch_pypi_distributions(VERSION, PACKAGE, http_get)
    assert inventory.status == rsg.STATUS_OK
    assert distributions is not None
    commands: list[tuple[list[str], dict | None, str | None]] = []
    delegate = _smoke_ok()

    def recording_subprocess(args: list[str], env=None, cwd=None):
        commands.append((args, env, cwd))
        return delegate(args, env=env, cwd=cwd)

    result = rsg.check_pypi_provenance(
        VERSION, PACKAGE, REPO, distributions, http_get, recording_subprocess
    )

    assert result.status == rsg.STATUS_OK
    assert "verified 3 files" in result.detail
    assert REPO in result.detail
    assert rsg.EXPECTED_PROVENANCE_WORKFLOW in result.detail
    assert rsg.EXPECTED_PROVENANCE_ENVIRONMENT in result.detail
    lock_check = next(command for command in commands if command[0][:2] == ["uv", "lock"])
    assert lock_check[0] == ["uv", "lock", "--check"]
    sync = next(command for command in commands if command[0][:2] == ["uv", "sync"])
    assert "--frozen" in sync[0]
    assert "--locked" not in sync[0]
    assert sync[0][sync[0].index("--only-group") + 1] == "dev"
    assert "--no-install-project" in sync[0]
    assert sync[1] is not None
    assert sync[1]["VIRTUAL_ENV"]
    verifier_calls = [
        command for command in commands if Path(command[0][0]).name == "pypi-attestations"
    ]
    assert [Path(command[0][3]).name for command in verifier_calls] == [
        distribution.filename for distribution in distributions
    ]
    assert all(command[0][-1] == f"https://github.com/{REPO}" for command in verifier_calls)


@pytest.mark.parametrize(
    ("repository", "workflow", "environment"),
    [
        ("someone/else", "publish.yml", "release"),
        (REPO, "other.yml", "release"),
        (REPO, "publish.yml", "unexpected"),
        (REPO, "publish.yml", None),
    ],
    ids=[
        "repository-mismatch",
        "workflow-mismatch",
        "environment-mismatch",
        "environment-missing",
    ],
)
def test_provenance_rejects_unexpected_publisher_identity(
    repository: str, workflow: str, environment: str | None
):
    result = _call_gate(
        http_get=_pypi_ok(
            provenance_repository=repository,
            provenance_workflow=workflow,
            provenance_environment=environment,
        )
    )

    provenance = next(s for s in result.surfaces if s.name == rsg.SURFACE_PYPI_PROVENANCE)
    assert result.ok is False
    assert provenance.status == rsg.STATUS_FAIL
    assert "unexpected provenance identity" in provenance.detail
    assert provenance.remediation


def test_provenance_rejects_non_utf8_identity_response_without_crashing():
    complete = _pypi_ok()

    def non_utf8_provenance(url: str) -> tuple[int, bytes, str]:
        if url.startswith("https://pypi.org/integrity/"):
            return 200, b"\xff", ""
        return complete(url)

    result = _call_gate(http_get=non_utf8_provenance)

    provenance = next(s for s in result.surfaces if s.name == rsg.SURFACE_PYPI_PROVENANCE)
    assert result.ok is False
    assert provenance.status == rsg.STATUS_FAIL
    assert "unexpected provenance identity" in provenance.detail
    assert provenance.remediation


def test_provenance_rejects_missing_extra_file_attestation_and_digest_mismatch():
    complete = _pypi_ok(extra_wheel=True)

    def missing_extra_provenance(url: str) -> tuple[int, bytes, str]:
        if "manylinux_x86_64.whl/provenance" in url:
            return 404, b"", "not found"
        return complete(url)

    missing = _call_gate(http_get=missing_extra_provenance)
    surface = next(s for s in missing.surfaces if s.name == rsg.SURFACE_PYPI_PROVENANCE)
    assert missing.ok is False
    assert surface.status == rsg.STATUS_FAIL
    assert "manylinux_x86_64.whl" in surface.detail

    def mismatched_artifact(url: str) -> tuple[int, bytes, str]:
        if url.startswith("https://files.pythonhosted.org/"):
            return 200, b"different bytes", ""
        return complete(url)

    mismatch = _call_gate(http_get=mismatched_artifact)
    surface = next(s for s in mismatch.surfaces if s.name == rsg.SURFACE_PYPI_PROVENANCE)
    assert mismatch.ok is False
    assert surface.status == rsg.STATUS_FAIL
    assert "digest mismatch" in surface.detail


@pytest.mark.parametrize(
    ("verifier_result", "expected_status", "expected_detail"),
    [
        ((1, "", "rejected"), rsg.STATUS_FAIL, "rejected provenance"),
        ((0, "not the verifier contract", ""), rsg.STATUS_ERROR, "unexpected result"),
        ((0, "x" * 5000, ""), rsg.STATUS_ERROR, "oversized output"),
    ],
    ids=["nonzero", "malformed-output", "oversized-output"],
)
def test_provenance_fails_closed_for_verifier_errors(
    verifier_result: tuple[int, str, str], expected_status: str, expected_detail: str
):
    delegate = _smoke_ok()

    def verifier_failure(args: list[str], env=None, cwd=None, input_text=None):
        if args and Path(args[0]).name == "pypi-attestations":
            return verifier_result
        return delegate(args, env=env, cwd=cwd, input_text=input_text)

    result = _call_gate(run_subprocess=verifier_failure)
    surface = next(s for s in result.surfaces if s.name == rsg.SURFACE_PYPI_PROVENANCE)
    output = json.dumps(result.to_dict())
    assert result.ok is False
    assert surface.status == expected_status
    assert expected_detail in surface.detail
    assert "not the verifier contract" not in output
    assert "x" * 100 not in output


def test_provenance_fails_closed_when_lock_is_missing_or_stale(tmp_path: Path):
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / "pyproject.toml").write_text(
        '[project]\nname = "fixture"\nversion = "1"\n'
        '[project.optional-dependencies]\ndev = ["pypi-attestations==0.0.30"]\n'
        '[dependency-groups]\ndev = ["pypi-attestations==0.0.30"]\n',
        encoding="utf-8",
    )
    (project_root / "uv.lock").write_text(
        'version = 1\n[[package]]\nname = "pypi-attestations"\nversion = "0.0.29"\n',
        encoding="utf-8",
    )
    http_get = _pypi_ok()
    distributions, _ = rsg.fetch_pypi_distributions(VERSION, PACKAGE, http_get)
    assert distributions is not None
    calls: list[list[str]] = []

    def must_not_run(args: list[str], env=None, cwd=None):
        calls.append(args)
        return 0, "", ""

    result = rsg.check_pypi_provenance(
        VERSION,
        PACKAGE,
        REPO,
        distributions,
        http_get,
        must_not_run,
        project_root=project_root,
    )

    assert result.status == rsg.STATUS_ERROR
    assert "uv.lock" in result.detail
    assert calls == []


def test_official_verifier_has_one_exact_pin_shared_with_uv_lock():
    version, error = rsg._locked_verifier_version(ROOT)

    assert version == "0.0.30"
    assert error == ""


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


def test_partial_publication_emits_one_exact_repository_run_and_job_command():
    result = _call_gate(
        repo=rsg.DEFAULT_REPO,
        run_gh=_gh_partial_publication(),
        http_get=_pypi_ok(provenance_repository=rsg.DEFAULT_REPO),
    )

    command = f"gh run rerun {PUBLISH_RUN_ID} --job {RELEASE_JOB_ID} --repo {rsg.DEFAULT_REPO}"
    remediations = [surface.remediation for surface in result.surfaces]
    assert remediations.count(command) == 1
    assert rsg.render_human(result).count(command) == 1
    assert json.dumps(result.to_dict()).count(command) == 1
    publish = next(s for s in result.surfaces if s.name == rsg.SURFACE_PUBLISH)
    assert publish.workflow_run_id == PUBLISH_RUN_ID
    assert publish.workflow_job_id == RELEASE_JOB_ID
    assert all(
        surface.remediation == command or surface.remediation.startswith("BOUNDED INSTRUCTION: ")
        for surface in result.surfaces
        if surface.status in (rsg.STATUS_FAIL, rsg.STATUS_ERROR)
    )
    assert result.ok is False


def test_failed_and_error_remediations_wrap_legacy_prose_as_bounded_instructions():
    result = _call_gate(
        run_git=_git_missing(),
        http_get=_pypi_error("Connection timed out"),
        run_subprocess=_smoke_fail(),
    )

    failed = [
        surface
        for surface in result.surfaces
        if surface.status in (rsg.STATUS_FAIL, rsg.STATUS_ERROR)
    ]
    assert failed
    assert all(surface.remediation.startswith("BOUNDED INSTRUCTION: ") for surface in failed)
    assert all(
        surface.to_dict()["remediation"].startswith("BOUNDED INSTRUCTION: ") for surface in failed
    )
    assert "BOUNDED INSTRUCTION: Fix the install metadata mismatch" in rsg.render_human(result)


@pytest.mark.parametrize(
    ("kwargs", "extra_blocker"),
    [
        ({"run_status": "in_progress"}, False),
        ({"publish_status": "failure"}, False),
        ({"duplicate_release_job": True}, False),
        ({}, True),
    ],
    ids=["rerun-in-progress", "publish-failed", "duplicate-job", "failed-prerequisite"],
)
def test_partial_publication_fails_closed_without_exact_command(kwargs, extra_blocker):
    run_subprocess = _smoke_fail() if extra_blocker else _smoke_ok()
    result = _call_gate(
        repo=rsg.DEFAULT_REPO,
        run_gh=_gh_partial_publication(**kwargs),
        http_get=_pypi_ok(provenance_repository=rsg.DEFAULT_REPO),
        run_subprocess=run_subprocess,
    )

    output = rsg.render_human(result)
    assert "gh run rerun" not in output
    publish = next(s for s in result.surfaces if s.name == rsg.SURFACE_PUBLISH)
    assert publish.remediation.startswith("BOUNDED INSTRUCTION:")


def test_partial_publication_command_is_never_rendered_for_another_repository():
    result = _call_gate(run_gh=_gh_partial_publication())

    assert "gh run rerun" not in rsg.render_human(result)


def test_completed_publication_has_no_recovery_command():
    result = _call_gate()

    assert result.ok is True
    assert "gh run rerun" not in rsg.render_human(result)


def test_exact_sha_workflow_check_rejects_stale_green_run():
    stale_sha = "b" * 40

    def gh_stale_green_exact_failure(args: list[str]) -> tuple[int, str, str]:
        if "run" in args and "list" in args and "Dependency Audit" not in args:
            runs = [
                {
                    "status": "completed",
                    "conclusion": "failure",
                    "headBranch": BRANCH,
                    "headSha": SHA,
                },
                {
                    "status": "completed",
                    "conclusion": "success",
                    "headBranch": BRANCH,
                    "headSha": stale_sha,
                },
            ]
            return 0, json.dumps(runs), ""
        return _gh_all_ok()(args)

    result = _call_gate(run_gh=gh_stale_green_exact_failure)

    tests_surf = next(s for s in result.surfaces if s.name == rsg.SURFACE_TESTS)
    publish_surf = next(s for s in result.surfaces if s.name == rsg.SURFACE_PUBLISH)
    assert result.ok is False
    assert tests_surf.status == rsg.STATUS_FAIL
    assert publish_surf.status == rsg.STATUS_FAIL
    assert stale_sha not in tests_surf.detail
    assert "candidate SHA" in tests_surf.remediation


def test_public_tag_target_is_reconciled_against_the_reviewed_sha():
    """A tag that was moved or recreated after review must not report green.

    `--expect-sha` is the documented invocation, so the public tag has to be
    resolved and peeled on that path too; assuming the reviewed SHA would leave
    the gate's central claim — the published tag targets the reviewed commit —
    unproven exactly where operators rely on it.
    """
    moved_sha = "d" * 40

    result = _call_gate(run_git=_git_annotated_tag(moved_sha), expect_sha=SHA)

    assert result.ok is False
    candidate_surf = next(s for s in result.surfaces if s.name == rsg.SURFACE_CANDIDATE_SHA)
    assert candidate_surf.status == rsg.STATUS_FAIL
    assert moved_sha in candidate_surf.detail
    assert SHA in candidate_surf.detail
    assert candidate_surf.remediation
    assert "never move a published tag" in candidate_surf.remediation
    assert any(moved_sha in blocker for blocker in result.blockers)


def test_public_tag_target_is_peeled_and_verified_when_expect_sha_matches():
    # The tag object SHA differs from the commit it targets, so an unpeeled
    # comparison would report a mismatch for a perfectly correct tag.
    result = _call_gate(run_git=_git_annotated_tag(SHA), expect_sha=SHA)

    candidate_surf = next(s for s in result.surfaces if s.name == rsg.SURFACE_CANDIDATE_SHA)
    assert candidate_surf.status == rsg.STATUS_OK
    assert "targets the reviewed SHA" in candidate_surf.detail
    assert SHA in candidate_surf.detail
    assert result.ok is True


def test_unresolvable_public_tag_is_reported_even_with_expect_sha():
    result = _call_gate(run_git=_git_missing(), expect_sha=SHA)

    candidate_surf = next(s for s in result.surfaces if s.name == rsg.SURFACE_CANDIDATE_SHA)
    assert candidate_surf.status == rsg.STATUS_FAIL
    assert "could not resolve" in candidate_surf.detail
    # The reviewed SHA still drives the exact-SHA surfaces, so their evidence is
    # not lost to the unresolved tag.
    tests_surf = next(s for s in result.surfaces if s.name == rsg.SURFACE_TESTS)
    assert tests_surf.status == rsg.STATUS_OK


def test_malformed_expect_sha_is_reported_on_the_candidate_surface():
    result = _call_gate(expect_sha="not-a-sha")

    candidate_surf = next(s for s in result.surfaces if s.name == rsg.SURFACE_CANDIDATE_SHA)
    assert candidate_surf.status == rsg.STATUS_FAIL
    assert "40 hexadecimal" in candidate_surf.detail
    assert result.ok is False


def test_malformed_expect_sha_does_not_let_workflow_surfaces_fall_back_to_branch_latest():
    """An unbound candidate must not be answered with the branch's latest run.

    `check_workflow_run` drops its SHA filter when no candidate is bound, so the
    exact-SHA workflow rows would silently become branch-latest rows and print
    `ok` for a commit nobody reviewed — inside a report that is failing for an
    unrelated reason and is therefore likely to be skimmed.
    """
    workflow_lookups: list[list[str]] = []

    def gh_recording(args: list[str]) -> tuple[int, str, str]:
        if "run" in args and "list" in args and "Dependency Audit" not in args:
            workflow_lookups.append(args)
        return _gh_all_ok()(args)

    result = _call_gate(expect_sha="not-a-sha", run_gh=gh_recording)

    tests_surf = next(s for s in result.surfaces if s.name == rsg.SURFACE_TESTS)
    publish_surf = next(s for s in result.surfaces if s.name == rsg.SURFACE_PUBLISH)
    assert tests_surf.status == rsg.STATUS_FAIL, tests_surf.detail
    assert publish_surf.status == rsg.STATUS_FAIL, publish_surf.detail
    assert "no candidate SHA is bound" in tests_surf.detail
    assert "no candidate SHA is bound" in publish_surf.detail
    assert tests_surf.remediation
    assert publish_surf.remediation
    # The unbound lookup is not merely ignored — it is never issued.
    assert workflow_lookups == []

    # The report stays complete and machine-readable: no surface is dropped and
    # every blocker is still enumerated.
    data = result.to_dict()
    surface_names = {s["name"] for s in data["surfaces"]}
    for required in rsg.REQUIRED_SURFACES:
        assert required in surface_names, required
    assert result.ok is False
    assert any("no candidate SHA is bound" in blocker for blocker in result.blockers)
    assert isinstance(json.dumps(data), str)


def test_missing_public_ref_protection_is_reported_without_mutation():
    """Both protected-ref predicates fail closed and only ever read."""
    mutating: list[list[str]] = []

    def gh_missing_protection(args: list[str]) -> tuple[int, str, str]:
        if args and args[0] == "api":
            if any(flag in args for flag in ("-f", "-F", "--method", "-X", "--input")):
                mutating.append(args)
            if "/rules/branches/" in args[1]:
                return 0, json.dumps([]), ""
            if "/rulesets" in args[1]:
                return 0, json.dumps([]), ""
        return _gh_all_ok()(args)

    result = _call_gate(run_gh=gh_missing_protection)

    main = next(s for s in result.surfaces if s.name == rsg.SURFACE_MAIN_PROTECTION)
    tags = next(s for s in result.surfaces if s.name == rsg.SURFACE_TAG_RULESET)
    assert result.ok is False
    assert main.status == rsg.STATUS_FAIL
    assert tags.status == rsg.STATUS_FAIL
    assert "release-required" in main.detail
    assert "non_fast_forward" in main.detail
    assert "refs/tags/v*" in tags.detail
    assert "docs/release-admission-rulesets.md" in tags.remediation
    assert mutating == []


def test_orphan_public_tag_preserves_v1132_evidence():
    """v1.13.2 is reviewed immutable evidence: always reported, never blocking."""

    def git_with_v1132(args: list[str]) -> tuple[int, str, str]:
        if args[:3] == ["ls-remote", "--tags", "--refs"]:
            return (
                0,
                f"{SHA}\trefs/tags/v{VERSION}\n{'b' * 40}\trefs/tags/v1.13.2\n",
                "",
            )
        if args[:2] == ["ls-remote", "--tags"]:
            return 0, f"{SHA}\trefs/tags/v{VERSION}\n", ""
        return 0, "", ""

    result = _call_gate(run_git=git_with_v1132)

    orphan = next(s for s in result.surfaces if s.name == rsg.SURFACE_ORPHAN_TAGS)
    assert orphan.status == rsg.STATUS_OK
    assert "v1.13.2" in orphan.detail
    assert "acknowledged" in orphan.detail
    assert result.ok is True


def test_new_orphan_public_tag_blocks_while_v1132_stays_evidence():
    """A v* tag that is not in the acknowledged registry fails closed."""

    def git_with_new_orphan(args: list[str]) -> tuple[int, str, str]:
        if args[:3] == ["ls-remote", "--tags", "--refs"]:
            return (
                0,
                f"{SHA}\trefs/tags/v{VERSION}\n"
                f"{'b' * 40}\trefs/tags/v1.13.2\n"
                f"{'c' * 40}\trefs/tags/v9.9.9\n",
                "",
            )
        if args[:2] == ["ls-remote", "--tags"]:
            return 0, f"{SHA}\trefs/tags/v{VERSION}\n", ""
        return 0, "", ""

    result = _call_gate(run_git=git_with_new_orphan)

    orphan = next(s for s in result.surfaces if s.name == rsg.SURFACE_ORPHAN_TAGS)
    assert result.ok is False
    assert orphan.status == rsg.STATUS_FAIL
    assert "v9.9.9" in orphan.detail
    assert "no GitHub Release" in orphan.detail
    # The acknowledged tag is still reported as evidence, not as the blocker.
    assert "acknowledged" in orphan.detail
    assert orphan.remediation


def test_missing_expected_public_tag_blocks_the_status_gate():
    """Post-publication, the tag for the released version must exist publicly."""

    def git_without_expected_tag(args: list[str]) -> tuple[int, str, str]:
        if args[:3] == ["ls-remote", "--tags", "--refs"]:
            return 0, f"{'b' * 40}\trefs/tags/v1.13.2\n", ""
        if args[:2] == ["ls-remote", "--tags"]:
            return 0, f"{SHA}\trefs/tags/v{VERSION}\n", ""
        return 0, "", ""

    result = _call_gate(run_git=git_without_expected_tag)

    orphan = next(s for s in result.surfaces if s.name == rsg.SURFACE_ORPHAN_TAGS)
    assert result.ok is False
    assert orphan.status == rsg.STATUS_FAIL
    assert f"v{VERSION}" in orphan.detail
    assert "expected public tag not found" in orphan.detail


def test_dependency_audit_lookup_failure_blocks_with_remediation():
    def gh_audit_error(args: list[str]) -> tuple[int, str, str]:
        if "run" in args and "list" in args and "Dependency Audit" in args:
            return 1, "", "api unavailable"
        return _gh_all_ok()(args)

    result = _call_gate(run_gh=gh_audit_error)

    audit = next(s for s in result.surfaces if s.name == rsg.SURFACE_AUDIT)
    assert result.ok is False
    assert audit.status == rsg.STATUS_ERROR
    assert "api unavailable" in audit.detail
    assert "Dependency Audit" in audit.remediation


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
        return _gh_all_ok()(args)

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
        expect_sha=SHA,
        required_check_name="release-required",
        audit_max_age_hours=168,
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


def test_gate_json_output_is_machine_readable_and_surface_complete(monkeypatch):
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

    def fake_run_gate(**kwargs):
        assert kwargs["expect_sha"] == SHA
        return rsg.GateResult(version=VERSION, ok=False, partial=True, surfaces=result.surfaces)

    monkeypatch.setattr(rsg, "run_gate", fake_run_gate)

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
                "--expect-sha",
                SHA,
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


def test_main_smoke_adapter_forwards_mcp_input_and_configured_timeout(monkeypatch):
    expected_command = ["mempalace-code-mcp", "--profile=minimal"]
    expected_env = {"PATH": "/fake/bin"}
    expected_cwd = "/neutral/probe"
    expected_input = (
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}) + "\n"
    )
    calls = []

    def fake_default_run_subprocess(cmd, env=None, cwd=None, input_text=None, timeout_seconds=None):
        calls.append(
            {
                "cmd": cmd,
                "env": env,
                "cwd": cwd,
                "input_text": input_text,
                "timeout_seconds": timeout_seconds,
            }
        )
        return 0, "", ""

    def fake_run_gate(**kwargs):
        kwargs["run_subprocess"](
            expected_command,
            env=expected_env,
            cwd=expected_cwd,
            input_text=expected_input,
        )
        return rsg.GateResult(version=VERSION, ok=True, partial=False)

    monkeypatch.setattr(rsg, "_default_run_subprocess", fake_default_run_subprocess)
    monkeypatch.setattr(rsg, "run_gate", fake_run_gate)

    assert rsg.main(["--version", VERSION, "--smoke-timeout-seconds", "37", "--json"]) == 0
    assert calls == [
        {
            "cmd": expected_command,
            "env": expected_env,
            "cwd": expected_cwd,
            "input_text": expected_input,
            "timeout_seconds": 37,
        }
    ]


# ── Regression: stale-success masking ────────────────────────────────────────


def test_workflow_stale_success_does_not_mask_newer_failure():
    """A newer completed failure must block the gate even when an older success exists in the window."""

    def gh_newer_failure_older_success(args: list[str]) -> tuple[int, str, str]:
        if "run" in args and "list" in args:
            if "Dependency Audit" in args:
                return _gh_all_ok()(args)
            runs = [
                {
                    "status": "completed",
                    "conclusion": "failure",
                    "headBranch": BRANCH,
                    "headSha": SHA,
                },
                {
                    "status": "completed",
                    "conclusion": "success",
                    "headBranch": BRANCH,
                    "headSha": "b" * 40,
                },
            ]
            return 0, json.dumps(runs), ""
        return _gh_all_ok()(args)

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


def test_workflow_run_recency_is_decided_by_timestamp_not_list_position():
    """Both runs are on the candidate SHA; only createdAt distinguishes them.

    The fixture above relies on list order, so it would still pass if `gh`'s
    ordering were trusted. Here the newest run is listed last, which fails only
    if the parsed timestamps really are what decide recency.
    """

    def gh_out_of_order(args: list[str]) -> tuple[int, str, str]:
        if "run" in args and "list" in args and "Dependency Audit" not in args:
            runs = [
                {
                    "status": "completed",
                    "conclusion": "success",
                    "headBranch": BRANCH,
                    "headSha": SHA,
                    "createdAt": "2026-01-01T00:00:00Z",
                },
                {
                    "status": "completed",
                    "conclusion": "failure",
                    "headBranch": BRANCH,
                    "headSha": SHA,
                    "createdAt": "2026-02-01T00:00:00Z",
                },
            ]
            return 0, json.dumps(runs), ""
        return _gh_all_ok()(args)

    result = _call_gate(run_gh=gh_out_of_order)

    assert result.ok is False
    tests_surf = next(s for s in result.surfaces if s.name == rsg.SURFACE_TESTS)
    assert tests_surf.status == rsg.STATUS_FAIL, tests_surf.detail
    assert "failure" in tests_surf.detail


def test_workflow_run_recency_survives_an_offset_bearing_created_at():
    """Lexical order is only correct while every stamp is Z-normalized.

    The success here is stamped `2026-02-01T05:00:00+05:00` (00:00 UTC) and the
    failure `2026-02-01T01:00:00Z` (01:00 UTC). Sorted as strings the success
    wins and the gate reports green; parsed as instants the failure is newer and
    blocks. `gh` normalizes today, so this is the case that turns a comment
    saying "parsed" into a fact.
    """

    def gh_mixed_offsets(args: list[str]) -> tuple[int, str, str]:
        if "run" in args and "list" in args and "Dependency Audit" not in args:
            runs = [
                {
                    "status": "completed",
                    "conclusion": "success",
                    "headBranch": BRANCH,
                    "headSha": SHA,
                    "createdAt": "2026-02-01T05:00:00+05:00",
                },
                {
                    "status": "completed",
                    "conclusion": "failure",
                    "headBranch": BRANCH,
                    "headSha": SHA,
                    "createdAt": "2026-02-01T01:00:00Z",
                },
            ]
            return 0, json.dumps(runs), ""
        return _gh_all_ok()(args)

    # The hazard is real: string ordering picks the older success.
    assert "2026-02-01T05:00:00+05:00" > "2026-02-01T01:00:00Z"

    result = _call_gate(run_gh=gh_mixed_offsets)

    assert result.ok is False
    tests_surf = next(s for s in result.surfaces if s.name == rsg.SURFACE_TESTS)
    assert tests_surf.status == rsg.STATUS_FAIL, tests_surf.detail
    assert "failure" in tests_surf.detail


def test_unorderable_workflow_runs_fail_closed_instead_of_letting_position_decide():
    """Two candidate runs and one unparseable stamp: there is no newest run.

    Falling back to list position would hand the decision to whatever order gh
    happened to return, which is exactly the property this surface must not have.
    """

    def gh_malformed_stamp(args: list[str]) -> tuple[int, str, str]:
        if "run" in args and "list" in args and "Dependency Audit" not in args:
            runs = [
                {
                    "status": "completed",
                    "conclusion": "success",
                    "headBranch": BRANCH,
                    "headSha": SHA,
                    "createdAt": "not-a-timestamp",
                },
                {
                    "status": "completed",
                    "conclusion": "failure",
                    "headBranch": BRANCH,
                    "headSha": SHA,
                    "createdAt": "2026-02-01T01:00:00Z",
                },
            ]
            return 0, json.dumps(runs), ""
        return _gh_all_ok()(args)

    result = _call_gate(run_gh=gh_malformed_stamp)

    assert result.ok is False
    tests_surf = next(s for s in result.surfaces if s.name == rsg.SURFACE_TESTS)
    assert tests_surf.status == rsg.STATUS_ERROR, tests_surf.detail
    assert "createdAt" in tests_surf.detail
    assert tests_surf.remediation


def test_a_single_undatable_workflow_run_is_still_usable_evidence():
    """One run needs no ordering, so a missing stamp must not manufacture an error."""

    def gh_single_undatable(args: list[str]) -> tuple[int, str, str]:
        if "run" in args and "list" in args and "Dependency Audit" not in args:
            runs = [
                {
                    "status": "completed",
                    "conclusion": "failure",
                    "headBranch": BRANCH,
                    "headSha": SHA,
                },
            ]
            return 0, json.dumps(runs), ""
        return _gh_all_ok()(args)

    result = _call_gate(run_gh=gh_single_undatable)

    tests_surf = next(s for s in result.surfaces if s.name == rsg.SURFACE_TESTS)
    assert tests_surf.status == rsg.STATUS_FAIL, tests_surf.detail
    assert "failure" in tests_surf.detail
