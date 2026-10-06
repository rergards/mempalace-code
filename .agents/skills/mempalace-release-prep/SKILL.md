---
name: mempalace-release-prep
description: Prepare a MemPalace release with safe repository cleanup, metadata reconciliation and credential-free local qualification. Use for release preparation; publication requires separate authorization.
---

# MemPalace release preparation

Resolve the MemPalace Git root. Read the repository-owned workflow at
`.claude/skills/release-prep/SKILL.md` from that root and execute it within the
active request's authority. Its body is the single workflow owner; its Claude
invocation metadata does not grant permissions or define Codex discovery.

Read the root `AGENTS.md` and workflow-linked runbook before mutations.
Use the owner's order: audit current user/LLM documentation, run source checks,
build/check both artifacts, qualify the exact wheel, write and commit its acceptance
report, then run committed-report/clean-tree preflight. Reuse unchanged evidence
and existing authorization; the wrapper adds no separate gates or permissions.
Apply the owner's mandatory privacy audit to hidden tracked LLM instructions,
metadata, archive contents and outgoing history before public delivery. Preserve
local evidence and report unresolved disclosure separately from secret-scan PASS.
If the owner is absent or unreadable, report that failure and stop dependent work.
Do not substitute remembered commands, duplicate the runbook, change global agent
configuration, or interpret preparation as authority to publish.

When present, read `.codex-local/LESSONS.md` for maintainer-local instructions.
Keep its contents and referenced local-only evidence out of public material.
