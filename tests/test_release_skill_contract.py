"""Contract tests for the tracked release skill.

The skill is the procedure an agent actually executes, so it is held to the same
contract as docs/RELEASING.md: the canonical exact-SHA commands verbatim, and one
documented row per required release-status surface. Every expectation below is
derived from the guard and the status gate rather than restated, so a constant
that moves fails here instead of silently leaving the skill stale.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
SKILL = ROOT / ".claude" / "skills" / "release" / "SKILL.md"
SKILL_PATH = ".claude/skills/release/SKILL.md"
MAX_SKILL_LINES = 500

# Each external mutation the skill performs, paired with the step that owns it.
APPROVED_MUTATIONS = (
    ("candidate branch push", "## Step 5 —"),
    ("fast-forward onto `main`", "## Step 5a —"),
    ("tag push", "## Step 6 —"),
    ("candidate branch deletion", "## Step 8 —"),
)
# "the only mutations are the two pushes in Steps 4 and 6" — a count that was
# already wrong once and licensed the mutations it forgot to count.
_FIXED_MUTATION_COUNT_RE = re.compile(
    r"only\s+mutations?|\b(?:one|two|three|four)\s+(?:pushes|push|mutations?)\b", re.IGNORECASE
)


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


guard = _load_module("docs_drift_guard", ROOT / "scripts" / "docs_drift_guard.py")
SKILL_TEXT = SKILL.read_text(encoding="utf-8")


def test_the_release_skill_carries_the_canonical_release_commands():
    for command in (
        guard.CANONICAL_LIVE_RELEASE_PREFLIGHT_COMMAND,
        guard.CANONICAL_EXACT_SHA_RELEASE_PREFLIGHT_COMMAND,
        guard.CANONICAL_RELEASE_STATUS_COMMAND,
    ):
        assert command in SKILL_TEXT, f"{SKILL_PATH} is missing: {command!r}"

    # The status command is only exact-SHA evidence when it is invoked with the
    # reviewed SHA; a skill that verified the branch would answer a different
    # question with the same row names.
    assert "--expect-sha" in guard.CANONICAL_RELEASE_STATUS_COMMAND
    assert "--expect-sha" in guard.CANONICAL_EXACT_SHA_RELEASE_PREFLIGHT_COMMAND


def test_the_release_skill_documents_exactly_the_required_status_surfaces():
    block = guard._marker_block(SKILL_TEXT, guard.RELEASE_STATUS_SURFACE_MARKER)
    assert block is not None, f"{SKILL_PATH} is missing the release-status surface block"

    documented = guard._RELEASE_STATUS_SURFACE_ROW_RE.findall(block)
    assert sorted(documented) == sorted(guard.release_status_surface_names())
    assert len(documented) == len(set(documented)), documented


def test_the_release_skill_requires_first_release_live_provenance_evidence():
    assert "first release after provenance verification lands" in SKILL_TEXT
    assert "exact-version" in SKILL_TEXT
    assert "exact-SHA" in SKILL_TEXT
    assert "public PyPI" in SKILL_TEXT
    assert "without mutation" in SKILL_TEXT
    assert "`pypi_provenance` row" in SKILL_TEXT
    assert "environment `release`" in SKILL_TEXT


def test_the_release_skill_gives_one_bounded_recovery_command():
    # Recovery is the row's own remediation plus one re-read of the same gate —
    # not an improvised repair, which is how a blocked release gets talked green.
    assert f"{guard.CANONICAL_RELEASE_STATUS_COMMAND} --json" in SKILL_TEXT
    assert "remediation" in SKILL_TEXT
    assert "docs/release-admission-rulesets.md" in SKILL_TEXT


def test_the_release_skill_carries_the_exact_partial_publication_contract():
    assert guard.CANONICAL_PARTIAL_PUBLICATION_RECOVERY_COMMAND in SKILL_TEXT
    assert "build=success" in SKILL_TEXT
    assert "publish=success" in SKILL_TEXT
    assert "unique `github-release=failure`" in SKILL_TEXT
    assert "BOUNDED INSTRUCTION: no safe publication mutation" in SKILL_TEXT
    assert "reruns only the exact `github-release` job" in SKILL_TEXT
    assert "never create the GitHub Release manually" in SKILL_TEXT


def test_the_release_skill_stays_a_short_frontmattered_procedure():
    lines = SKILL_TEXT.splitlines()
    assert len(lines) <= MAX_SKILL_LINES, len(lines)
    assert lines[0] == "---"
    frontmatter_end = lines.index("---", 1)
    frontmatter = lines[1:frontmatter_end]
    assert any(line.startswith("name: release") for line in frontmatter), frontmatter
    assert any(line.startswith("description: ") for line in frontmatter), frontmatter


def test_the_tracked_skill_satisfies_the_drift_guard():
    _, errors = guard.evaluate(ROOT)
    assert [error for error in errors if error.startswith(f"{SKILL_PATH}:")] == []


def test_the_release_skill_promotes_through_a_fast_forward_only_candidate_branch():
    """Public `main` is protected against non-fast-forward updates.

    Local `main` and public `main` are separate histories, so the skill must
    build a commit-tree candidate on `publish/main` rather than telling an agent
    to push local `main` (which is rejected) or to force-push (which is banned).
    """
    assert guard.release_promotion_errors({SKILL_PATH: SKILL_TEXT}) == []

    assert "git commit-tree" in SKILL_TEXT
    assert "git diff --stat" in SKILL_TEXT, (
        f"{SKILL_PATH}: must prove the candidate tree equals the reviewed tree"
    )


def test_the_release_skill_pushes_the_candidate_branch_before_it_moves_main():
    """The candidate earns its own green checks on a branch before `main` moves.

    Ordering is the contract, not just presence: pushing `release/vX.Y.Z` first
    is what gives `$CANDIDATE_SHA` its own **Tests** and `release-required`
    results, so the later fast-forward onto `main` cannot deadlock against
    required checks that can only run after the branch update.
    """
    branch_push = SKILL_TEXT.index('git push publish "$CANDIDATE_BRANCH"')
    main_push = SKILL_TEXT.index('git push publish "$CANDIDATE_SHA":refs/heads/main')
    assert branch_push < main_push, f"{SKILL_PATH}: main moves before the candidate is proven"

    # The one-shot form is the shape this ordering replaces: it lands on `main`
    # with no prior checks for that SHA.
    assert "git push publish release/vX.Y.Z:main" not in SKILL_TEXT

    green_gate = SKILL_TEXT.index("release-required", branch_push)
    assert green_gate < main_push, f"{SKILL_PATH}: no green requirement before the fast-forward"


def test_the_release_skill_rebuilds_a_failed_candidate_on_a_new_branch():
    """A published candidate branch is immutable, so a retry needs a new name.

    `git switch -C` is only safe before the push; after it, re-pointing the same
    branch at a rebuilt candidate is a non-fast-forward update of a public ref.
    """
    assert "CANDIDATE_BRANCH=release/vX.Y.Z-rc2" in SKILL_TEXT, (
        f"{SKILL_PATH}: no immutable retry branch name documented"
    )
    # Nothing after the parameter is defined may hardcode the first attempt's name.
    parameterized = SKILL_TEXT[SKILL_TEXT.index("CANDIDATE_BRANCH=release/vX.Y.Z\n") :]
    assert "git push publish release/vX.Y.Z" not in parameterized, (
        f"{SKILL_PATH}: a literal branch name would be wrong on an -rcN retry"
    )
    assert "--candidate-ref publish/release/vX.Y.Z" not in parameterized, SKILL_PATH


def test_the_release_skill_requires_separate_approval_to_delete_the_candidate_branch():
    """Cleanup is an external mutation, and it must not inherit an earlier approval."""
    delete = SKILL_TEXT.index('git push publish --delete "$CANDIDATE_BRANCH"')
    main_push = SKILL_TEXT.index('git push publish "$CANDIDATE_SHA":refs/heads/main')
    assert main_push < delete, f"{SKILL_PATH}: deletion is proposed before promotion"

    window = SKILL_TEXT[max(0, delete - 1200) : delete].lower()
    assert "approval" in window, f"{SKILL_PATH}: deletion has no nearby approval requirement"
    assert "proceed? [y/n]" in window, f"{SKILL_PATH}: deletion has no explicit prompt"


def test_the_release_skill_approves_each_mutation_separately():
    """The preamble must name every remote write, and count none of them.

    A fixed count goes stale the moment a step is added — the candidate branch
    push and its cleanup both arrived after "the two pushes" was written — and a
    stale count silently authorizes whatever it forgot to mention.
    """
    # Prose wraps, so match against a whitespace-collapsed copy: a phrase split
    # across two lines is the same requirement.
    preamble = " ".join(SKILL_TEXT[: SKILL_TEXT.index("## When to Use")].split())

    stale = _FIXED_MUTATION_COUNT_RE.search(preamble)
    assert stale is None, f"{SKILL_PATH}: preamble states a fixed mutation count: {stale}"
    assert "no approval carries over" in preamble.lower(), (
        f"{SKILL_PATH}: preamble does not say an approval stops at its own step"
    )

    headings = [heading for _, heading in APPROVED_MUTATIONS]
    for mutation, heading in APPROVED_MUTATIONS:
        assert mutation in preamble, (
            f"{SKILL_PATH}: preamble does not require approval for the {mutation}"
        )
        assert heading in SKILL_TEXT, f"{SKILL_PATH}: missing {heading}"

        # The step that performs the mutation asks for itself, so an agent
        # reading only that step still stops before writing to the remote.
        start = SKILL_TEXT.index(heading)
        later = [SKILL_TEXT.index(other) for other in headings if SKILL_TEXT.index(other) > start]
        body = SKILL_TEXT[start : min(later, default=len(SKILL_TEXT))].lower()
        assert "approval" in body or "ask before" in body, (
            f"{SKILL_PATH}: {heading} performs a mutation with no approval of its own"
        )


def test_the_release_skill_never_instructs_a_force_push():
    for banned in ("push --force", "push -f ", "--force publish"):
        assert banned not in SKILL_TEXT, f"{SKILL_PATH}: must not instruct {banned!r}"
