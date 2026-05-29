1. New Findings

- P1, High: [mempalace_code/mirror_preflight.py](/private/var/folders/jw/lhsrh3md3zn1gx15pt4g54th0000gn/T/tmp.qRVEdXVPnK/mempalace_code/mirror_preflight.py:14): `--delete-excluded` is listed as delete semantics, but a command with all required excludes is still classified `ok=True`. In rsync, `--delete-excluded` deletes excluded receiver files too, so the recommended excludes no longer protect `palace/`, KG, config, or backups. Repro classified safe: `rsync -a --delete-excluded --exclude=palace/ --exclude=knowledge_graph.sqlite3 --exclude=config.json --exclude=backups/ ~/.mempalace/ user@host:.mempalace/`.

- P2, Medium: [mempalace_code/mirror_preflight.py](/private/var/folders/jw/lhsrh3md3zn1gx15pt4g54th0000gn/T/tmp.qRVEdXVPnK/mempalace_code/mirror_preflight.py:107): the classifier only accepts `tokens[0]` as `rsync`, so dangerous mirror commands wrapped as `sudo rsync ...` or `env FOO=1 rsync ...` return `ok=True`. That leaves a plausible installed operator command shape outside the guard.

2. Known Issues Map Status

No previous audit was present at `docs/audits/REMOTE-MIRROR-SAFE-GUARDS-round-0.md`. Matching scoped context was limited to `docs/plans/REMOTE-MIRROR-SAFE-GUARDS.md`; no duplicate findings were found there.

3. Evidence Reviewed

- `.tasks/TASK-REMOTE-MIRROR-SAFE-GUARDS/codex-hardening-round-1.diff`
- `.tasks/TASK-REMOTE-MIRROR-SAFE-GUARDS/codex-hardening-round-1-files.txt`
- `docs/plans/REMOTE-MIRROR-SAFE-GUARDS.md`
- `mempalace_code/mirror_preflight.py`
- `mempalace_code/cli_commands/preflight.py`
- `mempalace_code/cli.py`
- `tests/test_cli.py`
- README and backup/restore doc diff hunks

4. Residual Risks

I did not run pytest because this isolated snapshot omits package files such as `mempalace_code/__init__.py`; normal imports resolve to the live checkout instead. I used direct file loading only to verify classifier behavior.

5. Convergence Recommendation

Do not converge yet. Fix the `--delete-excluded` safety hole first; then decide whether wrapper command detection is in scope for this feature or should be explicitly rejected/documented.

6. Suggested Claude Follow-Up

Add classifier tests for `--delete-excluded` with all excludes and for wrapped commands such as `sudo rsync -a --delete ~/.mempalace/ ...`. For `--delete-excluded`, safest behavior is to block any MemPalace state-dir mirror using it regardless of exclude coverage.