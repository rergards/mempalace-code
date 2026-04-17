---
slug: TREESITTER-VERSION-PINS
goal: "Raise tree-sitter version ceilings in [treesitter] extra to cover 0.24.x–0.25.x, preserving Python 3.9 support via environment markers"
risk: low
risk_note: "Pure packaging change; treesitter.py API is stable across target range; regex fallback is always available if install fails"
files:
  - path: pyproject.toml
    change: "Split tree-sitter core line into two marker-gated lines (<0.24 for py<3.10, <0.26 for py>=3.10); raise all grammar package ceilings from <0.24 to <0.26"
  - path: .github/workflows/ci.yml
    change: "Add treesitter-py313 job (Python 3.13) to verify latest core + grammars on newest CPython"
acceptance:
  - id: AC-1
    when: "pip install -e '.[treesitter]' on Python 3.9"
    then: "Resolves tree-sitter 0.23.x (not 0.24+), grammar packages <=0.23.x"
  - id: AC-2
    when: "pip install -e '.[treesitter]' on Python 3.11"
    then: "Resolves tree-sitter 0.25.x and latest compatible grammar packages"
  - id: AC-3
    when: "treesitter-compat CI job (Python 3.11)"
    then: "Job passes with tree-sitter 0.25.x installed"
  - id: AC-4
    when: "treesitter-py39 CI job"
    then: "Job passes with tree-sitter capped at 0.23.x"
  - id: AC-5
    when: "new treesitter-py313 CI job (Python 3.13)"
    then: "Job passes with latest core + grammars"
  - id: AC-6
    when: "pip check after install on any Python version"
    then: "No dependency conflicts reported"
out_of_scope:
  - "Any changes to mempalace/treesitter.py — Parser(Language(capsule)) API is stable across 0.22–0.25"
  - "Raising the floor below >=0.22"
  - "Adding new language grammars (e.g. Ruby, Java)"
  - "Updating the chroma or spellcheck extras"
---

## Design Notes

### Why the ceiling was <0.24

Tree-sitter 0.24.0 bumped `requires_python` from `>=3.9` to `>=3.10`. The `<0.24` ceiling was therefore load-bearing: it kept the extra installable on Python 3.9. Naively raising to `<0.26` would break the `treesitter-py39` CI job.

### Solution: split the core line with a Python version marker

PEP 508 allows listing the same package twice with complementary environment markers. The implementation is:

```toml
"tree-sitter>=0.22,<0.24; python_version < '3.10'",   # py3.9 → caps at 0.23.x
"tree-sitter>=0.22,<0.26; python_version >= '3.10'",   # py3.10+ → allows 0.25.x
```

pip evaluates only the applicable line at install time, so there is no conflict.

### Grammar package version landscape (as of 2026-04-17)

| Package                | Latest   | py_requires | Notes                         |
|------------------------|----------|-------------|-------------------------------|
| tree-sitter-python     | 0.25.0   | >=3.10      | no 0.24.x release             |
| tree-sitter-typescript | 0.23.2   | >=3.9       | no 0.24.x or 0.25.x yet       |
| tree-sitter-go         | 0.25.0   | >=3.10      | no 0.24.x release             |
| tree-sitter-rust       | 0.24.2   | >=3.9       | no 0.25.x yet                 |

All grammar packages stay at `>=0.23,<0.26`. pip resolves each to the highest version whose `requires_python` is satisfied by the active interpreter, so Python 3.9 automatically gets 0.23.x grammars and Python 3.10+ gets 0.25.x/0.24.x where available.

`tree-sitter-python` retains its existing `; python_version >= '3.10'` marker (unchanged).

### ABI compatibility

Tree-sitter 0.24 added ABI level 15; 0.23.x grammars use ABI 14. The 0.24 and 0.25 core libraries load both ABI levels, so grammar packages 0.23.x work correctly with tree-sitter core 0.24.x and 0.25.x. No changes to `treesitter.py` are required.

### treesitter.py API stability check

The pattern `Parser(Language(lang_obj))` used in `treesitter.py:62` is the grammar-capsule constructor introduced in 0.22. In 0.24 the integer-pointer form was deprecated (not removed); the capsule form is unaffected. In 0.25 the `Query`/`QueryCursor` API was restructured, but `Language` and `Parser` constructors are unchanged. No code edits needed.

### New CI job: treesitter-py313

The existing `treesitter-compat` job covers Python 3.11. The main `test` matrix already includes 3.13, but the treesitter extra has never been explicitly verified on 3.13. Add a `treesitter-py313` job mirroring `treesitter-compat` with Python 3.13. This closes the gap and provides early warning if a future grammar package drops 3.13 wheel support.
