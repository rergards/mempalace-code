---
slug: MINE-JAVA-PKG-PRIVATE-METHODS
status: completed
authority: non_authoritative
goal: "Extract symbol metadata for package-private Java methods without visibility modifiers"
risk: low
risk_note: "Single Java extract regex change plus focused unit coverage; chunking, storage, and other language extractors remain untouched"
files:
  - path: mempalace/miner.py
    change: "Relax the _JAVA_EXTRACT method regex so Java methods with no leading modifier still match while retaining guards against fields and call expressions"
  - path: tests/test_symbol_extract.py
    change: "Add Java extract_symbol tests for package-private void and typed methods plus false-positive guards for fields and bare calls"
acceptance:
  - id: AC-1
    when: "extract_symbol('void process() {\\n}\\n', 'java') is called"
    then: "returns ('process', 'method')"
  - id: AC-2
    when: "extract_symbol('String getName() {\\n}\\n', 'java') is called"
    then: "returns ('getName', 'method')"
  - id: AC-3
    when: "extract_symbol('String name;\\n', 'java') is called"
    then: "returns ('', '')"
  - id: AC-4
    when: "extract_symbol('process();\\n', 'java') is called"
    then: "returns ('', '')"
  - id: AC-5
    when: "extract_symbol('public void processRequest(HttpServletRequest req) {\\n}\\n', 'java') is called"
    then: "still returns ('processRequest', 'method')"
out_of_scope:
  - "JAVA_BOUNDARY chunking changes"
  - "Constructor extraction or symbol_type='constructor'"
  - "Nested generic method type-parameter fixes from the prior Java audit"
  - "Any non-Java extractor patterns"
---

## Design Notes

- The current method pattern requires one or more modifiers before the optional generic type parameter and return type. Change only that leading modifier group so valid package-private signatures can enter the same return-type/name matching path.
- Keep the method pattern anchored to line start and require an opening parenthesis after the captured name; this is what prevents plain fields such as `String name;` from matching.
- Add a bare-call negative test (`process();`) because allowing zero modifiers broadens the pattern. The implementation should still require a recognizable return type before the captured method name, so a standalone call expression is not treated as a declaration.
- Place new tests near the existing Java method tests in `tests/test_symbol_extract.py`; keep existing public/private/generic Java cases unchanged as regression coverage.
- Do not address the audit's nested generic type-bound issue (`public <K extends Comparable<K>> ...`) in this task; that was explicitly dismissed and would require a broader regex decision.
