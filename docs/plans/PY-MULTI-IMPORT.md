---
slug: PY-MULTI-IMPORT
goal: "Extract every module from comma-separated Python import lines into KG depends_on triples"
risk: low
risk_note: "Small parser refinement inside existing Python KG extraction; no storage schema, mining flow, or non-Python extractor changes."
files:
  - path: mempalace_code/miner.py
    change: "Change bare import extraction so `_python_type_rels()` captures the full `import ...` clause, splits it by comma, strips aliases, validates module tokens, and emits one deduplicated depends_on triple per imported module."
  - path: tests/test_kg_extract.py
    change: "Add focused Python KG extraction tests for comma-separated imports, alias handling, commented import lines, and deduplication with mixed single/multi import lines."
acceptance:
  - id: AC-1
    when: "`extract_type_relationships()` runs on a Python file containing `import os, sys\\n`"
    then: "The returned triples include both `(Test, depends_on, os)` and `(Test, depends_on, sys)`."
  - id: AC-2
    when: "`extract_type_relationships()` runs on `import os, sys as system, pathlib\\n`"
    then: "The returned triples include `os`, `sys`, and `pathlib` as depends_on objects, and do not include the alias name `system`."
  - id: AC-3
    when: "`extract_type_relationships()` runs on `# import os, sys\\nclass Real:\\n    pass\\n`"
    then: "No depends_on triples are emitted from the commented import line."
  - id: AC-4
    when: "`extract_type_relationships()` runs on `import os\\nimport os, sys\\n`"
    then: "Exactly one `(Test, depends_on, os)` triple is returned, and `(Test, depends_on, sys)` is returned."
  - id: AC-5
    when: "`extract_type_relationships()` runs on existing single bare-import and from-import fixtures"
    then: "Single `import foo` and `from foo.bar import baz` still return their existing depends_on triples."
out_of_scope:
  - "AST-based Python import parsing or support for multiline parenthesized import statements."
  - "Changing `from ... import ...` behavior, including the existing relative-import skip."
  - "Changing KG predicates, module subject naming, mining invalidation, or non-Python extractors."
---

## Design Notes

- Keep the change local to the Python import extraction block in `_python_type_rels()` and its compiled pattern near `_PY_IMPORT_RE`.
- Replace the first-module-only match with a clause match for the rest of the bare import line, then split the captured clause on commas.
- For each comma segment, trim whitespace and remove an optional `as <alias>` suffix before emitting the object name. This preserves the current single-import behavior where `import foo as bar` depends on `foo`, not `bar`.
- Validate each parsed object with a dotted-module token regex before adding a triple. Empty or malformed comma segments should be ignored rather than producing blank or alias-shaped objects.
- Keep using the existing `seen` set so repeated imports in the same file remain deduplicated after a multi-import line is expanded.
- Add the new tests in the existing Python section of `tests/test_kg_extract.py`, next to `test_py_import_depends_on()` and `test_py_import_deduplicated()`, using the existing `_py(tmp_path, content)` helper.
- Verification for implementation should run `python -m pytest tests/test_kg_extract.py -q` and `ruff check mempalace_code/ tests/`.
