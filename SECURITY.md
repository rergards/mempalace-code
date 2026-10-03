# Security Policy

## Supported versions

Only the latest release published on
[PyPI](https://pypi.org/project/mempalace-code/) receives security fixes.
Fixes ship in a new release; older versions are not patched. Upgrade with the
commands in [docs/UPDATES.md](docs/UPDATES.md).

## Reporting a vulnerability

Report vulnerabilities privately through GitHub private vulnerability
reporting:
[Report a vulnerability](https://github.com/rergards/mempalace-code/security/advisories/new).
Do not open a public issue, pull request, or discussion for an undisclosed
vulnerability.

Include the affected version, how to reproduce the problem, and its impact.
Leave out real secrets, private paths, and palace contents; describe them
instead. The maintainer confirms the report, agrees on a fix and disclosure
plan with you, and publishes a GitHub security advisory with the fixed release.

## Scope

This policy covers the `mempalace-code` package and this repository. Report
issues in the original MemPalace project to
[MemPalace/mempalace](https://github.com/MemPalace/mempalace).

Current releases contain no ChromaDB dependency. The retired `[chroma]` bridge
in release 1.13.4 depends on ChromaDB releases with known advisories; run it
only in isolation, as described in [docs/BACKUP_RESTORE.md](docs/BACKUP_RESTORE.md).

Dependency advisories are tracked by Dependabot alerts and by the scheduled
**Dependency Audit** workflow described in
[docs/DEPENDENCY_UPGRADE_GATE.md](docs/DEPENDENCY_UPGRADE_GATE.md).
