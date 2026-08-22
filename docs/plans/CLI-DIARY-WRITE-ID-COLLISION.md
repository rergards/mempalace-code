---
slug: CLI-DIARY-WRITE-ID-COLLISION
status: completed
authority: non_authoritative
goal: "Replace timestamp+MD5 diary entry ID with uuid4 in both cli.py and mcp_server.py"
risk: low
risk_note: "ID is an opaque internal key; no external system depends on its format. No tests assert on ID pattern."
files:
  - path: mempalace/cli.py
    change: "In cmd_diary_write(): swap `import hashlib` for `import uuid`; replace entry_id formula with f\"diary_{wing}_{uuid.uuid4().hex}\""
  - path: mempalace/mcp_server.py
    change: "Add `import uuid` at top-level; replace entry_id formula in tool_diary_write() with f\"diary_{wing}_{uuid.uuid4().hex}\"; leave top-level `import hashlib` (still used by tool_add_drawer)"
acceptance:
  - id: AC-1
    when: "two rapid diary writes with identical content and same agent are executed within the same second"
    then: "both succeed and return distinct entry_ids (no duplicate-ID error)"
  - id: AC-2
    when: "cmd_diary_write produces an entry_id"
    then: "it matches the pattern diary_<wing>_<32 hex chars> (uuid4.hex, no timestamp or MD5 component)"
  - id: AC-3
    when: "tool_diary_write produces an entry_id"
    then: "it matches the pattern diary_<wing>_<32 hex chars>"
  - id: AC-4
    when: "full test suite runs after the change"
    then: "all existing diary tests pass; no metadata fields (wing, room, topic, agent, filed_at, date) are altered"
  - id: AC-5
    when: "ruff check mempalace/ tests/ runs after the change"
    then: "no lint errors; in particular no unused-import F401 for hashlib in cli.py"
out_of_scope:
  - "tool_add_drawer ID formula in mcp_server.py (uses hashlib.md5 for dedup — separate concern)"
  - "test_export.py _add_diary_drawer helper (uses its own ad-hoc ID formula; not production code)"
  - "any migration of existing diary entries stored under the old timestamp+MD5 format"
---

## Design Notes

- **ID format chosen**: `f"diary_{wing}_{uuid.uuid4().hex}"` — keeps the `diary_` prefix for human readability and the wing segment for tracing, replaces the collision-prone suffix with 32 hex chars (uuid4, 122 bits of entropy). Parentheses around `uuid.uuid4()` are unnecessary; `.hex` directly on the return value is idiomatic.

- **`now` variable retained**: both sites keep `now = datetime.now()` because it feeds the `filed_at` and `date` metadata fields. Only the `entry_id` line changes.

- **`hashlib` import in `cli.py`**: it is currently imported inline inside `cmd_diary_write()` (not at module top-level) solely for the diary ID. After the fix, remove that inline import — `uuid` replaces it. No other code in `cli.py` uses `hashlib`.

- **`hashlib` import in `mcp_server.py`**: remains at the top-level because `tool_add_drawer()` (line 302) still uses `hashlib.md5` for its drawer dedup ID. Do not remove it.

- **No test updates needed**: grep across all test files finds zero assertions on entry_id format or on the substring `diary_` in IDs. The e2e test (`test_diary_write_read_continuity`) writes 5 entries with distinct content — it would have been safe with the old formula, but is equally safe with uuid4.

- **Atomic change**: both sites must be updated in the same commit to prevent a window where CLI and MCP use different ID schemes (either both old or both new; never mixed).
