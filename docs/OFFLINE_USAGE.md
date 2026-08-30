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

On a machine with internet access:

```bash
# Download or verify the model in the default cache location
mempalace-code fetch-model

# The model and .mempalace-model.json provenance live at:
#   ~/.cache/huggingface/mempalace-fastembed/all-MiniLM-L6-v2-v1/
# Archive it:
tar -czf minilm-cache.tar.gz -C ~/.cache/huggingface/mempalace-fastembed \
    all-MiniLM-L6-v2-v1
```

On the airgapped machine:

```bash
# Restore to the same cache location
mkdir -p ~/.cache/huggingface/mempalace-fastembed
tar -xzf minilm-cache.tar.gz -C ~/.cache/huggingface/mempalace-fastembed

# Install mempalace-code without triggering a download
pip install mempalace-code
mempalace-code init ~/my-project --skip-model-download
```

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

If the command exits with a connection error, the model is not fully cached.  Run
`mempalace-code fetch-model` on a connected machine first.

---

## 3. Using a Custom Model Offline

If you want to use a different embedding model (see `docs/UPSTREAM_HARDENING.md` for
the model upgrade policy):

On CPU-only Linux, create an owner-private scratch directory on a filesystem with
adequate free space, inspect that filesystem, and keep both ordered install stages on the
same `TMPDIR`:

```bash
install -d -m 700 "$HOME/.cache/mempalace/tmp"
df -h "$HOME/.cache/mempalace/tmp"
TMPDIR="$HOME/.cache/mempalace/tmp" python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
TMPDIR="$HOME/.cache/mempalace/tmp" python -m pip install 'mempalace-code[custom-models]'
```

An `Errno 28` or `No space left on device` result leaves the current CPU prerequisite or
custom-model extra stage incomplete. Free space on that filesystem, then recover from any
directory by repeating the complete ordered install on the same scratch directory:

```bash
install -d -m 700 "$HOME/.cache/mempalace/tmp"
df -h "$HOME/.cache/mempalace/tmp"
TMPDIR="$HOME/.cache/mempalace/tmp" python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
TMPDIR="$HOME/.cache/mempalace/tmp" python -m pip install 'mempalace-code[custom-models]'
```

On other supported platforms, install the custom-model extra directly:

```bash
# 1. Install the explicit custom-model compatibility boundary:
python -m pip install 'mempalace-code[custom-models]'

# 2. Download or verify on a connected machine:
mempalace-code fetch-model --model all-mpnet-base-v2

# 3. Pass the model name when opening the store (Python API):
from mempalace_code.storage import LanceStore
store = LanceStore(palace_path="~/.mempalace/palace", embed_model="all-mpnet-base-v2")

# 4. Or pass embed_model= wherever you open a LanceStore in your own scripts.
```

Only the explicit custom-model path may use SentenceTransformer trusted remote code.
Canonical `all-MiniLM-L6-v2` aliases always use CPU FastEmbed and never enable it.
Once a palace is created with a specific model, all subsequent queries must use the same
model; changing the model requires re-mining all content.

---

## 4. `fetch-model` Reference

```
mempalace-code fetch-model [--model MODEL] [--force]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--model MODEL` | `all-MiniLM-L6-v2` | HuggingFace model name or local model path |
| `--force` | off | Delete only an exact provenance-owned canonical cache and re-download |

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

# Force re-download (e.g. after corruption)
mempalace-code fetch-model --force

# Verify or download a non-default model after installing [custom-models]
mempalace-code fetch-model --model all-mpnet-base-v2
```

`fetch-model` always tries local-only model resolution first. If the model is
already cached, it does not make an online-capable HuggingFace Hub lookup and
prints `Model '<name>' is already available locally.`. Use `--force` only when
you intentionally want a fresh canonical download. It refuses symlinks, foreign
directories, and missing or mismatched provenance. Move refused state aside manually,
then run `mempalace-code fetch-model`.

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

The low-level Python API also exposes one explicit network-capable method:
`EntityRegistry.research()`. Calling it directly contacts the English Wikipedia REST
API for the requested word and caches the result in the entity registry. Standard CLI,
MCP, onboarding, mining, search, update, and watcher flows never call this method.
Airgapped applications should omit direct calls to `EntityRegistry.research()`.

To guarantee offline operation in automation or airgapped environments:

```bash
export MEMPALACE_VERSION_CHECK=0
```

This env var overrides any saved preference and prevents automatic and explicit version-check
network calls, including `version-check --check-now`; invalid values fail closed in the same way.
It does not block updater PyPI requests from `update status`, `update check`, `update apply --yes`,
or scheduled update execution, and it does not alter an application that explicitly calls
`EntityRegistry.research()`.

While offline, do not run `update status`, `update check`, `update apply --yes`, or scheduled
update execution. Avoid direct `EntityRegistry.research()` calls too. Retry them after connectivity
is available. Run `unset MEMPALACE_VERSION_CHECK` (or set it to `1`) only when you also want to
re-enable version checks.

---

See also: [`docs/UPSTREAM_HARDENING.md`](UPSTREAM_HARDENING.md) for the embedding model
upgrade policy and benchmark requirements.
