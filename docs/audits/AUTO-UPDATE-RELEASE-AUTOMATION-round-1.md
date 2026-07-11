slug: AUTO-UPDATE-RELEASE-AUTOMATION
round: 1
date: 2026-07-11
commit_range: 94c3e11..HEAD
findings:
  - id: F-1
    title: Installer timeout bypassed rollback
    severity: high
    location: mempalace_code/updater.py:759
    claim: A subprocess timeout escaped the command seam after watcher shutdown, which could skip rollback and leave the managed watcher stopped.
    decision: fixed
    fix: Installer commands now use a 15-minute timeout, and subprocess failures return a logged command failure so the existing rollback path restores the prior package and watcher state.
  - id: F-2
    title: Stale exclusive lock metadata blocked later upgrades
    severity: high
    location: mempalace_code/operation_lock.py:102
    claim: A killed updater could leave exclusive owner metadata after its advisory flock was released, causing every later apply to refuse before acquiring the free lock.
    decision: fixed
    fix: Exclusive owner metadata is now checked for a live PID and confirmed against the kernel lock before it blocks an update; stale records are pruned and recovery is documented.
  - id: F-3
    title: Default uv tool installs were refused
    severity: medium
    location: mempalace_code/updater.py:261
    claim: Detection required an optional uv environment override, so standard uv tool prefixes did not match the supported-install contract.
    decision: fixed
    fix: Detection recognizes default XDG and macOS uv tool roots as well as UV_TOOL_DIR, with resolved paths for symlink-safe matching.
totals:
  fixed: 3
  backlogged: 0
  dismissed: 0
fixes_applied:
  - Converted installer timeouts into rollback-triggering command failures.
  - Pruned stale update-owner metadata only after PID and advisory-lock checks.
  - Recognized default uv tool installation roots.
new_backlog: []
