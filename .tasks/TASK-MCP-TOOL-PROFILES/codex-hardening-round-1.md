## 1. New Findings

### P2 / High - Agent install runbook documents profiles but never applies one during MCP wiring

`docs/AGENT_INSTALL.md:189` still asks only for global vs project MCP scope, then every wiring path starts `mempalace_code.mcp_server` without `--profile`, `--tools`, or `--exclude` (`docs/AGENT_INSTALL.md:489`, `docs/AGENT_INSTALL.md:512`, `docs/AGENT_INSTALL.md:552`, `docs/AGENT_INSTALL.md:568`). Section 0 tells agents to recommend `--profile=minimal`/`--profile=code`, but the executable runbook has no variable or question for profile selection, so an agent following the install script will always register the full 28-tool default. Section 7 also injects the full usage-rules block (`docs/AGENT_INSTALL.md:671`) rather than selecting the matching profile block. This misses the feature's main user-visible goal in the install path that agents are told to execute.

### P2 / Medium - `code` profile is documented as read-only/no-write but exposes the mutating re-mine tool

`mempalace_code/mcp_tool_profiles.py:41` includes `mempalace_mine` in the `code` profile, while README/examples describe `code` as "no write/diary tools" (`README.md:370`, `examples/mcp_setup.md:47`) and the usage-rules block says it is for a "read-only code archaeology and architecture review" role (`docs/LLM_USAGE_RULES.md:226`). `mempalace_mine` is implemented as a re-indexing write path that calls `_mine_quiet(...)` and returns `drawers_filed` (`mempalace_code/mcp_server.py:438`, `mempalace_code/mcp_server.py:483`). Users choosing `--profile=code` for a read-only/reduced-risk agent still grant it an indexing mutation capability, so either the profile or the docs/role contract need to be corrected.

## 2. Known Issues Map Status

No previous round report existed at `docs/audits/MCP-TOOL-PROFILES-round-0.md` in this scoped snapshot. The directly matching backlog/plan context reviewed was `docs/plans/MCP-TOOL-PROFILES.md`; no duplicate prior findings were available to suppress.

## 3. Evidence Reviewed

- Scoped diff: `.tasks/TASK-MCP-TOOL-PROFILES/codex-hardening-round-1.diff`
- Scoped files manifest: `.tasks/TASK-MCP-TOOL-PROFILES/codex-hardening-round-1-files.txt`
- Matching feature plan/backlog: `docs/plans/MCP-TOOL-PROFILES.md`
- Implementation files: `mempalace_code/mcp_server.py`, `mempalace_code/mcp_tool_profiles.py`
- Scoped docs/tests: `README.md`, `docs/AGENT_INSTALL.md`, `docs/LLM_USAGE_RULES.md`, `examples/mcp_setup.md`, `mempalace_code/README.md`, `tests/test_mcp_server.py`, `tests/test_mcp_tool_profiles.py`
- Commands run:
  - `python -m pytest tests/test_mcp_tool_profiles.py tests/test_mcp_server.py -q` failed during collection because this isolated snapshot lacks a local `mempalace_code/__init__.py`, causing Python to resolve `mempalace_code` from `/Users/rerg/dev/mempalace` where the new module is absent.
  - `ruff check mempalace_code/ tests/` passed.
  - `ruff format --check mempalace_code/ tests/` failed because 5 scoped files would be reformatted; not reported as a finding per review bar.

## 4. Residual Risks

Targeted pytest could not run to completion in this isolated scoped snapshot because package import resolution used an installed checkout instead of the scoped `mempalace_code/mcp_tool_profiles.py`. Re-run the targeted pytest command in the full repository checkout after hardening. Packaging metadata was not present in the scoped manifest, so inclusion of the new module in built distributions was not independently verified.

## 5. Convergence Recommendation

Do not converge yet. Fix the install-runbook profile threading and resolve the `code` profile read-only contract mismatch, then rerun the targeted pytest command plus the existing ruff checks in a full checkout.

## 6. Suggested Claude Follow-Up

1. Add an MCP profile/tools selection step or variable to `docs/AGENT_INSTALL.md`, thread it into Claude/Codex CLI commands and JSON/TOML fallback args, and make Section 7 inject/copy the matching profile-scoped usage block when a reduced profile is selected.
2. Decide whether `mempalace_mine` belongs in `code`; if retained, remove "read-only" / "no write tools" wording and explain that re-mining mutates the index. If read-only is the intended contract, remove `mempalace_mine` from `PROFILES["code"]` and update tests/docs counts.
3. Re-run `python -m pytest tests/test_mcp_tool_profiles.py tests/test_mcp_server.py -q` from the full repo checkout, then `ruff check mempalace_code/ tests/` and `ruff format --check mempalace_code/ tests/`.
