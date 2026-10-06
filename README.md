<div align="center">

<img src="https://raw.githubusercontent.com/rergards/mempalace-code/main/assets/mempalace_banner.jpg" alt="mempalace-code" width="640">

# mempalace-code

### Your AI's long-term memory. Local. Instant. Private.

Index your codebase once. Your AI can recall architecture decisions, debugging sessions, and API patterns across sessions and projects without re-reading the repo.

No cloud service, no API keys, no subscription. After the one-time embedding model download, indexing and search stay on your machine.

[![][version-shield]][release-link]
[![][python-shield]][python-link]
[![][license-shield]][license-link]

<br>

[**Get Started in 30 seconds**](#quick-start) · [How It Works](#the-palace) · [All Features](#features) · [Benchmarks](#benchmarks)

<br>

<table>
<tr>
<td align="center"><strong>Language-Aware Mining</strong><br><sub>AST, regex, and adaptive chunking<br>matched to each file type</sub></td>
<td align="center"><strong>29 MCP Tools</strong><br><sub>Any MCP-capable agent<br>search, store, traverse · static profiles</sub></td>
<td align="center"><strong>Temporal Knowledge Graph</strong><br><sub>Facts that change over time<br>with validity windows</sub></td>
</tr>
<tr>
<td align="center"><strong>33.8x Token Savings</strong><br><sub>measured peak · median 14.5x<br><a href="https://github.com/rergards/mempalace-code/blob/main/docs/BENCH_TOKEN_DELTA.md">scales with project size</a></sub></td>
<td align="center"><strong>Cross-Project Tunnels</strong><br><sub>Search <code>auth</code> in one project<br>find it everywhere</sub></td>
<td align="center"><strong>3,000+ Tests · $0 Cost</strong><br><sub>Local test suite<br>offline after model setup</sub></td>
</tr>
</table>

</div>

---

## Quick Start

```bash
uv tool install mempalace-code        # recommended isolated install
# or
pipx install mempalace-code           # alternative
# or
pip install mempalace-code            # into current environment
# or
uvx --from mempalace-code mempalace-code --help  # try without installing
```

`mempalace-code` is the default command name so this fork can coexist with
upstream/vanilla `mempalace` on the same machine. If `mempalace` is unused on
your PATH and you want the shorter alias, run `mempalace-code install-alias`.
The alias is a symlink that the package manager does not record, so remove it
before `uv tool uninstall mempalace-code` or `pip uninstall mempalace-code`
(the command only deletes a `mempalace` that points at `mempalace-code`):

```bash
alias_path="$(command -v mempalace)" && case "$(readlink "$alias_path")" in mempalace-code|*/mempalace-code) rm "$alias_path" ;; esac
```

If you already uninstalled, the dangling `mempalace` symlink is left in the
directory that held `mempalace-code` (`uv tool dir --bin` prints it for uv); delete it there.
Packaged installs use the Python import package `mempalace_code`, so they can
coexist with vanilla MemPalace in the same Python environment. Source checkouts
keep a small `mempalace.mcp_server` shim only so older repo-local MCP configs
that run with `PYTHONPATH=/path/to/mempalace-code` continue to start.

Use [`docs/AGENT_INSTALL.md`](https://github.com/rergards/mempalace-code/blob/main/docs/AGENT_INSTALL.md) for a human-in-the-loop setup sequence. It covers installation, MCP wiring, supported Agent Plugin discovery, the unsupported-client stop boundary, and verification, and asks before choosing install scope, storage path, or model download.

Compatible [Agent Plugins 1.0](https://agent-plugins.org/) clients can load the
installed portable package. Discover it with:

```bash
mempalace-code agent-plugin path --json
```

Read the JSON `path` field and use that directory. It contains `plugin.json`, `mcp.json`, and
`skills/mempalace/SKILL.md`. Its MCP config runs the installed
`mempalace-code-mcp --profile=minimal` launcher, exposing only
`mempalace_status`, `mempalace_search`, `mempalace_check_duplicate`, and
`mempalace_add_drawer` by default. Use direct MCP registration, or edit a copy
of `mcp.json`, when a client needs richer profiles such as `--profile=kg`,
`--profile=code`, `--profile=notes`, or `--profile=full`.

<details>
<summary>Or do it manually</summary>

```bash
MEMPALACE_BIN="$(command -v mempalace-code)"
MEMPALACE_MCP="$(dirname "$(realpath "$MEMPALACE_BIN")")/mempalace-code-mcp"
"$MEMPALACE_BIN" init ~/projects/myapp --skip-model-download
# After explicit consent to download/cache the ~80 MB embedding model:
"$MEMPALACE_BIN" fetch-model
"$MEMPALACE_BIN" mine ~/projects/myapp
claude mcp add --scope user mempalace-code -- "$MEMPALACE_MCP"  # Claude user scope
codex mcp add mempalace-code -- "$MEMPALACE_MCP"                # Codex user config
```

**Optional: auto-sync on commit** (requires `[watch]` extra — see [Auto-Watch](#auto-watch)):
```bash
"$MEMPALACE_BIN" watch ~/projects/         # re-mines on every commit, zero noise
```

This registers all 29 tools with the configured MCP client. To expose a reduced subset, add a
`--profile` argv value (for example, `-- "$MEMPALACE_MCP" --profile=minimal`). Compatible Agent
Plugins 1.0 clients should discover the supported instruction bundle with
`mempalace-code agent-plugin path --json` and follow
[`docs/AGENT_INSTALL.md`](https://github.com/rergards/mempalace-code/blob/main/docs/AGENT_INSTALL.md) Section 7. For other clients,
[`docs/LLM_USAGE_RULES.md`](https://github.com/rergards/mempalace-code/blob/main/docs/LLM_USAGE_RULES.md) is read-only reference material;
instruction-file mutation is unsupported.

</details>

### Do you need it? Ask your LLM:

```
Read:
- https://github.com/rergards/mempalace-code/blob/main/README.md
- https://github.com/rergards/mempalace-code/blob/main/docs/AGENT_INSTALL.md
- https://github.com/rergards/mempalace-code/blob/main/docs/LLM_USAGE_RULES.md

Evaluate mempalace-code for this repo specifically, not generic memory tooling.

1. Current context burn: what do I re-explain, and how many tokens/week are spent re-reading files?
2. Highest-ROI surfaces: rank code, docs/prose, design notes, conversation/log exports, manual decisions, KG facts, architecture relationships.
3. Stack support: list supported languages/file types actually indexed; name unsupported extensions that are skipped by default. Distinguish tree-sitter AST, regex structural, Markdown/prose, Kubernetes YAML, and adaptive chunking.
4. Agent workflow fit: which MCP tools should you use proactively (`mempalace_search`, `mempalace_code_search`, `mempalace_file_context`, KG, tunnels, diary, manual drawers)?
5. Ops fit: recommend global MCP, project-scoped MCP, or no MCP; cover 29-tool prompt surface and profile subsetting options (`--profile`, `--tools`, `--exclude`), `mine` vs `mine-all`, `watch` cadence, backup/repair, and offline/model constraints.
6. Decision: install now, try scoped for a week, wait for a named feature, or skip. Give the first 3 commands you would run.
7. If waiting: ask me whether to draft a GitHub feature request.
```

For repos that already have a hand-curated memory file, evaluate mempalace-code
as a complement, not a replacement. A good trial order is:
1. **KG first** — move volatile current facts (active branch, phase, owner, deadline,
   status) into temporal triples; keep curated prose for reasoning and narrative.
2. **Drawers + docs second** — mine design docs, specs, long decision notes, and
   conversation/log exports where semantic retrieval beats manual grep.
3. **Code mining last** — start with one high-value subproject, then expand if
   agents actually use the results.

Cost caveat: a direct MCP registration without selectors defaults to all 29 tools;
the portable Agent Plugin defaults to the four-tool `minimal` profile. Use
`--profile=minimal` or `--tools=search,add_drawer` with direct registration to
reduce the prompt/tool-surface cost.
For proactive use, compatible Agent Plugins 1.0 clients load the package discovered by
`mempalace-code agent-plugin path --json` as described in
[`docs/AGENT_INSTALL.md`](https://github.com/rergards/mempalace-code/blob/main/docs/AGENT_INSTALL.md) Section 7. Other clients may use
[`docs/LLM_USAGE_RULES.md`](https://github.com/rergards/mempalace-code/blob/main/docs/LLM_USAGE_RULES.md) as read-only reference material;
instruction-file mutation is unsupported.
Prefer project-scoped MCP for trials, and keep it only if searches, KG lookups,
or drawer writes show up in real sessions.

### Supported MCP Clients

mempalace-code works with any [MCP](https://modelcontextprotocol.io/)-compatible client:

- **Claude Code** — `claude mcp add --scope user mempalace-code -- "$MEMPALACE_MCP"`
- **Codex CLI** — `codex mcp add mempalace-code -- "$MEMPALACE_MCP"`
- **Agent Plugins 1.0 clients** — parse the JSON `path` field from `mempalace-code agent-plugin path --json` and load that directory
- **Claude Desktop** — add the JSON entry below to `claude_desktop_config.json`
- **Cursor** — add the JSON entry below to `~/.cursor/mcp.json` (or a project's `.cursor/mcp.json`)
- **Windsurf** — add the JSON entry below to `~/.codeium/windsurf/mcp_config.json`
- **Any MCP client** — point it at the resolved installed `mempalace-code-mcp` launcher

JSON-configured clients take an `mcpServers` entry. Merge it into the existing file rather than
replacing the file. Print the absolute launcher path with
`echo "$(dirname "$(realpath "$(command -v mempalace-code)")")/mempalace-code-mcp"`:

```json
{
  "mcpServers": {
    "mempalace-code": {
      "command": "/absolute/path/to/bin/mempalace-code-mcp",
      "args": ["--profile=minimal"],
      "env": { "MEMPALACE_PALACE_PATH": "/absolute/path/to/palace" }
    }
  }
}
```

Use absolute paths: clients do not expand `~` or read your shell profile. The server opens
`MEMPALACE_PALACE_PATH` from this `env` object, else `palace_path` in `~/.mempalace/config.json`,
else `~/.mempalace/palace`. A relative path in either setting would depend on the directory
the client starts the server from, so every command warns about it on stderr. MCP tools never
create a missing palace directory except `mempalace_mine`: with a mistyped path, writes and
knowledge-graph tools answer `No palace found` exactly as `mempalace_status` and search do, so
check the `palace_path` that `mempalace_status` reports. Omit `env` when the palace is the
default or is already set in `config.json`; a variable exported only in your shell does not
reach the client. Instead of
`minimal`, choose `--profile=kg`, `code`, `notes`, or `full` from the MCP Server profile table below.

For local models without MCP support (Llama, Mistral, etc.), use `mempalace-code wake-up` to pipe context into the system prompt — see [Memory Layers](#memory-layers).

---

## How It Actually Works

You write code. You make decisions. You debug things. Between sessions, all that context vanishes.

mempalace-code **indexes it once** into a local vector store, then an MCP-capable AI can retrieve it in milliseconds — using [33.8x fewer tokens](https://github.com/rergards/mempalace-code/blob/main/docs/BENCH_TOKEN_DELTA.md) than grep + read at measured peak (median 14.5x on the canonical fixture). Think of it as `git log` for everything that *isn't* in the code: the *why*, the discussions, the dead ends, the decisions.

**What gets indexed or stored:**
- Code files — structural chunks for Python, TypeScript/JS/TSX/JSX, Go, Rust, Java, Kotlin, C#, F#, VB.NET, Swift, PHP, Scala, Dart, Lua, Terraform/HCL, Markdown, Kubernetes manifests, Helm charts/templates, and Ansible playbooks/roles/inventory; adaptive chunks for C/C++, Ruby, Perl, XAML, XML, shell (including extension-less scripts with a shebang), SQL, HTML/CSS, JSON/YAML/TOML, CSV, Dockerfile, Make, templates, and config files
- .NET solutions — `.sln`/`.csproj` project graphs, cross-project symbol relationships, interface implementations; a solution is filed under the wing named after its root `.sln` file, which `init` writes to `mempalace.yaml` (a `wing:` you set there, or `--wing`, overrides it)
- Architecture facts — pattern, layer, namespace, and project membership facts for .NET and Python projects
- Conversation/log exports — Claude Code JSONL, OpenAI Codex CLI JSONL, Gemini CLI JSONL, Claude.ai JSON, ChatGPT `conversations.json` (the whole export array; each conversation's displayed branch), Slack JSON (channel folders; each message keeps its `[speaker]`, export metadata such as `users.json` is not filed), plain text transcripts. Message text is never spell-corrected or reworded. Left out: Claude Code's injected wrappers and status lines, `[Request interrupted by user]` notice lines (text typed after one is kept), shell-mode (`!`) blocks, meta and compaction entries, inline subagent turns (a subagent's own `agent-*.jsonl` is filed), Slack join/leave-type events, and hidden or non-text ChatGPT parts. Claude Code tool output is abbreviated (long Bash output keeps its head and tail; Read/Edit/Write results are omitted), and an answered slash command is filed as the turn `/name args`
- MCP-saved context — manual drawers and diary entries are vector-indexed in the palace (diary entries under `wing_<agent>` / room `diary`, one wing per agent however its name is spelled: `claude-code` and `claude_code` share one wing, the one already holding that agent's diary (such as `wing_claude-code` from an earlier release) or else `wing_claude_code`; also readable with `mempalace_diary_read`); temporal KG facts live in a separate SQLite graph
- Architecture notes, decisions, anything else you store manually

Generated helper files such as `entities.json` are skipped during project
mining by default, because they are created by init/entity detection and should
not become source-code drawers unless explicitly force-included.

**Secrets:** mining stores every indexed file verbatim in the palace, and backups and
exports copy it. Kubernetes `kind: Secret` manifests with `data`/`stringData` are skipped
by default (the mine summary lists them; `--include-ignored <path>` indexes one anyway), but
no other credential file is detected: keep `.env` files, credential JSON/YAML, and keys out
of the palace with `.gitignore` or `scan_skip_globs` (in `~/.mempalace/config.json`) before
mining. Once a mined secret file is excluded, the next whole-project mine removes its
drawers; backups and exports made earlier still hold it.

**How you use it:** An MCP-capable agent can call mempalace tools during a session when its client policy permits the calls. Compatible Agent Plugins 1.0 clients load the supported instruction bundle discovered by `mempalace-code agent-plugin path --json`; see [`docs/AGENT_INSTALL.md`](https://github.com/rergards/mempalace-code/blob/main/docs/AGENT_INSTALL.md) Section 7. Other clients treat [`docs/LLM_USAGE_RULES.md`](https://github.com/rergards/mempalace-code/blob/main/docs/LLM_USAGE_RULES.md) as read-only reference material because instruction-file mutation is unsupported. The CLI remains available for direct use.

---

## Features

### Language-Aware Code Mining

`mempalace-code mine` walks your source tree and chooses the best chunker for each file type: AST boundaries where optional tree-sitter grammars are available, regex structural boundaries for supported languages, YAML-aware Kubernetes/Helm/Ansible resource splits, Markdown/prose sections, or adaptive line-count chunks for formats without reliable declarations. The shared catalog currently exposes **45 searchable language labels** to `code_search(language=...)`. Leading comments and docstrings stay attached to declarations where structural chunking is active; Markdown drawers keep heading path, section type, and Mermaid/code/table flags in search metadata.

Every drawer is an exact slice of its source file with its line range, so `read` can return any mined line. Nothing inside a file is dropped: small blocks (imports, short config sections, one-line statements) merge into a neighbouring drawer, and small files are indexed whole. Each named declaration starts its own drawer and names it in `symbol_name`: every function, class, and type, and the methods of a class, impl, or trait body (a class keeps a drawer of its own for its header, docstring, and attributes), so a `symbol_name` filter finds each of them. A function defined inside another function stays in the enclosing function's drawer and is found through it. Only unnamed declarations such as constants under 400 characters together may share a drawer, and a file header such as an F# `module A.B` line, a Rust `mod name;` or a Lua module table names a drawer only when nothing more specific is in it. A method is typed `method` (Python, Rust, Go receivers, and TypeScript with tree-sitter). A declaration longer than 4,000 characters is split into several drawers that keep its symbol, and with tree-sitter, code after a declaration (top-level statements, class attributes after the methods) gets drawers of its own. A single line longer than 4,000 characters is stored in several drawers, and `read` joins them back into the whole line.

| Language | Strategy | AST Support |
|----------|----------|:-----------:|
| Python | Functions, classes, methods, decorators | Optional tree-sitter |
| TypeScript / JavaScript / TSX / JSX (`.ts`, `.mts`, `.cts`, `.js`, `.mjs`, `.cjs`, `.tsx`, `.jsx`) | Functions, classes, exports, imports | Optional tree-sitter |
| Go | Functions, types, methods, interfaces | Optional tree-sitter |
| Rust | Functions, structs, enums, traits, impls | Optional tree-sitter |
| Java | Classes, interfaces, methods, annotations | Regex |
| Kotlin | Classes, objects, functions, extensions | Regex |
| Scala | Classes, case classes, objects, traits, enums, functions, implicits, type aliases, generics | Regex |
| Swift | Classes, structs, enums, protocols, functions, properties, extensions, actors, async/await | Regex |
| Dart | Classes, mixins, extensions, enums, functions, named/factory constructors, async/await | Regex |
| PHP | Classes, interfaces, traits, enums (8.1+), functions, methods, namespaces (Laravel/WP/Symfony aware) | Regex |
| C# | Classes, interfaces, records, methods, properties | Regex |
| F# / VB.NET | Modules, types, functions | Regex |
| XAML | Indexed and searchable with `x:Class` view metadata; chunked adaptively today. Mining also records KG facts for code-behind links, view-model bindings, named controls, resources, and commands | — |
| Terraform / HCL | Terraform/HCL top-level blocks (`resource`, `module`, `variable`, `moved`, `import`, `check`, etc.); symbols use Terraform addresses (`aws_instance.web`, `module.vpc`, `var.region`). `.tf`/`.tfvars` files carry the `terraform` language label and `.hcl` files the `hcl` label | Regex |
| Kubernetes manifests | Deployments, Services, ConfigMaps, Ingresses, CRDs (indexed by kind/name); `kind: Secret` manifests with data are skipped unless force-included | YAML-aware |
| Helm charts | `Chart.yaml`, `values*.yaml`, raw templates with kind/name metadata; no template rendering | YAML/Go-template aware |
| Ansible | Playbooks, role tasks/handlers/defaults/vars, inventories; no Jinja evaluation or inventory semantics | YAML/Jinja tolerant |
| Markdown / plain text | Heading sections (`#`-`######`), heading paths, section metadata, paragraphs | — |
| Lua | Functions, local functions, methods (dot/colon), module/table declarations | Regex |
| C / C++ | Indexed and searchable with best-effort symbol metadata; chunked adaptively today | — |
| Ruby | Indexed and searchable with best-effort static symbol metadata (classes, modules, methods, singleton methods, attrs, constants); chunked adaptively today; Rails DSL/metaprogramming not interpreted | — |
| shell / SQL / Perl / XML | Indexed and searchable; chunked adaptively today. Extension-less scripts are indexed when their shebang names a known interpreter (bash/sh/zsh, Python, Node, Ruby, Perl); Perl packages and subs become symbols; `.xml`, `.config`, `.props`, and `.targets` are labelled `xml` | — |
| HTML / CSS / CSV | Indexed and searchable; chunked adaptively today | — |
| YAML / JSON / TOML | Adaptive line-count; Kubernetes YAML auto-detected separately | — |
| Dockerfile / Make / templates / config | Dockerfile, Containerfile, Makefile, GNUmakefile, Vagrantfile, Go templates, Jinja2, `.conf`, `.cfg`, `.ini` | — |

The `mempalace_code_search` language filter is generated from the same language
catalog as the miner. If a file type is mined with a language label, the MCP
schema and unsupported-language hints stay aligned with that catalog.

Tree-sitter is optional (`pip install "mempalace-code[treesitter]"`). When a grammar is missing, Python, TypeScript/JavaScript/TSX/JSX, Go, and Rust fall back to regex structural chunking. Other recognized formats use their regex, YAML-aware, prose, or adaptive chunker as listed above.

Extensions outside the miner catalog are skipped by normal project scans unless
you explicitly force-include an exact path with `--include-ignored path/to/file`
(project-relative, or an absolute path inside the project); the mine summary counts
the skipped types, and an include path that does not exist is reported.

Files that would pollute search are skipped and named in the mine summary: binary
content (NUL bytes or undecodable data, even with a source extension), files larger
than `max_file_bytes` (1,000,000 bytes by default; set `max_file_bytes:` in
`mempalace.yaml`, `0` for no cap), and minified or generated bundles (`*.min.js`,
`*.min.css`, or script/stylesheet/JSON/HTML/XML files made of lines over 4,000
characters). An exact `--include-ignored` path indexes a
large or minified file anyway. Files that start with a UTF-16 or UTF-32 byte-order
mark are decoded as such. Other files that are not valid UTF-8 are decoded with their
declared `coding:` cookie when present; otherwise the undecodable bytes are stored as
U+FFFD and the file is reported. Empty files produce no drawers.

Mining indexes only ordinary readable regular files. Source-shaped FIFO, socket,
character device, block device, symlink, and directory entries are rejected or skipped
before their source content is opened. An ordinary regular file that cannot be read is
reported as a read error; it is not necessarily reported as
`<path>: not a regular file (<kind>)`. Mining continues with other ordinary readable
regular files, and its diagnostics are bounded and actionable. After replacing or
removing the offending entry, run `mempalace-code mine <dir> --full`.

```bash
mempalace-code mine ~/projects/myapp                  # all supported file types
mempalace-code mine ~/projects/myapp --wing myapp     # tag with a specific wing (normalized; see Wing names)
mempalace-code mine ~/chats/ --mode convos            # mine conversation exports
mempalace-code mine-all ~/projects/                   # sync all projects incrementally (one wing per project)
mempalace-code mine-all ~/projects/ --new-only        # skip projects whose wing already exists (first-run only)
```

Mining is **incremental** by default — content-hash based, only changed files are re-chunked. Files whose drawers were written by an older chunker version are re-chunked automatically, and editing the rooms or `architecture:` block in `mempalace.yaml` re-routes unchanged files and reruns architecture extraction on the next mine. Use `--full` to force a rebuild. Either way, a mine that walks the whole project (no `--limit`) removes drawers of files that were deleted, moved, or are now excluded (including every file under a deleted or renamed directory) and reports how many it removed. Mining only replaces drawers it produced: manual (`mempalace_add_drawer`) and diary drawers are never deleted by a mine, even when their `source_file` names a mined file. Ctrl-C stops a mine after saving the pending batch (a second Ctrl-C skips that save; a Ctrl-C during a batch's embedding does not embed it again) and exits with status 130; the next mine resumes incrementally.

**Conversation mining** (`--mode convos`) first normalizes each transcript into user
turns and answers, then keeps every line of that text with its line breaks: a drawer holds
one user turn and its answer, a long answer continues in the next drawers, and an exchange
too short to stand alone joins its neighbour. A transcript is filed however short it is;
one with no text left after normalization is skipped and named. Plain-text transcripts are
used as written (a leading UTF-8 byte-order mark is dropped) and mark user turns with `>`
or `User:`/`Assistant:` prefixes. Normalizing a structured export (Claude Code, Codex,
ChatGPT, Slack, ...) marks only the first line of each user turn with `> ` and keeps the
rest of the message as written, keeps each text block or part on its own line, summarizes
tool calls and tool results, and drops Claude Code system injections. Text is stored
verbatim; `--spellcheck`/`--no-spellcheck` are deprecated no-ops kept for compatibility. A
transcript that changed (such as a session that keeps growing) is re-chunked, and nothing
is backed up or optimized when nothing changed. An incremental mine keeps the drawers of transcripts that
are no longer on disk, because tools prune old transcripts (Claude Code deletes sessions
after `cleanupPeriodDays`) and the palace may hold the only copy. It prints how many
there are and the command that removes them: a `--full` mine of the whole directory.
Pass one transcript file instead of a directory to mine just that file; without `--wing` it
keeps the wing that already holds that transcript (else the name of its folder). `--extract general` adds classified
excerpts (rooms `decisions`, `preferences`, `milestones`, `problems`), each taken from
within one exchange, next to the verbatim exchange drawers and never replaces them; a
transcript with no such excerpt is read again on the next mine. The scan skips directories such as `build`,
`dist`, `env`, `venv`, `memory`, and `tool-results` and lists the ones it skipped; mine
such a directory directly to include it. A file that is not UTF-8 text or cannot be
parsed is reported, counted, and retried on the next mine.

**Multi-project wing naming** — `mine-all` assigns one wing per project using this priority:
1. `wing:` in the project's `mempalace.yaml` (explicit override)
2. Git origin repo name, when the project directory is a repository root (e.g. `my-repo.git` → `my_repo`)
3. Normalized folder name (also used for subdirectories of a monorepo)

`init` writes the wing from rules 2–3 into a new `mempalace.yaml`, so the `mine-all --dry-run`
preview, `init`, and `mine` agree. `mine-all` mines only initialized projects; its output names
the subdirectories it skipped because they have neither project markers nor `mempalace.yaml`,
and the `init` command of each uninitialized project. When every project it found is
uninitialized it mines nothing and exits 1 with the `init` command to run first. `--force` is
deprecated and has no effect (it prints a notice).
If two projects resolve to the same wing name, `mine-all` exits with an error before mining anything. Fix this by adding a unique `wing:` value to each project's `mempalace.yaml`. Use `--new-only` to skip projects already present in the palace (useful for first-run batch ingestion).

**Wing names** — `init`, `mine`, `mine --wing`, and `mine-all` apply one rule. The name is
lowercased, whitespace becomes `_`, and every character other than a letter or digit (of any
script), `_`, or `-` is dropped: `"Foo Bar (v2)!"`, `"foo bar v2"`, and `FOO_BAR_V2` all name
`foo_bar_v2`, while `café` and `日本語` stay as written. Names derived from a folder, git origin,
or `.sln` (and every wing of a `dotnet_structure` project) also turn `-` into `_`; a name with no
letter or digit falls back to `project`. A blank `--wing`, a `--wing` containing `/`, `\` or a
control character, and a blank `--agent` exit 2 before the palace is touched. A new wing that
differs from an existing wing only by case, spacing, or punctuation (`other-wing` when
`other_wing` exists) exits 2 and prints the `mine` command that files under the existing wing,
as `diary write --wing` and `mempalace_add_drawer` do; a `--wing` that names an existing wing
exactly (for example one an older release stored verbatim) keeps filing into it.

**Re-running `init`** never replaces an existing `mempalace.yaml`: it reports the file and keeps
it, so hand-edited wings, rooms, and `architecture:` blocks survive. `init <dir> --force`
regenerates the rooms while keeping the existing `wing:` and every other key, after copying the
old file to `mempalace.yaml.bak`; follow it with `mine <dir> --full` to re-file existing drawers
into the new rooms. Rooms are proposed only for directories `mine` traverses (symlinked,
generated, scan-excluded, and `.gitignore`d directories are skipped); in a .NET repository, code outside every `.csproj` project
keeps folder-based rooms (a root-level `.csproj` covers the whole tree, so it gets no folder rooms).
With a legacy `mempal.yaml`, `--force` writes a new `mempalace.yaml` and leaves the legacy file in place.

### Optional Entity Detection

`mempalace-code init <dir>` is config-first by default: it detects rooms from the directory
structure and does not scan file contents for names. Add `--detect-entities` only when
the directory contains prose where people or project names matter, such as meeting notes,
client notes, personal notes, or conversation exports:

```bash
mempalace-code init ~/notes --detect-entities        # prompts to confirm detected people/projects
mempalace-code init ~/notes --detect-entities --yes  # auto-accept entity confirmation (no room prompts)
```

When stdin is not a terminal (agents, CI, `< /dev/null`), `--detect-entities` auto-accepts
detected people and projects as with `--yes` and skips uncertain names. `--interactive` room
review needs a terminal: without one, init exits 2 before writing anything; `--yes` overrides it.

The detector is a lightweight bootstrap step, not the main miner. It samples up to 10
readable files, prefers prose files (`.md`, `.txt`, `.rst`, `.csv`), reads the first 5 KB
of each sampled file, and considers only capitalized names that appear at least 3 times in
that sample; its own `entities.json` and `mempalace.yaml` are never sampled. It classifies
each name from heuristic signals such as `Alice said`, `thanks Bob`, `Apollo repo`,
`deploy Apollo`, or `import Apollo`. A person needs at least two kinds of person signals
(for example `Alice said` and `thanks Alice`); a name with fewer or mixed signals is listed
as UNCERTAIN. Interactive confirmation lets you keep an uncertain name, while `--yes`
accepts only the confident people and projects. Confirmed results are written to
`<dir>/entities.json`. When a re-run keeps an existing `mempalace.yaml`, an existing
`entities.json` is kept too; `--force` replaces it. For example:

```json
{
  "people": ["Alice", "Bob"],
  "projects": ["Apollo"]
}
```

Use it for human/project context. Leave it off for normal code repos unless their docs
contain the entities you want captured. Full-repo scanning would be slower and noisier:
class names, packages, examples, and variables often look like people or products to a
heuristic pass. Code structure, symbols, languages, and architecture relationships are
handled by `mempalace-code mine`, not by entity detection.

### Auto-Watch

Keep your palace in sync automatically. By default, watches git metadata — branch refs plus
each checkout's `HEAD` reflog — and re-mines only when a **commit**, merge, rebase, reset, or
branch checkout moves the checkout; no noise from work-in-progress saves. Normal checkouts,
linked worktrees (`git worktree add`), and reftable repositories are supported. A linked
worktree files into the wing its `mempalace.yaml` names, which is the main checkout's wing
when that file is committed. A project without git needs `--on-save`: the watcher names each
such project, and when none has git it exits 1 before any backup or mine with the exact
`--on-save` command.

Requires the `watch` extra:
```bash
uv tool install "mempalace-code[watch]"   # or: pipx install "mempalace-code[watch]"
```

Already installed without it? Re-run the uv install with the extra. uv replaces the tool's
extras, so list every extra you use (for example `"mempalace-code[watch,treesitter]"`). pipx
can add watchfiles to the existing environment instead:
```bash
# List every extra you already use; uv drops the ones you leave out.
uv tool install --force "mempalace-code[watch,treesitter]"   # or: pipx inject mempalace-code watchfiles
```

```bash
mempalace-code watch ~/projects/my-app                # watch an initialized project (on commit)
mempalace-code watch ~/projects/                      # watch all initialized projects in a parent directory
mempalace-code watch ~/projects/ --on-save            # watch all file saves instead (noisier)
mempalace-code watch ~/projects/ schedule             # print launchd/cron snippet for daemon
```

`watch` accepts either an **initialized project directory** (has `mempalace.yaml`) or a **parent directory** containing immediate initialized project subdirectories. Pointing it at a project root that has project files but no `mempalace.yaml` exits with the correct `mempalace-code init <dir>` command, and a path to a file exits with the project directory to watch instead. In a parent directory, uninitialized children are named with their `init` command and skipped; projects initialized after the watcher starts are picked up when it restarts. One watcher watches a given project into a given palace: a second watcher skips that project, and exits 1 when nothing is left to watch.

Every re-mine cycle is logged, including one that only swept deleted files; in every mode
the line names the sources the cycle swept (`deleted source(s) swept: src/old.py`). In
`--on-save` mode, renaming a directory or moving one into or out of a project starts a cycle
that indexes the new paths and sweeps the old ones. A failed cycle
is reported with what `mine` printed, and the watcher keeps running. A watched project that
is removed, moved, or loses its `mempalace.yaml` is named and no longer watched
(`WATCH_RUN ... state=project-dropped`); its drawers stay in the palace, and when no project
remains the watcher exits 1 (`state=stopped reason=no-projects`). A storage error caused by
another process writing the same palace (a missing fragment on a stale handle, a commit
conflict) is retried on a fresh handle while the palace head stays readable. The watcher
never rolls a shared palace back on its own; see
[Degraded Startup Recovery](https://github.com/rergards/mempalace-code/blob/main/docs/BACKUP_RESTORE.md#degraded-startup-recovery).

Startup resolves and validates each watcher source root as a directory before creating a
pre-watch backup. Nested non-regular or unreadable source entries follow the mining
contract above: other ordinary readable regular files continue through the mine, and
such an entry does not by itself abort or restart the watcher. A watcher run also reuses
one warmed store and embedding-model lifecycle across remine cycles; regression tests
bound post-warm-up RSS, file descriptors, archive retention, disk growth, and SIGINT
shutdown.

**Install as persistent daemon (macOS):**

```bash
mempalace-code watch ~/projects/ schedule    # prints the plist; stderr prints its exact save and load commands
# For example (the label comes from the root's name and path):
mempalace-code watch ~/projects/ schedule > ~/Library/LaunchAgents/com.mempalace.watch.projects-1a2b3c4d.plist
launchctl load ~/Library/LaunchAgents/com.mempalace.watch.projects-1a2b3c4d.plist
```

Starts at login, restarts if crashed. Each watch root gets its own job,
`com.mempalace.watch.<root-name>-<hash>`, so scheduling a second root adds a job instead of
replacing the first, and re-rendering a root replaces only its own job. The daemon command
keeps `--palace`, `--on-save`, `--agent`, and `--no-gitignore`. `schedule` exits 1 instead of
printing a job that would crash-loop under `KeepAlive`: a missing path, a file, an
uninitialized root, a commit-mode root without git, or an installation without the `watch`
extra. The plist carries `EnvironmentVariables` for `HF_HOME` and every `MEMPALACE_*`
setting of the rendering shell, so re-render after changing them. The daemon runs offline
(`HF_HUB_OFFLINE=1` unless you set it) and never downloads the model; run
`mempalace-code fetch-model` first (`schedule` warns when the model is not cached). It gets
120 seconds (`ExitTimeOut`) to finish an in-flight re-mine after `SIGTERM`, and logs to the
per-user file `~/Library/Logs/<label>.log`, which launchd appends to without rotation. On
Linux the cron `@reboot` line carries the same settings as leading `NAME=value` assignments.

A job rendered by an earlier release keeps the fixed label `com.mempalace.watch` and logs to
`/tmp/mempalace-watch.log`; `watch <root> status` still finds it when it watches that root.
To move it to a per-root job, unload and remove it, then save and load the newly rendered
plist. `schedule` warns, with the unload command, when a saved job already watches the same
root, a parent, or a child into the same palace: a second watcher of a project refuses to
start. `watch <root> status` reads the loaded job's arguments, or else the saved plist, or
else its own options, and uses that job's palace and mode: a commit-mode root without git is
reported `Runnable: no` with the `--on-save` command. Its re-render hint keeps `--palace`,
`--on-save`, `--agent`, and `--no-gitignore` and writes to a temporary file first
(`... schedule > <plist>.tmp && mv <plist>.tmp <plist>`), so a refused render never empties
the saved plist.

**Disk-budget guard:** the daemon automatically skips mine/optimize cycles when free disk space falls below the configured floor (default **1 GiB**). Use `watch status` to check the current state:

```bash
mempalace-code watch ~/projects/ status      # disk budget, root validity, and this root's job (label, state, log, stop command)
```

To pause or stop the daemon when disk is low (use the label `watch status` prints):

```bash
launchctl unload ~/Library/LaunchAgents/<label>.plist   # stop until next login
launchctl load   ~/Library/LaunchAgents/<label>.plist   # re-enable after freeing space
```

**Diagnosing and stopping a crash-looping job:**

A job whose root was later removed or de-initialized, or one rendered by an earlier release
without the render-time checks, can crash-loop under `KeepAlive`. Confirm with:

```bash
mempalace-code watch ~/projects/ status   # shows state, runs count, and last exit code
```

Stop and optionally remove it:

```bash
# macOS 10.11+ preferred — unregisters the job immediately (status prints this line):
launchctl bootout gui/$(id -u)/<label>

# Older macOS / alternative:
launchctl unload ~/Library/LaunchAgents/<label>.plist

# Remove permanently (re-install after fixing the watch root):
rm ~/Library/LaunchAgents/<label>.plist
```

**Daemon health check:**

The daemon emits `WATCH_RUN` lines at each startup transition, and when a cycle fails, a
project is dropped, or the watcher stops, so the job's appended log (`watch status` prints
its path) can be searched to confirm the latest startup reached the watch loop. The full
state list is in [Startup State Markers](https://github.com/rergards/mempalace-code/blob/main/docs/BACKUP_RESTORE.md#startup-state-markers). Use
this sequence to diagnose daemon state:

```bash
# 1. Process state, log path, and stop command for this root's job
mempalace-code watch ~/projects/ status
# Or query launchd directly with the label status printed:
launchctl print gui/$(id -u)/<label>

# 2. Palace storage health
mempalace-code --palace ~/.mempalace/palace health

# 3. Find the latest startup that reached watch-ready (LOG is the path status printed)
grep -a 'state=watch-ready' "$LOG" | tail -1
# Example output: WATCH_RUN run_id=20260616T120102Z-p12345 state=watch-ready

# 4. Filter that run's context (replace the run_id from step 3):
grep -a 'run_id=20260616T120102Z-p12345' "$LOG"
```

A log file may contain `WATCH_RUN` lines from older runs that exited with disk-budget or backup failures. The `run_id` on the latest `state=watch-ready` line identifies the current healthy startup — lines from prior runs with different `run_id` values are stale and can be ignored. If no `watch-ready` line appears, check the most recent `run-started` line and the state that followed it (for example `state=preflight-failed`, `state=pre-watch-backup-failed`, or `state=initial-mine-skipped reason=disk-budget`).

Configure the threshold via environment variable or `~/.mempalace/config.json`:

```bash
# Environment variable (bytes or human suffix)
export MEMPALACE_WATCH_DISK_MIN_FREE_BYTES=2GiB    # watcher-specific floor
export MEMPALACE_DISK_MIN_FREE_BYTES=1GiB          # global floor (watcher + backup)
```

Or set byte values in `~/.mempalace/config.json`. This example keeps the 1 GiB global default
and raises the watcher and backup floors to 2 GiB each. The file must be a plain JSON object
without comments; a file that fails to parse, or whose top level is not an object, is ignored as
a whole with a one-line warning. A size value that cannot be parsed (for example `"lots"`)
is reported on stderr and the next size setting in precedence order applies instead.
An invalid `backup_dir` fails the managed backup operation without a fallback;
see [Backup directory configuration](https://github.com/rergards/mempalace-code/blob/main/docs/BACKUP_RESTORE.md#choosing-the-managed-backup-directory).

```json
{
  "disk_min_free_bytes": 1073741824,
  "watch_disk_min_free_bytes": 2147483648,
  "backup_disk_min_free_bytes": 2147483648,
  "backup_dir": null
}
```

MCP read/search behavior is **not affected** by a paused watcher — agents can still search the palace while the daemon waits for disk space.

---

### The Palace

mempalace-code organizes memories into a navigable structure — the same mental model ancient Greek orators used to memorize speeches.

```
  ┌─────────────────────────────────────────────────────────────┐
  │  WING: myapp                                               │
  │    ┌──────────┐            ┌──────────┐                    │
  │    │  backend │            │  frontend│                    │
  │    └────┬─────┘            └──────────┘                    │
  │         ▼                                                  │
  │    ┌──────────┐      ┌──────────┐                          │
  │    │  Closet  │ ───▶ │  Drawer  │  (verbatim content)     │
  │    └──────────┘      └──────────┘                          │
  └─────────┼──────────────────────────────────────────────────┘
            │ tunnel (auto-created when room names match)
  ┌─────────┼──────────────────────────────────────────────────┐
  │  WING: otherapp                                            │
  │    ┌────┴─────┐            ┌──────────┐                    │
  │    │  backend │            │  infra   │                    │
  │    └──────────┘            └──────────┘                    │
  └─────────────────────────────────────────────────────────────┘
```

| Concept | What it is |
|---------|-----------|
| **Wing** | A project, person, or domain. As many as you need. |
| **Room** | A topic within a wing: `backend`, `auth`, `deploy`, `decisions`. |
| **Drawer** | Verbatim content. Never summarized, never rewritten. |
| **Hall** | Optional `hall` label on a drawer. Only diary entries set one today (`hall_diary`); mined drawers leave it empty, so graph tools list halls only for diary rooms. |
| **Tunnel** | Auto-connection between wings when the same room name appears. |

---

### MCP Server — 29 Tools

Agent Plugins-compatible clients can discover the portable package with:

```bash
mempalace-code agent-plugin path --json
```

That package declares the installed stdio launcher
`mempalace-code-mcp --profile=minimal`. This is the portable default for
low tool-schema cost. Direct MCP registrations below remain supported for the
full surface or richer startup profiles.

```bash
MEMPALACE_BIN="$(command -v mempalace-code)"
MEMPALACE_MCP="$(dirname "$(realpath "$MEMPALACE_BIN")")/mempalace-code-mcp"
claude mcp add --scope user mempalace-code -- "$MEMPALACE_MCP"
```

The MCP server registration name defaults to `mempalace-code`. The MCP tool
identifiers remain `mempalace_*` for compatibility with existing agents and
usage rules.

**Protocol compatibility:** the server speaks both the stable **2026-07-28**
protocol revision (via `server/discover` and per-request metadata) and the
legacy `initialize`-based handshake, negotiated automatically per request —
existing `python -m mempalace_code.mcp_server` registrations (and the
source-checkout `mempalace.mcp_server` shim) keep working unchanged; there is
nothing to reconfigure.

Direct registration without a selector exposes all 29 tools. The portable Agent
Plugin above selects `minimal` and exposes four. Use startup flags to reduce the
direct tool surface (GitHub issue #6 — static profiles lower prompt cost while
preserving stable named-tool trigger patterns in usage rules):

```bash
# Named profiles — select a pre-defined subset at server startup
claude mcp add --scope user mempalace-code -- "$MEMPALACE_MCP" --profile=minimal
claude mcp add --scope user mempalace-code -- "$MEMPALACE_MCP" --profile=kg
claude mcp add --scope user mempalace-code -- "$MEMPALACE_MCP" --profile=code
claude mcp add --scope user mempalace-code -- "$MEMPALACE_MCP" --profile=notes

# Explicit tool list (replaces profile base set)
claude mcp add --scope user mempalace-code -- "$MEMPALACE_MCP" --tools=search,add_drawer,diary_*

# Add or remove tools from a profile
claude mcp add --scope user mempalace-code -- "$MEMPALACE_MCP" --profile=minimal --include=kg_query
claude mcp add --scope user mempalace-code -- "$MEMPALACE_MCP" --profile=full --exclude=delete_wing,delete_drawer
```

| Profile | Tools | Best for |
|---------|-------|----------|
| `full` _(default)_ | all 29 | Full capability; no surface reduction |
| `minimal` | 4 | Search + store only |
| `kg` | 8 | Minimal + temporal knowledge graph |
| `code` | 11 | Code archaeology; no drawer-write/diary tools (`mine` included) |
| `notes` | 12 | Knowledge management + diary; no code-search |

Selector rules for `--tools`, `--include`, `--exclude`:
- Accept full names (`mempalace_search`), short names (`search`), or wildcards (`diary_*`).
- `--tools` replaces the profile base set; cannot be combined with `--include`.
- `--include` adds to the profile base set; `--exclude` removes last (wins over everything).
- Invalid profile name, unknown selector, a selector flag given an empty value (`--tools=`, `--exclude=""`), or empty result → process exits with nonzero status and a stderr message.

An explicit `wing`/`room` filter passed to CLI `search`/`read` or the MCP
search/read/architecture tools is validated against the palace taxonomy
before retrieval runs (when the palace has a readable, non-empty taxonomy
to validate against). A valid scope with zero matches is still a normal
success (`results: []`, CLI exit status 0); an unknown wing, room, or
wing/room pair returns a structured `{error, filter, value, suggestions}`
validation error instead (CLI exit status 2), with up to 3 advisory
suggestions that are never auto-applied. See
[`docs/HOW_SEARCH_WORKS.md`](https://github.com/rergards/mempalace-code/blob/main/docs/HOW_SEARCH_WORKS.md#taxonomy-filter-validation)
for the full contract, including when validation is skipped.

A malformed MCP call is bounded, not fatal. Arguments that are not an object,
undeclared argument names, type mismatches, missing or blank required
arguments, numbers outside a schema `minimum`/`maximum`, text longer than a schema
`maxLength` (a search query over 10,000 characters, drawer or diary text over 100,000),
a `tools/call` without
a tool name, text with an unpaired surrogate escape (`\ud800`), and values a
tool cannot use (a malformed date, an inverted validity window, a path-like
wing) are each rejected with JSON-RPC `-32602` naming exactly what was
wrong — correct those arguments and retry the same tool. Numeric arguments
also accept a numeric string (`"3"`); an integer argument accepts only
integral values (`3`, `3.0`, `"3"`, not `2.5`). A line
that is not valid JSON — including invalid UTF-8, a number with more digits
than Python parses, or nesting deeper than its recursion limit — returns
`-32700` with a null id, and an unknown tool name returns `-32601`. None of
these end the session: the server answers and keeps reading, so the next valid
request is served normally and no restart is needed. A message without an `id`
is a JSON-RPC notification: it is never answered, and anything but
`notifications/*` is ignored with a stderr warning rather than run. `ping`
returns an empty result. A tool that reports a failure in its payload
(`{"error": ...}` or `{"success": false, ...}`) returns it with
`isError: true`; `-32000` means an internal server fault.
`mempalace-code-mcp --version` prints the launcher version.

<details>
<summary><strong>Palace — Read</strong></summary>

| Tool | What |
|------|------|
| `mempalace_status` | Palace overview — total drawers, wings, rooms |
| `mempalace_list_wings` | All wings with drawer counts |
| `mempalace_list_rooms` | Rooms within a wing |
| `mempalace_get_taxonomy` | Full wing → room → count tree |
| `mempalace_search` | Semantic search with optional wing/room filters (`limit` 1–50), in descending similarity; every hit carries its drawer `id`, and Markdown hits include heading path and section metadata |
| `mempalace_code_search` | Filter by language, symbol name/type, file glob (all applied before ranking); optional `rerank="hybrid"` |
| `mempalace_file_context` | Indexed chunks for a source file, ordered by chunk_index and paged with `limit`/`offset`; resolves paths like `mempalace_read` |
| `mempalace_read` | Surgical read of stored source lines in a range for a file; use after a search/file_context hit to avoid reading the whole file; reports gaps, `out_of_range`, and `no_line_metadata` (conversation drawers) |
| `mempalace_check_duplicate` | Similarity check before filing (duplicate at cosine similarity ≥ 0.9 by default; `threshold` must be -1 to 1) |

</details>

<details>
<summary><strong>Palace — Write</strong></summary>

| Tool | What |
|------|------|
| `mempalace_add_drawer` | File verbatim content into a wing/room; refuses a near-identical drawer (similarity ≥ 0.9 and no new number or identifier) and a new wing/room name that only re-spells an existing one (names are trimmed and case-sensitive) |
| `mempalace_delete_drawer` | Remove a drawer by ID |
| `mempalace_delete_wing` | Delete all drawers in a wing |
| `mempalace_mine` | Trigger re-mining of a project directory (incremental or full) |

</details>

<details>
<summary><strong>Knowledge Graph</strong></summary>

| Tool | What |
|------|------|
| `mempalace_kg_query` | Entity relationships with time filtering (paged: `limit`/`offset`, `total`, `truncated`, `next_offset`) |
| `mempalace_kg_add` | Add a fact with optional validity window; reports `created` and other current values |
| `mempalace_kg_invalidate` | Mark a fact as no longer true; `success: false` when no open fact matched |
| `mempalace_kg_timeline` | Chronological story of an entity (paged: `limit`/`offset`, `total`, `truncated`) |
| `mempalace_kg_stats` | Graph overview |

</details>

<details>
<summary><strong>Architecture Retrieval</strong></summary>

| Tool | What |
|------|------|
| `mempalace_find_implementations` | Find all types implementing a given interface |
| `mempalace_find_references` | Find all usages of a type (implementors, subclasses, deps) |
| `mempalace_show_project_graph` | .NET project-level dependency graph, optionally filtered by solution (an unknown solution returns `unknown_solution` with suggestions; paged per predicate: `limit`/`offset`, `totals`, `next_offset`) |
| `mempalace_show_type_dependencies` | Inheritance/implementation chain (ancestors + descendants) |
| `mempalace_explain_subsystem` | Explain how a subsystem works: semantic search + KG expansion |
| `mempalace_extract_reusable` | Classify deps as core/platform/glue; identify extraction boundary |
| `mempalace_kg_query` (entity="Service", direction="incoming") | Show all services in the project |
| `mempalace_kg_query` (entity="Data",    direction="incoming") | Show all types in the data layer |

</details>

<details>
<summary><strong>Navigation & Diary</strong></summary>

| Tool | What |
|------|------|
| `mempalace_traverse` | Walk the graph from a room across wings (the catch-all `general` room is not a node) |
| `mempalace_find_tunnels` | Find rooms bridging two wings (unknown wings return `unknown_wing`) |
| `mempalace_graph_stats` | Graph connectivity overview |
| `mempalace_diary_write` | Write a session journal entry (`agent_name` defaults to the server's `MEMPALACE_AGENT_NAME`) |
| `mempalace_diary_read` | Read an agent's recent diary entries from any wing, including CLI `diary write --wing` entries; identity ignores case, spaces, hyphens and underscores |

</details>

MCP-capable clients discover the registered tools. Compatible Agent Plugins 1.0 clients get the supported instruction bundle from `mempalace-code agent-plugin path --json`; follow [`docs/AGENT_INSTALL.md`](https://github.com/rergards/mempalace-code/blob/main/docs/AGENT_INSTALL.md) Section 7. Other clients may consult [`docs/LLM_USAGE_RULES.md`](https://github.com/rergards/mempalace-code/blob/main/docs/LLM_USAGE_RULES.md) as read-only reference material, including its profile-scoped routing guidance. Instruction-file and system-prompt mutation are unsupported.

---

### Knowledge Graph

Temporal entity-relationship triples — local SQLite, no Neo4j, no cloud.

```python
from mempalace_code.config import MempalaceConfig
from mempalace_code.knowledge_graph import open_palace_kg

palace_path = MempalaceConfig().palace_path  # or any palace directory
kg = open_palace_kg(palace_path)  # <palace>/knowledge_graph.sqlite3, shared with MCP and the CLI
kg.add_triple("myapp", "uses", "Postgres", valid_from="2025-11-03")
kg.add_triple("myapp", "uses", "Redis",    valid_from="2026-01-15")

kg.query_entity("myapp")                    # → Postgres (current), Redis (current)
kg.query_entity("myapp", as_of="2025-12-01")  # → Postgres only

kg.invalidate("myapp", "uses", "Postgres", ended="2026-03-01")  # fact expired
```

Entity names are case-insensitive: `LanceDB` and `lancedb` are one entity, shown
with the spelling first stored (`add_entity` sets it). Predicates are stored
lowercase with underscores. A dated `ended` is an inclusive end-of-day bound, so
to replace a value that changes today, invalidate without `ended` (or pass the
day before the new `valid_from`) before adding the new value.

**Good candidates:** version numbers, team assignments, tech stack choices, deployment states, deadlines.

**Architecture extraction** — `mempalace-code mine` automatically emits higher-level KG facts for .NET and Python projects after each mine:

| Predicate | Example | Query |
|-----------|---------|-------|
| `is_pattern` | `UserService → is_pattern → Service` | `kg_query(entity="Service", direction="incoming")` |
| `is_layer` | `UserRepository → is_layer → Data` | `kg_query(entity="Data", direction="incoming")` |
| `in_namespace` | `UserService → in_namespace → Company.App` | `kg_query(entity="UserService")` |
| `in_project` | `UserService → in_project → myapp` | `kg_query(entity="myapp", direction="incoming")` |

Default patterns: Service, Repository, Controller, ViewModel, Factory.
Default layers: UI (`*.UI`, `*.Web`, `*.Presentation`), Business (`*.Application`, `*.Domain`), Data (`*.Data`, `*.Persistence`), Infrastructure (`*.Infrastructure`).
A namespace glob also matches sub-namespaces (`*.Infrastructure` matches
`Shop.Infrastructure.Email`); a glob matching the whole namespace wins first, and
namespace placement beats the type-suffix fallback.

Re-mining a project refreshes architecture facts for that project's wing only,
so a multi-project palace can update one repo without expiring facts from
another. Unchanged facts keep their rows; only facts that are no longer derived
expire. Python `depends_on` facts name modules by their dotted import path
(`shop.web.models`); run `mempalace-code mine <dir> --full` once after upgrading
to replace older facts that used the bare file name.

Customize the rules with the `architecture:` block in `mempalace.yaml`. A
`patterns:` or `layers:` list replaces the whole default list, so re-list every
default rule you want to keep:

```yaml
architecture:
  enabled: true
  patterns:
    - name: Service
      suffixes: [Service]
      type_names: [AuditHandler]   # explicit names bypass suffix matching
    - name: Repository
      suffixes: [Repository]
    - name: Controller
      suffixes: [Controller]
    - name: ViewModel
      suffixes: [ViewModel, VM]
    - name: Factory
      suffixes: [Factory]
  layers:                          # omit to keep the default layers
    - name: UI
      namespace_globs: ["*.UI", "*.Web", "*.Presentation"]
      type_suffixes: [Controller, ViewModel]
      priority: 1
    - name: Business
      namespace_globs: ["*.Application", "*.Domain", "*.Audit"]
      type_suffixes: [Service]
      priority: 2
    - name: Data
      namespace_globs: ["*.Data", "*.Persistence"]
      type_suffixes: [Repository]
      priority: 3
    - name: Infrastructure
      namespace_globs: ["*.Infrastructure"]
      priority: 4
```

Set `enabled: false` to disable the pass entirely.

---

### Memory Layers

| Layer | What | When |
|-------|------|------|
| **L0** | Identity — the text you write in `~/.mempalace/identity.txt` (project, persona) | Always loaded (aim for ~100 tokens; capped at 800 characters) |
| **L1** | Essential story — up to 15 drawer snippets: recent diary entries and manual notes first, then decision rooms, conversations, and project files | Always loaded (~500–800 tokens) |
| **L2** | Room recall — current topic | On demand (`search --wing/--room`, MCP tools) |
| **L3** | Deep search — full semantic query | On demand (`search`) |

```bash
mempalace-code wake-up --wing myapp    # emit L0 + L1 context (~600–900 tokens)
```

L1 ranks drawers by kind and then by filing time, most recent first; raw JSON/XML
fragments are skipped and snippets are verbatim drawer text. It does not include
knowledge-graph facts — query those with `mempalace_kg_query`. `wake-up` writes only
the context to stdout and the token estimate (plus any warning) to stderr, so
`mempalace-code wake-up --wing myapp > context.txt` or a pipe carries nothing else. A
missing palace exits 1 and a blank `--wing` exits 2.

For local models (Llama, Mistral) that don't speak MCP, pipe `wake-up` into the system prompt.

### AAAK Summaries (`compress`)

`mempalace-code compress [--wing W]` prints a lossy AAAK summary — entity codes, topic
words, one key quote, flags — for each drawer, next to the drawer id it summarizes. It
is read-only: drawers keep their verbatim text, nothing is stored, and read, search,
export, and wake-up never return AAAK. Use the printed summaries wherever you want
compact context. Drawers whose summary would not be shorter are skipped and counted,
and `Total` uses the same token estimates as each row.

`--config <file>` loads entity codes from the `entities.json` that
`init --detect-entities` writes (`{"people": [...], "projects": [...]}`) or from
`{"entities": {"Alice": "ALC"}, "skip_names": [...]}`; a missing or invalid file exits
2. No `entities.json` is loaded unless you pass `--config`.

Releases before 1.15.0 overwrote drawers with AAAK in place. `compress` reports such
drawers; restore their verbatim text from the backup archive that the old command
created before writing (`mempalace-code backup list` shows it):

```bash
mempalace-code compress --recover-from <archive> --dry-run   # show what the archive can restore
mempalace-code compress --recover-from <archive>             # restore those drawers' text
```

Recovery replaces only drawers that still hold AAAK text and leaves later writes alone.
Drawers the archive cannot restore are listed and the command exits 1, with or without
`--dry-run`: retry with an older archive, or rebuild the drawers from their sources, with
`mempalace-code mine <project-dir> --full` for project files and
`mempalace-code mine <conversations-dir> --mode convos` for conversations.

---

### Concurrent Writers and Long-Running Servers

One palace can serve an MCP server, a watcher, CLI mines, and the hooks' background
conversation mines at the same time:

- **Writers take turns.** Each `mine` (project or `--mode convos`), each `mine-all`
  project, each watcher re-mine cycle, and each optimize or cleanup holds a per-palace
  write lease (`~/.mempalace/locks/palace-<id>.lock`). A second writer of the same palace
  prints `Waiting for another MemPalace writer to finish with <palace> (operation=..., pid=...)`
  and then runs, so overlapping mines never file a drawer twice. The CLI waits up to
  30 minutes, then exits 75 and prints the exact command to rerun; `mempalace_mine`
  waits up to 60 seconds, and `mempalace_add_drawer`, `mempalace_diary_write`, and the
  delete tools wait up to 30 seconds (they load the embedding model before taking the
  lease, so the lease covers only the write). Past that budget the call returns
  `success: false`, `retryable: true`, and a hint; nothing was written, so retry the same
  call once the named writer finishes (a mine can take minutes). Writers also
  hold the shared side of the install lease, so `update` never replaces the package
  mid-mine. Each palace ever written keeps three small files in `~/.mempalace/locks`
  (`palace-<id>.lock`, `.lock.metadata.lock`, `.lock.owners.json`); they are not removed
  automatically, and an owner entry left by a killed process is cleared the next time that
  palace is written. When no MemPalace process is running (no MCP server, watcher, mine, or
  scheduled job), the whole `~/.mempalace/locks` directory can be deleted; it is recreated
  on the next write.
- **Long-running readers stay current.** Every store handle reads the latest committed
  table version at the start of each operation, so an MCP server or watcher sees drawers
  that other processes wrote, without a restart. The MCP server reopens the palace when
  another process restored or rebuilt it. A mine (including `--full`) replaces a changed
  file's drawers in the same commit that writes the new ones, so a concurrent search,
  `file_context`, or `read` sees the file's old drawers or its new ones, never neither.
- **Cleanup spares live readers.** Post-optimize cleanup and
  `cleanup --older-than-days N` never remove a table version that was current within
  the last minute. Until those versions go, the palace takes more disk than its
  compacted size: about 2x after a typical mine, about 3x after `mine --full`, and
  more after a burst of mines within one minute. The next mine that starts more than a
  minute later prunes them before it writes (unless drawers were written since the last
  optimize or `optimize_after_mine` is off); `mempalace-code cleanup --older-than-days 0`
  reclaims them at any time (a plain `cleanup` keeps every version younger than 7 days).
  Only `cleanup --unsafe-now` also removes versions from the last minute, so stop every
  MemPalace process before using it.

---

### Backup & Restore

Create and inspect both recovery artifacts before rebuilding. The import preview
must target the inspected, already-existing palace.

```bash
set -euo pipefail

PALACE="${HOME}/.mempalace/palace"
EXPORT_JSONL="${HOME}/.mempalace/recovery-manual.jsonl"
BACKUP_TAR="${HOME}/.mempalace/recovery-full.tar.gz"

: "${PALACE:?set PALACE to the inspected existing palace}"
: "${EXPORT_JSONL:?set EXPORT_JSONL to a new JSONL path}"
: "${BACKUP_TAR:?set BACKUP_TAR to a new tar path}"
test -d "$PALACE/lance"
test ! -e "$EXPORT_JSONL"
test ! -e "$BACKUP_TAR"

mempalace-code --palace "$PALACE" export --only-manual --with-kg --out "$EXPORT_JSONL"
mempalace-code --palace "$PALACE" import "$EXPORT_JSONL" --dry-run
mempalace-code --palace "$PALACE" backup create --out "$BACKUP_TAR"
tar -tzf "$BACKUP_TAR"
```

The preview validates the JSONL and opens existing palace state read-only when
present. It does not write palace or KG state. When the selected palace and KG
are absent, it does not create them or initialize temporary, embedding-model, or
cache state. It previews record import without applying records. Without
`--force`, tar restore refuses state found at the selected palace or KG during
its checks, claims the exact `lance/` name exclusively, and publishes the KG with
an atomic no-replace operation. An existing real empty palace directory is the
only reusable initial state. Unsupported no-replace KG publication fails closed.
This boundary is not a transaction for concurrent replacement of the palace
root or its ancestors, or for arbitrary edits elsewhere in the palace. Back up
every reported destination before an intentional `--force` restore.

KG boundary: JSONL `--with-kg`, tar backup/restore, mining, MCP, and the watcher all
use the selected palace's `<palace>/knowledge_graph.sqlite3` (`--palace`, or the
configured palace); tar backup omits it from the archive when absent. Facts that only
the separate global KG at `~/.mempalace/knowledge_graph.sqlite3` holds (written by
earlier releases and by the Python `KnowledgeGraph()` default) are copied into the
configured palace's KG once, and again only after that file changes or after `import`
replays an export written before 1.15.0; its contents are never modified. `--kg-path` selects another
restore destination. The complete quarantine, rebuild, restore, force-restore,
and failure-recovery procedure is in [docs/BACKUP_RESTORE.md](https://github.com/rergards/mempalace-code/blob/main/docs/BACKUP_RESTORE.md).

**Backup kinds:** Each archive has a kind that controls its filename prefix and per-kind retention:

| Kind | Prefix | Created by |
|------|--------|-----------|
| `manual` | `mempalace_backup_` | `backup create` (default) |
| `scheduled` | `scheduled_` | `backup create --kind scheduled` / cron |
| `pre_optimize` | `pre_optimize_` | Auto-backup before optimize |
| `pre_watch` | `pre_watch_` | Auto-backup before the watcher's initial mine |

**Scheduled backups:**

```bash
# Print a scheduler snippet (does NOT install — owner action required)
mempalace-code backup schedule --freq daily    # daily at 03:00
mempalace-code backup schedule --freq weekly   # weekly on Sunday at 03:00
mempalace-code backup schedule --freq hourly   # every hour

# macOS: save and load the launchd plist; stderr prints the exact save and load commands.
# For example (the label comes from the palace directory's name and path):
mempalace-code backup schedule --freq daily > ~/Library/LaunchAgents/com.mempalace.backup.palace-1a2b3c4d.plist
launchctl load ~/Library/LaunchAgents/com.mempalace.backup.palace-1a2b3c4d.plist

# Linux: paste the printed cron line into crontab -e
mempalace-code backup schedule --freq daily
# → 0 3 * * * /usr/local/bin/mempalace-code --palace /path/to/palace backup create --kind scheduled
```

Each palace gets its own launchd job, `com.mempalace.backup.<palace-dir-name>-<hash>`, so
scheduling a second palace adds a job instead of replacing the first. A job saved by an
earlier release keeps the fixed label `com.mempalace.backup`; unload and remove it before
loading the newly rendered plist for the same palace, or both run. The plist logs every run to
`~/Library/Logs/<label>.log` (stderr prints the path), so a refused run (disk budget, degraded
palace, busy lease) leaves a trace. Like the watch job, the plist (and the cron line, as
leading `NAME=value` assignments) carries `HF_HOME` and every `MEMPALACE_*` setting of the
rendering shell, such as `MEMPALACE_BACKUP_RETAIN_COUNT`; re-render after changing them.
`schedule` warns when no palace exists at the target path yet.

**Backup directory:** Set `backup_dir` in `~/.mempalace/config.json` to put managed
archives on another disk, for example `{"backup_dir": "/mnt/backup/mempalace"}`.
`MEMPALACE_BACKUP_DIR` overrides that setting. Paths expand `~`; relative paths
resolve against the current directory and produce a warning. Use an absolute path
for scheduled jobs. An absent setting or JSON `null` keeps the default
`<palace_parent>/backups/<palace_name>/` directory.

The configured directory is a root. Each palace uses a child named
`<palace_name>-<hash>`, where the hash comes from its canonical source path, so
palaces with the same name keep separate archives and retention. Manual,
scheduled, pre-watch and pre-optimize backups, listing and footprint accounting
use that child. Free space is checked on the archive destination filesystem.
Missing directories are created during backup; listing creates no directories.
Invalid or inaccessible settings fail without writing to the default directory.
Managed children must be outside the palace and cannot be symbolic links.
New backup roots and managed children have owner-only access; an existing
configured root keeps its permissions. Archives remain owner-only.

Changing this setting moves or deletes no existing archives. Previous managed
archives remain at their old path; use `backup list --dir /previous/managed/path`
to list them. Explicit `--out` takes priority and keeps its existing behavior,
including no managed retention, even when `backup_dir` is invalid.
See [Backup directory configuration](https://github.com/rergards/mempalace-code/blob/main/docs/BACKUP_RESTORE.md#choosing-the-managed-backup-directory)
for inspection commands, permissions and existing-archive behavior.

**Retention (automatic pruning):**

`pre_optimize` and `pre_watch` archives are **bounded by default** to the newest 5 per kind (implicit safe default for repeated mine/optimize cycles and watcher restarts).
`scheduled` archives are **bounded by default** to the newest 14 (implicit safe default for cron and launchd jobs).
`manual` archives are **unbounded by default** (retain all, no pruning).

```bash
export MEMPALACE_BACKUP_RETAIN_COUNT=5   # explicit limit for all kinds; overrides implicit pre_optimize, pre_watch, and scheduled bounds
# Deliberate keep-all opt-out (including pre_optimize, pre_watch, and scheduled):
export MEMPALACE_BACKUP_RETAIN_COUNT=0   # 0 disables pruning for every kind
```

Or in `~/.mempalace/config.json`: `{"backup_retain_count": 5}`. Retention affects only
the palace's selected managed directory. With `backup_dir` unset, that directory is
`<palace_parent>/backups/<palace_name>/`; a configured root uses the isolated child
described above. Explicit `--out` archives are never pruned, and `backup create --out`
refuses to overwrite an existing file.

`backup list` (`--json` for scripts) prints `stale` in its FLAGS column for archives that would be pruned at the current retain count, `oversized` for archives larger than `MEMPALACE_BACKUP_WARN_SIZE_BYTES`, `degraded` for a snapshot of a damaged palace, and `shared` for archives an older release wrote into the shared `<palace_parent>/backups/` directory (they may belong to a sibling palace; check their wings before restoring, and retention never deletes them).

`backup create` fails with exit 1 instead of writing an empty archive when the path holds no palace (missing directory, empty directory, or a legacy ChromaDB palace). For a degraded palace (unreadable drawers, or a knowledge graph that fails SQLite's `quick_check`) it still writes a forensic `*_DEGRADED.tar.gz` copy, warns, and exits 1; `restore` refuses such an archive, and degraded archives never displace healthy ones in retention.

After a successful optimize and readability check, MemPalace also runs
best-effort verified Lance cleanup (`cleanup_stale_fragments` with
`unsafe_now=false`) so future backups do not keep archiving stale table versions.
That cleanup keeps every version that was current within the last minute, so
another process still reading the palace keeps its data files. The next mine that
starts more than a minute later prunes them before it writes, so its pre-optimize
backup does not carry them. That step only prunes: it never compacts, it is skipped
when drawers were added or deleted since the last optimize (the backup then comes
first), and it does nothing when `optimize_after_mine` is off.
`mempalace-code cleanup --older-than-days 0` reclaims them at any time; a plain
`cleanup` keeps every version younger than 7 days. Optimize and cleanup verification
re-opens the Lance table, so it checks the same fresh-handle path the next CLI, MCP
server, or watcher process will use. Use the manual `cleanup` command for older
installations that already accumulated stale versions or for emergency recovery.

**Disk-budget guard (1 GiB default):**

```bash
export MEMPALACE_BACKUP_DISK_MIN_FREE_BYTES=2GiB    # require 2 GiB projected free after backup
# Legacy alias still accepted:
export MEMPALACE_BACKUP_MIN_FREE_BYTES=2GiB
```

When projected free space after the archive would fall below the configured
floor, backup raises a `disk budget` error before writing the archive and
optimize is skipped (fail-closed). The backup floor falls back to
`backup_disk_min_free_bytes` → `disk_min_free_bytes` → **1 GiB default**.
Set the backup-specific floor to `0` to disable the backup guard.

**Auto-backup before optimize (on by default):**

`backup_before_optimize` is **`true` by default**. Before every `optimize()` call
(runs after mining), a `pre_optimize_*.tar.gz` backup is created in the selected managed
directory. With `backup_dir` unset, this is `<palace_parent>/backups/<palace_name>/`.

To opt out, add to `~/.mempalace/config.json`:
```json
{
  "auto_backup_before_optimize": false
}
```

Or set env var: `MEMPALACE_AUTO_BACKUP_BEFORE_OPTIMIZE=0` (preferred) or `MEMPALACE_BACKUP_BEFORE_OPTIMIZE=0`.

**Disable auto-optimize (paranoid mode):**

```json
{
  "optimize_after_mine": false
}
```

Skips compaction entirely. Storage will grow with more fragments but avoids any compaction-related corruption risk.

**Why backup matters:** Manual drawer additions (via `mempalace_add_drawer`) are not recoverable from source code. If LanceDB storage gets corrupted, only backups preserve this data. Code-mined drawers can be restored by re-running `mempalace-code mine`.

Also available: `mempalace-code export --only-manual --out <backup.jsonl>` for JSONL export of manually-stored drawers.

**Remote mirror risk — backups vs file mirroring:**

Managed backups and Lance cleanup protect **local** palace state. They do not protect against
delete-mode rsync between independent hosts. `rsync --delete` syncing a whole MemPalace state
directory removes remote-owned drawers, diary entries, and KG triples that were never synced
back to the source — even when local backups are healthy.

Use these recommended excludes for any delete-mode state-directory mirror:

```bash
rsync -a --delete \
  --exclude=palace/ \
  --exclude='palace.backup-*/' \
  --exclude='palace.quarantine-*/' \
  --exclude=knowledge_graph.sqlite3 \
  --exclude=knowledge_graph.sqlite3.adopted \
  --exclude=config.json \
  --exclude=backups/ \
  ~/.mempalace/ user@host:.mempalace/
```

`palace.backup-<UTC>/` (left by `repair`) and `palace.quarantine-<UTC>/` (left by the rebuild
workflow) are full palace copies. Run a preflight check before installing a mirror job (the
command is never executed). It also blocks `--del`, `--remove-source-files`, mirrors of a palace
configured outside `~/.mempalace`, and mirrors of a parent such as `~/` that contains
`~/.mempalace` without excluding the same families under it (for example
`--exclude=/.mempalace/palace/`), and reports `UNVERIFIED` when excludes come from files or an
earlier include:

```bash
mempalace-code preflight mirror --command \
  "rsync -a --delete --exclude=palace/ --exclude='palace.backup-*/' \
   --exclude='palace.quarantine-*/' --exclude=knowledge_graph.sqlite3 \
   --exclude=knowledge_graph.sqlite3.adopted --exclude=config.json --exclude=backups/ \
   ~/.mempalace/ user@host:.mempalace/"
# OK
#   warning: advisory: no --exclude for 'logs' (add --exclude='*.log' if you route MemPalace logs into the state directory)
```

See [docs/BACKUP_RESTORE.md](https://github.com/rergards/mempalace-code/blob/main/docs/BACKUP_RESTORE.md) for the full mirror-risk guidance and
the safer export/import alternative for cross-host transfer of non-regenerable content.

---

### Scan Excludes

By default `mempalace-code mine` already skips common generated directories (`node_modules`,
`__pycache__`, `.git`, etc.). For project-specific noise — generated LSP state, build
artifacts, IDE files — configure app-level excludes in `~/.mempalace/config.json`:

```json
{
  "scan_skip_dirs":  [".kotlin-lsp"],
  "scan_skip_files": ["workspace.json"],
  "scan_skip_globs": ["generated/**/*.js", "build/**"]
}
```

| Key | Match rule | Default |
|-----|------------|---------|
| `scan_skip_dirs` | directory **basename** — prunes the whole subtree | `[".kotlin-lsp"]` |
| `scan_skip_files` | file **basename** — skips matching files anywhere | `[]` |
| `scan_skip_globs` | project-relative POSIX glob — skips matching file paths | `[]` |

**`workspace.json` as opt-in example:** a root `workspace.json` can be a legitimate
monorepo config file, so it is *not* excluded by default. Add it to `scan_skip_files`
only if your LSP generates it as noise inside generated directories.

These rules apply to both `mempalace-code mine` and the auto-watcher (`mempalace-code mine --watch`
and `mempalace-code watch`). Force-include paths (`--include-ignored`) always win over
app-level excludes.

Watcher loops reload these app-level rules between scan cycles, so edits to
`~/.mempalace/config.json` apply to subsequent re-mines without restarting
`mempalace-code watch`.

**Removing previously indexed noise:** scan excludes prevent *future* scans from indexing
the excluded paths. To remove content that was indexed before adding the exclusion, mine
the project again:

```bash
mempalace-code mine <dir>
```

Every mine that walks the whole project (no `--limit`) ends with a stale-file sweep that
removes drawers of files that are no longer discovered by the scanner — deleted files and
previously indexed files that now fall under an exclusion rule. `--full` runs the same
sweep and also re-chunks and re-embeds every remaining file.

---

### Health & Repair

```bash
mempalace-code health              # probe palace for fragment corruption
mempalace-code health --json       # machine-readable report (JSON on errors too)
mempalace-code cleanup --older-than-days 7 --dry-run  # preview which versions cleanup removes
mempalace-code cleanup --older-than-days 7  # reclaim stale Lance versions
mempalace-code cleanup --unsafe-now         # emergency only; stop MemPalace processes first

mempalace-code repair --rollback --dry-run  # show what rollback would recover
mempalace-code repair --rollback   # roll back to last working version
mempalace-code repair              # rebuild the drawer table from stored data
```

**What `health` checks:**
1. Manifest read (count_rows)
2. Data fragment read (head)
3. Metadata scan (count_by_pair) - catches the silent-failure surface
4. Knowledge graph integrity (SQLite `quick_check` on `<palace>/knowledge_graph.sqlite3`)

A path without a drawer table (a project directory, or a palace whose first mine
failed) reports `No palace found` and exits 1. Every `Next:` hint repeats
`--palace <path>`, so following it never acts on the default palace.

**What `repair --rollback` does:**
1. Probes the current version first; a healthy palace is left unchanged
2. Otherwise walks LanceDB version history from newest to oldest
3. Finds the most recent version where all probes pass
4. Restores to that version (loses data added after corruption)

Use `--dry-run` first to see how many rows would be lost. Rollback never falls
back to a full rebuild.

**What `repair` (full rebuild) does:** it reads every stored drawer first and
stops with exit 1, changing nothing, at the first unreadable drawer or when another
process writes to the palace meanwhile. Then choose: restore an archive
(`backup list`), or `repair --salvage` to rebuild from the readable drawers only. It rebuilds just `lance/` from the stored text, metadata,
and vectors (no model needed), keeps `knowledge_graph.sqlite3` and `.mempalace/`
in place, and saves the pre-repair palace to a new `<palace>.backup-<UTC timestamp>`
directory; it never deletes an earlier backup.

**A degraded palace fails loudly.** When stored drawers cannot be read, `search`,
`read`, `status`, `wake-up`, and `export` exit 1 with the palace path and the
`health` / `repair --rollback --dry-run` / `repair` / `backup list` commands, and MCP
search returns that error, instead of reporting an empty palace.

**Running processes:** `repair`, `repair --rollback`, `cleanup`, and
`restore --force` take the installation's exclusive operation lease. They refuse,
naming the process, while an MCP server, watcher, or other MemPalace process
holds a lease; stop those first. The lease covers the whole installation, not one palace:
a holder working on a different palace still blocks them, and the refusal names that
holder's palace. Previews (`--dry-run`) need no lease.

Normal optimize runs already prune verified stale Lance versions after a
successful compaction and fresh-handle verification, keeping versions that were
current within the last minute for readers in other processes. Manual `cleanup`
applies the same reader grace and is still useful after older installs or large
historical accumulations (`--older-than-days 0` also reclaims versions younger than
the 7-day default); `cleanup --unsafe-now` skips the grace and is only for
emergency disk recovery after stopping watchers, miners, maintenance commands, and
MCP servers.

---

### Version Check (opt-in)

mempalace-code can notify you when a newer release is available on PyPI. This feature
is **strictly opt-in** — no network calls are made by default.

```bash
# Check your current status (local-only, no network)
mempalace-code version-check

# Opt in to periodic checks (contacts PyPI for package metadata only)
mempalace-code version-check --enable

# Opt out (suppresses future first-run prompts)
mempalace-code version-check --disable

# Check right now regardless of the interval or persisted preference
mempalace-code version-check --check-now
```

**How it works:**

- On the first interactive command after a fresh install, the CLI prompts once: *"Enable periodic new-version checks?"* — answering `n` records the opt-out permanently. Non-interactive (piped, CI, non-TTY) invocations **never prompt**.
- When opted in, a background check runs at most once per interval (default: 168 hours / 1 week). Any update hint appears on **stderr only** — stdout remains machine-parseable.
- Explicit `--check-now` ignores the interval and persisted preference, then contacts PyPI and
  prints current/latest/error to stdout. A successful explicit check updates `Last checked`. `MEMPALACE_VERSION_CHECK=0` and invalid values still block
  the request; run `unset MEMPALACE_VERSION_CHECK` (or set it to `1`) before retrying.
- Only `https://pypi.org/pypi/mempalace-code/json` is contacted. No telemetry, no user IDs, no installed-package inventory.

**Environment overrides:**

| Variable | Effect |
|---|---|
| `MEMPALACE_VERSION_CHECK=1` | Force-enable (overrides config and state); `true`, `yes`, `on` are accepted too |
| `MEMPALACE_VERSION_CHECK=0` | Force-disable (overrides config and state); `false`, `no`, `off` are accepted too |
| `MEMPALACE_VERSION_CHECK_INTERVAL_HOURS=N` | Override interval in whole hours, at least 1 (default: 168); an invalid value is reported and ignored |

Setting `MEMPALACE_VERSION_CHECK=0` in a CI pipeline guarantees no version-check network calls,
including explicit `--check-now`, regardless of any saved preference. Invalid values fail closed in
the same way, and `version-check --status` says the value is unrecognized. Run `unset MEMPALACE_VERSION_CHECK` (or set it to `1`) before an explicit check.

---

## This Fork vs Upstream

This is a code-first fork of the upstream `mempalace` project. The canonical upstream repository is [MemPalace/mempalace](https://github.com/MemPalace/mempalace); the older `milla-jovovich/mempalace` URL redirects there.

Snapshot reviewed on 2026-10-03 against upstream `develop` at commit `43122aefb8ed58e9fa4e1953e15ce70026339ec2` (upstream release 3.11.0), using pinned upstream public sources. Nothing below is a performance, quality, or adoption comparison — no upstream build or benchmark was run.

| Area | Upstream, as advertised at that commit | This fork |
|---|---|---|
| Focus | General-purpose AI memory | Code-first: repository mining, `code_search`, symbol/type/project-graph tools |
| Default storage | ChromaDB | LanceDB |
| Other backends offered | `sqlite_exact`, native `rust_exact`, Milvus, Qdrant, pgvector | LanceDB-only current package; ChromaDB support is retired; no server-backed backends |
| Embedding model | `all-MiniLM-L6-v2` by default; onboarding recommends the multilingual `embeddinggemma-300m`; optional OpenAI-compatible embedding server | `all-MiniLM-L6-v2`; no supported multilingual configuration or migration flow |
| Retrieval | Hybrid retrieval | Vector search, plus a local deterministic `code_search(rerank="hybrid")` |
| Reranking | Optional LLM reranking | None — no LLM reranker; this direction is explicitly rejected |
| MCP tools | 47 in the full server registry (its README still says 45), plus a 3-tool lightweight server | 29 in the full profile, plus a 4-tool minimal profile for agent plugins |

This fork has not adopted upstream's multilingual embedding, broad hybrid-retrieval, or alternative-backend paths. LLM reranking is explicitly rejected: it would put an API key, a per-query network call, and non-deterministic results into a tool that stays local after the one-time model download.

Reviewed comparison with source links, evidence limits, and the reasoning behind each decision: [`docs/UPSTREAM_COMPARISON.md`](https://github.com/rergards/mempalace-code/blob/main/docs/UPSTREAM_COMPARISON.md).

Historical community criticism of upstream from April 2026, and how this fork responded at the time, is archived in [`docs/UPSTREAM_HARDENING.md`](https://github.com/rergards/mempalace-code/blob/main/docs/UPSTREAM_HARDENING.md). Those findings describe April 2026 and are not claims about upstream today.

---

## Benchmarks

### Token savings vs grep + read ([full methodology](https://github.com/rergards/mempalace-code/blob/main/docs/BENCH_TOKEN_DELTA.md))

Measured 2026-08-09 on the canonical fixture, a snapshot of this repository (378 tracked files, 2,024 mined chunks, 20 queries):

| Median | Mean | Peak |
|--------|------|------|
| **14.5x** | 15.8x | **33.8x** |

These are read from the committed [`benchmarks/token_delta_fixture_facts.json`](https://github.com/rergards/mempalace-code/blob/main/benchmarks/token_delta_fixture_facts.json); `scripts/docs_drift_guard.py` fails CI if the Median or Peak columns drift from that file (Mean comes from the same file but is not individually guard-checked). Treat the figures as benchmark results for this fixture's query set and corpus size; re-run the benchmark before applying them to a different corpus.

### Retrieval quality

| Benchmark | Score |
|-----------|-------|
| Code retrieval R@5 (MiniLM, 469 chunks, 2026-04-09) | **95.0%** |
| Code retrieval R@10 | **100%** |
| .NET retrieval R@5 (CleanArchitecture pinned corpus, vector, 2026-05-03) | **90.0%** |
| .NET retrieval R@5 (same corpus, `rerank="hybrid"`) | **100%** |

These are read from the committed [`benchmarks/retrieval_quality_facts.json`](https://github.com/rergards/mempalace-code/blob/main/benchmarks/retrieval_quality_facts.json); `scripts/docs_drift_guard.py` fails CI if these values drift from that file. The code rows are the 2026-04-09 embedding A/B run (20 known-answer queries over a 469-chunk snapshot of this repository); the current `benchmarks/code_retrieval_bench.py` uses a different 33-query dataset and does not reproduce them. The .NET rows were measured 2026-05-03 on the pinned CleanArchitecture commit.

Upstream LongMemEval result (96.6% R@5 on conversations) retained with [methodology caveats](https://github.com/rergards/mempalace-code/blob/main/benchmarks/BENCHMARKS.md).

---

<details>
<summary><strong>Installation Details</strong></summary>

```bash
pip install mempalace-code
# or
uv pip install mempalace-code
```

**Bootstrap script** (explicit remote-script option for servers/CI):

```bash
[[ "${BOOTSTRAP_REF:-}" =~ ^[0-9a-fA-F]{40}$ ]] || { echo "BOOTSTRAP_REF must be a reviewed 40-hex commit" >&2; exit 2; }
BOOTSTRAP_FILE="$(mktemp -t mempalace-bootstrap.XXXXXX)" || exit 1
(
  trap 'rm -f -- "$BOOTSTRAP_FILE"' EXIT
  curl -fL "https://raw.githubusercontent.com/rergards/mempalace-code/$BOOTSTRAP_REF/scripts/bootstrap.sh" -o "$BOOTSTRAP_FILE" || exit 1
  less "$BOOTSTRAP_FILE" || exit 1
  bash "$BOOTSTRAP_FILE" || exit 1
) || exit 1
```

**Optional extras:**

```bash
# mempalace-code[custom-models]            # CPU-only Linux: docs/OFFLINE_USAGE.md
pip install "mempalace-code[treesitter]"  # AST parsing
pip install "mempalace-code[spellcheck]"  # autocorrect helper API; never applied to mined text
pip install "mempalace-code[watch]"       # optional watcher (auto-mine on file changes)
pip install "mempalace-code[dev]"         # pytest + ruff + pyright
```

CPU-only Linux custom models require the ordered CPU PyTorch contour and bounded recovery
in [Using a Custom Model Offline](https://github.com/rergards/mempalace-code/blob/main/docs/OFFLINE_USAGE.md#3-using-a-custom-model-offline).
That guide also covers arbitrary SentenceTransformer names and local paths, and how a
palace records its model so the CLI and MCP server use it.

**Requirements:** Python 3.11+. Use `mempalace-code init <dir> --skip-model-download` for an
offline-safe init. Run `mempalace-code fetch-model` later only after explicit consent to cache
the ~80 MB embedding model.

The default `all-MiniLM-L6-v2` runtime is CPU FastEmbed/ONNX and stores its
immutable MemPalace provenance under
`$HF_HOME/mempalace-fastembed/all-MiniLM-L6-v2-v1/`. Canonical aliases never
enable trusted remote code. Explicit custom models require `[custom-models]`;
that path retains SentenceTransformer's `trust_remote_code=True` compatibility
boundary. Recovery: run `mempalace-code fetch-model` while online, then retry
with `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1`. MemPalace sets
`ORT_DISABLE_TELEMETRY=1` before ONNX Runtime loads (an explicit value you set is
kept), so ONNX Runtime does not create its device-usage event store under your home
directory (on macOS `~/Library/Application Support/Microsoft/DeveloperTools/.onnxruntime/`).

</details>

<details>
<summary><strong>All CLI Commands</strong></summary>

```bash
mempalace-code help                                    # show top-level help message and exit
mempalace-code help <command>                          # show one command's help (same as <command> --help)
mempalace-code --version                               # print the installed package version and exit

# Setup
mempalace-code init <dir>                              # initialize rooms (keeps an existing mempalace.yaml)
mempalace-code init <dir> --force                      # regenerate rooms; keeps wing/settings, backs up the old file
mempalace-code init <dir> --detect-entities            # optional prose entity bootstrap
mempalace-code onboarding <dir>                        # record people/projects (entity registry, AAAK codes) + reference notes; <dir> is scanned only on request
mempalace-code split <dir>                             # split Claude Code transcript mega-files (top-level .txt) before mining
mempalace-code split <file>                            # split one mega-file; every line is kept, original → .mega_backup
mempalace-code install-alias                           # create optional 'mempalace' alias next to mempalace-code
mempalace-code install-alias --target-dir <dir>        # create it in an existing <dir> instead; only <dir> is inspected
mempalace-code-alias --yes                             # the same as install-alias, as its own console script (bare: help only)

# Mining
mempalace-code mine <dir>                              # mine code project
mempalace-code mine <dir> --wing myapp                 # tag with wing
mempalace-code mine <dir> --mode convos                # mine conversations
mempalace-code mine <dir> --full                       # force full rebuild
mempalace-code mine <dir> --watch                      # auto-incremental on file changes
mempalace-code mine-all <parent-dir>                   # sync all projects incrementally (one wing per project)
mempalace-code mine-all <parent-dir> --new-only        # only mine projects not yet in the palace

# Watch (project auto-sync)
mempalace-code watch <initialized-project>             # watch a single initialized project
mempalace-code watch <parent-dir>                      # watch all initialized projects in a parent directory
mempalace-code watch <parent-dir> schedule             # print this root's launchd/cron daemon snippet
mempalace-code watch <parent-dir> status               # disk budget, root validity, this root's launchd job

# Search
mempalace-code search "query"                          # search everything
mempalace-code search "query" --wing myapp             # scoped to wing
mempalace-code search "query" --room auth              # scoped to room
mempalace-code search "query" --json                   # one JSON object: hits with id, source_file, line_range
mempalace-code read <file> --start N --end N           # print stored source lines for a file/range
mempalace-code compress --wing myapp                   # print lossy AAAK Dialect summaries (read-only; drawers stay verbatim)
mempalace-code compress --recover-from <archive>       # restore drawers that compress rewrote before 1.15.0

# Diary
mempalace-code diary write --agent <name> --entry "<text>"  # write a diary entry
```

A successful direct diary write prints `Diary entry stored.`, stable `ID`, `Wing`, `Room`, and
`Topic` poststate, then a bounded `Verify before retry` search command. If that output is retained
after an ambiguous result, run the printed search (it prints JSON hits) before any retry. An exact
hit means success — a hit whose `id` equals the printed `ID`, not merely similar text: do
not repeat the write. If the response or printed command is unavailable, do not retry; inspect
recent same-agent entries with exposed `mempalace_diary_read` (it also returns entries written
under `--wing`), or stop for owner reconciliation. A blank `--agent`, `--entry`, `--topic`, or
`--wing`, or a name containing `/`, `\` or control characters, exits 2 before the palace is
touched. A new `--wing` that only re-spells an existing wing (`Shop` when `shop` exists) also
exits 2 and names the existing wing, as `mempalace_add_drawer` does.

```bash

# Backup & Recovery
mempalace-code backup create                           # create backup (default: <palace_parent>/backups/<palace_name>/)
mempalace-code backup list                             # list existing backups
mempalace-code backup schedule --freq daily            # print daily scheduler snippet
mempalace-code restore <archive>                       # restore from backup
mempalace-code export --only-manual --out backup.jsonl # JSONL export
mempalace-code import <file>                           # JSONL import
mempalace-code health                                  # probe for fragment corruption
mempalace-code cleanup                                 # reclaim stale Lance versions
mempalace-code repair --rollback                       # roll back to last working version

# Context
mempalace-code wake-up                                 # L0 + L1 context on stdout
mempalace-code wake-up --wing myapp                    # project-scoped
mempalace-code status                                  # detailed overview; grows with wing/room count
mempalace-code status --summary                        # bounded agent-facing status (drawer/wing/room-pair counts + storage)
mempalace-code health --json                           # compact integrity report

# Model
mempalace-code fetch-model                             # cache or verify model for offline use

# Advanced / Ops
# Legacy Chroma palace recovery: back up SRC before upgrading, then run the last bridge in isolation.
# The bridge installs a pre-1.0 chromadb with server-side advisories: run it once, locally, no Chroma server.
mempalace-code migrate-storage SRC DST --verify         # retired; exits before mutation and points here
uvx --python 3.12 --from 'mempalace-code[chroma]==1.13.4' mempalace-code migrate-storage SRC DST --verify
mempalace-code preflight mirror --command "<cmd>"      # inspect an rsync command for state-dir risks
mempalace-code version-check                           # show version-check status (opt-in PyPI checks)
mempalace-code version-check --check-now               # check PyPI now; prints a pip fallback for unmanaged installs
mempalace-code update status                            # inspect upgrade eligibility (supported installs)
mempalace-code agent-plugin path --json                # locate the installed Agent Plugins package directory
mempalace-code wing-migration qualify --mode synthetic # qualify the receipt-bound copy migration operator
```

Plain `status` prints a full wing/room breakdown, so its output grows with palace size. Do not use it as a routine agent bootstrap or machine-readable health check; use `status --summary` for bounded shell-based CLI discovery, task-specific MCP retrieval, or `mempalace-code health --json` for a compact CLI integrity report.

</details>

<details>
<summary><strong>Saving Conversation Context</strong></summary>

Code mining is automatic via `mempalace-code watch`. For conversation context (decisions, discussions, debugging notes), an MCP-capable client can expose the storage tools:

1. Wire the MCP server (see [install docs](https://github.com/rergards/mempalace-code/blob/main/docs/AGENT_INSTALL.md))
2. For compatible Agent Plugins 1.0 clients, load the package reported by `mempalace-code agent-plugin path --json`; follow [Section 7](https://github.com/rergards/mempalace-code/blob/main/docs/AGENT_INSTALL.md#section-7--agent-instruction-loading-agent-plugin-only)
3. For other clients, stop after MCP wiring. [`docs/LLM_USAGE_RULES.md`](https://github.com/rergards/mempalace-code/blob/main/docs/LLM_USAGE_RULES.md) remains read-only reference material; instruction-file and system-prompt mutation are unsupported
4. Subject to client policy, call `mempalace_add_drawer` and `mempalace_diary_write` during sessions

> **Legacy:** Claude Code also supports optional [auto-save hooks](https://github.com/rergards/mempalace-code/blob/main/hooks/README.md) that remind the AI to save at fixed intervals. They are repository scripts, not part of the installed package; the hooks README shows how to download them. They are independent of the Agent Plugin instruction-loading boundary.

</details>

<details>
<summary><strong>Project Structure</strong></summary>

```
mempalace-code/
├── mempalace_code/
│   ├── cli.py              ← CLI entry point
│   ├── cli_commands/       ← CLI command handlers
│   ├── mcp/                ← MCP server implementation (29 tools, profiled at startup)
│   ├── mcp_server.py       ← MCP entrypoint compatibility facade
│   ├── storage.py          ← LanceDB vector storage
│   ├── mining/             ← language-aware project mining and chunking
│   ├── miner.py            ← mining compatibility facade
│   ├── convo_miner.py      ← conversation ingest
│   ├── searcher.py         ← semantic search
│   ├── knowledge_graph.py  ← temporal entity graph (SQLite)
│   ├── palace_graph.py     ← room navigation graph
│   └── layers.py           ← 4-layer memory stack
├── mempalace/              ← source-only MCP compatibility shim
├── benchmarks/             ← reproducible benchmark runners
├── hooks/                  ← Claude Code auto-save hooks (legacy, optional)
├── examples/               ← usage examples
└── tests/                  ← 3,000+ tests
```

</details>

---

## Opt-in updates

Supported isolated installs can inspect and explicitly apply upgrades. The command never runs
from ordinary MemPalace startup, and its systemd-user scheduler is disabled until installed by
the operator.

```bash
mempalace-code update status                 # read-only: installer, extras, provenance, service, timer
mempalace-code update check                  # read-only canonical PyPI provenance refresh
mempalace-code update apply --yes            # explicit package and managed-watcher transaction
mempalace-code update scheduler render       # inspect systemd-user units without writing them
mempalace-code update scheduler install --yes # explicit daily scheduler opt-in (Linux systemd-user)
```

Omitting `--yes` from `update apply`, `update scheduler install`, or `update scheduler remove`
exits 2 before mutation. Human output prints `Recovery: <command>`; JSON output supplies the exact
guarded command in `recovery_command`. Review current mutation authority before running that
emitted command. See [the update runbook](https://github.com/rergards/mempalace-code/blob/main/docs/UPDATES.md) for the complete refusal contract.

The first slice supports `uv tool`, `pipx`, and the documented `~/.mempalace/venv` bootstrap
install. It refuses system Python, distro-managed, editable/source, and ambiguous environments
before stopping a watcher or changing package state. If you installed with plain `pip`, upgrade
yourself — `mempalace-code version-check --check-now` prints the exact pinned `python -m pip install`
command for the interpreter that is running mempalace-code. Stable, compatible-major releases
are selected from canonical PyPI provenance; prereleases, yanked files, and releases without a
wheel are refused.
Detected extras are retained. A configured watcher missing its required `watch` extra is also a
preflight refusal.

An update serializes with watchers, records its stage and bounded log under `~/.mempalace/updates/`,
validates the new console and palace, then restores a previously active managed watcher. Any failure
after version recording invokes the same installer to roll back the prior version and restores the
prior watcher state. See [the update runbook](https://github.com/rergards/mempalace-code/blob/main/docs/UPDATES.md) for recovery.

## Contributing

PRs welcome. See [CONTRIBUTING.md](https://github.com/rergards/mempalace-code/blob/main/CONTRIBUTING.md).
Maintainers should follow [docs/RELEASING.md](https://github.com/rergards/mempalace-code/blob/main/docs/RELEASING.md) before tagging or publishing.

```bash
python -m pytest tests/ -x -q    # full suite, all local, no network
python -m pyright --pythonpath "$(python -c 'import sys; print(sys.executable)')"  # type-check baseline
```

## License

Apache 2.0 — see [LICENSE](https://github.com/rergards/mempalace-code/blob/main/LICENSE) and [NOTICE](https://github.com/rergards/mempalace-code/blob/main/NOTICE).

<!-- Link Definitions -->
[version-shield]: https://img.shields.io/badge/version-1.16.0-4dc9f6?style=flat-square&labelColor=0a0e14
[release-link]: https://github.com/rergards/mempalace-code/releases
[python-shield]: https://img.shields.io/badge/python-3.11+-7dd8f8?style=flat-square&labelColor=0a0e14&logo=python&logoColor=7dd8f8
[python-link]: https://www.python.org/
[license-shield]: https://img.shields.io/badge/license-Apache_2.0-b0e8ff?style=flat-square&labelColor=0a0e14
[license-link]: https://github.com/rergards/mempalace-code/blob/main/LICENSE
