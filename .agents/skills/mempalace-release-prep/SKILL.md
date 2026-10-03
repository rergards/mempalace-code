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
If the owner is absent or unreadable, report that failure and stop dependent work.
Do not substitute remembered commands, duplicate the runbook, change global agent
configuration, or interpret preparation as authority to publish.
