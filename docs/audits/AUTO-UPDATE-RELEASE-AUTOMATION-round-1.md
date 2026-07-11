slug: AUTO-UPDATE-RELEASE-AUTOMATION
round: 1
date: 2026-07-11
commit_range: 94c3e11..dfb62af
findings:
  - id: F-1
    title: Installer timeout bypassed rollback
    severity: high
    location: mempalace_code/updater.py:779
    claim: A subprocess timeout escaped the command seam after watcher shutdown, which could skip rollback and leave the managed watcher stopped.
    decision: fixed
    fix: Command timeouts now use a 15-minute limit and return logged failures that enter rollback; the transaction guard also compensates unexpected validation errors after prior state is persisted.
  - id: F-2
    title: Stale exclusive lock metadata blocked later upgrades
    severity: high
    location: mempalace_code/operation_lock.py:102
    claim: A killed updater could leave exclusive owner metadata after its advisory flock was released, causing every later apply to refuse before acquiring the free lock.
    decision: fixed
    fix: Owner records are checked for a live PID under the metadata lock before they block an update; dead records are pruned during inspection and lease acquisition, and recovery behavior is documented.
  - id: F-3
    title: Default uv tool installs were refused
    severity: medium
    location: mempalace_code/updater.py:260
    claim: Detection required an optional uv environment override, so standard uv tool prefixes did not match the supported-install contract.
    decision: fixed
    fix: Detection recognizes default XDG and macOS uv tool roots as well as UV_TOOL_DIR, with resolved paths for symlink-safe matching.
totals:
  fixed: 3
  backlogged: 0
  dismissed: 0
fixes_applied:
  - Converted installer timeouts into rollback-triggering command failures and guarded unexpected transaction errors.
  - Pruned stale update-owner metadata after a live-PID check under the metadata lock.
  - Recognized default uv tool installation roots.
new_backlog: []
