"""Focused tests for scripts/workflow_security_gate.py — immutable Action pins."""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]  # reason: script path always has a spec
    sys.modules[name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]  # reason: script path always has a loader
    return mod


wsg = _load_module("workflow_security_gate", ROOT / "scripts" / "workflow_security_gate.py")

CHECKOUT_SHA = "fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09"
PUBLISH_SHA = "dc37677b2e1c63e2034f94d8a5b11f265b73ba33"

CI_YML = f"""name: CI
jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@{CHECKOUT_SHA} # v5
      - uses: ./.github/actions/local
"""

PUBLISH_YML = f"""name: Publish
permissions:
  contents: read
jobs:
  build:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      checks: read
      actions: read
    steps:
      - uses: actions/checkout@{CHECKOUT_SHA} # v5
  publish:
    permissions:
      id-token: write
    steps:
      - uses: pypa/gh-action-pypi-publish@{PUBLISH_SHA} # release/v1
  github-release:
    permissions:
      contents: write
      checks: read
      actions: read
    steps:
      - run: gh release create "$GITHUB_REF_NAME"
"""


def _write_pinned_repo(root: Path) -> Path:
    workflows = root / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text(CI_YML, encoding="utf-8")
    (workflows / "publish.yml").write_text(PUBLISH_YML, encoding="utf-8")
    return root


def _rewrite(path: Path, old: str, new: str) -> None:
    path.write_text(path.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")


def _codes(report) -> list[str]:
    return [error.split(":", 1)[0] for error in report["errors"]]


def test_pinned_tree_passes_and_reports_external_uses(tmp_path):
    root = _write_pinned_repo(tmp_path / "repo")

    report = wsg.check_workflow_security(root)

    assert report["ok"] is True
    assert report["errors"] == []
    ci = next(w for w in report["workflows"] if w["path"] == ".github/workflows/ci.yml")
    # The repository-local `./` reference is not an external pin and is not reported.
    assert ci["external_uses"] == [
        {"action": "actions/checkout", "line": 6, "sha": CHECKOUT_SHA, "version": "v5"}
    ]
    assert report["publish_permissions"][""] == {"contents": "read"}


def test_unpinned_action_reference_fails_the_gate(tmp_path):
    root = _write_pinned_repo(tmp_path / "repo")
    _rewrite(root / ".github" / "workflows" / "ci.yml", f"@{CHECKOUT_SHA} # v5", "@v5")

    report = wsg.check_workflow_security(root)

    assert report["ok"] is False
    assert _codes(report) == ["MUTABLE-REF"]
    assert "actions/checkout@v5" in report["errors"][0]


def test_short_sha_reference_fails_the_gate(tmp_path):
    root = _write_pinned_repo(tmp_path / "repo")
    _rewrite(root / ".github" / "workflows" / "ci.yml", CHECKOUT_SHA, CHECKOUT_SHA[:7])

    report = wsg.check_workflow_security(root)

    assert _codes(report) == ["MUTABLE-REF"]


def test_pin_without_version_comment_fails_the_gate(tmp_path):
    root = _write_pinned_repo(tmp_path / "repo")
    _rewrite(root / ".github" / "workflows" / "ci.yml", " # v5", "")

    report = wsg.check_workflow_security(root)

    assert _codes(report) == ["MISSING-VERSION-COMMENT"]


def test_broadened_publish_job_permissions_fail_the_gate(tmp_path):
    root = _write_pinned_repo(tmp_path / "repo")
    _rewrite(
        root / ".github" / "workflows" / "publish.yml",
        "      id-token: write\n",
        "      id-token: write\n      contents: write\n",
    )

    report = wsg.check_workflow_security(root)

    assert _codes(report) == ["PUBLISH-PERMISSIONS"]
    assert "job 'publish'" in report["errors"][0]


@pytest.mark.parametrize(
    ("appended_step", "expected"),
    [
        # A bare trailing '#' leaves no reviewed version behind.
        (f"      - uses: actions/checkout@{CHECKOUT_SHA} #\n", "MISSING-VERSION-COMMENT"),
        # Flow-style step mapping — legal Actions YAML, mutable reference.
        ("      - {uses: evil/action@v1}\n", "MUTABLE-REF"),
        # Quoted scalar reference.
        ('      - uses: "actions/setup-python@v6" # v6\n', "MUTABLE-REF"),
        # Structurally present but unusable values must fail closed, never disappear.
        ("      - uses:\n", "UNPARSED-USES"),
        ("      - uses: [actions/checkout, v5]\n", "UNPARSED-USES"),
    ],
)
def test_every_structurally_present_uses_is_checked(tmp_path, appended_step, expected):
    root = _write_pinned_repo(tmp_path / "repo")
    ci = root / ".github" / "workflows" / "ci.yml"
    ci.write_text(ci.read_text(encoding="utf-8") + appended_step, encoding="utf-8")

    report = wsg.check_workflow_security(root)

    assert _codes(report) == [expected]


def test_job_level_reusable_workflow_reference_is_pinned(tmp_path):
    root = _write_pinned_repo(tmp_path / "repo")
    ci = root / ".github" / "workflows" / "ci.yml"
    ci.write_text(
        ci.read_text(encoding="utf-8") + "  call:\n    uses: other/repo/.github/wf.yml@v1\n",
        encoding="utf-8",
    )

    report = wsg.check_workflow_security(root)

    assert _codes(report) == ["MUTABLE-REF"]
    assert "other/repo/.github/wf.yml@v1" in report["errors"][0]


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("name: CI\njobs: [not, a, mapping]\n", "UNPARSED-JOBS"),
        ("name: CI\njobs:\n  lint:\n    steps: nope\n", "UNPARSED-STEPS"),
        ("name: CI\njobs:\n  lint:\n    steps:\n      - just-a-string\n", "UNPARSED-STEPS"),
        ("name: CI\njobs: [\n", "UNPARSABLE-WORKFLOW"),
    ],
)
def test_unparsed_workflow_shapes_fail_closed(tmp_path, body, expected):
    root = _write_pinned_repo(tmp_path / "repo")
    (root / ".github" / "workflows" / "ci.yml").write_text(body, encoding="utf-8")

    report = wsg.check_workflow_security(root)

    assert _codes(report) == [expected]


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        # An added elevated job must be reviewed here, not inherited silently.
        (
            "  github-release:\n",
            "  sneaky:\n    permissions:\n      contents: write\n"
            "    steps:\n      - run: true\n  github-release:\n",
            ["UNEXPECTED-PUBLISH-JOB"],
        ),
        # A renamed job is both an unknown job and a missing required one.
        ("  publish:\n", "  pypi-publish:\n", ["MISSING-PUBLISH-JOB", "UNEXPECTED-PUBLISH-JOB"]),
        # The packaging job must declare exactly the reviewed read-only scopes it
        # needs for release admission — no broader, no different.
        (
            "  build:\n    runs-on: ubuntu-latest\n    permissions:\n"
            "      contents: read\n      checks: read\n      actions: read\n",
            "  build:\n    runs-on: ubuntu-latest\n    permissions:\n"
            "      contents: read\n      administration: read\n",
            ["PUBLISH-PERMISSIONS"],
        ),
        # Widening the packaging job to a write scope is a review-blocking change.
        (
            "      contents: read\n      checks: read\n",
            "      contents: write\n      checks: read\n",
            ["PUBLISH-PERMISSIONS"],
        ),
        # The release job must retain every scope used to recheck admission evidence.
        (
            "  github-release:\n    permissions:\n      contents: write\n"
            "      checks: read\n      actions: read\n",
            "  github-release:\n    permissions:\n      contents: write\n      actions: read\n",
            ["PUBLISH-PERMISSIONS"],
        ),
        # Widening a reviewed release evidence scope is also rejected.
        (
            "  github-release:\n    permissions:\n      contents: write\n"
            "      checks: read\n      actions: read\n",
            "  github-release:\n    permissions:\n      contents: write\n"
            "      checks: read\n      actions: write\n",
            ["PUBLISH-PERMISSIONS"],
        ),
    ],
)
def test_publish_job_set_and_permissions_are_exact(tmp_path, old, new, expected):
    root = _write_pinned_repo(tmp_path / "repo")
    _rewrite(root / ".github" / "workflows" / "publish.yml", old, new)

    report = wsg.check_workflow_security(root)

    assert sorted(_codes(report)) == expected


def test_missing_publish_workflow_fails_the_gate(tmp_path):
    root = _write_pinned_repo(tmp_path / "repo")
    (root / ".github" / "workflows" / "publish.yml").unlink()

    report = wsg.check_workflow_security(root)

    assert _codes(report) == ["MISSING-PUBLISH-WORKFLOW"]


def test_main_reports_failures_with_one_recovery_instruction(tmp_path, capsys):
    root = _write_pinned_repo(tmp_path / "repo")
    _rewrite(root / ".github" / "workflows" / "ci.yml", f"@{CHECKOUT_SHA} # v5", "@v5")

    rc = wsg.main(["--root", str(root)])

    assert rc == 1
    err = capsys.readouterr().err
    assert "workflow-security-gate: FAIL" in err
    assert "MUTABLE-REF" in err
    assert err.count("Recovery:") == 1


def test_main_json_output_is_machine_readable(tmp_path, capsys):
    root = _write_pinned_repo(tmp_path / "repo")

    rc = wsg.main(["--root", str(root), "--format", "json"])

    assert rc == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True


def test_live_repository_workflows_are_immutably_pinned():
    report = wsg.check_workflow_security(ROOT)

    assert report["errors"] == []
    pinned = [use for w in report["workflows"] for use in w["external_uses"]]
    assert pinned, "expected at least one external action reference"


def test_dependabot_maintains_github_actions_weekly():
    import yaml

    config = yaml.safe_load((ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8"))

    assert config["version"] == 2
    actions = [u for u in config["updates"] if u["package-ecosystem"] == "github-actions"]
    assert [(u["directory"], u["schedule"]["interval"]) for u in actions] == [("/", "weekly")]


def test_dependabot_maintains_the_pinned_gitleaks_tool_module_weekly():
    """The Gitleaks CLI pin must have a maintainer, not just an immutable version."""
    import yaml

    config = yaml.safe_load((ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8"))

    gomod = [u for u in config["updates"] if u["package-ecosystem"] == "gomod"]
    assert [(u["directory"], u["schedule"]["interval"]) for u in gomod] == [
        ("/tools/gitleaks", "weekly")
    ]
    # The tool module records Gitleaks as a direct requirement (tools.go blank
    # import), so the direct-dependency allowlist still covers it.
    assert gomod[0]["allow"] == [{"dependency-type": "direct"}]


def test_repository_local_composite_actions_contain_no_unpinned_external_uses():
    """The gate skips `./` references, so a local action must not smuggle one in.

    scripts/workflow_security_gate.py only globs .github/workflows/, and treats a
    `./`-prefixed `uses:` as repository-local with nothing to pin. That is only
    sound while local composite actions call no external actions themselves.
    """
    import yaml

    actions = sorted((ROOT / ".github" / "actions").glob("*/action.yml"))
    assert actions, "expected at least one repository-local composite action"

    for path in actions:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        steps = document.get("runs", {}).get("steps", [])
        relative = path.relative_to(ROOT).as_posix()
        assert steps, f"{relative} declares no steps"
        for index, step in enumerate(steps):
            assert "uses" not in step, (
                f"{relative} step {index} calls {step.get('uses')!r}; external references inside a "
                "repository-local action are not audited by workflow_security_gate.py"
            )
            assert step.get("shell") == "bash", f"{relative} step {index} must declare shell: bash"

        # zizmor audits .github/actions/ too (gate_inventory.ZIZMOR_COMMAND), so a
        # suppression here must stay narrow: one named audit on one line, never a
        # bare `# zizmor: ignore` that disables every audit for the line.
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "zizmor: ignore" not in line:
                continue
            assert re.search(r"#\s*zizmor:\s*ignore\[[a-z0-9-]+(,[a-z0-9-]+)*\]", line), (
                f"{relative}:{line_number} suppresses zizmor without naming the audit"
            )


def test_workflows_calling_the_gitleaks_gate_keep_their_setup_actions_pinned():
    """setup-go/setup-python stay in the calling workflow so the gate audits them."""
    report = wsg.check_workflow_security(ROOT)
    assert report["errors"] == []

    by_path = {w["path"]: w for w in report["workflows"]}
    for relative in (
        ".github/workflows/ci.yml",
        ".github/workflows/publish.yml",
        ".github/workflows/gitleaks-history.yml",
    ):
        text = (ROOT / relative).read_text(encoding="utf-8")
        if "./.github/actions/gitleaks-gate" not in text:
            continue
        actions = {use["action"] for use in by_path[relative]["external_uses"]}
        assert "actions/setup-go" in actions, relative
        assert "actions/setup-python" in actions, relative
