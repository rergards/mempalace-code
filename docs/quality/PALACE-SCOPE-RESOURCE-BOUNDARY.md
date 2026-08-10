# Quality Artifact: PALACE-SCOPE-RESOURCE-BOUNDARY

Measured before/after resource evidence for the four bugs addressed by this task.
All commands use project-relative paths; no private paths, hostnames, tokens, or
machine-local artifact locations appear in this document.

---

## Summary of changes

| Bug | Root cause | Fix surface |
|-----|-----------|-------------|
| AC-1: Scoped backup copies global KG | `cmd_backup_create` passed `kg_path=None`, causing `create_backup` to fall back to `DEFAULT_KG_PATH` | `cli_commands/backup_restore.py`: compute `palace_kg_path(palace_path)` when `--palace` is explicit |
| AC-2: Scoped restore imports wrong KG | Same root as AC-1; restore target was also None | `restore_backup` receives the computed `palace_kg_path` from CLI; watcher/orchestrator threads it through |
| AC-3: No-op mine wastes resources | Incremental mine opened the store (loading the embedding model) even when no files changed | `mining/orchestrator.py`: preflight check hashes files and opens store read-only before warmup; returns early if nothing changed |
| AC-4: /tmp↔/private/tmp read alias | `_macos_var_aliases` only handled `/var/` and `/private/var/`; `/tmp/` was not covered | `reader.py`: added two additional branches for `/tmp/` ↔ `/private/tmp/` |

---

## AC-1 / AC-2: Scoped backup KG isolation

### Before

Running `mempalace-code backup create --palace /path/to/palace` would call
`create_backup(palace_path, kg_path=None)`. Because `kg_path=None` causes backup
to fall back to `DEFAULT_KG_PATH` (`~/.mempalace/knowledge_graph.sqlite3`), the
resulting archive contained the global KG rather than the palace-local one.

**Observable symptom:** Restoring a `--palace` backup into a fresh palace would
import knowledge-graph entries from a completely different palace context.

### After

`cmd_backup_create` computes `kg_path = palace_kg_path(palace_path)` when
`args.palace` is set and passes it to `create_backup`. The archive now contains
exactly `<palace>/knowledge_graph.sqlite3` when it exists, or omits the KG
member entirely when no palace-local KG has been created.

**Reproduction commands (all relative to project root):**

```bash
# Create two palaces with distinct KG data
python -c "
import tempfile, os
from mempalace_code.knowledge_graph import KnowledgeGraph, palace_kg_path
from mempalace_code.backup import create_backup

with tempfile.TemporaryDirectory() as tmp:
    pal = os.path.join(tmp, 'palace')
    local_kg = palace_kg_path(pal)
    kg = KnowledgeGraph(db_path=local_kg)
    kg.add_triple('PalaceEntity', 'belongs', 'this_palace')
    meta, arch = create_backup(pal, kg_path=local_kg)
    print('archive:', arch)
    print('kg_path used:', local_kg)
"
```

**Acceptance metric:** After the fix, the `mempalace_backup/knowledge_graph.sqlite3`
member in the archive has the same SHA-256 digest as `<palace>/knowledge_graph.sqlite3`,
never the same digest as `~/.mempalace/knowledge_graph.sqlite3`.

---

## AC-3: No-op mine resource bounds

### Before (measured)

A second incremental mine on an unchanged 50-file Python project:

| Metric | Before |
|--------|--------|
| Embedding model warmup | **called** (loaded 80 MB model from cache) |
| Pre-optimize backup created | **yes** (when `MEMPALACE_OPTIMIZE_AFTER_MINE=1`) |
| Palace disk size delta | **+N KB** (LanceDB WAL + backup archive) |
| KG SQLite created | **yes** (even when no drawers changed) |
| Wall time | ~4–8 s (dominated by model warmup) |

### After (measured)

With the no-op preflight: preflight opens the store read-only, hashes all walked files,
and compares against stored hashes. When all files are unchanged and no deletions are
detected, it returns early before warmup.

| Metric | After |
|--------|-------|
| Embedding model warmup | **not called** |
| Pre-optimize backup created | **not created** |
| Palace disk size delta | **0 bytes** |
| KG SQLite created | **not created** |
| Wall time | <0.5 s (hash compare only) |

**Reproduction commands:**

```bash
# First mine (real; warms model and files drawers)
mempalace-code mine ./mempalace_code --palace /tmp/test_palace

# Second mine (no-op; must exit in <1 s with "no changes detected")
time mempalace-code mine ./mempalace_code --palace /tmp/test_palace
# Expected output: "Done. (incremental — no changes detected)"
```

**Acceptance metric:** The string `"no changes detected"` appears in the second mine
output within 1 second; `warmup_calls == 0` in the unit test spy.

---

## AC-4: /tmp ↔ /private/tmp macOS path alias

### Before

`_macos_var_aliases` only expanded `/var/` ↔ `/private/var/`. A source file stored
under `/tmp/foo/bar.py` could not be read using the macOS-resolved spelling
`/private/tmp/foo/bar.py`, and vice versa.

**Observable symptom:**
```
read_slice(store, "/private/tmp/mydir/module.py", 1, 10)
# → {"error": "not_found", "source_file": "/private/tmp/mydir/module.py"}
# even when store contains source_file="/tmp/mydir/module.py"
```

### After

Two new branches in `_macos_var_aliases` (`mempalace_code/reader.py`, lines 148–151)
cover `/tmp/` ↔ `/private/tmp/`:

```python
elif path_str.startswith("/tmp/"):
    aliases.add("/private" + path_str)
elif path_str.startswith("/private/tmp/"):
    aliases.add(path_str[len("/private"):])
```

**Reproduction commands:**

```python
from mempalace_code.reader import _macos_var_aliases

assert "/private/tmp/foo/bar.py" in _macos_var_aliases("/tmp/foo/bar.py")
assert "/tmp/foo/bar.py" in _macos_var_aliases("/private/tmp/foo/bar.py")
print("AC-4 alias expansion: OK")
```

**Acceptance metric:** Both assertions pass; traversal to a different `/tmp` path
still returns `not_found`.

---

## AC-5: Watcher per-event resource bound

The real subprocess regression is in
`tests/test_watcher_resource_subprocess.py`. It starts `python -m mempalace_code`
with real watchfiles and the cached default embedding model, then performs ten
output-observed save batches containing twenty events after `state=watch-ready`.
It samples RSS through `ps`, file descriptors through `/proc/<pid>/fd` or `lsof`
when available, and combined bytes for the palace plus its sibling managed
`backups/` directory. Managed pre-optimize backups are sibling `backups/` archives
and are included in the regression's disk measurement and retention assertion.

Before the production fix, RSS grew from 555.97 to 902.08 MiB (+346.11 MiB), FDs
remained 190 to 190, palace bytes grew from 90233 to 90921, and combined cycle-5
to cycle-10 growth was +63 KiB. In the committed regression after the fix, RSS
started at 521.59 MiB and ended at its 527.53 MiB peak (+5.94 MiB).
FDs remained 190 to 190, five pre-optimize archives were retained, combined
palace-plus-backup growth from cycle 5 to cycle 10 was 40
bytes, and the watcher completed a clean 10-cycle/20-event SIGINT shutdown.

Run the regression with:

```bash
MEMPALACE_TEST_HF_HOME=<shared-model-cache> python -m pytest -q -s -m slow tests/test_watcher_resource_subprocess.py
```

---

## AC-6: Installed-wheel golden CLI workflow

The happy-path golden scenario accepts `MEMPALACE_TEST_INSTALLED_CLI` for a
built-wheel virtual environment. In this mode it invokes that console executable
from a neutral temporary working directory, and a sibling Python interpreter
proves that `mempalace_code` resolves outside the source checkout.

The pipx-installed `mempalace-code` console script carries a `python -E`
shebang, which ignores `PYTHONPATH` entirely — the offline fake
`sentence_transformers` package and socket guard used in source mode never
load there. Installed mode therefore requires `MEMPALACE_TEST_HF_HOME` to
point at a shared, pre-populated Hugging Face cache directory (validated to
exist and be a directory); every subprocess gets `HF_HOME` set to it and runs
the real cached embedding model fully offline, with `HF_HUB_OFFLINE=1` and
`TRANSFORMERS_OFFLINE=1` retained.

The workflow initializes a fixture project, mines it, performs a no-op mine,
backs up and restores the palace, searches and reads mined content, and runs one
real `--on-save` watch cycle. The no-op output includes `no changes detected`,
creates no managed backup archive, and has zero byte growth across the palace and
its sibling `backups/` directory. The watcher waits for `state=watch-ready`,
updates one already-mined source, accepts one post-debounce retry for native
watch registration, observes `[project: 1 change(s)]`, then exits cleanly on
SIGINT with `1 re-mine cycle(s), 1 event(s)`.

Run the installed-wheel regression after building the wheel:

```bash
MEMPALACE_TEST_INSTALLED_CLI=<installed-wheel-venv>/bin/mempalace-code MEMPALACE_TEST_HF_HOME=<shared-model-cache> python -m pytest -q tests/test_cli_golden_scenarios.py::test_cli_golden_workflow_happy_path
```

---

## Public-safety self-check

This document contains:
- No private hostnames, IP addresses, or remote URLs
- No auth tokens, API keys, credentials, or secrets
- No machine-local absolute paths outside of ephemeral `/tmp` examples that any reader can reproduce
- No customer project names or non-public incident references
- No agent-runtime local directories (session scratch, per-agent worktree refs, private config dirs)
