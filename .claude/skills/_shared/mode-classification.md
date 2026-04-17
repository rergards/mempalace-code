# Mode Classification — 5-Axis Triage

Shared procedure for classifying a task as `lite`, `standard`, or `strict`.
Referenced by `/task-plan` and `/task-hardening`.

## Axes

Judge these five axes from repo evidence (not user-supplied size labels):

- **boundary risk**: storage operations, schema migrations, embedding model changes, MCP tool contracts, CLI breaking changes, backup/restore paths
- **ambiguity**: multiple plausible implementations, unclear API design, unresolved contract decisions, or (for hardening) ambiguity still remaining in the behavior
- **blast radius**: number of subsystems/files likely affected and coupling to shared helpers (storage.py, mcp_server.py, miner.py)
- **verification difficulty**: whether the change needs non-trivial regression coverage or multi-step validation
- **failure cost**: user data loss, palace corruption, embedding drift, hard-to-reverse regressions

## Decision Rule

- `lite` only if all five axes are low and the implementation path looks obvious
- `strict` if any sensitive boundary is touched or any axis is clearly high
- otherwise `standard`
- if still uncertain, choose `standard`

## Size Labels

Do not trust user-provided size markers like `[S]`, `[M]`, `XS`, or `low` as authoritative. Treat them as weak hints only. A user-supplied size estimate never overrides repo-evidenced risk.
