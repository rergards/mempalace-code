"""
Suppression-policy scanner.

Enforces that every type-suppress or pyright-suppress comment in
`mempalace_code/` and `tests/` (excluding `tests/fixtures/`) matches:

    # (type|pyright): ignore[<code>]  # reason: <non-empty text>

Accepted form regex (case-sensitive):
    r"#\\s*(?:type|pyright):\\s*ignore\\[[^\\]\\s]+\\]\\s*#\\s*reason:\\s*\\S"

Bare suppress comments without a bracket code, or any suppression without a
`# reason:` justification, are rejected.
"""

import re
from pathlib import Path

ACCEPTED_RE = re.compile(r"#\s*(?:type|pyright):\s*ignore\[[^\]\s]+\]\s*#\s*reason:\s*\S")
SUPPRESSION_RE = re.compile(r"#\s*(?:type|pyright):\s*ignore")

ROOT = Path(__file__).parent.parent
ENFORCED_ROOTS = [ROOT / "mempalace_code", ROOT / "tests"]
EXCLUDED_DIR = ROOT / "tests" / "fixtures"


def _collect_enforced_files() -> list[Path]:
    files = []
    for root in ENFORCED_ROOTS:
        for path in root.rglob("*.py"):
            if path.is_relative_to(EXCLUDED_DIR):
                continue
            files.append(path)
    return sorted(files)


def _violations(path: Path) -> list[tuple[int, str]]:
    """Return (line_number, line) pairs that contain a suppression but fail the policy."""
    result = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if SUPPRESSION_RE.search(line) and not ACCEPTED_RE.search(line):
            result.append((lineno, line.rstrip()))
    return result


def test_all_suppressions_have_code_and_reason():
    """Every type/pyright ignore in the enforced set must carry [code] and # reason: text."""
    files = _collect_enforced_files()
    assert files, "No Python files found under enforced roots — check test setup"

    all_violations: list[str] = []
    for path in files:
        for lineno, line in _violations(path):
            all_violations.append(f"  {path.relative_to(ROOT)}:{lineno}: {line}")

    assert not all_violations, (
        "Unreasoned type suppressions found "
        "(required form: # type: ignore[code]  # reason: text):\n" + "\n".join(all_violations)
    )


def test_fixture_is_rejected():
    """The unreasoned_suppression.py fixture must fail the policy (negative case)."""
    fixture = EXCLUDED_DIR / "unreasoned_suppression.py"
    assert fixture.exists(), f"Negative fixture missing: {fixture}"
    violations = _violations(fixture)
    assert violations, (
        "Expected the negative fixture to contain unreasoned suppressions, but none found. "
        "Update tests/fixtures/unreasoned_suppression.py to include bare type: ignore lines."
    )
