# Opt-in update operations

## Boundary

MemPalace never upgrades itself from normal CLI, MCP, watcher, or version-check execution. The
operator invokes `mempalace-code update` explicitly. Automatic runs stay disabled until the operator
installs the systemd-user timer with `mempalace-code update scheduler install --yes`.

Supported install ownership is deliberately narrow:

- `uv tool` installations
- `pipx` installations
- the documented bootstrap venv at `~/.mempalace/venv`

System Python, distro-managed packages, editable/source checkouts, and ambiguous virtual
environments are refused before package or service mutation. The first scheduler slice supports only
Linux systemd-user units. It does not create machine-wide units or support cron, launchd, or Windows
Task Scheduler.

### Ordinary pip installs

If you installed with plain `pip`, `mempalace-code update` refuses your installation by design — it
will not mutate an environment it does not own. Upgrade yourself instead, naming the interpreter
that actually runs mempalace-code and an explicit version:

```bash
"/absolute/path/to/python" -m pip install --upgrade "mempalace-code==X.Y.Z"
```

Run `mempalace-code version-check --check-now` to get that line filled in: it prints the absolute path
the interpreter running mempalace-code and the newest version on PyPI, so you never have to work out
which `python` on `PATH` owns the install. `MEMPALACE_VERSION_CHECK=0` and invalid values block this
explicit network request; run `unset MEMPALACE_VERSION_CHECK` (or set it to `1`) before retrying.
Nothing is installed for you: no scheduler, no watcher coordination, no rollback. Move to `uv tool`
or `pipx` if you want the managed flow.

The hint is only printed for an ordinary pip install. A `uv tool`, `pipx`, or bootstrap-venv install
is the managed updater's to move; a system interpreter is usually externally managed and must be
left to the OS package manager; an editable checkout has no released version to move to; and an
environment mempalace-code cannot identify gets no command at all rather than one aimed at the wrong
interpreter. In every one of those cases you see the `update status` / `update apply --yes`
guidance and nothing more.

## Preflight and provenance

Inspect state before changing anything:

```bash
mempalace-code update status
mempalace-code update check --json
```

These commands are read-only. They report the current version, selected target, installer, retained
extras, managed watcher state, scheduler state, next run, and canonical PyPI provenance. Eligible
targets are newer stable PEP 440 releases in the compatible major version with a non-yanked wheel.
Prereleases, yanked files, wheels missing from PyPI metadata, and failed provenance requests do not
produce an update target.

The updater detects the installed optional topology. It retains `watch`, `treesitter`, `spellcheck`,
and `chroma-migration` bridge extras where present. An active configured watcher without the `watch` extra is a
preflight failure. The update transaction also checks free disk capacity and the local backup policy;
it does not alter palace data or create a replacement palace backup.

## Confirmation refusal contract

The guarded mutations are `update apply`, `update scheduler install`, and
`update scheduler remove`. If any is invoked without `--yes`, it exits 2 before mutation: no
package, scheduler, service, log, state, lease, or palace change occurs.

In human mode the command prints a concise confirmation refusal followed by
`Recovery: <command>`. In JSON mode stdout contains exactly one parseable JSON object and stderr
contains no human prose. The object contains `ok: false`, `stage: confirmation`, `exit_code: 2`,
and `recovery_command`; that command matches the refused action and ends in `--yes --json`.
Review the current target and mutation authority before running the emitted recovery command.

## Manual update

```bash
mempalace-code update apply --yes
```

`--yes` confirms package and service mutation. The updater records the old version and whether the
selected managed watcher was active only after installer, provenance, extras, disk/backup, and
operation-lease preflight succeeds. Discovery accepts the legacy `mempalace-watch.service` or one
active named `mempalace-watch-<root>.service` whose `ExecStart` is a supported MemPalace `watch`
command. Ambiguous, malformed, unrelated, or unavailable systemd-user discovery is a visible refusal
before package, lease, or service mutation. It stops the selected active watcher, takes the exclusive
lease, installs the selected version with retained extras, validates `mempalace-code update --help`,
probes the palace, then restarts and verifies that same watcher if it was running before the attempt.

Watchers hold shared leases throughout their lifetime. The updater reports lock owner metadata rather
than racing an unmanaged watcher. A scheduled overlap exits before package or service mutation.
Dead-PID owner records from an interrupted process are pruned before they can block a later update;
the kernel lease remains the concurrency authority.

## Scheduled update

Review the generated units first:

```bash
mempalace-code update scheduler render
mempalace-code update scheduler install --yes
mempalace-code update scheduler status
```

The user service runs the guarded `update apply --yes --scheduled` command. The timer is persistent,
uses systemd-user only, and remains disabled unless `install --yes` has completed. The scheduler
unit sets a controlled `PATH` for the oneshot process. For `uv tool` and `pipx` installs, the
admitted absolute manager directory is prepended to `/usr/local/bin:/usr/bin:/bin` so the updater can
rediscover the same package manager under the minimal systemd-user manager environment. The generated
unit does not copy an interactive shell `PATH` or embed host-private fallback directories.

When a scheduled run proves from PyPI that the installed stable wheel is already current and no newer
compatible stable wheel is available, it exits successfully with the `up-to-date` stage before
watcher coordination, update locks, package installation, update logs, state writes, backup preflight,
palace validation, or palace file access. Manual `update apply --yes` with no eligible target still
returns a visible nonzero preflight refusal. Failed provenance, unsupported installers, unsafe watcher
discovery, missing extras, disk preflight failures, backup failures, and lock ownership also remain
nonzero for scheduled runs.

The scheduler remains disabled until `install --yes` runs. Disable it with:

```bash
mempalace-code update scheduler remove --yes
```

## Logs, status, and rollback

Durable update state is stored at `~/.mempalace/updates/state.json`. Date-addressable, bounded command
logs are stored beneath `~/.mempalace/updates/logs/`; every apply result prints the log location.

Failures after prior-version recording enter rollback. MemPalace uses the same supported installer to
restore the recorded prior version, rechecks package health, and restores the prior active watcher
state. It never overwrites or repairs palace data during rollback. A successful rollback reports the
failed stage and log path with a nonzero exit. A rollback failure requires operator recovery:

1. Read the log path printed by `mempalace-code update apply --yes`.
2. Run `mempalace-code update status` to inspect installer, provenance, watcher, and scheduler state.
3. Restore the recorded version only through the detected supported installer; do not use a system
   package manager for this installation.
4. Run `mempalace-code health` and check the watcher unit named by `mempalace-code update status`
   before re-enabling the scheduler.
