# Backup and Restore — Protecting Manual Drawers

## The Silent Data Loss Problem

Replacing the active palace before validating recovery artifacts can destroy:

- **Drawers added via `mempalace_add_drawer`** (MCP tool) — architectural decisions, people facts, debugging notes, meeting context
- **Diary entries** written via `mempalace_diary_write` — agent session journals and continuity entries
- **Knowledge graph triples** stored in the palace's `<palace>/knowledge_graph.sqlite3` — if you rely on KG for temporal facts

The miners only regenerate drawers they produced from source files or conversation exports (every
`chunker_strategy` except `manual_v1` and `diary_v1`). They know nothing about manually-added content.

---

## Recommended Rebuild Workflow

This is the complete rebuild procedure. A palace usually holds several mined
sources, and the rebuild regenerates only the sources you list: a project or
conversation directory missing from the lists below loses its drawers. Keep every
command in one shell so the same explicit paths are used throughout.

Before running anything:

1. Run `mempalace-code --palace "$PALACE" status` and account for every wing. A
   wing filed by `mine` belongs to one project directory (its `mempalace.yaml`
   names the wing), and a wing filed by `mine --mode convos` to one conversation
   directory. Manual and diary wings come back from the export.
2. List every such project directory in `PROJECTS` and every conversation
   directory in `CONVOS` (leave `CONVOS=()` empty if there are none). If you mined
   projects with `mine-all PARENT`, list each project below `PARENT`.
3. Replace `KNOWN_QUERY` with content you expect to find after rebuilding.

```bash
set -euo pipefail

PALACE="${HOME}/.mempalace/palace"
PROJECTS=("${HOME}/projects/my_app" "${HOME}/projects/frontend")
CONVOS=()
KNOWN_QUERY="a known decision or source phrase"
EXPORT_JSONL="${HOME}/.mempalace/recovery-manual.jsonl"
BACKUP_TAR="${HOME}/.mempalace/recovery-full.tar.gz"
WINGS_BEFORE="${HOME}/.mempalace/recovery-wings-before.txt"
WINGS_AFTER="${HOME}/.mempalace/recovery-wings-after.txt"
QUARANTINE="${PALACE}.quarantine-$(date -u +%Y%m%dT%H%M%SZ)"

: "${PALACE:?set PALACE to the inspected active palace}"
: "${KNOWN_QUERY:?set KNOWN_QUERY to expected content}"
: "${EXPORT_JSONL:?set EXPORT_JSONL to a new JSONL path}"
: "${BACKUP_TAR:?set BACKUP_TAR to a new tar path}"
: "${QUARANTINE:?set QUARANTINE to a new sibling path}"
test "${#PROJECTS[@]}" -gt 0
test -d "$PALACE/lance"
for dir in "${PROJECTS[@]}" ${CONVOS[@]+"${CONVOS[@]}"}; do test -d "$dir"; done
PALACE_ID="$(cd "$PALACE" && pwd -P)"
: "${PALACE_ID:?failed to resolve PALACE identity}"
test ! -e "$EXPORT_JSONL"
test ! -e "$BACKUP_TAR"
test ! -e "$WINGS_BEFORE"
test ! -e "$WINGS_AFTER"
test ! -e "$QUARANTINE"

mempalace-code --palace "$PALACE" status | sed -n 's/^  WING: //p' | sort > "$WINGS_BEFORE"
mempalace-code --palace "$PALACE" export --only-manual --with-kg --out "$EXPORT_JSONL"
mempalace-code --palace "$PALACE" import "$EXPORT_JSONL" --dry-run
mempalace-code --palace "$PALACE" backup create --out "$BACKUP_TAR"
tar -tzf "$BACKUP_TAR"

test "$(cd "$PALACE" && pwd -P)" = "$PALACE_ID"
test -d "$PALACE/lance"
test ! -e "$QUARANTINE"
mv "$PALACE" "$QUARANTINE"
for project in "${PROJECTS[@]}"; do
  mempalace-code --palace "$PALACE" mine "$project"
done
for convos in ${CONVOS[@]+"${CONVOS[@]}"}; do
  mempalace-code --palace "$PALACE" mine "$convos" --mode convos
done
mempalace-code --palace "$PALACE" import "$EXPORT_JSONL"
mempalace-code --palace "$PALACE" health
mempalace-code --palace "$PALACE" status | sed -n 's/^  WING: //p' | sort > "$WINGS_AFTER"
diff -u "$WINGS_BEFORE" "$WINGS_AFTER"
mempalace-code --palace "$PALACE" search "$KNOWN_QUERY" --results 5
```

The fail-fast setting stops the workflow when any command fails. The `diff`
compares the wing inventory before and after the rebuild and fails on any
difference: a line starting with `-` is a wing whose source is missing from
`PROJECTS` or `CONVOS`, and a line starting with `+` is a wing whose name changed
(for example a project originally mined with `--wing`). Mine the missing source
with its original flags against the same `$PALACE`, then rerun the `status`,
`diff`, and `search` lines; or restore the original palace with Failure recovery
below. Compare the drawer totals that `status` prints before and after as well:
edits since the last mine change them slightly, but a large drop means a source
was mined incompletely. The JSONL
import dry run validates input and opens existing palace state read-only when
present. It checks every drawer and KG record as a real import does and exits
non-zero naming each invalid record, so the workflow stops before the palace is
moved. It does not write palace or KG state. When the selected palace and KG
are absent, it does not create them or initialize temporary, embedding-model, or
cache state. Here it previews record import without applying records. Inspect
the `tar -tzf` listing and confirm it contains `metadata.json` and the expected
`lance/` content. The JSONL contains:

- All drawers with `chunker_strategy` in `manual_v1` (MCP `add_drawer`) or `diary_v1` (diary entries)
- All triples from the palace KG at `<palace>/knowledge_graph.sqlite3`, the same KG
  that MCP and the watcher use; `--only-manual` does not filter KG records

Every command resolves the KG from its palace (`--palace`, or the configured
palace). The separate global KG at `~/.mempalace/knowledge_graph.sqlite3` is a
legacy file: MCP before v1.13.5 and CLI commands run without `--palace` through
v1.14.2 wrote it, and the Python `KnowledgeGraph()` default without `db_path`
still opens it (and emits a `DeprecationWarning`). The first command that opens
the configured palace's KG after the legacy file appears or changes copies in
each legacy fact whose subject, predicate, and object the palace KG does not hold
in any validity state; facts the palace KG already holds stay unchanged, and the
adoption message counts them. The configured palace is the `--palace`-free
selection: `MEMPALACE_PALACE_PATH`, else `config.json`, else the default. A palace
selected only by `MEMPALACE_PALACE_PATH` that differs from the `config.json`
palace adopts only when it already exists and the `config.json` palace does not.
The marker `~/.mempalace/knowledge_graph.sqlite3.adopted` records the adopted
legacy file state, so a quarantined, rebuilt, or restored palace does not receive
the legacy facts again. Delete that marker to adopt again. `import` replays its
JSONL KG records before adopting. `backup create` opens the palace KG too, so in
the rebuild workflow above it adopts into the palace about to be quarantined and
writes the marker. Take a rebuild's export with this release or later: its
`export --with-kg` adopts first, so the export already holds the legacy facts.
An export written by a release before 1.15.0 with `--palace` holds the palace
KG but not the legacy facts, so after replaying such an export into the
configured palace, `import` adopts again even though the marker exists and
prints `Adopted N fact(s)`. Because the replay runs first, a fact the export
holds closed stays closed. Through 1.14.2, `export --with-kg` and `backup create`
run without `--palace` wrote the legacy KG instead of the palace KG, so such an
export or archive lacks every fact added through MCP. Neither records whether
`--palace` was passed, so the triple ids decide: when every KG fact of a
pre-1.15.0 export is in the legacy file, `import` and `import --dry-run` refuse
it before writing anything and print the `export` command that takes the palace
KG with this release (`--skip-kg` imports only its drawers). When the source
cannot be told, because the export holds no KG records (an empty legacy KG, for
example when only MCP was used) or the legacy file is gone, they refuse an export
with no KG records while the target palace KG holds facts (`--skip-kg` then loses
nothing), and otherwise warn that the export may lack those facts. Restoring a
tar archive written with `--palace` before upgrading, once the marker exists,
keeps the archived KG without the legacy facts; to copy them in, delete the
marker and run any command that opens the palace KG, for example
`mempalace-code export --with-kg --out - > /dev/null`. A pre-1.15.0 archive
written without `--palace` holds the legacy KG: `restore --force` refuses to put
it over the palace's own KG and prints the rerun that writes it to a separate
`--kg-path`, keeping the palace KG; a restore into a new location warns that the
restored KG is the legacy one. When a pre-1.15.0 archive's KG source cannot be
told (it holds no facts, or the legacy file is gone), `restore --force` refuses
only if the palace KG holds facts the archive lacks, with the same rerun, and a
restore into a new location warns that the KG may be the legacy one. The legacy
database contents are never modified (SQLite may leave `-wal` and `-shm` files
next to it), and other palaces never receive its facts. An unreadable legacy file
is retried on every open; the warning names the command that moves it aside.
Adopted facts mined from files that have changed since can show as current until
`mempalace-code mine <dir> --full` re-mines that project.

Import deduplicates against the freshly mined palace: it skips a drawer whose id
is already stored or repeats earlier in the file, or whose target wing already
held a drawer with cosine similarity of at least 0.9 before the import began, so
similar records of one file never dedup each other. `Imported drawers`,
`Skipped duplicates`, `Skipped invalid`, and `Failed drawers` (printed only when not
zero) should add up to the `drawer_count` in the export header (the first JSONL
line); this count covers only the manual and diary drawers, so it cannot detect a
missing project: the wing comparison does. A palace can still hold rows that older
releases imported without an id, wing, room, or text, or KG facts without a subject,
predicate, or object; its export carries them, and the dry run names each one so you
can fix it in the JSONL before the palace is moved. KG records merge in one
transaction, so replaying an export is a no-op: a triple whose exported id or exact
subject, predicate, object, and validity window is already stored counts under
`Skipped KG duplicates`, and `Imported KG triples` counts only inserted facts. A
fact this palace invalidated after the export stays invalidated and is reported as
a KG conflict; a newer export that invalidated a fact with the same id applies that
end date. An export's own history imports whole: a fact it holds both closed and
reopened keeps its current copy. If the KG transaction fails, for example because
another process holds the KG write lock, no KG record is imported and `import`
exits non-zero with the command to re-run it. Keep `$QUARANTINE`, `$EXPORT_JSONL`,
`$BACKUP_TAR`, and the two wing lists until the import summary, health result, empty
wing `diff`, and bounded known-result search are all
correct. Only then may you dispose of the quarantine.

### Failure recovery

If validation fails, stop the new palace process and recover the
original palace with the standalone workflow below. Replace the quarantine
timestamp with the exact path created above.

```bash
set -euo pipefail

PALACE="${HOME}/.mempalace/palace"
QUARANTINE="${PALACE}.quarantine-REPLACE_WITH_ORIGINAL_TIMESTAMP"
FAILED_REBUILD="${PALACE}.failed-rebuild-$(date -u +%Y%m%dT%H%M%SZ)"

: "${PALACE:?set PALACE to the failed rebuilt palace}"
: "${QUARANTINE:?set QUARANTINE to the original quarantine path}"
: "${FAILED_REBUILD:?set FAILED_REBUILD to a new sibling path}"
test -d "$QUARANTINE/lance"
test ! -e "$FAILED_REBUILD"
if test -e "$PALACE" || test -L "$PALACE"; then
  mv "$PALACE" "$FAILED_REBUILD"
fi
test ! -e "$PALACE"
test ! -L "$PALACE"
mv "$QUARANTINE" "$PALACE"
mempalace-code --palace "$PALACE" health
```

When present, the failed rebuild is preserved at `$FAILED_REBUILD`. The original
palace is restored for inspection. Do not delete either state during recovery.

---

## Restore Procedure

```bash
set -euo pipefail

PALACE="${HOME}/.mempalace/palace"
EXPORT_JSONL="${HOME}/.mempalace/recovery-manual.jsonl"

: "${PALACE:?set PALACE to the inspected existing palace}"
: "${EXPORT_JSONL:?set EXPORT_JSONL to the inspected JSONL path}"
test -d "$PALACE/lance"
test -f "$EXPORT_JSONL"

mempalace-code --palace "$PALACE" import "$EXPORT_JSONL"
mempalace-code --palace "$PALACE" health
```

Use `--skip-kg` to omit KG triples, `--wing-override NAME` to replace drawer
wings, or `--skip-dedup` to skip only the similarity check; a record whose id is
already stored or repeats in the file is still skipped, so drawer ids stay unique.
Preview the inspected file against the inspected existing palace with:

```bash
set -euo pipefail

PALACE="${HOME}/.mempalace/palace"
EXPORT_JSONL="${HOME}/.mempalace/recovery-manual.jsonl"

: "${PALACE:?set PALACE to the inspected existing palace}"
: "${EXPORT_JSONL:?set EXPORT_JSONL to the inspected JSONL path}"
test -d "$PALACE/lance"
test -f "$EXPORT_JSONL"

mempalace-code --palace "$PALACE" import "$EXPORT_JSONL" --dry-run
```

This validates input and opens existing palace state read-only when present. It
does not write palace or KG state. When the selected palace and KG are absent,
it does not create them or initialize temporary, embedding-model, or cache
state. It previews record import without applying records.

---

## Filter Semantics

### `--only-manual`

Exports only drawers that the miner **cannot regenerate**:

| `chunker_strategy` | Source | Regenerable by miner? |
|--------------------|--------|-----------------------|
| `regex_structural_v3` (`_v2` in 1.15 before per-symbol chunking, `_v1` before 1.15) | `mempalace-code mine` (regex, prose, YAML-aware, and adaptive chunks) | Yes — skip |
| `treesitter_v3`, `treesitter_adaptive_v2` (`treesitter_v2` in 1.15 before per-symbol chunking, `_v1` before 1.15) | `mempalace-code mine` with the `[treesitter]` extra | Yes — skip |
| `dotnet_project_xml_v2` (`_v1` before 1.15) | `mempalace-code mine` (`.csproj`/`.fsproj`/`.vbproj` files) | Yes — skip |
| `convo_turn_v3` | `mempalace-code mine --mode convos` (verbatim exchanges) | Yes — skip |
| `convo_general_v2` | `mempalace-code mine --mode convos --extract general` | Yes — skip |
| `convo_turn_v1`, `convo_turn_v2`, `convo_general_v1` | Earlier `mine --mode convos` releases and 1.15.0 pre-release builds; the next convos mine rebuilds these rows | Yes — skip |
| `manual_v1` | MCP `add_drawer` tool | **No — include** |
| `diary_v1` | MCP `diary_write` / CLI `diary write` | **No — include** |

Use `--only-manual` for the standard nuke-and-re-seed workflow and for moving a palace to another
machine; both then re-mine every project and conversation directory. Omit it only for a full
snapshot restored where every mined directory keeps its exact absolute path; see
[Airgap / Machine Transfer](#airgap--machine-transfer-scenario).

Conversation rows can be regenerated only while their transcripts are still on disk. Tools
prune old transcripts (Claude Code deletes sessions after `cleanupPeriodDays`), and an
incremental `mine --mode convos` keeps the drawers of transcripts that are gone, so the
palace may hold the only copy. Omit `--only-manual` when you need those conversations.

### `--wing`, `--room`, `--since`

Scope the export to a subset of your palace:

```bash
# Only the 'people' wing
mempalace-code export --out backup.jsonl --wing people

# Decisions room in the mempalace wing
mempalace-code export --out backup.jsonl --wing mempalace --room decisions

# Only drawers filed on or after 2026-01-01
mempalace-code export --out backup.jsonl --since 2026-01-01
```

`--since` takes a date as `YYYY-MM-DD`; any other spelling (for example `2026-9-1`
or `yesterday`) is rejected with an error instead of exporting nothing. `--out`
creates missing parent directories and a new file readable only by you; it refuses
an existing path instead of overwriting it (`--out -` writes to stdout).

With `--with-kg`, `--wing` or `--room` also scopes the KG: the export holds only
facts extracted from the exported drawers' source files (and, with `--wing`, that
wing's namespace-to-project architecture facts), so sharing one wing does not leak
other projects' facts. Facts without a source file (MCP `kg_add` facts)
are palace-wide and are left out; the header records `"kg_scope": "drawer_sources"`
and the CLI says so. `--since` keeps facts whose `valid_from` is on or after the
date, or that have no `valid_from` and were recorded on or after it. Without
`--wing` or `--room`, the whole KG is exported (`"kg_scope": "all"`).

### `--with-embeddings`

Include raw embedding vectors in the JSONL. This makes the file larger (roughly 8–9 KB more per drawer for the default 384-dimension vectors) but allows offline import without re-embedding (the current import path re-embeds regardless — this is for future use).

---

## Airgap / Machine Transfer Scenario

Mined drawers are path-bound: each records the absolute `source_file` it came from, and `mine`
removes stale drawers only under the directory it is mining. If you import a full export and
then mine a project or conversation directory that now lives at a different path, the old-path
drawers stay beside the new ones, even with `mine --full`, and every search hit appears twice.
Move only the non-regenerable content and re-mine every mined source on the target instead:
each project directory with `mine` and each conversation directory with `mine --mode convos`.
A source you do not re-mine loses its drawers, so record the wing inventory first and compare
it on the target.

**On the connected machine:**

```bash
# Every wing; the target must end up with the same list
mempalace-code status | sed -n 's/^  WING: //p' | sort > palace_wings.txt
# Manual drawers, diary entries, and the KG; mined drawers are rebuilt on the target
mempalace-code export --only-manual --with-kg --out palace_manual.jsonl
```

Account for every wing in `palace_wings.txt`. A wing filed by `mine` belongs to one project
directory (its `mempalace.yaml` names the wing), a wing filed by `mine --mode convos` to one
conversation directory, and manual and diary wings come back from the import. Copy
`palace_wings.txt`, `palace_manual.jsonl`, and every project and conversation directory to the
target machine (USB, encrypted transfer, etc.).

When a conversation directory no longer exists (for example, transcripts the client has since
pruned), carry that wing as stored instead and do not mine it on the target:

```bash
# On the connected machine: the wing's drawers exactly as stored
mempalace-code export --wing chats --out palace_wing_chats.jsonl
# On the airgap machine, after importing palace_manual.jsonl
mempalace-code import palace_wing_chats.jsonl
```

**On the airgap machine:**

```bash
# Ensure the canonical FastEmbed model and provenance are cached first
# (fetch-model while online, or copy the cache as docs/OFFLINE_USAGE.md describes)
mempalace-code fetch-model

# Mine every project and conversation directory at its new path, then import
# (re-embeds with the local model)
mempalace-code mine /path/on/target/to/my_app
mempalace-code mine /path/on/target/to/chats --mode convos
mempalace-code import palace_manual.jsonl
# No output means every wing came back
mempalace-code status | sed -n 's/^  WING: //p' | sort | diff -u palace_wings.txt -
```

The `diff` exits non-zero on any difference. A line starting with `-` is a wing whose source
was neither mined nor imported on the target: mine that directory, or import its wing export,
and rerun the comparison. A line starting with `+` is a wing whose name changed: a wing
defaults to the directory name, so mine a renamed directory with its original `--wing` (and a
conversation directory with its original `--extract`).

Use a full export (`export --with-kg` without `--only-manual`) only when the target cannot mine
the sources, or when every project and conversation directory keeps the same absolute path
there; `mine` then recognizes the imported drawers as unchanged. Never combine a full export
with a mine of a moved directory.

The JSONL format is backend-agnostic: JSONL that a 1.13.4-or-earlier install exported from a
ChromaDB palace still imports into LanceDB. Current releases cannot open a ChromaDB palace to
export it; see [Legacy Chroma Palace Recovery Before Upgrade](#legacy-chroma-palace-recovery-before-upgrade).

---

## Export Format Reference

The JSONL file starts with a header line, followed by drawer and KG records:

```jsonl
{"type": "export_header", "version": "1.x.y", "palace_path": "...", "exported_at": "...", "filters": {...}, "drawer_count": 42, "kg_count": 7, "kg_entity_count": 1}
{"type": "drawer", "id": "drawer_notes_decisions_abc123", "text": "...", "wing": "notes", "room": "decisions", "chunker_strategy": "manual_v1", "embedding": null, ...}
{"type": "kg_entity", "id": "alice", "name": "Alice", "entity_type": "person", "properties": {"role": "owner"}, "created_at": "..."}
{"type": "kg_triple", "id": "t_alice_works_on_mempalace_...", "subject": "Alice", "predicate": "works_on", "object": "mempalace", "valid_from": "2026-01-01", "valid_to": null, "extracted_at": "...", ...}
```

`kg_entity` records carry entity types and properties for entities that have
them; import restores them and fills in a type or properties an existing entity
lacks. Import keeps each triple's exported `id` and `extracted_at`.

The header `version` is the mempalace-code package version that wrote the file; import prints a
warning once and proceeds when it differs from the running version.

Import requires a non-empty `text` and non-blank `id`, `wing` (unless `--wing-override`
is given), and `room` on every `drawer` record, and a non-blank `subject`, `predicate`,
and `object` plus valid `valid_from`/`valid_to` dates on every `kg_triple` record. It
skips each record that fails these checks, names it by position and id in a warning,
counts it under `Skipped invalid` or `Invalid KG triples`, imports the valid records,
and then exits non-zero; a dry run reports the same records. Fix the named records and
run the command it prints, which keeps your import options: drawers already imported
are skipped as duplicates, and when every KG triple was imported it adds `--skip-kg`.
When KG triples were rejected, the rerun replays the file's KG records; facts
already stored, open or closed, count under `Skipped KG duplicates` and are not
stored again.
Records of an unknown `type` are ignored with a warning.

The format is human-readable, version-control-friendly, and streamable. You can inspect or edit it with standard text tools.

---

## Tarball Backup (Full Snapshot)

For full binary snapshots (faster, includes everything, not human-readable):

```bash
set -euo pipefail

PALACE="${HOME}/.mempalace/palace"
BACKUP_TAR="${HOME}/.mempalace/recovery-full.tar.gz"
RESTORE_TARGET="${HOME}/.mempalace/restored-palace"
ARCHIVE="${HOME}/.mempalace/archive-to-restore.tar.gz"

: "${PALACE:?set PALACE to the inspected source palace}"
: "${BACKUP_TAR:?set BACKUP_TAR to a new backup artifact path}"
: "${RESTORE_TARGET:?set RESTORE_TARGET to a new restore target}"
: "${ARCHIVE:?set ARCHIVE to the inspected archive being restored}"
test -d "$PALACE/lance"
test ! -e "$BACKUP_TAR"
mempalace-code --palace "$PALACE" backup create --out "$BACKUP_TAR"
tar -tzf "$BACKUP_TAR"
test -f "$ARCHIVE"
tar -tzf "$ARCHIVE"
test ! -e "$RESTORE_TARGET"
mempalace-code --palace "$RESTORE_TARGET" restore "$ARCHIVE"
mempalace-code --palace "$RESTORE_TARGET" health
```

Without `--force`, the CLI refuses when its checks find state in the selected
palace or at the selected KG destination. A real empty palace directory remains
reusable. At publication, restore claims the exact `lance/` name exclusively and
creates the exact KG destination with an atomic no-replace hard link. If either
name is raced in, restore preserves it; a KG publication failure also removes
the Lance root still owned by that invocation. Unsupported hard links fail
closed. This boundary does not make arbitrary concurrent edits elsewhere under
the palace transactional and does not protect concurrent replacement of the
palace root or its ancestors. The safe flow above uses absent destinations so
retries cannot overwrite managed publication names.

`--force` replaces the target's managed `lance/` data and atomically replaces the
selected KG after archive validation. It preserves unrelated entries in a real
palace directory. Symlink objects found at the selected palace, Lance, or KG
validation boundary are replaced without modifying their referents; concurrent
replacement of the palace root or its ancestors remains outside this boundary.
The palace root itself is the exception: when `--palace` names a symlink,
`--force` refuses and prints the resolved path to rerun with, so a restore never
detaches a palace from the volume its symlink points to.

`--force` takes the installation's exclusive operation lease. While an MCP
server, watcher, or other MemPalace process holds a lease, restore refuses and
names that process (`operation=...`, `pid=...`); stop it first, because a
running server would keep writing into the replaced palace. A restore without
`--force` into an absent or empty destination does not need the lease.

`--force` rolls the whole palace back to the archive, discarding later changes in
every wing. To recover only drawers that `compress` rewrote with AAAK before 1.15.0,
use `mempalace-code compress --recover-from <archive>` (preview with `--dry-run`)
instead: it restores only drawers that still hold AAAK text and leaves later writes alone.

A failed restore names the archive and the reason (for example
`invalid_backup_shape: mempalace_backup/lance` or `not a gzip file`) and points
to `tar -tzf <archive>` and `backup list`; a missing archive points to `backup
list` only. An existing directory passed as `--kg-path` is refused before
anything is read. A successful restore prints where it wrote the palace and the
knowledge graph.

Use `--force` only after inspecting the archive and exact destinations, then
creating and inspecting a fresh backup of the current target. If `--kg-path`
selects a KG outside that target, back up that file separately before adding
`--force`:

```bash
set -euo pipefail

ARCHIVE="${HOME}/.mempalace/archive-to-restore.tar.gz"
RESTORE_TARGET="${HOME}/.mempalace/palace"
CURRENT_BACKUP="${HOME}/.mempalace/pre-force-restore.tar.gz"
KG_DEST="${RESTORE_TARGET}/knowledge_graph.sqlite3"

: "${ARCHIVE:?set ARCHIVE to the archive being restored}"
: "${RESTORE_TARGET:?set RESTORE_TARGET to the exact destination}"
: "${CURRENT_BACKUP:?set CURRENT_BACKUP to a new backup path}"
: "${KG_DEST:?set KG_DEST to the selected KG destination}"
test -f "$ARCHIVE"
test -d "$RESTORE_TARGET/lance"
test ! -e "$CURRENT_BACKUP"
printf 'Restore target: %s\n' "$RESTORE_TARGET"
printf 'KG destination: %s\n' "$KG_DEST"
tar -tzf "$ARCHIVE"
mempalace-code --palace "$RESTORE_TARGET" backup create --out "$CURRENT_BACKUP"
tar -tzf "$CURRENT_BACKUP"
mempalace-code --palace "$RESTORE_TARGET" restore "$ARCHIVE" --force
mempalace-code --palace "$RESTORE_TARGET" health
```

### Tarball Restore — KG Destination

When a tarball archive includes `knowledge_graph.sqlite3`, the restore command decides
where to write it based on your invocation:

| Invocation | KG written to |
|------------|---------------|
| `mempalace-code restore FILE` | `<configured palace>/knowledge_graph.sqlite3` |
| `mempalace-code --palace <dir> restore FILE` | `<dir>/knowledge_graph.sqlite3` (palace-scoped) |
| `mempalace-code --palace <dir> restore FILE --kg-path <path>` | `<path>` (explicit override) |
| `mempalace-code restore FILE --kg-path <path>` | `<path>` (explicit override) |

**Important:** Without `--kg-path`, the archived KG data is written next to the
restored palace — never to the legacy global KG — to avoid silently overwriting an
unrelated knowledge graph.

Use `--kg-path` to direct the KG to any other destination, such as a shared location
or a testing path:

```bash
# Restore Lance data to a custom palace, KG to the custom palace (default scoping)
mempalace-code --palace ~/my_palace restore ~/backup.tar.gz

# Override the KG destination explicitly
mempalace-code --palace ~/my_palace restore ~/backup.tar.gz --kg-path ~/shared_kg.sqlite3

# Restore without --palace: palace and KG go to the configured palace
mempalace-code restore ~/backup.tar.gz
```

> **Note:** This tarball restore behavior is separate from JSONL import/export KG
> handling. The `--skip-kg` and `--with-kg` flags documented in the [Restore
> Procedure](#restore-procedure) section above apply to JSONL imports only.

### Scheduled Backups

```bash
mempalace-code backup schedule --freq daily     # prints launchd plist (macOS) or cron line (Linux)
```

Install the printed snippet manually — mempalace-code does not write to system directories.
The launchd job logs each run to `~/Library/Logs/<label>.log` and carries the rendering
shell's `HF_HOME` and `MEMPALACE_*` settings (for example `MEMPALACE_BACKUP_RETAIN_COUNT`) in
`EnvironmentVariables`; the cron line carries them as leading assignments, and cron mails its
output to the account owner. Re-render after changing those settings.

### Backup Kinds

Each backup has a kind that controls its filename prefix and per-kind retention:

| Kind | Prefix | Created by |
|------|--------|-----------|
| `manual` | `mempalace_backup_` | `backup create` (default) |
| `scheduled` | `scheduled_` | `backup create --kind scheduled` / cron |
| `pre_optimize` | `pre_optimize_` | Auto-backup before optimize |
| `pre_watch` | `pre_watch_` | Auto-backup before watcher initial mine |

### Watch Pre-Run Backups

When an existing palace is detected on watcher startup, `mempalace-code watch` (and
`mempalace-code mine --watch`) creates a `pre_watch` archive **before** the initial
incremental mine.  The archive path is printed to stdout:

```
  Pre-watch backup: /path/to/.mempalace/backups/palace/pre_watch_20260101_120000_123456.tar.gz
```

If the archive cannot be created (e.g. disk budget too low), the watcher **exits
immediately** — the initial mine is never run and the palace is not mutated. A Lance file
that another process's commit or cleanup removed while it was being archived is retried
first (up to 3 attempts).

### Startup State Markers

The watcher emits grep-friendly `WATCH_RUN` lines at each startup transition, and when a cycle fails, a project is dropped, or the watcher stops, so that the appended daemon log can be searched to determine the state of any startup attempt. A job rendered by `watch <root> schedule` logs to `~/Library/Logs/<label>.log` (`watch <root> status` prints the path); a job rendered by a release before 1.15.0 (label `com.mempalace.watch`) logs to `/tmp/mempalace-watch.log`.

| State line | Meaning |
|-----------|---------|
| `WATCH_RUN run_id=<id> state=run-started` | Daemon startup began |
| `WATCH_RUN run_id=<id> state=preflight-failed` | The watch root failed validation (the preceding `Error:` names the recovery command); nothing was backed up or mined |
| `WATCH_RUN run_id=<id> state=preflight-failed reason=already-watched` | Every project is already watched into this palace by another watcher; nothing was backed up or mined |
| `WATCH_RUN run_id=<id> state=pre-watch-backup-failed` | Pre-watch backup failed; daemon exited before mine |
| `WATCH_RUN run_id=<id> state=initial-mine-started` | Initial mine is running |
| `WATCH_RUN run_id=<id> state=initial-mine-completed` | Initial mine finished successfully |
| `WATCH_RUN run_id=<id> state=initial-mine-failed` | Initial mine failed (the preceding `Error` line names the cause); daemon exited 1 |
| `WATCH_RUN run_id=<id> state=degraded` | A fresh probe of the palace head failed after a storage error; the watcher exited with recovery commands and rolled nothing back (see [Degraded Startup Recovery](#degraded-startup-recovery)) |
| `WATCH_RUN run_id=<id> state=initial-mine-skipped reason=disk-budget` | Mine skipped because disk budget is too low |
| `WATCH_RUN run_id=<id> state=initial-mine-skipped reason=no-valid-sources` | Every source candidate was rejected as a non-regular entry; no pre-watch backup or initial mine ran |
| `WATCH_RUN run_id=<id> state=optimize-completed` | Post-mine optimize pass succeeded |
| `WATCH_RUN run_id=<id> state=optimize-skipped reason=safety-check` | Safe optimize refused or failed; see the preceding storage log for the precise cause |
| `WATCH_RUN run_id=<id> state=optimize-skipped reason=error` | Optimize raised an unexpected error; the preceding optimize line contains the cause |
| `WATCH_RUN run_id=<id> state=watch-ready` | Daemon entered the watch loop; inspect earlier markers for startup work that was skipped |
| `WATCH_RUN run_id=<id> state=cycle-failed wing=<wing>` | One re-mine failed (the preceding `Error` line names the cause); the watcher keeps running and retries on the next change |
| `WATCH_RUN run_id=<id> state=cycle-skipped wing=<wing> reason=palace-busy` | Another writer held the palace write lease past the wait (the preceding `Waiting for another MemPalace writer` and `Skipped` lines name it); the watcher keeps running and mines on the next change |
| `WATCH_RUN run_id=<id> state=interrupted stage=startup` | SIGTERM, SIGHUP, or Ctrl-C arrived during the pre-watch backup or initial mine; the watcher released its leases and exited 0. Restart it to finish the initial mine (incremental mining resumes). A stop that arrives while a mine runs prints `Stop requested; finishing the current batch before exiting...` as soon as Python regains control from native embedding code, before the batch flush completes |
| `WATCH_RUN run_id=<id> state=project-dropped wing=<wing> reason=<reason>` | The project was `removed` (or moved), `uninitialized` (its `mempalace.yaml` is gone), or `not-git` (commit mode); it is no longer watched and its drawers stay in the palace |
| `WATCH_RUN run_id=<id> state=stopped reason=no-projects` | No watched project remains; the watcher exited 1 |
| `WATCH_RUN run_id=<id> state=stopped reason=signal` | SIGTERM, SIGHUP, or Ctrl-C stopped the watch loop cleanly (after any cycle in flight finished); the watcher exited 0 |
| `WATCH_RUN run_id=<id> state=stopped reason=watch-failed` | The file-watch backend could not watch a path that still exists; the watcher exited 1 |

For either `optimize-skipped` reason, the initial mine completed but optimization did not.
The watcher continues. Inspect the preceding optimize output, then run
`mempalace-code --palace /path/palace health`; if it recurs, resolve that reported storage
error before restarting.

The `run_id` is unique per startup attempt. An appended log file may contain `WATCH_RUN` lines from older runs that exited with disk-budget or backup failures. To find the latest healthy startup, locate the last `state=watch-ready` line and use its `run_id` to filter the associated transitions:

```bash
# LOG is the job log path that `mempalace-code watch <root> status` prints.
# Find the latest run that reached watch-ready
grep -a 'state=watch-ready' "$LOG" | tail -1
# WATCH_RUN run_id=20260616T120102Z-p12345 state=watch-ready

# See all transitions for that startup (replace the run_id from above)
grep -a 'run_id=20260616T120102Z-p12345' "$LOG"
```

If `state=pre-watch-backup-failed` appears for the current `run_id`, the daemon exited before modifying the palace. See [Degraded Startup Recovery](#degraded-startup-recovery) for next steps.

### Degraded Startup Recovery

If the initial mine (or a later re-mine) fails with a Lance storage error — a missing
fragment or a commit conflict — the watcher first reopens the store and probes the latest
palace version through a fresh handle. It never restores a shared palace to an older
version on its own: a table-wide rollback would discard every commit other watchers,
miners, or MCP servers made after that version.

1. If the palace head passes its read probes, the error came from another process writing
   the same palace (for example its cleanup removed a fragment that a stale handle still
   referenced). The watcher prints `Transient storage error ... No rollback is performed.`
   and retries on the fresh handle, up to 3 attempts.
2. If the error persists while the head stays readable, startup exits 1 with
   `initial mine failed` (`state=initial-mine-failed`); in the watch loop the cycle is
   reported (`state=cycle-failed`) and the watcher keeps running.
3. If the fresh probe of the head fails, the palace itself is unreadable. The watcher prints
   `DEGRADED`, the failing probes, and `WATCH_RUN ... state=degraded`, then exits **before
   watching** (or stops watching) and prints operator-safe recovery commands:

```
  To diagnose and recover, run:
    mempalace-code --palace /path/palace health
    mempalace-code --palace /path/palace repair --rollback --dry-run
```

Stop the other processes that write this palace before any rollback or restore.

The watcher may also print a `restore --force` suggestion for its `pre_watch`
tarball. Do not run that suggestion
directly. Set its palace as `RESTORE_TARGET`, set the tarball as `ARCHIVE`, and
follow the inspected force-restore procedure in [Tarball Backup](#tarball-backup-full-snapshot).

### Auto-Backup Before Optimize

Enabled by default. Every `mempalace-code mine` creates a backup before compacting storage:

```
~/.mempalace/backups/palace/pre_optimize_YYYYMMDD_HHMMSS_ffffff.tar.gz
```

To disable: set `auto_backup_before_optimize: false` in `~/.mempalace/config.json` or `MEMPALACE_AUTO_BACKUP_BEFORE_OPTIMIZE=0`.

### Retention (automatic pruning)

**`pre_optimize` archives are bounded by default** to the newest 5.  A long-running
`mempalace-code watch` daemon creates one archive before every compaction, so without a
bound the `backups/` directory can fill the local volume even when the palace itself
is small.

**`pre_watch` archives are bounded by default** to the newest 5. The watcher creates one before
each startup's initial mine when an existing palace is present.

**`scheduled` archives are bounded by default** to the newest 14.  Cron and launchd
jobs create one archive per run, so without a bound the `backups/` directory
accumulates archives indefinitely.

**`manual` archives are unbounded by default** — they are never pruned unless you
set `backup_retain_count` explicitly.

```bash
# Override the implicit pre_optimize, pre_watch, and scheduled bounds with an explicit limit for all kinds:
export MEMPALACE_BACKUP_RETAIN_COUNT=10
# Or in ~/.mempalace/config.json:
# {"backup_retain_count": 10}

# Deliberate keep-all opt-out — disables pruning for every kind, including pre_optimize and pre_watch:
export MEMPALACE_BACKUP_RETAIN_COUNT=0
```

Each palace has its own managed backups directory, `<palace_parent>/backups/<palace_name>/`
(the default palace `~/.mempalace/palace` uses `~/.mempalace/backups/palace/`). Retention prunes
**only that directory**, so palaces that share a parent directory never prune each other's
archives. Archives written with explicit `--out` paths are never pruned, and `backup create
--out` never overwrites an existing file. Each archive's `metadata.json` records the absolute
`palace_path` it was taken from.

Archive publication uses an atomic hard link to keep concurrent archives intact.
If the destination filesystem refuses hard links, `backup create` fails with exit 1
and a message to choose a backup directory on a filesystem that supports hard links.
It removes its temporary archive and skips retention pruning. Existing archives are
preserved; the command never falls back to a rename that can replace another archive.

Releases before 1.15.0 wrote every sibling palace's archives into the shared
`<palace_parent>/backups/` directory. `backup list` still shows those archives with the
`shared` flag, because they may belong to another palace: check their wings (or `backup list
--json`) before restoring one. Retention never deletes them; move or remove them yourself.

`backup list` prints `stale` in its FLAGS column for would-be-pruned archives, `oversized` for
archives larger than `MEMPALACE_BACKUP_WARN_SIZE_BYTES`, and `degraded` for snapshots of a
damaged palace. `backup list --json` prints the same entries as JSON.

`backup create` refuses, with exit 1 and no archive, when there is nothing to back up: a
missing path, an empty directory, a directory whose first mine failed, or a legacy ChromaDB
palace (see [Legacy Chroma Palace Recovery](#legacy-chroma-palace-recovery-before-upgrade)).
A palace whose drawers cannot all be read, or whose knowledge graph fails SQLite's
`quick_check` (`health` reports `kg_corrupt`), is still archived as a forensic copy named
`*_DEGRADED.tar.gz`, with `degraded: true` and the reason (`kg_corrupt: ...` for the KG) in
its metadata; the command warns and exits 1. `restore` refuses such an archive, naming it a
forensic copy, and also refuses an older archive whose knowledge graph fails `quick_check`
(`invalid_kg_payload`). Degraded archives are counted and pruned separately, so they never
push a healthy backup out of retention. When retention deletes older archives, `backup
create` prints how many.

When a miner or watcher writes while an archive is being written, the snapshot could
mix table versions or lose files. Lance temporary files are skipped. If a committed file
vanishes, or a new table version is committed before the archive is complete, the archive
is discarded and rebuilt (up to three attempts), so a published archive always holds the
version its `metadata.json` counts. After three attempts the command fails with a message
to retry when writers are idle.

After a successful optimize and readability check, MemPalace also runs
best-effort verified Lance cleanup so future backups do not keep archiving stale
table versions. That cleanup keeps every version that was current within the last
minute, so another process still reading the palace keeps its data files. The next
mine that starts more than a minute later prunes them before it writes, so its
pre-optimize backup does not carry them. That step only prunes: it never compacts, it
is skipped when drawers were added or deleted since the last optimize (the backup then
comes first), and it does nothing when `optimize_after_mine` is off.
`mempalace-code cleanup --older-than-days 0` reclaims them at any time; a plain
`cleanup` keeps every version younger than 7 days. Optimize and cleanup verification
re-opens the Lance table, so it checks the same fresh-handle path the next CLI, MCP
server, or watcher process will use. Manual `cleanup` remains the recovery tool for older
installations that already accumulated stale versions or for emergency disk
recovery.

### Disk-budget quick setup

To change the backup disk floor:

```bash
export MEMPALACE_BACKUP_DISK_MIN_FREE_BYTES=2GiB    # require 2 GiB projected free after backup
# Legacy alias still accepted:
export MEMPALACE_BACKUP_MIN_FREE_BYTES=2GiB
```

The guard is enabled by default through `disk_min_free_bytes` (1 GiB). See the
full [Disk-Budget Guard](#disk-budget-guard) section below for precedence and
failure behavior.

### Emergency cleanup

If the backups directory has grown large, inspect with:

```bash
mempalace-code backup list
```

Then delete old archives manually, or set `MEMPALACE_BACKUP_RETAIN_COUNT` to let future backups prune automatically.
With current defaults, future managed `pre_optimize` and `pre_watch` backups keep the newest 5
each and managed `scheduled` backups keep the newest 14; `manual` backups stay
unbounded unless you set an explicit retain count.

If LanceDB stale versions/fragments are the problem rather than backup archives,
run storage cleanup only after stopping MemPalace watchers, miners, maintenance
commands, and MCP servers. `cleanup` takes the exclusive operation lease and refuses,
naming the process, while another MemPalace process (an MCP server or a watcher, for
example) holds the operation lease. Preview first; removed versions
are no longer available to `repair --rollback`:

```bash
mempalace-code cleanup --older-than-days 7 --dry-run  # list versions and bytes; change nothing
mempalace-code cleanup --older-than-days 7
mempalace-code cleanup --unsafe-now  # emergency only; no MemPalace process may be running
```

`--older-than-days` must be 0 or greater; `0` removes every older version no live
reader can still be on and warns that rollback history goes with it. The reader grace
keeps versions that were current within the last minute, and versions committed within
a second before the newest of those once compaction commits newer ones; the dry run
lists exactly those as `Kept for live readers` (`versions_kept_for_readers` in JSON),
and the real run reports how many it kept. Run cleanup again after a minute to remove
them. After a failed cleanup the reported
`version_count_after` is re-read from disk (or `unknown`), never a placeholder.

---

## Health Check and Repair

A damaged palace is never reported as empty. When stored drawers cannot be read,
`search`, `read`, `status`, `wake-up`, and `export` exit 1 with
`stored drawers in <palace> are unreadable (palace degraded)` and the exact
`health` and `repair --rollback --dry-run` commands for that palace, then `repair`
and `backup list` for when nothing can be rolled back; MCP search
returns the same error. `export` writes no file in that case, so a 0-drawer export
is never mistaken for a backup.

```bash
PALACE="${HOME}/.mempalace/palace"
mempalace-code --palace "$PALACE" health         # probe drawers and the knowledge graph
mempalace-code --palace "$PALACE" health --json  # machine-readable report (JSON on errors too)
```

`health` runs three Lance probes (manifest, fragment data, metadata scan) and a
SQLite `quick_check` of `<palace>/knowledge_graph.sqlite3`. The check opens the
knowledge graph read-only; SQLite may leave its usual `-shm` and `-wal` side files
next to it. A path without a drawer table reports `No palace found` and exits 1;
when an earlier mine left `lance/` without drawers, the next step names
`mempalace-code fetch-model` (a missing embedding model is the usual cause). Every
`Next:` line repeats `--palace <path>`.

If the drawer store is degraded, preview a rollback first. Rollback probes the
current version before anything else, so a healthy palace is left unchanged:

```bash
mempalace-code --palace "$PALACE" repair --rollback --dry-run  # candidate, rows now/after/lost
mempalace-code --palace "$PALACE" repair --rollback            # roll back to that version
```

Rollback uses LanceDB's version history to find the most recent version that passes
every probe. Data added after that version is lost, and the preview shows how many
rows. It never falls back to a full rebuild.

When no healthy version exists, restore an archive or rebuild:

```bash
mempalace-code --palace "$PALACE" backup list  # pre_optimize, pre_watch, scheduled archives
mempalace-code --palace "$PALACE" repair       # full rebuild; stops if any drawer is unreadable
```

The full rebuild reads every drawer before it changes anything. At the first
unreadable drawer it exits 1 and leaves the palace unchanged. Restore an archive
then, or accept the loss explicitly with `repair --salvage`, which reads the rest row
by row, rebuilds from the readable drawers, and reports how many were not carried
over (its time grows with the number of unreadable drawers). If another process
writes to the palace while repair runs, repair also stops without changing anything,
so a write can never be dropped from the rebuilt table. A rebuild replaces only `lance/`: it reuses the stored text,
metadata, and vectors (no embedding model needed) and keeps
`knowledge_graph.sqlite3`, `.mempalace/`, and other files in place. The pre-repair
palace is saved to a new `<palace>.backup-<UTC timestamp>` directory; an existing
backup directory is never deleted or overwritten.

If `health` reports only `kg_corrupt`, the drawers are fine: keep a copy of the
corrupt `knowledge_graph.sqlite3`, then restore the knowledge graph from an archive
listed by `backup list` without the `degraded` flag (restore it into a scratch palace
with `--kg-path`, and move that file into place while no MemPalace process runs; a
`restore --force` over this palace would replace its drawers too). If no archive holds
a healthy knowledge graph, move the corrupt file aside and re-mine each project with
`mine <dir> --full`, which rebuilds the mined facts; facts added through MCP are lost.
`mine` checks the knowledge graph before it changes any drawer, so a corrupt or
read-only knowledge graph stops it with the palace unchanged.

`repair`, `repair --rollback`, and `cleanup` take the exclusive operation lease and
refuse, naming the process, while another MemPalace process (an MCP server or a
watcher, for example) holds the operation lease; stop those processes, and any
running `mine`, first. Previews (`--dry-run`) run without the lease.

### File permissions

Palace directories that MemPalace creates (by `mine`, `mine --mode convos`, diary
and MCP writes, or `restore` into a new path) are owner-only (`0700`), like the
managed backups directory and its `0600` archives, because drawers hold verbatim
notes and transcripts. An existing directory keeps the permissions you gave it.
MemPalace does not change permissions of an existing palace, `~/.mempalace/`,
`config.json`, or JSONL exports; for a palace outside your home directory or an
export you keep, restrict them yourself:

```bash
chmod 700 "$PALACE" "${HOME}/.mempalace"
chmod 600 recovery-manual.jsonl
```

---

## Disk-Budget Guard

`backup create` checks available disk space before opening any file handles. If the projected post-backup free space would fall below the configured floor, the command exits with an error and **no archive or temp file is written**.

```
Error: disk budget: not enough free space to create backup.
Free: 450.0 MiB, required floor after archive: 1.0 GiB.
Palace: /Users/you/.mempalace/palace.
Free up disk space or lower disk_min_free_bytes (1 GiB default).
```

The last sentence names the setting that actually set the floor, for example
`MEMPALACE_BACKUP_DISK_MIN_FREE_BYTES` or `backup_disk_min_free_bytes in
/Users/you/.mempalace/config.json`.

The projection is conservative: it assumes the archive size equals the uncompressed palace + KG size. Actual compressed archives are usually smaller, but the guard refuses when even the worst-case estimate would leave insufficient headroom.

### Configuring the backup floor

```bash
# Preferred environment variable
export MEMPALACE_BACKUP_DISK_MIN_FREE_BYTES=2GiB

# Legacy alias accepted for existing installs
export MEMPALACE_BACKUP_MIN_FREE_BYTES=2GiB
```

Or set the byte value (2 GiB here) in `~/.mempalace/config.json`, which must be plain JSON
without comments:

```json
{
  "backup_disk_min_free_bytes": 2147483648
}
```

The backup floor resolves as:

1. `MEMPALACE_BACKUP_DISK_MIN_FREE_BYTES`
2. legacy `MEMPALACE_BACKUP_MIN_FREE_BYTES`
3. `backup_disk_min_free_bytes` in `~/.mempalace/config.json`
4. legacy `backup_min_free_bytes` in `~/.mempalace/config.json`
5. the global floor: `MEMPALACE_DISK_MIN_FREE_BYTES`
6. the global floor: `disk_min_free_bytes` in `~/.mempalace/config.json`
7. **1 GiB default**

Every level accepts a plain byte count or a size suffix (`2GiB`, `500MB`). A value
that cannot be parsed is not silently replaced by the default: a one-line
`Warning: ignoring ...` on stderr names it, and resolution continues with the next
level. `MEMPALACE_BACKUP_WARN_SIZE_BYTES` / `backup_warn_size_bytes` accept the same
values.

### Emergency cleanup

If the backup guard refuses because disk is nearly full:

1. Check what is taking space:
   ```bash
   du -sh ~/.mempalace/palace ~/.mempalace/backups
   ```
2. List existing backups and remove stale ones manually if immediate space is needed:
   ```bash
   mempalace-code backup list
   ls -lh ~/.mempalace/backups/palace/
   rm ~/.mempalace/backups/palace/<stale_archive>.tar.gz
   ```
3. Re-run the backup once enough space is freed.

### Relationship to watcher thresholds

The watcher (`mempalace-code watch`) uses its own `watch_disk_min_free_bytes` threshold (also defaults to 1 GiB via `disk_min_free_bytes`). Set `disk_min_free_bytes` once to control both:

```json
{
  "disk_min_free_bytes": 1073741824
}
```

Or set them independently to give the watcher a tighter budget:

```json
{
  "disk_min_free_bytes": 1073741824,
  "watch_disk_min_free_bytes": 2147483648,
  "backup_disk_min_free_bytes": 1073741824
}
```

---

## Legacy Chroma Palace Recovery Before Upgrade

Current releases contain no ChromaDB dependency or migration bridge. A legacy
palace with `chroma.sqlite3` fails closed without modifying the source, marker,
destination, backup, or archive.

Create and verify a separate source backup before upgrading. Then run the last
public bridge release in an isolated `uvx` environment:

```bash
uvx --python 3.12 --from 'mempalace-code[chroma]==1.13.4' mempalace-code migrate-storage SRC DST --verify
```

`--python 3.12` selects an interpreter with prebuilt wheels for the bridge's ChromaDB
dependencies (uv downloads one if needed); on Python 3.13 or later they must be compiled from
source. The bridge installs a pre-1.0 `chromadb` release with published advisories against the
ChromaDB server. Run it once, locally, and never start a Chroma server from that environment.

Inspect the destination and retain the source backup until the LanceDB palace has
passed `mempalace-code --palace DST health`. Re-running a current-version
`migrate-storage` invocation only prints the retirement recovery message and exits
nonzero; it performs no filesystem reads or writes.

---

## Remote Mirror Risk

Managed backups and Lance cleanup protect **local** palace state. They do not protect
against a separate class of operator risk: delete-mode file mirroring between independent
hosts (`rsync --delete`).

When `rsync --delete` syncs a whole MemPalace state directory from one host to another,
it removes files on the destination that are absent on the source. If the destination host
holds **remote-owned** drawers, diary entries, or KG triples that were never synced back
to the source, those are permanently deleted — even though local backups and Lance cleanup
are healthy.

### Why managed backups do not protect against this

- Backups archive the **source** palace. A delete-mode mirror of the source removes content
  from the **destination** that the source never knew about.
- Backup retention and Lance cleanup run on the source; they have no visibility into remote
  state or what `rsync --delete` will remove on the destination.

### Safe rsync with recommended excludes

If you must mirror the palace state directory between hosts, exclude the live palace data,
the full palace copies `repair` (`palace.backup-<UTC>/`) and the rebuild workflow
(`palace.quarantine-<UTC>/`) leave beside it, the KG database, config, and managed backups
directory so a delete sweep cannot remove remote-owned content. The legacy-KG adoption marker
records a host-local file state, so exclude it too:

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

Add `--exclude='*.log'` if you route MemPalace watch logs into the state directory
(by default, watch daemon logs go to `~/Library/Logs/` and do not need excluding).

### Preflight check before installing a mirror job

Before installing a launchd or cron mirror job, run the preflight command to verify your
rsync invocation is safe (the command is inspected only — it is never executed):

```bash
mempalace-code preflight mirror --command \
  "rsync -a --delete --exclude=palace/ --exclude='palace.backup-*/' \
   --exclude='palace.quarantine-*/' --exclude=knowledge_graph.sqlite3 \
   --exclude=knowledge_graph.sqlite3.adopted --exclude=config.json --exclude=backups/ \
   ~/.mempalace/ user@host:.mempalace/"
# OK
#   warning: advisory: no --exclude for 'logs' (add --exclude='*.log' if you route MemPalace logs into the state directory)

mempalace-code preflight mirror --command "rsync -a --delete ~/.mempalace/ user@host:.mempalace/"
# BLOCKED [delete-mode-state-mirror-missing-excludes]
#   missing exclude: palace
#   missing exclude: kg
#   missing exclude: config
#   missing exclude: backups
#   missing exclude: repair-backups
#   missing exclude: quarantines
#   warning: advisory: no --exclude for 'logs' (add --exclude='*.log' if you route MemPalace logs into the state directory)
#   warning: advisory: no --exclude for 'adopted' (add --exclude=knowledge_graph.sqlite3.adopted; the legacy-KG adoption marker records host-local state)
```

The check covers every rsync deletion form (`--delete`, its `--del` alias, and the
`--delete-*` variants), blocks `--remove-source-files` from the state directory or a palace,
and compares path arguments with the configured palace (`palace_path`, `MEMPALACE_PALACE_PATH`,
or the global `--palace`), so a delete-mode mirror of a palace outside `~/.mempalace`, or of a
directory that contains it without excluding it, is `BLOCKED [delete-mode-palace-mirror]`.
A delete-mode mirror of a parent of the state directory, such as `~/`, is checked for the same
families under `.mempalace/` (for example `--exclude=/.mempalace/palace/` or
`--exclude=/.mempalace/`) and is `BLOCKED [delete-mode-state-mirror-missing-excludes]` when one
is missing.
`--filter='- PATTERN'` and `-f` exclude rules count like `--exclude`. rsync applies the first
matching rule, and the preflight cannot read `--exclude-from`, `--include-from`, or merge files,
so a family protected only by such a file, or by an exclude placed after an include or merge
rule, is reported as `UNVERIFIED [unverifiable-filter-rules]` (exit 1). An rsync that runs after
another command, such as `cd ~ && rsync ...`, is classified with its own arguments. A verdict its
own arguments already prove wins: a relative path that names `.mempalace` is still checked for
the state-directory excludes, so `cd ~ && rsync -a --delete .mempalace/ host:.mempalace/` without
them is `BLOCKED [delete-mode-state-mirror-missing-excludes]`. Otherwise it is reported
`UNVERIFIED [unverifiable-compound-command]` (exit 1) when it deletes or removes source files
and a local path is relative (not starting with `/`, `~`, or `$HOME`) or an earlier command
assigns `HOME`, because the earlier command could change what the path means; inspect the rsync
command itself with absolute paths. `--remove-sent-files` counts like `--remove-source-files`.

Use `--json` for automation scripts that parse the result; it adds `unverified_excludes`.

### Recommended alternative: export/import instead of whole-state mirrors

Whole-state mirrors transfer regenerable code-chunked drawers along with the irreplaceable
manual content. A safer cross-host transfer uses the export/import flow:

```bash
# On source host: export only manual drawers and KG (non-regenerable content)
mempalace-code export --only-manual --with-kg --out ~/transfer.jsonl

# Copy the JSONL to the destination host, then import
mempalace-code import ~/transfer.jsonl
```

This preserves remote-owned content on both sides and avoids delete-sweep risk entirely.

---

## Related

- Upstream data loss context: issue #469 in the original ChromaDB-based fork
