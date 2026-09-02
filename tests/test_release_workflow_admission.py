"""Workflow-shape tests for exact-SHA release admission wiring.

These parse the workflow YAML and compare it against the admission contract
constants in scripts/release_admission_checks.py, so the workflows and the
library cannot drift apart. Text greps are used only where the assertion really
is about literal shell text (for example, that a step invokes a specific flag).
"""

from __future__ import annotations

import copy
import importlib.util
import re
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parent.parent
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
PUBLISH_WORKFLOW = ROOT / ".github" / "workflows" / "publish.yml"
UPSTREAM_DRIFT_WORKFLOW = ROOT / ".github" / "workflows" / "upstream-drift.yml"
DOTNET_BENCH_WORKFLOW = ROOT / ".github" / "workflows" / "dotnet-bench.yml"
WORKFLOW_DIR = ROOT / ".github" / "workflows"
WORKFLOWS = sorted((*WORKFLOW_DIR.glob("*.yml"), *WORKFLOW_DIR.glob("*.yaml")))


def _load_admission():
    name = "release_admission_checks"
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


ADMISSION = _load_admission()


def _workflow(path: Path) -> dict:
    # PyYAML parses the bare `on:` key as the boolean True; that is fine here
    # because every trigger assertion looks the key up explicitly.
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _uses_nodes(node):
    matches = []
    if isinstance(node, yaml.MappingNode):
        for key, value in node.value:
            if isinstance(key, yaml.ScalarNode) and key.value == "uses":
                matches.append(value)
            matches.extend(_uses_nodes(key))
            matches.extend(_uses_nodes(value))
    elif isinstance(node, yaml.SequenceNode):
        for value in node.value:
            matches.extend(_uses_nodes(value))
    return matches


def _publish_build_job() -> dict:
    return _workflow(PUBLISH_WORKFLOW)["jobs"]["build"]


def _github_release_job() -> dict:
    return _workflow(PUBLISH_WORKFLOW)["jobs"]["github-release"]


# ── ci.yml: the stable aggregate check ────────────────────────────────────────


def test_standalone_upstream_drift_workflow_is_absent():
    assert not UPSTREAM_DRIFT_WORKFLOW.exists()


def test_standalone_dotnet_benchmark_workflow_is_absent():
    assert not DOTNET_BENCH_WORKFLOW.exists()


def test_dotnet_benchmark_is_pinned_and_release_blocking():
    workflow = _workflow(CI_WORKFLOW)
    job = workflow["jobs"]["dotnet-bench"]
    assert "if" not in job
    assert job["env"]["CLEAN_ARCHITECTURE_COMMIT"] == ("5a600ab8749c110384bc3bd436b9c67f3067b489")
    assert str(job["env"]["R5_THRESHOLD"]) == "0.900"
    commands = "\n".join(str(step.get("run", "")) for step in job["steps"])
    assert "mempalace-code fetch-model" in commands
    assert "git -C /tmp/CleanArchitecture checkout --detach FETCH_HEAD" in commands
    assert "--validate-queries" in commands
    assert "--fail-under-r5 ${{ env.R5_THRESHOLD }}" in commands
    upload = next(step for step in job["steps"] if step.get("name") == "Upload benchmark report")
    assert str(upload["if"]).strip() == "always()"
    assert upload["with"] == {
        "name": "dotnet-bench-results",
        "path": "benchmarks/results_dotnet_bench_ci.json",
    }


def test_aggregate_check_job_exists_with_the_contract_name():
    jobs = _workflow(CI_WORKFLOW)["jobs"]
    assert ADMISSION.AGGREGATE_REQUIRED_CHECK in jobs
    job = jobs[ADMISSION.AGGREGATE_REQUIRED_CHECK]
    # The check-run name is what a branch ruleset requires, so it must equal the
    # contract constant and not merely the job id.
    assert job["name"] == ADMISSION.AGGREGATE_REQUIRED_CHECK


def test_aggregate_check_depends_on_exactly_the_release_critical_jobs():
    job = _workflow(CI_WORKFLOW)["jobs"][ADMISSION.AGGREGATE_REQUIRED_CHECK]
    assert sorted(job["needs"]) == sorted(ADMISSION.RELEASE_CRITICAL_CI_JOBS)


def test_release_critical_jobs_all_exist_in_ci():
    jobs = _workflow(CI_WORKFLOW)["jobs"]
    missing = [name for name in ADMISSION.RELEASE_CRITICAL_CI_JOBS if name not in jobs]
    assert missing == []


def test_installed_application_job_uses_local_wheel_without_credentials():
    job = _workflow(CI_WORKFLOW)["jobs"]["installed-application"]
    assert job["permissions"] == {"contents": "read"}
    commands = "\n".join(str(step.get("run", "")) for step in job["steps"])
    assert "python -m build --wheel" in commands
    assert "release_install_metadata_smoke.py" in commands
    assert "--all-installers" in commands
    assert "--installed-golden-wheel" in commands
    assert (
        'python scripts/release_readiness_gate.py --installed-golden-wheel "$WHEEL" --json'
        in commands
    )
    assert "dist/*.whl" in commands
    assert "for installer in" not in commands
    assert "--installer" not in commands
    assert all(client not in commands for client in ("codex", "claude", "gemini"))


def test_installed_application_self_seeds_required_minilm_cache_on_miss():
    job = _workflow(CI_WORKFLOW)["jobs"]["installed-application"]
    assert job["env"] == {
        "HF_HOME": "${{ github.workspace }}/.cache/huggingface",
        "MEMPALACE_TEST_HF_HOME": "${{ github.workspace }}/.cache/huggingface",
    }
    steps = job["steps"]
    cache = next(step for step in job["steps"] if step.get("id") == "hf-cache")
    assert str(cache["uses"]).startswith("actions/cache@")
    assert cache["with"]["path"].endswith(
        "/.cache/huggingface/mempalace-fastembed/all-MiniLM-L6-v2-v1"
    )
    assert "fail-on-cache-miss" not in cache["with"]
    assert "fastembed-" in cache["with"]["key"]
    assert "benchmarks/minilm_runtime_compatibility_fixture.json" in cache["with"]["key"]
    assert job["runs-on"] == "${{ matrix.runner }}"
    assert job["strategy"]["matrix"]["include"] == [
        {"runner": "ubuntu-latest", "python": "3.11", "arch": "x64"},
        {"runner": "ubuntu-24.04-arm", "python": "3.12", "arch": "arm64"},
    ]

    bootstrap = next(step for step in steps if "fetch-model" in str(step.get("run", "")))
    assert bootstrap["if"] == "steps.hf-cache.outputs.cache-hit != 'true'"
    assert bootstrap["shell"] == "bash"
    bootstrap_command = bootstrap["run"]
    assert "set -euo pipefail" in bootstrap_command
    assert "clean_env=(" in bootstrap_command
    assert "env -i" in bootstrap_command
    for assignment in (
        'HOME="$bootstrap_home"',
        'HF_HOME="$HF_HOME"',
        "HF_HUB_DISABLE_IMPLICIT_TOKEN=1",
        'PATH="$PATH"',
        "PIP_CONFIG_FILE=/dev/null",
        "PIP_KEYRING_PROVIDER=disabled",
        "PYTHONNOUSERSITE=1",
    ):
        assert assignment in bootstrap_command
    assert bootstrap_command.count('"${clean_env[@]}"') == 2
    assert '"${clean_env[@]}" python -m pip install .' in bootstrap_command
    assert '"${clean_env[@]}" mempalace-code fetch-model' in bootstrap_command
    for forbidden in (
        "HF_TOKEN",
        "HUGGING_FACE_HUB_TOKEN",
        "PIP_INDEX_URL",
        "PIP_EXTRA_INDEX_URL",
        "GITHUB_TOKEN",
    ):
        assert forbidden not in bootstrap_command
    assert "continue-on-error" not in bootstrap
    assert "continue-on-error" not in job

    build_index = next(
        index
        for index, step in enumerate(steps)
        if "python -m build --wheel" in step.get("run", "")
    )
    bootstrap_index = steps.index(bootstrap)
    manager_index = next(
        index
        for index, step in enumerate(steps)
        if "release_install_metadata_smoke.py" in step.get("run", "")
    )
    golden_index = next(
        index
        for index, step in enumerate(steps)
        if "--installed-golden-wheel" in step.get("run", "")
    )
    compatibility = next(
        step for step in steps if "--check-minilm-runtime-compatibility" in step.get("run", "")
    )
    compatibility_index = steps.index(compatibility)
    assert compatibility["if"] == "matrix.arch == 'x64'"
    assert 'python -m pip install "${wheel[0]}"' in compatibility["run"]
    checkout = next(
        step for step in steps if str(step.get("uses", "")).startswith("actions/checkout@")
    )
    assert checkout["with"]["fetch-depth"] == 1
    assert "git fetch" not in compatibility["run"]
    assert "git archive" not in compatibility["run"]
    assert (
        steps.index(cache)
        < bootstrap_index
        < build_index
        < compatibility_index
        < manager_index
        < golden_index
    )


def test_installed_application_cache_bootstrap_has_no_credential_or_provider_access():
    workflow = _workflow(CI_WORKFLOW)
    job = workflow["jobs"]["installed-application"]
    serialized = yaml.safe_dump(job).lower()

    assert "persist-credentials: false" in serialized
    assert "secrets." not in serialized
    assert all(client not in serialized for client in ("codex", "claude", "gemini"))
    assert workflow["jobs"]["release-required"]["needs"].count("installed-application") == 1


def test_installed_application_keeps_manager_matrix_and_full_suite_separate():
    job = _workflow(CI_WORKFLOW)["jobs"]["installed-application"]
    commands = [str(step.get("run", "")) for step in job["steps"]]
    manager = [command for command in commands if "release_install_metadata_smoke.py" in command]
    golden = [command for command in commands if "--installed-golden-wheel" in command]

    assert len(manager) == 1
    assert len(golden) == 1
    assert "--all-installers" in manager[0]
    assert "test_cli_golden_scenarios.py" not in manager[0]
    assert "release_install_metadata_smoke.py" not in golden[0]


def test_installed_application_uses_disposable_systemd_user_lifecycle():
    workflow = _workflow(CI_WORKFLOW)
    job = workflow["jobs"]["installed-application"]
    commands = [str(step.get("run", "")) for step in job["steps"]]
    manager = [command for command in commands if "release_install_metadata_smoke.py" in command]

    assert len(manager) == 1
    command = manager[0]
    assert "useradd --create-home" in command
    assert 'systemctl start "user@${lifecycle_uid}.service"' in command
    assert 'XDG_RUNTIME_DIR="$lifecycle_runtime"' in command
    assert 'DBUS_SESSION_BUS_ADDRESS="unix:path=$lifecycle_runtime/bus"' in command
    assert "MEMPALACE_RELEASE_SYSTEMD_USER=1" in command
    assert 'sudo -u "$lifecycle_user" env -i' in command
    assert 'userdel --remove "$lifecycle_user"' in command
    assert "loginctl" not in command
    assert (
        'stage_dir="$(sudo mktemp -d /var/tmp/mempalace-installed-application.XXXXXX)"' in command
    )
    assert 'staged_wheel="$stage_dir/${wheel[0]##*/}"' in command
    assert 'staged_wheel="$stage_dir/candidate.whl"' not in command
    assert 'sudo install -o root -g root -m 0444 -- "$script_source" "$staged_script"' in command
    assert 'sudo install -o root -g root -m 0444 -- "$wheel_source" "$staged_wheel"' in command
    assert 'sudo test -f "$staged_path" && sudo test ! -L "$staged_path"' in command
    assert 'test "$(sudo stat -c %u "$staged_path")" = 0' in command
    assert 'test "$(sudo stat -c %a "$staged_path")" = 444' in command
    assert 'sudo -u "$lifecycle_user" test -r "$staged_path"' in command
    assert 'cmp -s -- "$script_source" "$staged_script"' in command
    assert 'cmp -s -- "$wheel_source" "$staged_wheel"' in command
    assert 'sudo rm -f -- "$staged_script" "$staged_wheel"' in command
    assert 'sudo rmdir -- "$stage_dir"' in command
    assert "rm -rf" not in command
    assert "setsid bash -c" in command
    assert 'exec "$3" "$4" --all-installers --install-spec "$5" --json' in command
    assert 'smoke_identity="$lifecycle_home/.mempalace-release-smoke.identity"' in command
    assert 'smoke_identity_tmp="$smoke_identity.tmp"' in command
    assert "umask 077" in command
    assert r"""trap '\''rm -f -- "$2"'\'' EXIT""" in command
    assert 'test ! -e "$2"\n    test ! -L "$2"' in command
    assert 'printf "%s %s %s %s\\n" "$$" "$$" "$(id -u)" "$3" > "$2"' in command
    assert 'test "$(stat -c %u "$2")" = "$(id -u)"' in command
    assert 'test "$(stat -c %a "$2")" = 600' in command
    assert 'mv -- "$2" "$1"' in command
    write_index = command.index('printf "%s %s %s %s\\n"')
    chmod_index = command.index('chmod 0600 -- "$2"')
    mode_check_index = command.index('test "$(stat -c %a "$2")" = 600')
    publish_index = command.index('mv -- "$2" "$1"')
    assert write_index < chmod_index < mode_check_index < publish_index
    assert command.count("read -r smoke_pid smoke_pgid smoke_uid smoke_command smoke_extra") == 2
    assert (
        'test -n "$smoke_pid" && test -n "$smoke_pgid" && test -n "$smoke_uid" && test -n "$smoke_command"'
        in command
    )
    assert 'test -z "$smoke_extra"' in command
    assert 'test "$smoke_pid" = "$smoke_pgid"' in command
    assert 'test "$smoke_uid" = "$lifecycle_uid"' in command
    assert 'test "$smoke_command" = "$python_bin"' in command
    assert 'test "${smoke_cmdline[0]:-}" = "$python_bin"' in command
    assert 'test "${smoke_cmdline[1]:-}" = "$staged_script"' in command
    assert 'sudo kill -TERM -- "-$smoke_pgid"' in command
    assert 'sudo kill -KILL -- "-$smoke_pgid"' in command
    assert command.count('sudo kill -0 -- "-$smoke_pgid" 2>/dev/null || break') == 2
    assert "disposable smoke process identity or termination failed" in command
    assert 'sudo rm -f -- "$smoke_identity_tmp"' in command
    assert "smoke_started_at=$SECONDS" in command
    assert 'while kill -0 "$smoke_launcher_pid" 2>/dev/null; do' in command
    assert "SECONDS - smoke_started_at >= 2400" in command
    assert (
        "installed-application smoke exceeded its 40-minute deadline; recovery: rerun the installed-application job"
        in command
    )
    assert "exit 124" in command
    assert 'if wait "$smoke_launcher_pid"; then' in command
    assert 'exit "$smoke_launcher_rc"' in command
    assert '\n          wait "$smoke_launcher_pid"\n' not in command
    assert command.index('sudo kill -TERM -- "-$smoke_pgid"') < command.index(
        'userdel --remove "$lifecycle_user"'
    )
    assert '"$python_bin" scripts/release_install_metadata_smoke.py' not in command
    assert '--install-spec "$wheel_path"' not in command
    assert command.index("trap cleanup_lifecycle_user EXIT") < command.index(
        "sudo useradd --create-home"
    )
    assert command.index("trap cleanup_lifecycle_user EXIT") < command.index("sudo mktemp -d")
    assert command.index("lifecycle_created=1") < command.index("sudo useradd --create-home")
    assert all(client not in command for client in ("codex", "claude", "gemini"))
    assert command.count("--all-installers") == 1
    assert workflow["jobs"]["release-required"]["needs"].count("installed-application") == 1


def test_no_ci_job_escapes_the_release_critical_classification():
    """Every ci.yml job is release-critical, the aggregate check, or exempt with a reason.

    The `needs:` comparison above only sees jobs someone already wired in. This
    is the direction that catches a new security-relevant job added to ci.yml
    while `needs:` is left alone — otherwise release-required stays green while
    silently ignoring the new gate.
    """
    jobs = set(_workflow(CI_WORKFLOW)["jobs"])
    unclassified = jobs - {ADMISSION.AGGREGATE_REQUIRED_CHECK}
    unclassified -= set(ADMISSION.RELEASE_CRITICAL_CI_JOBS)
    unclassified -= set(ADMISSION.AGGREGATE_EXEMPT_CI_JOBS)
    assert unclassified == set(), (
        f"ci.yml jobs {sorted(unclassified)} are neither release-critical nor exempt: add them "
        "to RELEASE_CRITICAL_CI_JOBS and the aggregate needs:, or to AGGREGATE_EXEMPT_CI_JOBS "
        "with a reason"
    )


def test_every_exempt_ci_job_exists_and_carries_a_reason():
    jobs = _workflow(CI_WORKFLOW)["jobs"]
    for name, reason in ADMISSION.AGGREGATE_EXEMPT_CI_JOBS.items():
        assert name in jobs, f"exempt job {name!r} no longer exists in ci.yml"
        assert name not in ADMISSION.RELEASE_CRITICAL_CI_JOBS, name
        assert reason.strip(), f"exempt job {name!r} has no recorded reason"


# ── The exemption set cannot absorb a canonical gate ──────────────────────────
def test_aggregate_check_runs_even_when_an_upstream_job_fails_or_skips():
    job = _workflow(CI_WORKFLOW)["jobs"][ADMISSION.AGGREGATE_REQUIRED_CHECK]
    # Without `if: always()` a failed or skipped dependency skips this job too,
    # and a skipped required check does not block.
    assert str(job["if"]).strip() == "always()"


def test_aggregate_check_uses_a_runner_provided_interpreter_and_bash():
    job = _workflow(CI_WORKFLOW)["jobs"][ADMISSION.AGGREGATE_REQUIRED_CHECK]
    step = job["steps"][0]
    # No setup-python step runs here, so the script must call the interpreter that
    # the runner image guarantees.
    assert "python3 -" in step["run"]
    assert "\npython -" not in f"\n{step['run']}"
    assert step["shell"] == "bash"


def test_aggregate_check_expects_the_contract_job_list_at_runtime():
    job = _workflow(CI_WORKFLOW)["jobs"][ADMISSION.AGGREGATE_REQUIRED_CHECK]
    env = job["steps"][0]["env"]
    assert sorted(str(env["EXPECTED_JOBS"]).split()) == sorted(ADMISSION.RELEASE_CRITICAL_CI_JOBS)
    assert env["NEEDS_JSON"] == "${{ toJson(needs) }}"


def _run_aggregate_script(needs: dict) -> tuple[int, str]:
    """Execute the embedded aggregate-check script exactly as the workflow does."""
    import json
    import subprocess

    job = _workflow(CI_WORKFLOW)["jobs"][ADMISSION.AGGREGATE_REQUIRED_CHECK]
    step = job["steps"][0]
    body = step["run"]
    script = body.split("<<'PY'\n", 1)[1].rsplit("PY", 1)[0]
    completed = subprocess.run(
        [sys.executable, "-"],
        input=script,
        capture_output=True,
        text=True,
        env={
            "PATH": "/usr/bin:/bin",
            "NEEDS_JSON": json.dumps(needs),
            "EXPECTED_JOBS": str(step["env"]["EXPECTED_JOBS"]),
        },
    )
    return completed.returncode, completed.stdout + completed.stderr


def _all_successful() -> dict:
    return {name: {"result": "success"} for name in ADMISSION.RELEASE_CRITICAL_CI_JOBS}


def test_aggregate_script_passes_when_every_release_critical_job_succeeded():
    code, output = _run_aggregate_script(_all_successful())
    assert code == 0, output


@pytest.mark.parametrize("result", ["failure", "cancelled", "skipped", "", "neutral"])
def test_aggregate_script_fails_for_every_non_success_result(result):
    needs = _all_successful()
    needs["lint"] = {"result": result}
    code, output = _run_aggregate_script(needs)
    assert code == 1, output
    assert "lint" in output


def test_aggregate_script_fails_when_a_release_critical_job_is_missing():
    needs = _all_successful()
    del needs["typecheck"]
    code, output = _run_aggregate_script(needs)
    assert code == 1
    assert "typecheck: missing from needs" in output


@pytest.mark.parametrize("result", ["failure", "cancelled", "skipped", "", "neutral"])
def test_aggregate_script_fails_closed_for_dotnet_benchmark(result):
    needs = _all_successful()
    needs["dotnet-bench"] = {"result": result}
    code, output = _run_aggregate_script(needs)
    assert code == 1, output
    assert f"dotnet-bench: {result or 'unknown'}" in output


def test_aggregate_script_fails_when_dotnet_benchmark_is_missing():
    needs = _all_successful()
    del needs["dotnet-bench"]
    code, output = _run_aggregate_script(needs)
    assert code == 1, output
    assert "dotnet-bench: missing from needs" in output


def test_aggregate_script_fails_when_installed_application_bootstrap_fails():
    needs = _all_successful()
    needs["installed-application"] = {"result": "failure"}
    code, output = _run_aggregate_script(needs)
    assert code == 1
    assert "installed-application: failure" in output


def test_aggregate_script_fails_when_needs_carries_an_unlisted_job():
    needs = _all_successful()
    needs["some-new-job"] = {"result": "success"}
    code, output = _run_aggregate_script(needs)
    assert code == 1
    assert "some-new-job" in output


def test_aggregate_script_fails_on_a_completely_empty_needs_context():
    code, output = _run_aggregate_script({})
    assert code == 1
    assert "missing from needs" in output


# ci.yml gates these release-critical jobs on the triggering event, so they are
# skipped in a manually dispatched Tests run.
DISPATCH_SKIPPED_RELEASE_CRITICAL_JOBS = ("dependency-upgrade-gate", "gitleaks-changed-range")


def test_dispatch_skipped_jobs_are_release_critical_and_event_gated_in_ci():
    jobs = _workflow(CI_WORKFLOW)["jobs"]
    for name in DISPATCH_SKIPPED_RELEASE_CRITICAL_JOBS:
        assert name in ADMISSION.RELEASE_CRITICAL_CI_JOBS, name
        condition = str(jobs[name].get("if", ""))
        # Event-gated: the job cannot run for every trigger, which is what makes
        # the dispatch replay below a real workflow shape rather than a guess.
        assert "github.event_name" in condition, f"{name} is no longer event-gated: {condition!r}"
        assert "workflow_dispatch" not in condition or "!=" in condition, condition


def test_aggregate_script_fails_for_a_workflow_dispatch_shaped_needs_context():
    """A manually dispatched Tests run must never yield a green release-required.

    `dependency-upgrade-gate` and `gitleaks-changed-range` are skipped on
    `workflow_dispatch`, and skipped fails closed — that is correct: a green
    aggregate check must never be manufacturable on a SHA whose Gitleaks and
    dependency gates never ran. It is also why the remediation re-runs the run
    that already exists instead of dispatching a new one, which would publish
    exactly this failure onto the candidate SHA.
    """
    needs = _all_successful()
    for name in DISPATCH_SKIPPED_RELEASE_CRITICAL_JOBS:
        needs[name] = {"result": "skipped"}

    code, output = _run_aggregate_script(needs)

    assert code == 1, output
    for name in DISPATCH_SKIPPED_RELEASE_CRITICAL_JOBS:
        assert f"{name}: skipped" in output, output


# ── ci.yml: the release-candidate branch is real release evidence ─────────────

# The candidate branch shape the release docs push before `main` ever moves. It is
# in the push trigger so the candidate SHA can carry its own Tests and
# `release-required` results; a SHA promoted to `main` afterwards is then already
# green, which is what keeps the flow working if `main` later gains required checks.
RELEASE_CANDIDATE_BRANCH_PATTERN = "release/v*"

# All-zeros is what GitHub reports as `github.event.before` when a push *creates* a
# branch — exactly how the candidate branch appears. Both range-based gates have to
# resolve a real base for it or they fail closed and the candidate can never go green.
ALL_ZEROS_SHA = "0" * 40
BRANCH_CREATION_FALLBACK_BASE = "origin/main"


def _ci_triggers() -> dict:
    workflow = _workflow(CI_WORKFLOW)
    return workflow[True] if True in workflow else workflow["on"]


def test_ci_push_trigger_covers_main_and_the_release_candidate_branch():
    triggers = _ci_triggers()
    assert triggers["push"]["branches"] == ["main", RELEASE_CANDIDATE_BRANCH_PATTERN]
    # Reviews still happen against `main`; the candidate branch never opens a PR.
    assert triggers["pull_request"]["branches"] == ["main"]


def test_ci_push_trigger_stays_narrow():
    """A catch-all branch pattern would make any pushed branch release evidence."""
    for pattern in _ci_triggers()["push"]["branches"]:
        assert pattern in {"main", RELEASE_CANDIDATE_BRANCH_PATTERN}, pattern


# `if:` guards that still admit a `push` event to a non-default branch. A guard
# outside this set has to be re-reviewed before it can gate a release-critical job.
PUSH_ADMITTING_CONDITIONS = {
    "",
    "always()",
    "github.event_name == 'pull_request' || github.event_name == 'push'",
    "github.event_name != 'workflow_dispatch'",
}


def test_a_release_candidate_push_runs_the_complete_release_required_job_graph():
    """Every release-critical job must run for a push to `release/v*`, not just `main`.

    A job that quietly skipped there would be reported as `skipped` in the
    aggregate's `needs` context, which fails closed — the candidate could never be
    admitted. This is the shape assertion that the extended trigger actually buys a
    complete job graph rather than a partial one.
    """
    jobs = _workflow(CI_WORKFLOW)["jobs"]
    for name in ADMISSION.RELEASE_CRITICAL_CI_JOBS:
        condition = str(jobs[name].get("if", "")).strip()
        assert condition in PUSH_ADMITTING_CONDITIONS, f"{name}: unreviewed guard {condition!r}"
        # A `github.ref` test is the specific way a job would run on `main` but not
        # on the candidate branch, so the two SHAs would not get the same graph.
        assert "github.ref" not in condition, f"{name} is branch-gated: {condition!r}"

    aggregate = jobs[ADMISSION.AGGREGATE_REQUIRED_CHECK]
    assert str(aggregate.get("if", "")).strip() == "always()"
    assert sorted(aggregate["needs"]) == sorted(ADMISSION.RELEASE_CRITICAL_CI_JOBS)


def _ci_step_run(job: str, name_fragment: str) -> str:
    steps = _workflow(CI_WORKFLOW)["jobs"][job]["steps"]
    step = next(s for s in steps if name_fragment in str(s.get("name", "")))
    return str(step["run"])


@pytest.mark.parametrize(
    ("job", "step"),
    [
        ("gitleaks-changed-range", "Derive exact Gitleaks commit range"),
        ("dependency-upgrade-gate", "Dependency upgrade gate"),
    ],
)
def test_range_gates_resolve_a_real_base_when_a_push_creates_the_branch(job, step):
    run = _ci_step_run(job, step)
    assert ALL_ZEROS_SHA in run, f"{job} does not handle the branch-creation sentinel"
    assert BRANCH_CREATION_FALLBACK_BASE in run, f"{job} has no resolvable fallback base"


def test_the_branch_creation_fallback_never_narrows_the_scanned_range():
    """`origin/main..HEAD` is the same commit set as `merge-base(main, HEAD)..HEAD`.

    Falling back to the default branch is therefore honest: it covers every commit
    the candidate branch adds. Pinning it here stops a future edit from swapping in
    `HEAD^`, which would scan only the newest commit of a multi-commit branch.
    """
    for job, step in (
        ("gitleaks-changed-range", "Derive exact Gitleaks commit range"),
        ("dependency-upgrade-gate", "Dependency upgrade gate"),
    ):
        run = _ci_step_run(job, step)
        assert "HEAD^" not in run, f"{job} narrows the range to a single commit"
        assert "HEAD~" not in run, f"{job} narrows the range to a fixed commit count"


@pytest.mark.parametrize("job", ["gitleaks-changed-range", "dependency-upgrade-gate"])
def test_the_range_gates_fetch_deeply_enough_to_resolve_the_fallback_base(job: str):
    """The fallback base is a ref, so it has to exist in the runner's clone.

    A shallow checkout of a freshly pushed `release/v*` branch has no
    `refs/remotes/origin/main`, and the fallback would fail to resolve exactly
    on the push it was written for. `fetch-depth: 0` is what makes it resolvable.
    """
    steps = _workflow(CI_WORKFLOW)["jobs"][job]["steps"]
    checkout = next(s for s in steps if str(s.get("uses", "")).startswith("actions/checkout@"))
    assert checkout["with"]["fetch-depth"] == 0, (
        f"{job}: shallow checkout breaks {BRANCH_CREATION_FALLBACK_BASE}"
    )


# ── publish.yml: admission before artifact build ──────────────────────────────


def test_publish_stays_tag_triggered_only():
    workflow = _workflow(PUBLISH_WORKFLOW)
    triggers = workflow[True] if True in workflow else workflow["on"]
    assert set(triggers) == {"push"}
    assert triggers["push"] == {"tags": ["v*"]}


def test_publish_workflow_default_permissions_stay_read_only():
    workflow = _workflow(PUBLISH_WORKFLOW)
    assert workflow["permissions"] == {"contents": "read"}


def test_publish_has_exactly_the_approved_jobs():
    assert set(_workflow(PUBLISH_WORKFLOW)["jobs"]) == {
        "build",
        "publish",
        "github-release",
    }


def test_every_external_workflow_action_has_an_immutable_sha_and_version_comment():
    external = []
    local = []
    for workflow in WORKFLOWS:
        source = workflow.read_text(encoding="utf-8")
        root = yaml.compose(source)
        assert root is not None, f"{workflow.name} is empty"
        lines = source.splitlines()
        for node in _uses_nodes(root):
            line_number = node.start_mark.line + 1
            assert isinstance(node, yaml.ScalarNode), (
                f"{workflow.name}:{line_number}: uses must be a scalar"
            )
            reference = node.value
            if reference.startswith("./"):
                if workflow == PUBLISH_WORKFLOW:
                    local.append(reference)
                continue

            version = None
            if node.start_mark.line == node.end_mark.line:
                suffix = lines[node.end_mark.line][node.end_mark.column :]
                comment = re.fullmatch(r"\s+#(.*)", suffix)
                if comment is not None:
                    version = comment.group(1).strip()
            external.append((workflow.name, line_number, reference, version))

    assert external
    assert all(re.fullmatch(r"[^@]+@[0-9a-f]{40}", item[2]) for item in external), external
    assert all(item[3] for item in external), external
    assert local == ["./.github/actions/gitleaks-gate"]


def test_trusted_pypi_publish_is_the_only_attestation_generation_path():
    workflow = _workflow(PUBLISH_WORKFLOW)
    uses = [
        str(step["uses"])
        for job in workflow["jobs"].values()
        for step in job.get("steps", [])
        if "uses" in step
    ]
    pypi_publish = [value for value in uses if value.startswith("pypa/gh-action-pypi-publish@")]
    text = PUBLISH_WORKFLOW.read_text(encoding="utf-8").lower()

    assert len(pypi_publish) == 1
    assert workflow["jobs"]["publish"]["environment"] == "release"
    assert workflow["jobs"]["publish"]["permissions"] == {"id-token": "write"}
    assert "actions/attest" not in text
    assert "attest-build-provenance" not in text
    assert "sigstore" not in text
    assert "cosign" not in text
    assert "sbom" not in text
    assert "twine upload" not in text


def test_publish_build_job_holds_only_read_scopes_needed_for_admission():
    # administration:read cannot be granted to GITHUB_TOKEN, so the build job must
    # not depend on it; checks/actions read are the exact admission scopes.
    assert _publish_build_job()["permissions"] == {
        "contents": "read",
        "checks": "read",
        "statuses": "read",
        "actions": "read",
    }


def test_github_release_job_is_the_only_retry_target_and_cannot_publish_to_pypi():
    job = _github_release_job()
    text = "\n".join(str(step) for step in job["steps"])

    assert job["needs"] == "publish"
    assert job["permissions"] == {
        "contents": "write",
        "checks": "read",
        "actions": "read",
    }
    assert "pypa/gh-action-pypi-publish" not in text
    assert "twine upload" not in text
    assert "workflow_dispatch" not in PUBLISH_WORKFLOW.read_text(encoding="utf-8")


def test_github_release_rerun_downloads_the_exact_original_run_artifact():
    downloads = [
        step
        for step in _github_release_job()["steps"]
        if str(step.get("uses", "")).startswith("actions/download-artifact@")
    ]

    assert len(downloads) == 1
    assert downloads[0]["with"] == {
        "name": "dist",
        "path": "dist/",
        "run-id": "${{ github.run_id }}",
        "repository": "${{ github.repository }}",
        "github-token": "${{ github.token }}",
    }


def test_github_release_rerun_rechecks_exact_repository_tag_sha_and_admission():
    step = next(
        item
        for item in _github_release_job()["steps"]
        if item.get("name") == "Re-verify exact SHA release admission"
    )
    run = step["run"]

    assert 'test "$GITHUB_REPOSITORY" = "rergards/mempalace-code"' in run
    assert 'test "$GITHUB_EVENT_NAME" = "push"' in run
    assert 'git rev-parse --verify "refs/tags/${TAG_NAME}^{commit}"' in run
    assert 'test "$TAG_SHA" = "$GITHUB_SHA"' in run
    assert "--check-public-main" in run
    assert "git fetch" not in run
    assert '--expect-sha "$TAG_SHA"' in run
    assert "--check-required-check" in run
    assert "--check-dependency-audit" in run
    assert "--check-branch-rules" in run
    assert "--check-tag-ruleset" in run


def test_github_release_rerun_rechecks_artifact_pypi_and_provenance_identity():
    steps = _github_release_job()["steps"]
    names = [step.get("name") for step in steps]
    assert "Inspect original-run distributions" in names
    match = next(
        step
        for step in steps
        if step.get("name") == "Match original-run distributions to PyPI and provenance"
    )["run"]

    assert "fetch_pypi_distributions" in match
    assert "set(public_by_name)" in match
    assert "hashlib.sha256" in match
    assert "_publisher_identity_matches" in match
    assert '"pypi-attestations"' in match
    assert '"--repository"' in match
    assert "_credential_free_env" in match
    assert "_isolate_probe_state" in match
    assert "_default_run_subprocess" in match
    assert "MAX_VERIFIER_OUTPUT_BYTES" in match
    assert "subprocess.run" not in match


def test_github_release_reconciliation_is_idempotent_and_fails_closed_on_asset_drift():
    run = next(
        step["run"]
        for step in _github_release_job()["steps"]
        if step.get("name") == "Create or reconcile the public GitHub Release"
    )

    assert re.search(r'"release",\s+"create"', run)
    assert '"--verify-tag"' in run
    assert re.search(r'"release",\s+"upload"', run)
    assert "existing release has duplicate or unexpected assets" in run
    assert "release asset digest differs" in run
    assert "final release asset filename set differs" in run
    assert "--clobber" not in run
    assert '"release", "delete"' not in run


def test_admission_step_runs_before_any_artifact_is_built_or_uploaded():
    steps = _publish_build_job()["steps"]
    names = [str(step.get("name", step.get("uses", ""))) for step in steps]
    admission_index = names.index("Verify exact SHA release admission")
    live_upstream_index = names.index("Upstream comparison guard (live head, read-only)")
    build_index = names.index("Build distributions")
    dist_upload_index = next(
        index
        for index, step in enumerate(steps)
        if str(step.get("uses", "")).startswith("actions/upload-artifact")
        and step.get("with", {}).get("name") == "dist"
    )
    assert admission_index < live_upstream_index < build_index < dist_upload_index


def test_admission_step_binds_the_exact_tag_commit_and_public_candidate_ref():
    steps = _publish_build_job()["steps"]
    step = next(s for s in steps if s.get("name") == "Verify exact SHA release admission")
    run = step["run"]

    assert step["shell"] == "bash"
    assert "set -euo pipefail" in run
    # Fully qualified tag ref: a same-named branch must not be resolvable here.
    assert 'git rev-parse --verify "refs/tags/${TAG_NAME}^{commit}"' in run
    assert "--check-public-main" in run
    assert "git fetch" not in run
    assert '--expect-sha "$TAG_SHA"' in run
    assert "--candidate-ref" not in run
    assert '--repo "$GITHUB_REPOSITORY"' in run
    assert "--require-clean" in run
    # The tag name arrives through env, never interpolated into the shell body.
    assert step["env"]["TAG_NAME"] == "${{ github.ref_name }}"
    assert "${{ github.ref_name }}" not in run


def test_admission_step_requires_check_audit_branch_and_tag_rules():
    steps = _publish_build_job()["steps"]
    run = next(s for s in steps if s.get("name") == "Verify exact SHA release admission")["run"]

    assert "--check-required-check" in run
    assert "--check-dependency-audit" in run
    assert "--check-branch-rules" in run
    assert "--check-tag-ruleset" in run


def test_publish_keeps_gitleaks_full_history_admission_before_admission_step():
    steps = _publish_build_job()["steps"]
    names = [str(step.get("name", step.get("uses", ""))) for step in steps]
    assert any("gitleaks-gate" in name for name in names)
    assert any("full-history" in str(step.get("run", "")) for step in steps)


ARTIFACT_GATE_STEP_NAME = "Inspect built distributions"
ARTIFACT_GATE_COMMAND = (
    "python scripts/release_artifact_gate.py --dist dist --require-wheel --require-sdist"
)
BUILD_COMMAND = "python -m build"


def _gate_index(job: dict) -> int:
    """Locate the gate step by name, so every assertion below is about that step."""
    matches = [
        i for i, step in enumerate(job["steps"]) if step.get("name") == ARTIFACT_GATE_STEP_NAME
    ]
    assert len(matches) == 1, f"expected exactly one {ARTIFACT_GATE_STEP_NAME!r} step"
    return matches[0]


def _artifact_gate_violations(job: dict, *, upload_must_follow: bool) -> list[str]:
    """Return the ways a job's artifact-gate wiring departs from the contract.

    Written as a predicate rather than inline asserts so the mutation test below
    can prove it rejects the shapes it is supposed to reject.
    """
    steps = job.get("steps", [])
    matched = [i for i, step in enumerate(steps) if step.get("name") == ARTIFACT_GATE_STEP_NAME]
    if len(matched) != 1:
        return [f"expected one {ARTIFACT_GATE_STEP_NAME!r} step, found {len(matched)}"]
    index = matched[0]
    step = steps[index]

    violations: list[str] = []
    # Equality, not containment: a trailing `|| true` or a dropped --require flag
    # keeps a substring match satisfied while changing what the gate asserts.
    if str(step.get("run", "")).strip() != ARTIFACT_GATE_COMMAND:
        violations.append(f"gate runs {str(step.get('run', '')).strip()!r}")
    if "continue-on-error" in step:
        violations.append("gate step is continue-on-error")
    if "continue-on-error" in job:
        violations.append("owning job is continue-on-error")

    builds = [i for i, s in enumerate(steps) if str(s.get("run", "")).strip() == BUILD_COMMAND]
    if len(builds) != 1:
        violations.append(f"expected one {BUILD_COMMAND!r} step, found {len(builds)}")
    elif builds[0] > index:
        violations.append("gate runs before the build")

    if upload_must_follow:
        uploads = [
            i
            for i, s in enumerate(steps)
            if str(s.get("uses", "")).startswith("actions/upload-artifact")
            and s.get("with", {}).get("name") == "dist"
        ]
        if len(uploads) != 1:
            violations.append(f"expected one dist upload, found {len(uploads)}")
        elif uploads[0] != index + 1:
            violations.append("a step runs between inspection and upload")
    return violations


@pytest.mark.parametrize(
    ("workflow", "job", "upload_must_follow"),
    [(CI_WORKFLOW, "package", False), (PUBLISH_WORKFLOW, "build", True)],
    ids=["ci-package", "publish-build"],
)
def test_artifact_gate_wiring_matches_the_contract(
    workflow: Path, job: str, upload_must_follow: bool
):
    """The gate runs the exact command, after the build, and cannot be soft-failed.

    In publish the upload must follow it immediately: any step in between could
    rewrite or add a file, and the artifact that leaves the job would be one no
    gate ever read.
    """
    parsed = _workflow(workflow)["jobs"][job]
    assert _artifact_gate_violations(parsed, upload_must_follow=upload_must_follow) == []


def _soft_fail_the_gate(job: dict) -> None:
    job["steps"][_gate_index(job)]["continue-on-error"] = True


def _soft_fail_the_job(job: dict) -> None:
    job["continue-on-error"] = True


def _widen_the_gate_command(job: dict) -> None:
    job["steps"][_gate_index(job)]["run"] += " || true"


def _drop_a_required_flag(job: dict) -> None:
    step = job["steps"][_gate_index(job)]
    step["run"] = step["run"].replace(" --require-sdist", "")


def _repack_after_the_gate(job: dict) -> None:
    job["steps"].insert(_gate_index(job) + 1, {"name": "Repack", "run": "touch dist/extra.whl"})


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (_soft_fail_the_gate, "gate step is continue-on-error"),
        (_soft_fail_the_job, "owning job is continue-on-error"),
        (_widen_the_gate_command, "gate runs"),
        (_drop_a_required_flag, "gate runs"),
        (_repack_after_the_gate, "a step runs between inspection and upload"),
    ],
    ids=["soft-fail-step", "soft-fail-job", "or-true", "dropped-flag", "repack-after-gate"],
)
def test_the_gate_contract_rejects_each_way_it_could_be_weakened(mutate, expected: str):
    """A contract that passes on the shapes it forbids is not a contract."""
    job = copy.deepcopy(_publish_build_job())
    mutate(job)
    violations = _artifact_gate_violations(job, upload_must_follow=True)
    assert any(expected in violation for violation in violations), violations


@pytest.mark.parametrize("workflow", [CI_WORKFLOW, PUBLISH_WORKFLOW])
def test_no_job_runs_a_standalone_twine_check(workflow: Path):
    # The artifact gate invokes twine itself. A second bare invocation reads as
    # independent coverage while asserting strictly less than the gate around it.
    for job in _workflow(workflow)["jobs"].values():
        for step in job.get("steps", []):
            assert "twine check" not in str(step.get("run", ""))


def test_publish_never_gains_a_manual_or_release_trigger():
    text = PUBLISH_WORKFLOW.read_text(encoding="utf-8")
    assert "workflow_dispatch" not in text
    assert "\n  release:" not in text


def test_benchmark_owner_uses_canonical_fastembed_cache():
    job = _workflow(CI_WORKFLOW)["jobs"]["dotnet-bench"]
    text = str(job)
    assert ".cache/huggingface/mempalace-fastembed/all-MiniLM-L6-v2-v1" in text
    assert "hub/models--sentence-transformers--all-MiniLM-L6-v2" not in text
    assert "--check-facts benchmarks/retrieval_quality_facts.json" not in text
