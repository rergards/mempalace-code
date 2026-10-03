# Contributing to mempalace-code

Thanks for wanting to help. mempalace-code is open source and we welcome contributions of all sizes — from typo fixes to new features.

## Getting Started

```bash
git clone https://github.com/rergards/mempalace-code.git
cd mempalace-code
pip install -e ".[dev,spellcheck,treesitter]"    # the extras the CI type check installs
```

`.[dev]` alone cannot pass the type check: Pyright reports the Tree-sitter
imports as missing without the `treesitter` extra.

## Running Tests

This is the gate set the **Tests** workflow (`.github/workflows/ci.yml`) runs on
every pull request:

```bash
python -m pytest tests/ -x -q -m "not needs_network"
ruff check mempalace_code/ tests/ scripts/
ruff format --check mempalace_code/ tests/ scripts/
python -m pyright --pythonpath "$(python -c 'import sys; print(sys.executable)')"
python -m pyright -p pyrightconfig.strict.json
python scripts/architecture_guard.py --root .
actionlint .github/workflows/*.yml
zizmor --offline --min-severity=medium .github/workflows/ .github/actions/
python scripts/docs_drift_guard.py
python scripts/public_safety_scan.py --tracked --staged
python scripts/quality_scorecard.py --check
python benchmarks/demo_perf_budgets.py --check --ci
```

CI also runs `python scripts/gitleaks_scan.py fixture-smoke` and a changed-range
secret scan with the Gitleaks CLI pinned in `tools/gitleaks/go.mod`; running them
locally needs Go to build that scanner.

All tests and checks must pass before submitting a PR. Tests should run without
API keys or network access unless they are explicitly marked `needs_network`.

## Release Changes

Changes to public CLI/MCP behavior, package metadata, documentation, workflows,
or release tooling must keep the release contract green:

```bash
python scripts/docs_drift_guard.py
python scripts/release_preflight.py
```

See [docs/RELEASING.md](docs/RELEASING.md) for the tag, trusted-publishing, public
repository, and post-publication verification sequence. Contributors must not
create tags, releases, or package publications without maintainer approval.

## Running Benchmarks

The current code-retrieval benchmark mines this repository and runs its
known-answer queries:

```bash
# Validate the dataset without embedding
python benchmarks/code_retrieval_bench.py --repo-dir . --validate-dataset

# Fast smoke run; keep reports outside the checkout
python benchmarks/code_retrieval_bench.py --repo-dir . --modes smart --limit 5 --out "$(mktemp -d)/code-bench.json"
```

See [benchmarks/README.md](benchmarks/README.md) for the code, .NET, and
performance-budget benchmarks. The LongMemEval, LoCoMo, ConvoMem, and MemBench
scripts are historical upstream harnesses: they import `chromadb`, which current
packages do not install and whose available releases carry known advisories, so
they run only in an isolated, disposable legacy environment.

## Project Structure

```
mempalace_code/     ← core package (see mempalace_code/README.md for module guide)
mempalace/          ← compatibility import namespace
benchmarks/         ← reproducible benchmark runners
hooks/              ← Claude Code auto-save hooks
examples/           ← usage examples
tests/              ← test suite
assets/             ← logo + brand
```

## PR Guidelines

1. Fork the repo and create a feature branch: `git checkout -b feat/my-thing`
2. Write your code
3. Add or update tests if applicable
4. Run the checks in [Running Tests](#running-tests) — everything must pass
5. Commit with a clear message following [conventional commits](https://www.conventionalcommits.org/):
   - `feat: add Notion export format`
   - `fix: handle empty transcript files`
   - `docs: update MCP tool descriptions`
   - `bench: add LoCoMo turn-level metrics`
6. Push to your fork and open a PR against `main`

Public `main` advances only through release candidates (see
[docs/RELEASING.md](docs/RELEASING.md)). A maintainer ports an accepted PR,
including Dependabot updates, into the development trunk and closes it with a
note naming the release that ships it; PRs are not merged on GitHub.

## Code Style

- **Formatting**: [Ruff](https://docs.astral.sh/ruff/) with 100-char line limit (configured in `pyproject.toml`)
- **Naming**: `snake_case` for functions/variables, `PascalCase` for classes
- **Docstrings**: on all modules and public functions
- **Type hints**: where they improve readability
- **Dependencies**: minimize. Core runtime dependencies are declared once, in `[project].dependencies` of `pyproject.toml`. Custom sentence-transformers models require the `custom-models` extra. Current releases expose no ChromaDB extra. Before raising dependency bounds or refreshing `uv.lock`, check current and target versions against OSV or an equivalent advisory source, audit a fresh resolved environment, and run clean resolver tests matching CI. Don't add new deps without discussion.

## Good First Issues

Check the [Issues](https://github.com/rergards/mempalace-code/issues) tab. Great starting points:

- **New chat formats**: Add import support for Cursor, Copilot, or other AI tool exports
- **Room detection**: Improve pattern matching in `room_detector_local.py`
- **Tests**: Increase coverage — especially for `knowledge_graph.py` and `palace_graph.py`
- **Entity detection**: Better name disambiguation in `entity_detector.py`
- **Docs**: Improve examples, add tutorials

## Architecture Decisions

If you're planning a significant change, open an issue first to discuss the approach. Key principles:

- **Verbatim first**: Never summarize user content. Store exact words.
- **Local first**: Everything runs on the user's machine. No cloud dependencies.
- **Zero API by default**: Core features must work without any API key.
- **Palace structure matters**: Wings and rooms provide explicit retrieval scopes. Use them when the content has a clear project or topic owner.

## Community

- **Issues**: bug reports, feature requests, and questions about this fork go to
  [rergards/mempalace-code issues](https://github.com/rergards/mempalace-code/issues).
- **Security**: report vulnerabilities privately as described in [SECURITY.md](SECURITY.md).
- **Upstream**: the original MemPalace project and its community live at
  [MemPalace/mempalace](https://github.com/MemPalace/mempalace).

## License

Apache 2.0 — your contributions will be released under the same license.
