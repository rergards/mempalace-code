"""Section-bound contracts for agent skill mutation authority."""

from __future__ import annotations

import json
import subprocess
import tomllib
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parent.parent
SKILLS = ROOT / ".claude" / "skills"
PLANS = ROOT / "docs" / "plans"
PLAN_CONTRACT = PLANS / "README.md"
PLAN_LIFECYCLE_STATES = {"active", "completed", "superseded", "historical"}


def _read(relative: str) -> str:
    return (SKILLS / relative).read_text(encoding="utf-8")


def _section(text: str, start: str, end: str) -> str:
    return text[text.index(start) : text.index(end, text.index(start) + len(start))]


def _assert_in_order(text: str, *needles: str) -> None:
    positions = [text.index(needle) for needle in needles]
    assert positions == sorted(positions), dict(zip(needles, positions, strict=True))


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def _front_matter(text: str) -> tuple[dict[str, object], list[str], str]:
    assert text.startswith("---\n"), "plan must start with YAML front matter"
    raw, separator, body = text[4:].partition("\n---\n")
    if not separator:
        raw, heading, body = text[4:].partition("\n\n## ")
        assert heading, "plan metadata must end before the first Markdown heading"
        body = f"## {body}"
    parsed: dict[str, object] = {}
    lifecycle_keys = {"slug", "status", "authority", "superseded_by", "public_evidence"}
    for line in raw.splitlines():
        if line.startswith((" ", "\t")) or ":" not in line:
            continue
        key, value = line.split(":", 1)
        if key in lifecycle_keys:
            parsed[key] = yaml.safe_load(value.strip())
    return parsed, raw.splitlines(), body


def _backlog_keys(path: Path, *, require_open: bool = False) -> set[str]:
    parsed = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError(f"malformed backlog source: {path.name}")
    items = parsed.get("items", [])
    if items is None:  # Historical fixtures encode empty lists as YAML null.
        items = []
    if not isinstance(items, list):
        raise ValueError(f"malformed backlog items: {path.name}")
    keys: set[str] = set()
    selected: set[str] = set()
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("key"), str):
            raise ValueError(f"malformed backlog item: {path.name}")
        key = item["key"]
        if key in keys:
            raise ValueError(f"duplicate backlog key: {key}")
        keys.add(key)
        if not require_open or item.get("status") == "open":
            selected.add(key)
    return selected


def _strict_json(path: Path) -> dict:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key in {path.name}: {key}")
            result[key] = value
        return result

    parsed = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)
    if not isinstance(parsed, dict):
        raise ValueError(f"malformed canonical source: {path.name}")
    return parsed


def _canonical_plan_states(root: Path) -> dict[str, str] | None:
    store = root / ".backlog"
    if not store.exists():
        return None
    try:
        if _strict_json(store / "format.json").get("format") != "backlog-files/v2":
            raise ValueError("unsupported canonical backlog format")
        project = store / "projects" / "mempalace-code"
        metadata = _strict_json(project / "project.json")
        if metadata.get("project") != "mempalace-code":
            raise ValueError("mismatched canonical backlog project")
        states: dict[str, str] = {}
        for path in sorted((project / "tasks").glob("*.json")):
            envelope = _strict_json(path)
            if envelope.get("format") != "backlog-task-envelope/v2":
                raise ValueError(f"malformed canonical task envelope: {path.name}")
            record = envelope["task_record"]
            task = record["task"]
            key, state = task["id"], task["state"]
            if not isinstance(key, str) or not key or task["project"] != "mempalace-code":
                raise ValueError(f"malformed canonical task identity: {path.name}")
            if key in states:
                raise ValueError(f"duplicate canonical task: {key}")
            if path.stem != key or task["schema"] != "backlog/v1":
                raise ValueError(f"mismatched canonical task: {path.name}")
            if state not in {"draft", "open", "done", "cancelled"}:
                raise ValueError(f"malformed canonical task state: {key}")
            if state == "done":
                # completion_valid is cached; native derive owns dependency validity.
                # This lifecycle check only verifies the structural completion receipt.
                completion = task.get("completion")
                if not isinstance(completion, dict):
                    raise ValueError(f"invalid canonical completion: {key}")
                result = completion.get("result")
                evidence = completion.get("evidence")
                acceptance = task.get("acceptance")
                digest = task.get("contract_digest")
                if (
                    not isinstance(result, str)
                    or not result.strip()
                    or not isinstance(digest, str)
                    or not digest
                    or completion.get("contract_digest") != digest
                    or not isinstance(evidence, list)
                    or not isinstance(acceptance, list)
                    or not acceptance
                ):
                    raise ValueError(f"invalid canonical completion: {key}")
                acceptance_ids = [criterion["id"] for criterion in acceptance]
                evidence_ids = [entry["acceptance_id"] for entry in evidence]
                if (
                    len(set(acceptance_ids)) != len(acceptance_ids)
                    or sorted(evidence_ids) != sorted(acceptance_ids)
                    or any(
                        entry.get("verification_result") != "pass"
                        or not isinstance(entry.get("artifact_ref"), str)
                        or not entry["artifact_ref"].strip()
                        for entry in evidence
                    )
                ):
                    raise ValueError(f"invalid canonical completion: {key}")
            states[key] = {"open": "active", "done": "completed"}.get(state, "historical")
        return states
    except (OSError, KeyError, TypeError) as error:
        raise ValueError(f"malformed canonical backlog: {error}") from error


def _expected_plan_status(root: Path, slug: str) -> str:
    canonical = _canonical_plan_states(root)
    archived_keys = _backlog_keys(root / "docs" / "BACKLOG-archived.yaml")
    if canonical is not None:
        if _backlog_keys(root / "docs" / "BACKLOG.yaml"):
            raise ValueError("duplicate active backlog source: docs/BACKLOG.yaml")
        if slug in canonical:
            if canonical[slug] != "completed" and slug in archived_keys:
                raise ValueError(f"contradictory repository lifecycle for {slug}")
            return canonical[slug]
        return "completed" if slug in archived_keys else "historical"
    open_keys = _backlog_keys(root / "docs" / "BACKLOG.yaml", require_open=True)
    if slug in open_keys and slug in archived_keys:
        raise ValueError(f"contradictory repository lifecycle for {slug}")
    if slug in open_keys:
        return "active"
    return "completed" if slug in archived_keys else "historical"


def _plan_lifecycle_errors(root: Path, relative: str) -> list[str]:
    text = (root / relative).read_text(encoding="utf-8")
    metadata, lines, _ = _front_matter(text)
    status_lines = [line for line in lines if line.startswith("status:")]
    authority_lines = [line for line in lines if line.startswith("authority:")]
    errors: list[str] = []
    if len(status_lines) != 1:
        errors.append(f"expected exactly one lifecycle status; found {len(status_lines)}")
    status = metadata.get("status")
    if status not in PLAN_LIFECYCLE_STATES:
        errors.append(f"unsupported lifecycle status: {status!r}")
    if len(authority_lines) != 1 or metadata.get("authority") != "non_authoritative":
        errors.append("expected exactly one authority: non_authoritative marker")
    slug = metadata.get("slug")
    if not isinstance(slug, str):
        errors.append("plan slug must be a string")
        return errors
    try:
        expected = _expected_plan_status(root, slug)
    except ValueError as error:
        errors.append(str(error))
        return errors
    if status == "superseded":
        if not isinstance(metadata.get("superseded_by"), str):
            errors.append("superseded lifecycle requires a superseded_by reference")
    elif status in PLAN_LIFECYCLE_STATES and status != expected:
        errors.append(f"repository lifecycle for {slug} requires {expected}; found {status}")
    return errors


def _write_lifecycle_fixture(
    root: Path,
    front_matter: str,
    *,
    open_keys: tuple[str, ...] = (),
    archived_keys: tuple[str, ...] = (),
) -> str:
    plans = root / "docs" / "plans"
    plans.mkdir(parents=True)
    relative = "docs/plans/FIXTURE.md"
    (root / relative).write_text(
        f"---\n{front_matter}\n---\n\n```sh\nmutate\n```\n",
        encoding="utf-8",
    )
    open_items = "".join(f"  - key: {key}\n    status: open\n" for key in open_keys)
    archived_items = "".join(f"  - key: {key}\n" for key in archived_keys)
    (root / "docs" / "BACKLOG.yaml").write_text(f"items:\n{open_items}", encoding="utf-8")
    (root / "docs" / "BACKLOG-archived.yaml").write_text(
        f"items:\n{archived_items}",
        encoding="utf-8",
    )
    return relative


def test_plan_and_hardening_preserve_state_before_initialization():
    state = _read("_shared/task-state.md")
    admission = _section(state, "## State Admission", "## State Record")
    _assert_in_order(
        admission,
        "inspect whether it exists",
        "Inspect the current Git root",
        "autopilot doctor --json",
        "autopilot status",
        "phase_write_allowed=true",
        "safe_to_edit=true",
        "absent plus",
        "valid matching state is resumed",
        "active-owner, blocked, resumable, stale, malformed, unknown, mismatched, or",
    )
    assert "Never overwrite, clear, repair, or replace evidence" in admission

    for relative in ("task-plan/INSTRUCTIONS.md", "task-hardening/INSTRUCTIONS.md"):
        instructions = _read(relative)
        section = _section(
            instructions,
            "## 1. Admit Existing State Before Initialization",
            "## 2.",
        )
        assert "`.claude/skills/_shared/task-state.md` in full" in section
        assert "sole owner of admission, persistence, resume, and\nrecovery behavior" in section
        assert "Recovery: `autopilot doctor --json`" in section
        assert "phase_write_allowed" not in section
        assert "safe_to_edit" not in section


def test_ship_and_checkpoint_require_ordered_exact_target_admission():
    ship = _read("ship/INSTRUCTIONS.md")
    target = _section(ship, "## 2. Admit the Exact Target", "## 3.")
    _assert_in_order(
        target,
        "exact repository root and Git directory",
        "Resolve live ownership",
        "literal remote name and URL",
        "full destination ref",
        "40-hex local SHA",
        "Normalize the supported remote URL",
        "gh repo view --json nameWithOwner,isPrivate",
        "git ls-remote <remote> <full-ref>",
    )
    assert "mismatched identity or visibility stops" in target
    assert "Perform no push here" in target
    assert ".claude/skills/release/SKILL.md" in target

    checkpoint = _read("_shared/commit-checkpoint.md")
    admission = _section(checkpoint, "## Read-Only Admission", "## Mutation Admission")
    _assert_in_order(
        admission,
        "repository root and Git directory",
        "git status --porcelain",
        "Resolve the live owner",
        "literal remote name, URL, full destination ref",
        "Normalize the URL",
        "gh repo view --json nameWithOwner,isPrivate",
        "exact staged content and exact commit message or amend command",
        "requesting authority",
    )
    assert "Unknown identity, visibility, ref, or SHA stops" in admission
    assert "Public targets and release intent leave this checkpoint read-only" in admission
    assert "/tmp/claude-edits.log" not in checkpoint
    assert 'if [ -n "${AUTOPILOT_TASK_STATE:-}" ]; then' in admission
    assert 'state_file="$AUTOPILOT_TASK_STATE"' in admission
    assert 'elif [ -n "${task_slug:-}" ]; then' in admission
    assert 'state_file="/tmp/claude-task-state-${task_slug}.json"' in admission
    assert 'echo "ERROR: exact task state path or task slug required" >&2' in admission
    assert "${task_slug:-unknown}" not in admission
    assert 'if [ -e "$state_file" ]; then' in admission
    assert "python -c '" in admission
    assert '"$state_file" 2>/dev/null; then' in admission
    assert (
        'files = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))["modified_files"]'
        in admission
    )
    assert (
        "valid = isinstance(files, list) and all(isinstance(item, str) for item in files)"
        in admission
    )
    assert 'sys.exit(1) if not valid else print(*sorted(set(files)), sep="\\n")' in admission
    assert "lambda files" not in admission
    assert "(_ for _ in ())" not in admission
    assert 'echo "ERROR: invalid task state" >&2' in admission
    assert "<<'PY'" not in admission
    assert "grep -oP" not in admission
    assert "git diff --name-only && git diff --name-only --cached" in admission
    assert "If another agent has\n   an uncommitted edit" in admission
    _assert_in_order(
        admission,
        "git status --porcelain",
        'if [ -e "$state_file" ]; then',
        "git diff --name-only && git diff --name-only --cached",
        "If another agent has\n   an uncommitted edit",
    )
    scan = checkpoint[checkpoint.index("Before staging any public diff") :]
    assert "python scripts/public_safety_scan.py --tracked --staged" in scan
    assert "Review any reported false positive explicitly" in scan
    _assert_in_order(
        scan,
        "Before staging any public diff",
        "python scripts/public_safety_scan.py --tracked --staged",
        "Review any reported false positive explicitly",
    )


def test_each_mutation_requires_fresh_exact_single_use_authority():
    checkpoint = _read("_shared/commit-checkpoint.md")
    mutation = _section(checkpoint, "## Mutation Admission", "## Execute One Authorized Action")
    for authority in (
        "staging authority",
        "commit authority",
        "amend authority",
        "ordinary-push authority",
    ):
        assert authority in mutation
    assert "one named mutation attempt only" in mutation
    assert "consumed when the command starts, including failure or ambiguous outcome" in mutation
    assert "retries, reordered commands, invocations, repositories, or skills" in mutation

    for relative, heading in (
        ("task-plan/INSTRUCTIONS.md", "## 5. Admit Each Tracked or Remote Mutation Separately"),
        ("task-hardening/INSTRUCTIONS.md", "## 4. Admit Each Mutation Separately"),
    ):
        instructions = _read(relative)
        section = instructions[instructions.index(heading) :]
        for authority in (
            "source edit" if relative.startswith("task-plan") else "fix authority",
            "backlog",
            "staging",
            "commit",
            "amend",
            "ordinary push" if relative.startswith("task-plan") else "ordinary-push",
            "publication",
        ):
            assert authority in section, (relative, authority)
        assert "single-use authority" in section
        assert "consumed when its command starts" in section
        assert "reordered" in section
        assert "invocations" in section


def test_provider_failure_and_partial_invocation_preserve_bound_evidence():
    state = _read("_shared/task-state.md")
    failure = _section(state, "## Provider-Failure Evidence", "## Commit Checkpoint Integration")
    for field in ("run_id", "attempt", "provider", "model", "phase", "freshness"):
        assert field in failure
    assert "does not require a\nbacklog edit, tracked report, staging, or commit" in failure
    assert "Keep completed evidence and completed actions" in failure
    assert "single remaining exact action" in failure
    assert "never replay a\ncompleted action" in failure

    for relative, heading, end in (
        ("task-plan/INSTRUCTIONS.md", "## 4. Handle Provider Failure or Partial Resume", "## 5."),
        (
            "task-hardening/INSTRUCTIONS.md",
            "## 3. Preserve Evidence Across Failure and Partial Invocation",
            "## 4.",
        ),
    ):
        section = _section(_read(relative), heading, end)
        normalized = " ".join(section.split())
        for field in ("run", "attempt", "provider", "model", "phase", "freshness"):
            assert field in section, (relative, field)
        assert "does not require a backlog" in normalized
        assert "post-state" in section
        assert "completed" in section
        assert "single remaining exact action" in section


def test_skill_entrypoints_and_section_bound_contracts_agree():
    entrypoint = _read("ship/SKILL.md")
    instructions = _read("ship/INSTRUCTIONS.md")
    assert "Report-first workflow" in entrypoint
    assert "readiness report" in entrypoint
    assert "does not authorize fixes, staging, commit, amend, push, or\npublication" in entrypoint
    assert "Autonomous loop" not in entrypoint
    assert "Invocation authorizes read-only inspection, verification" in instructions

    push = _section(instructions, "## 4. Admit One Ordinary Private Push", "## 5.")
    assert "isPrivate=true" in push
    assert "git push <literal-remote> <40-hex-local-sha>:<full-destination-ref>" in push
    assert "Do not use\na branch name, tag, or `HEAD` as the source refspec" in push
    _assert_in_order(
        push,
        "Request fresh ordinary-push authority",
        "immutable SHA as its source refspec",
        "Immediately before execution, re-read live ownership",
        "resolve the intended local\nsource ref to its 40-hex SHA",
        "resolved local SHA to equal both the authorized SHA",
    )
    assert "Any change invalidates authority" in push
    assert "Never rebase, force, retarget, or retry automatically" in push

    checkpoint = _read("_shared/commit-checkpoint.md")
    mutation = _section(checkpoint, "## Mutation Admission", "## Execute One Authorized Action")
    assert "amend authority" in mutation
    assert "retries, reordered commands, invocations" in mutation

    for relative in ("task-plan/INSTRUCTIONS.md", "task-hardening/INSTRUCTIONS.md"):
        text = _read(relative)
        preamble = text[: text.index("## 1.")]
        assert "report" in preamble.lower()
        assert "does not authorize" in preamble


def test_tracked_plan_lifecycle_metadata_matches_repository_state():
    tracked_markdown = _git("ls-files", "docs/plans/*.md").splitlines()
    contract_relative = "docs/plans/README.md"
    implementation_plans = [
        relative
        for relative in tracked_markdown
        if relative != contract_relative and (ROOT / relative).is_file()
    ]
    existing_tracked = {relative for relative in tracked_markdown if (ROOT / relative).is_file()}
    assert PLAN_CONTRACT.is_file()
    assert all(relative.startswith("docs/plans/") for relative in implementation_plans)
    assert existing_tracked - set(implementation_plans) <= {contract_relative}
    assert implementation_plans

    for relative in implementation_plans:
        text = (ROOT / relative).read_text(encoding="utf-8")
        metadata, lines, _ = _front_matter(text)
        assert sum(line.startswith("status:") for line in lines) == 1, relative
        assert sum(line.startswith("authority:") for line in lines) == 1, relative
        assert metadata["status"] in PLAN_LIFECYCLE_STATES, relative
        assert metadata["authority"] == "non_authoritative", relative
        assert metadata["status"] == _expected_plan_status(ROOT, str(metadata["slug"])), relative

    current = _front_matter((PLANS / "DOC-PLAN-LIFECYCLE-BOUNDARY.md").read_text())[0]
    assert current["public_evidence"] == ["docs/plans/"]


def test_plan_lifecycle_contract_and_task_skill_agree():
    contract = PLAN_CONTRACT.read_text(encoding="utf-8")
    instructions = _read("task-plan/INSTRUCTIONS.md")
    for marker in (
        ".backlog",
        "docs/BACKLOG.yaml",
        "docs/BACKLOG-archived.yaml",
        "status: active",
        "completed",
        "superseded",
        "historical",
        "authority: non_authoritative",
        "owner decision",
    ):
        assert marker in contract, marker
        assert marker in instructions, marker
    assert "Every mutation requires fresh, exact, current, single-use authority" in contract
    assert (
        "Plans describe\noutcomes and high-level approach; they do not grant implementation authority"
        in instructions
    )


def test_plan_lifecycle_contract_rejects_missing_or_contradictory_status(tmp_path: Path):
    cases = (
        (
            "slug: FIXTURE\nauthority: non_authoritative",
            (),
            (),
            "expected exactly one lifecycle status; found 0",
        ),
        (
            "slug: FIXTURE\nstatus: historical\nstatus: completed\nauthority: non_authoritative",
            (),
            ("FIXTURE",),
            "expected exactly one lifecycle status; found 2",
        ),
        (
            "slug: FIXTURE\nstatus: retired\nauthority: non_authoritative",
            (),
            (),
            "unsupported lifecycle status: 'retired'",
        ),
        (
            "slug: FIXTURE\nstatus: historical\nauthority: non_authoritative",
            (),
            ("FIXTURE",),
            "repository lifecycle for FIXTURE requires completed; found historical",
        ),
        (
            "slug: FIXTURE\nstatus: historical",
            (),
            (),
            "expected exactly one authority: non_authoritative marker",
        ),
        (
            "slug: 42\nstatus: historical\nauthority: non_authoritative",
            (),
            (),
            "plan slug must be a string",
        ),
        (
            "slug: FIXTURE\nstatus: superseded\nauthority: non_authoritative",
            (),
            (),
            "superseded lifecycle requires a superseded_by reference",
        ),
        (
            "slug: FIXTURE\nstatus: active\nauthority: non_authoritative",
            ("FIXTURE",),
            ("FIXTURE",),
            "contradictory repository lifecycle for FIXTURE",
        ),
    )
    for index, (front_matter, open_keys, archived_keys, expected) in enumerate(cases):
        fixture_root = tmp_path / str(index)
        relative = _write_lifecycle_fixture(
            fixture_root,
            front_matter,
            open_keys=open_keys,
            archived_keys=archived_keys,
        )
        assert expected in _plan_lifecycle_errors(fixture_root, relative)

    valid_superseded = _write_lifecycle_fixture(
        tmp_path / "valid-superseded",
        "slug: FIXTURE\nstatus: superseded\nauthority: non_authoritative\n"
        "superseded_by: REPLACEMENT",
    )
    assert _plan_lifecycle_errors(tmp_path / "valid-superseded", valid_superseded) == []


def test_plan_lifecycle_contract_rejects_stale_active_status(tmp_path: Path):
    relative = _write_lifecycle_fixture(
        tmp_path,
        "slug: FIXTURE\nstatus: active\nauthority: non_authoritative",
    )
    assert _plan_lifecycle_errors(tmp_path, relative) == [
        "repository lifecycle for FIXTURE requires historical; found active"
    ]


def test_historical_plan_direct_retrieval_is_non_authoritative():
    tracked = _git("ls-files", "docs/plans/*.md").splitlines()
    historical = []
    for relative in tracked:
        if relative == "docs/plans/README.md" or not (ROOT / relative).is_file():
            continue
        text = (ROOT / relative).read_text(encoding="utf-8")
        metadata, _, _ = _front_matter(text)
        if _expected_plan_status(ROOT, str(metadata["slug"])) == "historical":
            historical.append((relative, text, metadata))
    assert historical
    relative, text, metadata = historical[0]
    assert _git("ls-files", "--error-unmatch", relative).strip() == relative
    assert metadata["status"] == "historical"
    assert metadata["authority"] == "non_authoritative"
    command_boundary = text.find("`")
    assert command_boundary > 0
    assert text.index("status: historical") < command_boundary
    assert text.index("authority: non_authoritative") < command_boundary


def test_plan_repository_and_distribution_boundaries_are_truthful():
    historical = PLANS / "AUTOPILOT-DEMO-QUALITY-ROADMAP.md"
    assert _git("ls-files", "--error-unmatch", str(historical.relative_to(ROOT))).strip()
    ignored = subprocess.run(
        ["git", "check-ignore", "--no-index", "docs/plans/UNTRACKED-PROBE.md"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert ignored.stdout.strip() == "docs/plans/UNTRACKED-PROBE.md"

    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    hatch = project["tool"]["hatch"]["build"]["targets"]
    assert hatch["wheel"]["packages"] == ["mempalace_code"]
    assert "docs/plans/" in hatch["sdist"]["exclude"]
    assert not historical.is_relative_to(ROOT / "mempalace_code")
    assert "repository search" in PLAN_CONTRACT.read_text(encoding="utf-8")


def _canonical_lifecycle_fixture(root: Path, task: dict) -> Path:
    store = root / ".backlog"
    project = store / "projects" / "mempalace-code"
    tasks = project / "tasks"
    tasks.mkdir(parents=True, exist_ok=True)
    (store / "format.json").write_text(json.dumps({"format": "backlog-files/v2"}))
    (project / "project.json").write_text(json.dumps({"project": "mempalace-code"}))
    path = tasks / f"{task['id']}.json"
    path.write_text(
        json.dumps({"format": "backlog-task-envelope/v2", "task_record": {"task": task}})
    )
    return path


def test_canonical_migration_keeps_held_tasks_open_and_plans_non_authoritative(tmp_path: Path):
    # Retained native snapshots survive squashed and shallow public release history.
    original = ROOT / ".backlog" / "projects" / "mempalace-code" / "tasks"
    initial_tasks = []
    for key in (
        "WING-MIGRATION-FULL-COPY-QUALIFICATION",
        "LOCAL-ROLLOUT-RECONCILE-AND-ACCEPT",
    ):
        envelope = _strict_json(original / f"{key}.json")
        assert envelope["format"] == "backlog-task-envelope/v2"
        task = min(
            (
                entry["task"]
                for entry in envelope["task_record"]["history"]
                if entry["task"]["state"] == "open"
            ),
            key=lambda snapshot: snapshot["revision"],
        )
        assert task["id"] == key
        assert task["state"] == "open"
        assert task["completion_valid"] is False
        initial = next(node for node in envelope["planning"]["nodes"] if not node["parents"])
        assert initial["payload"]["expected_planning_version"] == "unplanned"
        assert initial["state"]["hold"]["reason"]
        assert initial["state"]["priority"] == "P2"
        root = tmp_path / key
        relative = _write_lifecycle_fixture(
            root, f"slug: {key}\nstatus: active\nauthority: non_authoritative"
        )
        _canonical_lifecycle_fixture(root, task)
        assert _expected_plan_status(root, key) == "active"
        assert _plan_lifecycle_errors(root, relative) == []
        initial_tasks.append(task)

    root = tmp_path / "FIXTURE"
    relative = _write_lifecycle_fixture(
        root, "slug: FIXTURE\nstatus: active\nauthority: non_authoritative"
    )
    fixture = dict(initial_tasks[0], id="FIXTURE")
    _canonical_lifecycle_fixture(root, fixture)
    assert _plan_lifecycle_errors(root, relative) == []
    text = (root / relative).read_text()
    assert text.index("authority: non_authoritative") < text.index("mutate")
    assert "owner holds and prerequisites still" in _read("task-plan/INSTRUCTIONS.md")
    (root / relative).write_text(text.replace("status: active", "status: completed"))
    assert _plan_lifecycle_errors(root, relative) == [
        "repository lifecycle for FIXTURE requires active; found completed"
    ]


def test_canonical_lifecycle_rejects_invalid_sources_without_yaml_fallback(tmp_path: Path):
    task = {
        "id": "FIXTURE",
        "project": "mempalace-code",
        "schema": "backlog/v1",
        "state": "open",
        "completion_valid": False,
    }
    cases = ("malformed", "duplicate", "yaml-owner", "archived-open", "invalid-done")
    for case in cases:
        root = tmp_path / case
        _write_lifecycle_fixture(
            root,
            "slug: FIXTURE\nstatus: active\nauthority: non_authoritative",
            archived_keys=("FIXTURE",) if case == "archived-open" else (),
        )
        path = _canonical_lifecycle_fixture(root, task)
        if case == "malformed":
            path.write_text('{"format":"backlog-task-envelope/v2"}')
        elif case == "duplicate":
            (path.parent / "ZZ-DUPLICATE.json").write_text(path.read_text())
        elif case == "yaml-owner":
            (root / "docs" / "BACKLOG.yaml").write_text("items: [{key: FIXTURE, status: open}]")
        elif case == "invalid-done":
            envelope = _strict_json(path)
            envelope["task_record"]["task"]["state"] = "done"
            path.write_text(json.dumps(envelope))
        with pytest.raises(ValueError, match="malformed|duplicate|contradictory|invalid"):
            _expected_plan_status(root, "FIXTURE")


@pytest.mark.parametrize(
    ("receipt_changes", "valid"),
    [
        ({}, True),  # Native validity is derived even when the cached value is false.
        (None, False),
        ({"contract_digest": "sha256:stale"}, False),
        ({"result": " "}, False),
        ({"result": None}, False),
        ({"evidence": None}, False),
        ({"evidence": []}, False),
        ({"evidence": [{"acceptance_id": "A1"}]}, False),
        (
            {
                "evidence": [
                    {
                        "acceptance_id": "A1",
                        "artifact_ref": "receipt",
                        "verification_result": "fail",
                    }
                ]
            },
            False,
        ),
        (
            {
                "evidence": [
                    {"acceptance_id": "A1", "artifact_ref": " ", "verification_result": "pass"}
                ]
            },
            False,
        ),
        (
            {
                "evidence": [
                    {
                        "acceptance_id": "unknown",
                        "artifact_ref": "receipt",
                        "verification_result": "pass",
                    }
                ]
            },
            False,
        ),
        (
            {
                "evidence": [
                    {
                        "acceptance_id": "A1",
                        "artifact_ref": "receipt",
                        "verification_result": "pass",
                    }
                ]
                * 2
            },
            False,
        ),
    ],
)
def test_canonical_done_lifecycle_checks_receipt_not_cached_validity(
    tmp_path: Path, receipt_changes: dict | None, valid: bool
):
    completion = {
        "contract_digest": "sha256:fixture",
        "result": "Accepted outcome verified",
        "evidence": [
            {"acceptance_id": "A1", "artifact_ref": "receipt", "verification_result": "pass"}
        ],
    }
    if receipt_changes is not None:
        completion.update(receipt_changes)
    task = {
        "id": "FIXTURE",
        "project": "mempalace-code",
        "schema": "backlog/v1",
        "state": "done",
        "completion_valid": False,
        "contract_digest": "sha256:fixture",
        "acceptance": [{"id": "A1"}],
        "completion": completion if receipt_changes is not None else None,
    }
    _write_lifecycle_fixture(
        tmp_path, "slug: FIXTURE\nstatus: completed\nauthority: non_authoritative"
    )
    _canonical_lifecycle_fixture(tmp_path, task)
    if valid:
        assert _plan_lifecycle_errors(tmp_path, "docs/plans/FIXTURE.md") == []
    else:
        with pytest.raises(ValueError, match="invalid canonical completion"):
            _expected_plan_status(tmp_path, "FIXTURE")


def test_entrypoints_use_canonical_backlog_and_preserve_unknown_and_hold_guards():
    for relative in ("start/INSTRUCTIONS.md", "status/SKILL.md", "doc-refresh/INSTRUCTIONS.md"):
        text = _read(relative)
        for tool in ("backlog_context", "backlog_workset_context", "backlog_workset_queue"):
            assert tool in text
        assert "unknown" in text
        assert "validate --store .backlog" in text
        assert "backlog list" not in text
        assert "backlog done" not in text
        assert "validate --file docs/BACKLOG.yaml" not in text
    retired = yaml.safe_load((ROOT / "docs" / "BACKLOG.yaml").read_text())
    assert retired["items"] == []
    assert retired["sections"]
