# Published 1.15.1 direct functional follow-up

The installed 1.15.1 package passed the direct scenarios below on disposable data.
This retrospective evidence supplements the release checks. It does not admit a
new release or prove an exhaustive repository audit. Automatic completeness
enforcement remains open under `MP-RELEASE-DIRECT-COVERAGE`.

## Candidate and execution boundary

- Published source: `df379c058d00f7255a76dc7f7d36280b3284ea44`.
- Artifact: `mempalace_code-1.15.1-py3-none-any.whl`.
- Wheel SHA-256: `bfa4902403102be364aaaa2fcf83f968eb51576b6e50e1f123cab818af12f983`.
- Tests used fresh non-editable wheel installations and a clean archive of that
  source for the existing qualification script. Concurrent development changes
  were excluded from the tested package and preserved.
- Fixtures used synthetic code, drawers, facts, conversations and isolated
  HOME/XDG/model-cache paths. Direct CLI/MCP launches used runtime socket guards. Nested wing-runtime
  subprocesses used the existing owner's offline environment; no external AI
  client or account credentials were used for qualification.
- Existing client processes, services and real palaces were preserved. Live wing
  migration and full-copy qualification were checked for their explicit refusal
  without authority. Those refusals do not establish successful live execution.
- LDR selection: empty. This task reuses qualification owners and adds evidence
  and release instructions; no accepted decision corpus exists in the inspected
  committed tree and no new architecture is proposed.

## Fresh direct results

| Interface or area | Actual execution and result |
| --- | --- |
| Installed golden CLI suite | macOS and Linux: all 26 aggregate rows passed. These rows include model-cache checks, init, project mining and incremental behavior, search/read, import/export, backup/restore guards, health/cleanup/repair guards, split, compression retries, schedule rendering, aliases and isolated watcher signals. |
| MCP tools and profiles | On each OS, all 29 tools were exercised wherever enabled: minimal 4, kg 8, code 11, notes 12, full 29. Both legacy initialization and modern `2026-07-28` discovery were used. Each OS passed 128 tool/profile/protocol success cases; combined total 256. Results were checked against known fixture facts. Modern structured results matched their text payloads. |
| MCP failure and recovery | Each success case had an undeclared-argument control: 256 combined rejections. Each limited profile rejected a disabled tool: 16 combined controls. All 20 sessions rejected malformed JSON, then completed a valid discovery request and exited with leases released. |
| MCP type, bounds and alias guards | macOS: 14 additional requests across both protocols covered wrong types, oversized query/drawer input, out-of-range `max_results`, conflicting `limit`/`max_results`, and unknown tools. Expected protocol errors occurred; exact palace file hashes stayed unchanged. |
| Wing migration qualification | Actual `wing-migration qualify --mode synthetic` passed on both OSes. All seven reported predicates were true, including snapshot/restore, exact typed union, native wing update and zero-write merged retry. |
| Individual wing commands | macOS: actual `inventory`, `snapshot`, `apply`, `classify`, `recover`; apply without snapshot refused with unchanged state; merged retry wrote zero rows. Recovery restored typed rows/schema, complete KG logical state, sidecar/configuration data and exact Lance file bytes. Missing-input, full-copy-without-inventory and live-without-authority refusals preserved protected state. |
| Onboarding | macOS: successful synthetic project setup, unchanged repeat, and EOF refusal. Registry/reference files were present after success; EOF preserved them; source project bytes stayed unchanged. |
| Conversation formats | macOS: Claude Code JSONL, Codex JSONL, Gemini JSONL, Claude.ai JSON, ChatGPT JSON, Slack JSON and plain text each produced the expected normalized code-question drawer. Retry added no drawers and preserved the complete exported records. A recognized empty Codex envelope was skipped without raw-JSON fallback or data change. |
| Previous published package | Verified PyPI history identified 1.14.2 as the preceding published version. Its actual installed CLI seeded four drawers and six facts. 1.15.1 CLI health/export and real stdio status/KG/code-search passed. All old serialized fields and IDs were preserved. The current export adds the existing KG extraction timestamp; its additional field is not data loss. |
| Optional source hooks | Matching release-source scripts were invoked directly with synthetic client-event JSON. The Stop script triggered at 15 human prompts, updated the reminder checkpoint, suppressed a repeated trigger and accepted its reentry guard. PreCompact exited without blocking. No hook was installed and optional background mining remained disabled. This tests reminder semantics, not persistence confirmation. |
| Optional extras and public exports | The installed golden owner completed its existing extra/API reconciliation on macOS and Linux. No new default embedding model was selected. |

Representative commands, with every path below referring to disposable fixtures:

```bash
python -B scripts/release_readiness_gate.py --installed-golden-wheel "$WHEEL" --json
mempalace-code wing-migration qualify --mode synthetic
mempalace-code wing-migration inventory --inventory "$INVENTORY" --receipt "$RECEIPT"
mempalace-code wing-migration snapshot --receipt "$RECEIPT"
mempalace-code wing-migration apply --inventory "$INVENTORY" --receipt "$RECEIPT"
mempalace-code wing-migration classify --receipt "$RECEIPT"
mempalace-code wing-migration recover --inventory "$INVENTORY" --receipt "$RECEIPT"
mempalace-code onboarding "$PROJECT"
mempalace-code --palace "$PALACE" mine "$TRANSCRIPTS" --mode convos --wing synthetic-code-questions --no-spellcheck
mempalace-code --palace "$PALACE" export --with-kg --out "$NEW_EXPORT"
```

MCP requests ran through the installed `mempalace-code-mcp` process. For example,
`tools/call` with `mempalace_search` and `{"query":"fixture","max_results":true}`
returned `-32602`, while an unknown tool returned `-32601`. Commands, synthetic
inputs, actual responses, assertions and receipt hashes are retained in the
existing ignored task evidence, outside the published tree.

## Findings and release rules

`MP-RELEASE-DIRECT-COVERAGE` is P1/open. The published qualification owner calls
tools only under `full`; other profiles receive initialization and discovery.
Its root CLI inventory misses delegated wing-migration actions, and missing-input
parent guidance can count as an execution receipt. The extra direct scenarios
above supply present evidence. They do not repair future automatic enforcement.
The same existing owner must reject missing functional cases; this remains a
prerequisite for the next release's complete acceptance claim.

`MP-RELEASE-MACOS-SOCKET-PATH` was reproduced in the unchanged published owner:
the installed suite failed on an overlong socket fixture path. The same wheel
and script passed all 26 rows with a shorter temporary root, and Linux passed
without that workaround. A separate executor has completed and independently
reviewed the same-owner fixture correction. Its exact evidence and status are
in `docs/handoffs/direct-functional-2026-10-05.md` and the existing backlog task.
This follow-up did not overwrite that executor's code or completion.

Release requirements are committed in `AGENTS.md`, `docs/RELEASING.md`,
`docs/quality/acceptance/README.md` and `.claude/skills/release-prep/SKILL.md`.
They require checked direct installed outcomes, delegated-command inventory,
each enabled tool/profile, both protocols, guards/retries and supported platform
evidence. Discovery or usage errors cannot stand in for execution. Missing
required coverage blocks acceptance; qualification does not authorize live work.
Independent Astra medium read-only instruction review passed frozen diff
SHA-256 `b5259cac881d0f45ec395cfcbe38ed47653e546e4c3832561ea93ad3a08fab4f`.
Documentation drift, public-safety and skill frontmatter checks passed before
commit `2f01b2a292fbc53039dd824e21849704a56bc181`.

## Evidence limits

The individual wing-command, onboarding-success, seven-format, upgrade and
additional type/size cases above were newly run on macOS. Linux newly ran the
golden suite, complete tool/profile/protocol matrix and synthetic qualification.
The new macOS-specific supplemental cases were not repeated on Linux.

Unchanged prior candidate evidence remains separate: installer contours,
credential-free hosted tests and isolated Linux service/update lifecycle. A
macOS-only installer aggregate correctly reports Linux lifecycle as unrun;
individual macOS installer successes do not replace Linux evidence. No new
hosted workflow was triggered for these documentation changes.

Successful live wing migration, service installation, arbitrary custom-model
retrieval and real AI-client interoperability were not run in this follow-up.
Their authority/environment boundaries remain explicit. These results do not
claim every input, option combination, or language-specific extraction variant
was separately exercised through the public CLI. Source unit tests and prior
platform evidence are not relabeled as fresh direct execution.

Private harness failures were corrected against existing contracts: EOF is
onboarding exit 1; export headers are not drawers; SQLite recovery preserves the
logical state; skip guidance may use stdout; KG export requires `--with-kg` and
supports the added extraction timestamp. Initial observations were retained.
These harness corrections did not establish additional product defects.

Recovery: inspect the current repository status, read the current backlog task
journals, then rerun the existing installed-golden command against the named
wheel. Refresh task ownership before changing the shared qualification owner.
