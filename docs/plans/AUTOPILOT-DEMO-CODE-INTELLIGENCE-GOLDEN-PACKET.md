---
slug: "AUTOPILOT-DEMO-CODE-INTELLIGENCE-GOLDEN-PACKET"
goal: "Generate a deterministic public-safe code-intelligence packet from real MemPalace CLI output and one minimal MCP stdio exhibit on a synthetic fixture project."
priority: P1
files:
  - path: scripts/gen_code_intelligence_packet.py
    change: "Generator: synthetic fixture, mine, 5 known-answer search queries, read exhibit, MCP stdio exhibit (initialize/tools/list/tools/call), public-safety check, --check mode for release verification."
  - path: tests/test_code_intelligence_packet.py
    change: "Tests covering output normalization, known-answer validation, schema validation, packet comparison, public-safety rejection, fixture creation, CLI returncode handling, and MCP exchange validation."
  - path: docs/demo/code-intelligence-packet.json
    change: "Committed packet JSON artifact generated from the script; includes fixture inventory, mine output, search exhibits, read exhibit, and MCP stdio exhibit."
  - path: docs/demo/code-intelligence-packet.md
    change: "Committed packet Markdown artifact generated from the same script; human-readable rendering of all exhibits."
---

## Design

The task shipped a deterministic, public-safe code-intelligence demo packet from real
MemPalace CLI output on a synthetic polyglot fixture project. The generator builds the
following exhibits from scratch on each run:

- **Fixture project** (`src/auth.py`, `src/calculator.py`, `src/models.py`,
  `docs/architecture.md`, `config.yaml`, `Makefile`, `mempalace.yaml`) — six
  source-language files covering Python, Markdown, YAML, and Makefile.
- **Mine output** — normalized CLI output from `mempalace-code mine` with
  `--full`, with timing and path placeholders stripped.
- **Five known-answer search queries** — each query validates the expected file
  appears in the top-3 results; CLI output is normalized and stored as an exhibit.
- **Read exhibit** — normalized output of `mempalace-code read src/auth.py --start 1 --end 25`.
- **MCP stdio exhibit** — three JSON-RPC exchanges with a spawned
  `python -m mempalace_code.mcp_server --profile code` subprocess:
  `initialize`, `tools/list`, and `tools/call` (mempalace_code_search).

The `--check` mode regenerates into a temp dir and compares fresh output against the
committed JSON via `_compare_packets`, validates the schema, and runs a public-safety
scan. It is a manual pre-release gate (requires the cached embedding model and takes
20-60 s) rather than a /verify or daily CI step.

## Verification

- 62 focused pytest tests in `tests/test_code_intelligence_packet.py` covering
  normalization, known-answer paths, schema validation, packet comparison, public-safety
  rejection, fixture creation, CLI returncode handling, and MCP exchange validation.
- `ruff check` and `ruff format --check` pass on generator and tests.
- Public-safety scan (`python scripts/public_safety_scan.py --tracked`) raised no findings
  on the generator or committed demo artifacts.
- Known-answer queries confirmed in top-3 results for all five fixture files at time of generation.

## Out-of-scope

- Generator `--check` is not wired into `/verify` or daily CI.
- Changing the fixture project, known-answer query catalog, or MCP profile.
- Remediation of unrelated tracked docs/audits/ findings or .tasks/ artifacts.
