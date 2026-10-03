# Opt-in update operations

## Boundary

MemPalace never upgrades itself from normal CLI, MCP, watcher, or version-check execution. The
operator invokes `mempalace-code update` explicitly. Automatic runs stay disabled until the operator
installs the systemd-user timer with `mempalace-code update scheduler install --yes`.

Supported install ownership is deliberately narrow:

- `uv tool` installations
- `pipx` installations
- Custom `PIPX_HOME` paths are compared by resolved filesystem location, including symlink
  and platform aliases. The `pipx` manager must still be discoverable.
- the documented bootstrap venv at `~/.mempalace/venv`

System Python, distro-managed packages, editable/source checkouts, and ambiguous virtual
environments are refused before package or service mutation.

The two boundaries are independent:

- **Manual `update apply --yes`** runs on Linux (systemd-user) and macOS (launchd-user) for those
  supported isolated installers. Every other platform is refused with `stage: unsupported-platform`.
- **Scheduled package updates** remain Linux systemd-user only. There is no macOS scheduler: no
  launchd update agent, and no cron or Windows Task Scheduler support. Machine-wide units are never
  created.

### Ordinary pip installs

If you installed with plain `pip`, `mempalace-code update` refuses your installation by design — it
will not mutate an environment it does not own. Upgrade yourself instead, naming the interpreter
that actually runs mempalace-code and an explicit version:

```bash
"/absolute/path/to/python" -m pip install --upgrade "mempalace-code==X.Y.Z"
```

Run `mempalace-code version-check --check-now` to get that line filled in: it prints the absolute path
the interpreter running mempalace-code and the newest version on PyPI, so you never have to work out
which `python` on `PATH` owns the install. For an ordinary pip install it prints only that command,
not the `update apply` line; `update status` shows the same command under
`Upgrade this pip install with:`, and `update apply --yes` names it in its refusal. When PyPI
offers no newer compatible release (or cannot be reached), both say so under `Pip upgrade:`
instead of printing a command. `MEMPALACE_VERSION_CHECK=0` and invalid values block this
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
extras, managed watcher state, scheduler state, next run, and canonical PyPI provenance. `update check`
reports `stage: check` and `update status` reports `stage: status`; both refresh the same PyPI
provenance.

The `Decision` line (`reason` in JSON) names the refusal to act on first: an unsupported platform, then
an installation `update` does not own (shown as `Installer refusal:`), then watcher, `HOME`, extras,
and provenance preconditions. `update apply --yes` refuses in the same order. `manual_update_supported`
is true only when both the platform and the installation can be updated with `update apply`. Eligible
targets are newer stable PEP 440 releases in the compatible major version with a non-yanked wheel.
Prereleases, yanked files, wheels missing from PyPI metadata, and failed provenance requests do not
produce an update target.

The updater detects the installed optional topology. It retains `watch`, `treesitter`,
`spellcheck`, and `custom-models` extras where present. Retired Chroma extras are excluded. An active configured watcher without the `watch` extra is a
preflight failure. The update transaction also checks free disk capacity and the local backup policy;
it does not alter palace data or create a replacement palace backup.

## Confirmation refusal contract

The guarded mutations are `update apply`, `update scheduler install`, and
`update scheduler remove`. If any is invoked without `--yes`, it exits 2 before mutation: no
package, scheduler, service, log, state, lease, or palace change occurs.

In human mode the command prints a concise confirmation refusal, naming the platform's user service
manager, followed by `Recovery: <command>`. The recovery names the launcher you invoked when
`mempalace-code` on `PATH` is a different one. On a platform without systemd-user,
`update scheduler install` and `update scheduler remove` never offer `--yes`: they report
`stage: unsupported-platform` instead. In JSON mode stdout contains exactly one parseable JSON object and stderr
contains no human prose. The object contains `ok: false`, `stage: confirmation`, `exit_code: 2`,
and `recovery_command`; that command matches the refused action and ends in `--yes --json`.
For `unsupported-platform`, recovery instead runs `update status --json` through the same
launcher. Release checks validate the launcher identity and exact action arguments for both
short and absolute recovery commands.
Review the current target and mutation authority before running the emitted recovery command.

## Manual update

```bash
mempalace-code update apply --yes
```

`--yes` confirms package and service mutation. The updater records the old version and whether the
selected managed watcher was active only after installer, provenance, extras, disk/backup, and
operation-lease preflight succeeds. It stops the selected active watchers, takes the exclusive lease,
installs the selected version with retained extras, validates `mempalace-code update --help`, probes
the palace, then restarts and verifies exactly the watchers it stopped.

Watcher coordination follows whichever user service manager owns the host:

- **Linux (systemd-user)** — discovery accepts the legacy `mempalace-watch.service` or one active
  `mempalace-watch-<root>.service` whose `ExecStart` is a supported MemPalace `watch` command, and
  the update coordinates that single selected unit.
- **macOS (launchd-user)** — discovery coordinates *every* loaded attributable
  `com.mempalace.watch*` LaunchAgent, not just one. A loaded job that lists no PID is included,
  because `KeepAlive` can respawn it mid-replacement. Each label must be backed by an owned, regular,
  label-matching plist in `~/Library/LaunchAgents` whose `ProgramArguments` is a supported MemPalace
  `watch` command.

Ambiguous, malformed, unattributable, or unavailable watcher evidence is a visible refusal before
package, lease, or service mutation. When `HOME` is not the account's passwd home directory (for
example in a sandboxed shell), the refusal names the fix instead:
`rerun with HOME set to the account home: HOME=<account home> mempalace-code update status --json`.
Otherwise it names the command that shows what the watchers were left in:

```bash
mempalace-code update status --json
```

Watchers hold shared leases throughout their lifetime. The updater reports lock owner metadata rather
than racing an unmanaged watcher. A scheduled overlap exits before package or service mutation.
Dead-PID owner records from an interrupted process are pruned before they can block a later update;
the kernel lease remains the concurrency authority.

### macOS on v1.13.5: one-time manual recovery

v1.13.5 on macOS **cannot self-apply this patch**: that version refuses manual apply on any
non-Linux platform, so `mempalace-code update apply --yes` returns an unsupported-platform refusal
before it can install the release that adds launchd support. Move once with the installer that owns
your installation:

```bash
uv tool upgrade mempalace-code   # uv tool installs
pipx upgrade mempalace-code      # pipx installs
~/.mempalace/venv/bin/python -m pip install --upgrade mempalace-code   # bootstrap-venv installs
```

Then confirm the new boundary:

```bash
mempalace-code update status
```

Do not use plain `pip` for a `uv tool` or `pipx` installation — it would write into an environment
the owning installer manages. The bootstrap-venv line above is not plain `pip`: it names that venv's
own interpreter explicitly, so it upgrades only that environment. After this one-time upgrade, macOS
manual updates work through `mempalace-code update apply --yes`; scheduled updates stay Linux-only.

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
rediscover the same package manager under the minimal systemd-user manager environment. A custom
`PIPX_HOME` or `PIPX_BIN_DIR` (pipx) and `UV_TOOL_DIR` or `UV_TOOL_BIN_DIR` (uv tool) set when you
render or install the units is carried into the service environment so the scheduled run finds the
same installation. Installed units that differ from a fresh render only in these carried lines
(units from an earlier release, or rendered from a shell with other values) still count as owned:
`install --yes` rewrites them with the current values and `remove --yes` removes them. The
generated unit does not copy an interactive shell `PATH` or embed host-private
fallback directories. `update scheduler render` still prints the units for an installation or platform
the scheduler cannot serve, as a preview, and warns on stderr with the reason
`update scheduler install --yes` would refuse; with `--json` the warning also goes to stderr only,
so stdout stays the unit JSON.

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
