# Offline Usage Guide

mempalace-code is designed to run fully offline after a one-time model download during setup.
This guide covers airgapped installs, offline verification, custom models, and the
`fetch-model` CLI reference.

---

## 1. Airgapped Install

On an airgapped machine you cannot download the embedding model automatically.  The
recommended approach is to pre-seed the MemPalace-owned FastEmbed cache from a connected
machine and copy it with its immutable provenance file.

### Option A — Copy the cache from a connected machine

On a machine with internet access and the same operating system, CPU architecture, and Python
minor version as the airgapped machine:

```bash
# Download or verify the model in the default cache location
mempalace-code fetch-model

# The model and .mempalace-model.json provenance live at:
#   ~/.cache/huggingface/mempalace-fastembed/all-MiniLM-L6-v2-v1/
# Archive it:
tar -czf minilm-cache.tar.gz -C ~/.cache/huggingface/mempalace-fastembed \
    all-MiniLM-L6-v2-v1

# Collect the package and every dependency wheel (add ==X.Y.Z to pin a release):
python3 -m pip download mempalace-code -d mempalace-wheels
```

Copy `minilm-cache.tar.gz` and the `mempalace-wheels/` directory to the airgapped machine, then:

```bash
# Restore to the same cache location
mkdir -p ~/.cache/huggingface/mempalace-fastembed
tar -xzf minilm-cache.tar.gz -C ~/.cache/huggingface/mempalace-fastembed

# Install from the copied wheels only; --no-index keeps pip off the network
python3 -m venv ~/.mempalace/venv
~/.mempalace/venv/bin/python -m pip install --no-index --find-links mempalace-wheels mempalace-code
~/.mempalace/venv/bin/mempalace-code init ~/my-project --skip-model-download
```

An internal package mirror can replace the wheel directory. Add `~/.mempalace/venv/bin` to
`PATH` to call `mempalace-code` by name. Package updates and version checks need network access;
see [Version Checks and Offline Guarantees](#5-version-checks-and-offline-guarantees).

### Option B — Use a custom `HF_HOME`

If your cache lives in a non-default location (e.g. on a read-only network share):

```bash
export HF_HOME=/mnt/shared/huggingface
mempalace-code search "my query"   # resolves from $HF_HOME/mempalace-fastembed/
```

Set `HF_HOME` in your shell profile so it persists across sessions.

---

## 2. Verify Offline Operation

Once the model is cached, you can confirm that no network calls are made by setting the
HuggingFace offline flags:

```bash
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1

# This must succeed without network access:
mempalace-code search "test"
```

If the model is not fully cached, the command exits 1 and names its recovery:

```
Canonical FastEmbed cache is not owned: <reason>. Run `mempalace-code fetch-model` while online, then retry offline.
```

The reason includes an artifact whose size does not match FastEmbed's download metadata, such
as a truncated `model.onnx`. A cache that passes these checks but whose model still fails to
load names the model cache, not the palace:

```
Canonical FastEmbed model cache failed to load: <reason>. Cache: <path>. Run `mempalace-code fetch-model` while online, then retry.
```

Run the named `fetch-model` command on a connected machine (and copy the cache as in section 1),
then retry. Palace repair cannot fix a model-cache error.

---

## 3. Using a Custom Model Offline

If you want to use a different embedding model (see the
[Embedding Model Policy in `AGENTS.md`](../AGENTS.md#embedding-model-policy) for the model
upgrade policy):

Install the `[custom-models]` extra into the installation that runs `mempalace-code`, not into
whichever `python` comes first on `PATH`. A custom-model command that finds the extra missing
prints the exact install command for its own installation.

A `uv tool` install is rebuilt from its uv receipt on every `uv tool upgrade`, so record the
extra there and list every extra you already use (for example
`'mempalace-code[custom-models,watch]'`):

```bash
uv tool install --force 'mempalace-code[custom-models]'
```

A pipx install is changed only through pipx, so pipx records the package and keeps it on
`pipx reinstall`. Add the extra's requirement to the existing environment (on CPU-only Linux,
first run `pipx inject mempalace-code torch --pip-args='--index-url https://download.pytorch.org/whl/cpu'`):

```bash
pipx inject mempalace-code 'sentence-transformers>=5.6.0'
```

If you installed with a custom `PIPX_HOME`, keep it set for this command; the hint a
custom-model command prints names it for you.

For bootstrap and project-venv installs, and for a `uv tool` install that needs the
CPU-only stages below, resolve the interpreter that owns `mempalace-code` once:

```bash
MEMPALACE_PYTHON="$(dirname "$(realpath "$(command -v mempalace-code)")")/python"
test -x "$MEMPALACE_PYTHON"
```

If `test -x` fails, `mempalace-code` lives in a user or system site; use the Python you
installed it with. The commands below run `"$MEMPALACE_PYTHON" -m pip install`; the hint
a custom-model command prints pins the running release, for example
`'mempalace-code[custom-models]==X.Y.Z'`, so pip does not change the installed version. When that
environment has no pip (`uv venv` or `uv tool`), run `uv pip install --python "$MEMPALACE_PYTHON"`
with the same arguments instead; a `uv tool` upgrade removes packages installed that way, so
repeat the stages after each upgrade.

On CPU-only Linux, create an owner-private scratch directory on a filesystem with
adequate free space, inspect that filesystem, and keep both ordered install stages on the
same `TMPDIR`:

```bash
install -d -m 700 "$HOME/.cache/mempalace/tmp"
df -h "$HOME/.cache/mempalace/tmp"
TMPDIR="$HOME/.cache/mempalace/tmp" "$MEMPALACE_PYTHON" -m pip install torch --index-url https://download.pytorch.org/whl/cpu
TMPDIR="$HOME/.cache/mempalace/tmp" "$MEMPALACE_PYTHON" -m pip install 'mempalace-code[custom-models]'
```

An `Errno 28` or `No space left on device` result leaves the current CPU prerequisite or
custom-model extra stage incomplete. Free space on that filesystem, then recover from any
directory by repeating the complete ordered install on the same scratch directory:

```bash
MEMPALACE_PYTHON="$(dirname "$(realpath "$(command -v mempalace-code)")")/python"
install -d -m 700 "$HOME/.cache/mempalace/tmp"
df -h "$HOME/.cache/mempalace/tmp"
TMPDIR="$HOME/.cache/mempalace/tmp" "$MEMPALACE_PYTHON" -m pip install torch --index-url https://download.pytorch.org/whl/cpu
TMPDIR="$HOME/.cache/mempalace/tmp" "$MEMPALACE_PYTHON" -m pip install 'mempalace-code[custom-models]'
```

On other supported platforms, install the custom-model extra directly:

```bash
# 1. Install the explicit custom-model compatibility boundary
#    (a uv tool install that ran the `uv tool install --force` command above already has it):
"$MEMPALACE_PYTHON" -m pip install 'mempalace-code[custom-models]'

# 2. Download or verify on a connected machine:
mempalace-code fetch-model --model all-mpnet-base-v2

# 3. Create the palace with that model once (Python API), before anything else writes to it:
from mempalace_code.storage import LanceStore
store = LanceStore(palace_path="/home/me/.mempalace/palace", embed_model="all-mpnet-base-v2")

# 4. From then on `mempalace-code mine`, `search`, and the MCP server use the recorded model.
```

Only the explicit custom-model path (`LanceStore(..., embed_model=...)`) may use
SentenceTransformer trusted remote code. Canonical `all-MiniLM-L6-v2` aliases always use CPU
FastEmbed and never enable it.

A palace records the model that created it on its vector column. `mempalace-code` commands,
the MCP server, and `LanceStore(path)` without `embed_model` open it with that model, so the
installation running them needs `[custom-models]` and the cached model; otherwise they exit 1
with an error that names the model and the command to run. A model named only by the palace
record is untrusted palace data: it is loaded from local files with remote code disabled and
is never downloaded. Download it yourself with `mempalace-code fetch-model --model <model>`;
a model that needs remote code opens only through the Python API with an explicit
`embed_model`. Opening a palace with a different `embed_model` is refused: changing the model
means re-mining the content into a new palace.

Palaces created by releases before model recording do not record a model and open with the
default. If you built
one with a custom model, record it once, from an installation that has the model:

```python
from mempalace_code.storage import LanceStore
LanceStore("/home/me/.mempalace/palace", embed_model="all-mpnet-base-v2").record_embed_model()
```

`record_embed_model()` loads the model and refuses one whose vector size does not fit the
palace. Until a model is recorded, a command whose default model does not fit the palace's
vectors exits 1 with this recovery instead of returning wrong results; a custom model with the
same vector size as the default cannot be detected, so record it.

---

## 4. `fetch-model` Reference

```
mempalace-code fetch-model [--model MODEL] [--force]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--model MODEL` | `all-MiniLM-L6-v2` | HuggingFace model name or local model path |
| `--force` | off | Download a fresh canonical copy; the owned cache is set aside, deleted only after the new copy validates, and restored if the download fails |

**Exit codes:**
- `0` — model is available locally or was downloaded and cached successfully
- `1` — local verification or download failed (missing cache, network error, disk full, etc.)

**Cache location:**

The canonical FastEmbed artifact is stored at:

```
$HF_HOME/mempalace-fastembed/all-MiniLM-L6-v2-v1/
```

`HF_HOME` defaults to `~/.cache/huggingface`.  Override it with the `HF_HOME`
environment variable.

**Examples:**

```bash
# Verify or download the default model
mempalace-code fetch-model

# Force a fresh download (needs network access; refused while offline mode is on)
mempalace-code fetch-model --force

# Verify or download a non-default model after installing [custom-models]
mempalace-code fetch-model --model all-mpnet-base-v2
```

`fetch-model` always tries local-only model resolution first. If the model is
already cached, it does not make an online-capable HuggingFace Hub lookup and
prints `Model '<name>' is already available locally.`.

The download is pinned: it fetches exactly the reviewed revision
(`5f1b8cd78bc4fb444dd171e59b18f3a3af89a079` of `qdrant/all-MiniLM-L6-v2-onnx`), whatever
the repository's `main` branch points to now, and checks every file's size and digest
against the reviewed copy before the cache is trusted. New upstream commits therefore never
change or break what is installed. If that revision is no longer published, the error says
so and that retrying will not help; copy a prepared cache instead
([Option A](#option-a--copy-the-cache-from-a-connected-machine)).

A download that fails, is interrupted, or does not match the reviewed files is deleted,
whether `fetch-model`, `init`, or a first online `mine`/`search`/MCP call started it, so
repeated attempts never pile up copies. A first-use failure prints one line with the
recovery (`fetch-model` for a network failure, a prepared cache for an unavailable revision). Use `--force` only when
you intentionally want a fresh canonical download. A working cache is never deleted
first: `--force` renames it to a hidden sibling, downloads the replacement, and deletes the
old copy only after the new one validates. If the download fails, the old copy is put back
and the error says `The previous cache was restored`. Pressing Ctrl-C during the download
restores it too and prints the same line before `Stopped by Ctrl-C`. If the process is killed
before it can restore it (for example with `kill -9`), the working copy stays beside the cache
root as `.all-MiniLM-L6-v2-v1.replace-<pid>-<id>`; `search` and `mine` then say an interrupted
`fetch-model` left it set aside, and the next `mempalace-code fetch-model` (offline too) puts
it back, deleting the killed run's incomplete download, or deletes the set-aside copy when a
valid cache already replaced it.

A provenance-owned cache whose model fails to load is replaced the same way by a plain
`mempalace-code fetch-model`; retrying never loops on the same broken copy.

A partial or unowned cache (missing or mismatched provenance, an artifact whose size does not
match FastEmbed's download metadata, a deleted blob, or a foreign directory) is kept, not
deleted: `fetch-model` renames it beside the cache root as
`all-MiniLM-L6-v2-v1.quarantine-<id>`, prints `Preserved partial cache at: <path>`, and
downloads a fresh copy. Remove the preserved copy once you no longer need it. Only a cache
that was already there is preserved; a cache directory that holds no files is removed instead. `fetch-model` refuses a cache root that is a symlink or not a directory, a
symlinked provenance file, and any link that resolves outside the cache. Move that path aside
manually, then run `mempalace-code fetch-model`.

While `HF_HUB_OFFLINE` or `TRANSFORMERS_OFFLINE` is set, no download can run, so
`fetch-model` never moves, preserves, or deletes a cache, apart from putting back a cache that
a killed `fetch-model --force` set aside (above). It verifies an owned cache and
otherwise exits 1 with one message that names the offline switch, leaves the cache unchanged,
and gives the command to run with network access, for example
`env -u HF_HUB_OFFLINE mempalace-code fetch-model --model all-MiniLM-L6-v2`. On an
airgapped machine, copy a prepared cache instead ([Option A](#option-a--copy-the-cache-from-a-connected-machine)).

---

## 5. Version Checks and Offline Guarantees

With version checks disabled, the core commands — `init`, `mine`, `mine-all`, `search`,
`status`, `health`, `repair`, `backup`, and `watch` — and ordinary MCP tools run completely
offline after the one-time model download. Search/mining model startup first uses local-only
resolution, so a populated cache does not require HuggingFace metadata checks. These named
application operations do not themselves contact PyPI or any external service.

The CLI also exposes these network-capable operations:

- **Opted-in automatic checks:** contact `https://pypi.org/pypi/mempalace-code/json` for
  package metadata at most once per interval (default 168 h). Only the `info.version` field
  is read. No telemetry, no user IDs, no installed-package inventory.
- **`version-check --check-now`:** performs a single metadata fetch and prints the result to
  stdout, unless the process environment kill switch below is disabled or invalid.
- **`update status` and `update check`:** are read-only, but each refreshes canonical package
  metadata from `https://pypi.org/pypi/mempalace-code/json`. They can fail when PyPI or the
  network is unavailable. Read-only means that they do not install a package or persist updater
  state; it does not mean offline.
- **`update apply --yes` and scheduled update execution:** can contact PyPI and package sources
  to establish provenance and install an eligible release. See [UPDATES.md](UPDATES.md) for the
  complete updater contract.

The entity registry performs no network lookup. Existing `wiki_cache` entries from older
versions remain readable, but current packages expose no method that creates new entries.

MemPalace sets `ORT_DISABLE_TELEMETRY=1` before ONNX Runtime loads (a value you set yourself is
kept), so ONNX Runtime does not create its usage-telemetry store under your home directory.

To guarantee offline operation in automation or airgapped environments:

```bash
export MEMPALACE_VERSION_CHECK=0
```

This env var overrides any saved preference and prevents automatic and explicit version-check
network calls, including `version-check --check-now`; invalid values fail closed in the same way.
It does not block updater PyPI requests from `update status`, `update check`, `update apply --yes`,
or scheduled update execution.

While offline, do not run `update status`, `update check`, `update apply --yes`, or scheduled
update execution. Retry them after connectivity is available. Run
`unset MEMPALACE_VERSION_CHECK` (or set it to `1`) only when you also want to re-enable version
checks.

---

See also: the [Embedding Model Policy in `AGENTS.md`](../AGENTS.md#embedding-model-policy)
for the embedding model upgrade policy and benchmark requirements.
