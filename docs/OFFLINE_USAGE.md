# Offline Usage Guide

mempalace-code is designed to run fully offline after a one-time model download during setup.
This guide covers airgapped installs, offline verification, custom models, and the
`fetch-model` CLI reference.

---

## 1. Airgapped Install

On an airgapped machine you cannot download the embedding model automatically.  The
recommended approach is to pre-seed the HuggingFace Hub cache from a connected machine
and copy it over.

### Option A — Copy the cache from a connected machine

On a machine with internet access:

```bash
# Download the model to the default cache location
mempalace-code fetch-model

# The model lives at:
#   ~/.cache/huggingface/hub/models--sentence-transformers--all-MiniLM-L6-v2/
# Archive it:
tar -czf minilm-cache.tar.gz -C ~/.cache/huggingface/hub \
    models--sentence-transformers--all-MiniLM-L6-v2
```

On the airgapped machine:

```bash
# Restore to the same cache location
mkdir -p ~/.cache/huggingface/hub
tar -xzf minilm-cache.tar.gz -C ~/.cache/huggingface/hub

# Install mempalace-code without triggering a download
pip install mempalace-code
mempalace-code init ~/my-project --skip-model-download
```

### Option B — Use a custom `HF_HOME`

If your cache lives in a non-default location (e.g. on a read-only network share):

```bash
export HF_HOME=/mnt/shared/huggingface
mempalace-code search "my query"   # resolves model from $HF_HOME/hub/
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

```bash
# 1. Download on a connected machine:
mempalace-code fetch-model --model all-mpnet-base-v2

# 2. Pass the model name when opening the store (Python API):
from mempalace_code.storage import LanceStore
store = LanceStore(palace_path="~/.mempalace/palace", embed_model="all-mpnet-base-v2")

# 3. Or pass embed_model= wherever you open a LanceStore in your own scripts.
```

Note: once a palace is created with a specific model, all subsequent queries must use
the same model — changing the model requires re-mining all content.

---

## 4. `fetch-model` Reference

```
mempalace-code fetch-model [--model MODEL] [--force]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--model MODEL` | `all-MiniLM-L6-v2` | HuggingFace model name to download |
| `--force` | off | Delete existing cached model and re-download |

**Exit codes:**
- `0` — model downloaded and cached successfully
- `1` — download failed (network error, disk full, etc.)

**Cache location:**

The model is stored in the HuggingFace Hub cache:

```
$HF_HOME/hub/models--sentence-transformers--<model-name>/
```

`HF_HOME` defaults to `~/.cache/huggingface`.  Override it with the `HF_HOME`
environment variable.

**Examples:**

```bash
# Download the default model
mempalace-code fetch-model

# Force re-download (e.g. after corruption)
mempalace-code fetch-model --force

# Download a non-default model
mempalace-code fetch-model --model all-mpnet-base-v2
```

---

---

## 5. Version Checks and Offline Guarantees

All mempalace-code commands — `init`, `mine`, `mine-all`, `search`, `status`, `health`,
`repair`, `backup`, `watch`, and all MCP tools — run completely offline after the
one-time model download. None of them contact PyPI or any external service.

The **only** optional network activity is the version check:

- **Default (no opt-in):** no network calls, ever.
- **Opted-in automatic checks:** contact `https://pypi.org/pypi/mempalace-code/json` for
  package metadata at most once per interval (default 168 h). Only the `info.version` field
  is read. No telemetry, no user IDs, no installed-package inventory.
- **`--check-now`:** single metadata fetch, result printed to stdout.

To guarantee offline operation in automation or airgapped environments:

```bash
export MEMPALACE_VERSION_CHECK=0
```

This env var overrides any saved preference and prevents all version-check network calls.

---

See also: [`docs/UPSTREAM_HARDENING.md`](UPSTREAM_HARDENING.md) for the embedding model
upgrade policy and benchmark requirements.
