# /entropy-gc — Agent Codebase Garbage Collection

Scan for and fix entropy in the codebase: duplicated helpers, unvalidated boundaries, stale documentation, spreading anti-patterns, and dead code.

## When to Use

- Regular cleanup cadence (weekly, alongside `/doc-refresh`)
- When noticing copy-paste patterns spreading
- After a burst of AI-assisted development
- "Check for pattern drift" / "clean up AI slop"

## When NOT to Use

- General refactoring unrelated to drift (just refactor directly)
- Code review of a single PR (use standard review)
- Docs-only cleanup (use `/doc-refresh`)

## Constraints

- **Read-only by default**: Phase 1 (detect) runs without edits. Phase 2 (fix) requires user approval before applying changes
- **NEVER** refactor working code just for style preferences — only fix actual drift
- **NEVER** delete code without verifying it's truly unused (check imports, tests)
- **NEVER** use `git add .` or `git add -A` — explicit staging only
- **ALWAYS** propose a "golden principle" for each recurring issue — prevent, don't just fix
- **Scope argument**: accepts an optional directory argument (e.g., `/entropy-gc mempalace/`). If omitted, scans `mempalace/`, `tests/`

## Workflow

### Phase 1: Detect Entropy

Scan for the 5 entropy categories. Use the Grep and Glob tools (NOT bash grep/find). Run searches in parallel where possible.

#### 1. Duplicated Helpers

Look for utility functions reimplemented in multiple places:

```
Grep: pattern="def (retry|with_timeout|safe_json|normalize_|slugify|clamp|truncate)"
Glob: *.py
Exclude: tests/, __pycache__
```

Also check for:
- Similar try/except patterns that should be shared
- Duplicated validation logic
- Repeated file I/O patterns

**Threshold**: 3+ similar implementations = consolidation candidate.

#### 2. Unvalidated Boundaries

Data consumed without validation at system boundaries:

```
Grep: pattern="json\.loads|yaml\.safe_load" glob="*.py" path="mempalace/"
```

**Ignore**: test files, internal module boundaries.
**Flag**: external API responses, file reads, MCP tool inputs consumed without schema validation.

#### 3. Stale Documentation

Cross-reference docs against code reality:

- Check `README.md` CLI commands against `cli.py`
- Check `CLAUDE.md` Key Modules table against actual modules
- Look for broken file path references in `docs/*.md`
- `Grep: pattern="TODO|FIXME|HACK|DEPRECATED" glob="*.md" path="docs/"`

#### 4. Spreading Anti-Patterns

Patterns that appear in recent files but violate project conventions:

- **Bare except**: `Grep: pattern="except:" glob="*.py"` — should specify exception type
- **Print statements**: `Grep: pattern="print\(" glob="*.py" path="mempalace/"` — should use logging
- **Hardcoded paths**: `Grep: pattern="~/.mempalace|/Users/" glob="*.py"` — should use config
- **Raw SQL**: `Grep: pattern="execute\(.*SELECT|INSERT|UPDATE" glob="*.py"` — check for injection risks

**Threshold**: same non-standard pattern in 5+ files = anti-pattern spread.

#### 5. Dead Code & Unused Exports

- Look for functions not called anywhere
- Check for imports not used
- Look for test files testing deleted functionality

**Use Agent tool** (model: sonnet) for cross-referencing — this requires multiple search rounds.

### Phase 1.5: Codex Second-Pass Review (optional)

After Phase 1, optionally run Codex as an independent reviewer to validate findings.

**When to run**: always recommended for full-repo scans; skip for narrow scoped runs (<20 findings).

```bash
./scripts/codex-review.sh --show-output entropy "entropy-<scope-slug>" ".tasks/TASK-entropy-<scope-slug>/entropy-report.md" "<scanned directories>"
```

Reconcile: drop false positives Codex identified, add missed issues Codex found.

### Phase 2: Fix & Report

**STOP after Phase 1 (or 1.5) and present findings to user.** Do not auto-fix without approval.

For each finding, classify the action:

| Action | When | Example |
|--------|------|---------|
| **Auto-fix** (after approval) | Duplicated helpers -> consolidate | Merge retry patterns into utils |
| **Auto-fix** (after approval) | Stale cross-links -> update/remove | Fix broken path in docs |
| **Suggest** | Unvalidated boundaries | Recommend Pydantic schema |
| **Suggest** | Anti-patterns | Propose golden principle |
| **Flag** | Dead code | List for human review |

After user approves fixes:
1. Apply changes in small, reviewable chunks
2. Run verification: `python -m pytest tests/ -x -q && ruff check mempalace/`
3. Do NOT commit — leave for user to review and commit

### Golden Principles

Each recurring finding should include a "golden principle" — an opinionated, mechanical rule that prevents future drift.

**Good**: "All MCP tool inputs must be validated with Pydantic before use"
**Bad**: "Write clean code"

## Output Format

```
ENTROPY GC: mempalace
=====================

Scope: {scanned directories}
Files checked: {N}
Codex review: {validated | revised after review | skipped: <reason>}

Category                 Found  Auto-fixable  Needs Review
----------------------   -----  ------------  ------------
Duplicated Helpers       {n}    {n}           {n}
Unvalidated Boundaries   {n}    {n}           {n}
Stale Documentation      {n}    {n}           {n}
Spreading Anti-Patterns  {n}    {n}           {n}
Dead Code                {n}    {n}           {n}
----------------------   -----  ------------  ------------
TOTAL                    {N}    {N}           {N}

## Findings

### 1. Duplicated Helpers
- {file1}:{line} and {file2}:{line}: {description}
  Action: consolidate into {target}

### 2. Unvalidated Boundaries
- {file}:{line}: {description}
  Recommendation: {specific fix}

[...]

## Golden Principles Proposed
1. "{principle}" — prevents: {category}
2. "{principle}" — prevents: {category}

Awaiting approval to apply auto-fixes.
```
