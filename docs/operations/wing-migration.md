# Disposable wing migration runner

Status: installed maintenance operator for synthetic qualification, owner-authorized isolated-copy
qualification, and an exact-host live merge with retained recovery evidence.

The runner coordinates existing LanceDB, knowledge-graph, project-marker, tiny-hash,
and operation-lock owners. It changes only the `wing` field of inventoried Lance rows,
updates sealed eligible `in_project` triples in place, merges the two tiny-hash maps,
and activates the copied project marker. It never exports, imports, embeds, adds, upserts,
deduplicates, regenerates IDs, starts a watcher, or edits an original host.

## Current authority and invocation

The only standalone qualification command is:

```bash
mempalace-code wing-migration qualify --mode synthetic
```

It creates one private disposable fixture, runs inventory, snapshot, a real source-wing mine,
pre-activation installed-runtime resolver and synthetic destination no-op proof, apply, and idempotent retry
checks, emits a sanitized JSON report, and removes the successful fixture at command exit. The
report has `synthetic_only: true`. It cannot approve a full-copy rehearsal or live rollout.
Synthetic qualification requires the prepared canonical MiniLM cache selected by `HF_HOME` (or the
default Hugging Face cache). The runner refuses before creating a receipt or migration runtime when
that cache is absent or invalid. The runner copies only the validated canonical cache into the
disposable fixture and points every synthetic baseline and runtime subprocess at that independent
copy. Each subprocess forces
`HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1`, even when the parent environment clears or
overrides them. The external cache remains read-only authority: the runner seals its file content
and stable filesystem metadata before and after copying, verifies the same seal around every
subprocess, and checks it again immediately before marker activation.

An owner-authorized isolated full copy is qualified only through the exact private inventory named
by the environment:

```bash
export WING_MIGRATION_INVENTORY_PATH=/absolute/private/full-copy-inventory.json
mempalace-code wing-migration qualify --mode full-copy
```

Supplying `--inventory` is optional and provides only an equality guard: it must resolve to the
same file selected by `WING_MIGRATION_INVENTORY_PATH`. Selection and mode-0600 regular-file checks
run before a receipt, snapshot, lock, runtime artifact, or report is created. Public output contains
fixed predicates; paths, inventory values, measured counts, runtime diagnostics, source content,
the recovery command, and the retention deadline remain in private evidence.

The receipt-bound fixture actions are:

```bash
mempalace-code wing-migration inventory --inventory /absolute/disposable/inventory.json --receipt /absolute/disposable/receipt.json
mempalace-code wing-migration snapshot --receipt /absolute/disposable/receipt.json
mempalace-code wing-migration apply --inventory /absolute/disposable/inventory.json --receipt /absolute/disposable/receipt.json
mempalace-code wing-migration classify --receipt /absolute/disposable/receipt.json
mempalace-code wing-migration recover --inventory /absolute/disposable/inventory.json --receipt /absolute/disposable/receipt.json
```

An authorized live merge is one command:

```bash
mempalace-code wing-migration live-run --authority /absolute/private/live-authority.json
```

The mode-0600 authority names the exact host, source and destination wings, canonical palace,
configuration, operation lock, both KG candidates, project marker, a fresh evidence root, a future
retention deadline, and the retained full-copy qualification report with its SHA-256, inventory
seal, and qualified runner hash. It must set `scope` to `single_host_live_wing_merge`, set both
`live_mutation` and `mcp_downtime` to true, contain the owner's approval, and name the exact
operation as `merge wing SOURCE into DESTINATION`. The operator rejects a non-canonical palace,
configuration, lock, tiny-hash path, KG inventory, reused evidence root, different host, changed
qualification report, missing recovery space, target replacement, collision, or active non-MCP
client before its first data write.

The live command writes a maintenance marker before stopping this user's installed MemPalace MCP
stdio processes. Every newly started MCP server checks that marker and then holds a shared
operation lease for its lifetime; the live operator uses the exclusive lease. The marker contains
one recovery command and remains after any hard interruption. During admission that command proves
that no receipt and no live write exist before clearing the marker. After receipt publication it
uses the private retained runner; an unsnapshotted receipt must still match its complete zero-write
preimage, while a snapshotted receipt follows normal recovery.
Successful apply proves the exact merged state, runs the installed CLI mine against the original
project path with the sealed live configuration, requires the destination wing and zero drawer
writes, admits only semantic tiny-hash formatting and bounded KG refresh, seals the resulting postimage,
and removes the marker. Receipt-bound recovery restores the full snapshot, verifies the logical
preimage and Lance bytes, and then removes the marker. Clients reconnect through their normal host
supervisor after the marker disappears.

Each result states the observed state, authority, and allowed action. Full-copy stdout contains
only fixed action/state/status/authority/allowed-next-action fields and never exposes private
paths, counts, runtime identity, or receipt contents. A refusal for full-copy, unavailable, or
malformed private evidence keeps
the same sanitized boundary and directs the operator to private evidence. A valid synthetic
receipt retains its exact receipt-bound recovery command so synthetic operators can recover it.
`apply` accepts only `original` state with a proved snapshot, or an exact `merged` retry that
performs zero writes. `recover` accepts only a sealed `partial` or `merged` state. Unknown state
remains untouched. The runtime `zero_drawer_writes` predicate applies only to the synthetic
no-op proof; full-copy qualification uses its measured source/destination row and filed-drawer
counts.

## Inventory contract

Every JSON inventory has version `1`, `disposable: true`, a random `fixture_id`, and absolute paths
for `fixture_root`, `palace`, `project_root`, `marker`, `configuration`, `tiny_hashes`, `lock`,
`snapshot_root`, `runtime_root`, `evidence_root`, and every `kg_candidates` entry. It also names
distinct non-empty `source_wing` and `destination_wing`. The fixture root contains
`.wing-migration-fixture.json` with exactly:

```json
{"disposable": true, "fixture_id": "the-same-random-id"}
```

The inventory, receipt/evidence, snapshot, runtime, palace/Lance, project/marker, configuration,
sidecar, physical KGs, home, and lock must all remain inside that root and obey their sealed
disjointness graph. The receipt must be inside `evidence_root`; a receipt under palace or Lance is
rejected before creation. Marker-in-project and Lance/sidecar/local-KG-in-palace are the only
intentional containment edges. Symlinks, hard-linked private files, changed fixture identity,
unaccounted lock owners, target aliases, insufficient recovery space, malformed sidecars,
collisions, incomplete KG candidate inventory, configuration drift, and preimage drift fail before
migration writes. An intentionally identical physical KG candidate may appear twice; the receipt
records the alias and processes it once.

The recovery-space gate requires the larger of the inventoried minimum and twice the active
fixture working set plus 1 MiB. The working set includes the current project, palace, snapshot, and
other active fixture files. It excludes the immutable runtime, retained historical snapshots, and
retained evidence tree: their existing bytes already reduce reported free space, and migration and
recovery never duplicate them.

The inventoried `operation.lock` and adjacent `operation.lock.metadata.lock` are stable lock
anchors. Owner preparation must create both as mode-0600 regular, single-linked files before
sealing the inventory. The runner never replaces or removes either anchor, including refusal
cleanup, so every contender coordinates through the same inodes. Disposable synthetic and
descendant fixture construction creates the anchors before its first fence.

A full-copy inventory is identified by its private `authority` object. It has an absolute
`logical_source_root` distinct from `project_root`, a positive `lance_batch_size`, and these
fail-closed authority values:

```json
{
  "scope": "isolated_full_copy_only",
  "live_mutation": false,
  "watcher_restart": false,
  "fixture_process_authority": "acquire fixture lock and stop only fixture-owned subprocesses",
  "retention_rule": "retain through deadline and until verified recovery or owner disposition, whichever is later"
}
```

The same object names distinct original and qualification hosts, explicit owner approval, all
original paths excluded from mutation, and the future UTC `retention_deadline`. The qualification
host must equal the current host name. Logical provenance paths are absolute, reject dot
components, and are compared by lexical path components; the runner never resolves or accesses
the original root.
Every full-copy inventory also has a `retained_snapshot_roots` object that maps at most one retained
root to its exact historical receipt path. Use an empty object for the first attempt. The root must be
an absolute, existing, symlink-free private directory inside the fixture root and must be pairwise
disjoint from every current migration owner. Each receipt must be a private mode-0600 file in the
current evidence root, have a valid self-seal and an older receipt version, bind the same fixture,
evidence, and snapshot roots, and contain the exact private root-bound `manifest.json`. Admission
therefore proves every exclusion against receipt-bound historical evidence. The inventory authority
seal binds the complete map. The unrelated-file scan prunes the current evidence, runtime, active
snapshot, and proven retained snapshot roots before traversal. It still hashes every ordinary
copied-repository file, so an unrelated project change remains a blocking drift.
`copy_verification` records a zero-difference checksum dry run, its method, `source_host`, stable
`source_filesystem_id`, `source_snapshot_id`, absolute source snapshot root, source-device
diagnostic, qualification device, and exact device, inode, size, and modification time for the
copied palace and repository roots. Host, filesystem, and snapshot identity establish provenance;
numeric device inequality across hosts is only diagnostic. Its `source_preimage_sha256` binds the owner's complete logical
SQLite/Lance/configuration/sidecar/unrelated-file preimage to the admitted copy. Admission
recomputes those facts, requires both KG candidates as private regular files on the qualification
device, and seals a physical-location-normalized copied preimage. Admission reads SQLite main/WAL
bytes into an in-memory image, validates WAL salts and checksums, and never opens the admitted
database or touches SHM. A reused WAL may contain a complete current generation followed by
retained frames from an older generation; the runner accepts the current frames and ignores that
stale tail while still rejecting truncated current-generation frames. Every mutation fence
rechecks stable copy roots, parent authority,
preimages, and readers/writers. `runtime_authority` names the original version/interpreter, exact
qualification interpreter, runtime prefix, module and distribution origins, package and
distribution hash maps, offline model-cache path and seal, source commit, source
`pyproject.toml` hash, and runner hash. Admission compares this owner-sealed static identity before
running a `-B -I` import probe. Full-copy mode uses the installed runtime directly and never builds
a substitute from the checkout.

Stored Lance and KG eligibility uses `logical_source_root`; filesystem access and runtime probes
use `project_root`. The runtime probe works only on a disposable descendant copy of that copied
repository. Private evidence records measured source/destination row counts before and after the
probe plus both filed-drawer counts. All six measurements must be non-negative integers;
`source_rows_before` and `source_filed_drawers` must be positive, source filed drawers cannot
exceed source rows, `source_rows_after` must be zero, and the destination row delta after the
measured relocation must be non-negative. A zero destination filed-drawer count requires a zero
new-row delta; a positive filed-drawer count requires a new-row delta at least as large as that
count. Missing, negative, impossible, or inconsistent measurements refuse qualification.
Relocated full-copy mining may file drawers; zero filed drawers is valid only when the measured
destination row delta proves that run was a no-op. The probe does not treat relocated stored paths
as evidence for an original-path no-op.

Each installed-runtime mine has a bounded timeout: 90 seconds for the small synthetic fixture and
15 minutes for a full-copy descendant. A timeout records a specific source-baseline or destination-
probe predicate in private qualification evidence, retains the active receipt, and requires its
receipt-bound recovery command before another qualification attempt.
Large-fixture client observation allows 60 seconds for fail-closed recursive `lsof` scans of the
active palace, project, and current snapshot plus direct checks of active KG, configuration,
marker, and lock files. Direct KG checks include each SQLite main file and its existing `-wal` and
`-shm` sidecars. Immutable runtime, retained snapshots, and retained evidence are outside that
mutation and recovery fence.

Lance admission accepts current file rows with `ingest_mode: file`. Legacy rows with an empty
`ingest_mode` require an exact scoped source path, a valid file hash, an empty protected type, and a
known file-mining strategy (`regex_structural_v1`, `treesitter_v1`,
`treesitter_adaptive_v1`, or `dotnet_project_xml_v1`). For legacy rows, manual, diary, blank, and
unknown strategies remain protected and stop admission before mutation.

## Evidence and recovery

The mode-0600 receipt seals canonical typed preimages, Arrow schema, exact row multiplicity,
expected postimages, configuration bytes, the frozen UTC instant, exact eligible triple IDs, runner
hash, isolated non-editable interpreter, distribution and module origins, package hashes,
model-cache content and metadata, snapshot paths, and durable stage boundaries. Full-copy Lance rows
use bounded-batch witnesses containing identity, wing, file-provenance fields, and a SHA-256 digest
of every remaining typed field, including text, vectors, and extension metadata. Raw Lance bytes
remain in the verified snapshot used for recovery. Classification compares current witnesses with
the sealed values. Duplicate rows or IDs, schema-only drift, configuration drift, and any state
outside the sealed transition envelope classify as unknown; recovery refuses unknown. The last
recorded phase never grants authority. Receipt decoding has a 256 MiB size bound; an oversized
receipt refuses before JSON allocation.

After the parent snapshot proves those complete witnesses and Arrow schema against its Lance bytes,
descendant authority checks rehash every current parent Lance file and compare the exact file map
with the still-verified snapshot. They then rebuild the admission digest from those hashes, the
sealed logical Lance state, and fresh KG, configuration, marker, tiny-hash, and unrelated-file
observations. File additions, deletions, byte drift, unsafe links, and changes between the parent and
child fences refuse before descendant mutation. This transitive check avoids repeatedly decoding
the unchanged parent table while preserving both fence checks.

Every file-owned source group has one consistent source hash across all chunk indexes. Cross-wing
groups compare the complete chunk/hash-row multiset. Tiny-hash migration preserves every stored
hash exactly; it never edits a source hash to make the later mine appear unchanged.

Immediately before marker activation, the runner revalidates the sealed interpreter,
distribution/module origins, dependency link, and package hashes. In an evidence-contained copy it
then creates the baseline through the real source-wing mine, applies the sealed prospective identity,
proves the installed resolver selects the destination, and proves the installed effective mine files
zero unchanged drawers. A checkout or `PYTHONPATH` result cannot satisfy this predicate.

Snapshots retain the complete Lance directory and byte preimages for non-SQLite state. Every
inventoried SQLite database is copied through `Connection.backup`, integrity-checked, and proved
in a fresh isolated restore before apply. Recovery replaces the complete Lance snapshot, removes
the SQLite main/WAL/SHM set, installs each canonical SQLite backup, restores sidecar and marker
bytes, and verifies the full logical preimage. If recovery stops after creating a receipt-bound
removed-database backup and before unlinking the live SQLite set, the same recovery command safely
continues with that staged backup and restores the preimage.

Keep a failed fixture, its receipt, and snapshot private until this command succeeds:

```bash
mempalace-code wing-migration recover --inventory /absolute/disposable/inventory.json --receipt /absolute/disposable/receipt.json
```

An inventoried receipt with no snapshot has performed zero migration writes. Retain it at its
versioned path as failed evidence. A newer receipt version uses a distinct filename in the same
excluded evidence root; never move or replace a receipt that may require receipt-bound recovery.

Keep failed or partial fixture evidence for at least 30 days and until verified recovery or an
explicit owner disposition, whichever is later. After verified recovery, an owner may dispose of
that inventoried fixture. Successful synthetic qualification removes its fixture automatically.
Full-copy qualification restores the admitted copy to its complete sealed preimage and retains the
baseline snapshot, receipt, report, and compact sealed result for every collision, retry, apply, and
recovery interruption outcome. Each successfully verified descendant copy is removed before the
next challenge starts. Collision and interruption challenges each use a distinct,
non-hardlinked descendant copy with a distinct receipt and runtime area; the admitted baseline seal
is checked after every challenge. Every descendant receipt seals the parent receipt, private
inventory authority, and normalized baseline. Apply, classify, snapshot, and recovery revalidate
that chain, so stale, reordered, or changed parent authority refuses before descendant mutation.
The collision challenge is written into its own descendant before its sealed admission calculation.
Every descendant KG, including an external WAL-backed candidate and its aliases, is materialized
through verified SQLite backup. It writes versioned `full-copy-receipt-vN.json` and
`full-copy-qualification-vN.json` files below the owner-selected evidence destination. A failed
older-format receipt stays in place when a newer receipt version is qualified. Descendant trials
use `trials/vN/` below that evidence root while active. Any retained trial tree or unaccounted
`snapshot-vN` directory blocks a new qualification before evidence writes; recover it and obtain
owner disposition instead of creating another generation. Each retry inventory names a fresh empty
snapshot root; the installed runtime remains the separately sealed reusable authority.
On macOS, descendant project trees without embedded KG candidates use APFS copy-on-write clones.
The clone must produce distinct inodes and pass the same complete logical preimage check. A clone
refusal falls back to the ordinary independent copy path.
Older-format receipts remain byte-for-byte retained evidence. Recovery requires the matching
historical runner version and hash because the current runner refuses older receipt versions or
hashes. Preserve that runner separately until recovery or owner disposition.
Retain this evidence through the inventoried deadline and until verified recovery or owner
disposition, whichever is later. The private receipt contains one exact recovery command. The
descendant receipt is persisted before copied storage is written; if construction stops
before a snapshot exists, that command removes only incomplete descendant contents and retains the
receipt. Sanitized command output may be retained with task evidence.

## Authority boundary

Full-copy qualification alone grants no live authority. Live execution requires the separate
mode-0600 authority described above and accepts only its exact host, paths, operation, retained
qualification proof, interruption, and retention scope. The operator does not start a watcher,
change configuration, publish artifacts, or mutate another repository.

Remove this file, `mempalace_code/wing_migration.py`, its repository wrapper, CLI adapter, and
`tests/test_wing_migration.py` together after the separately authorized full-copy/live work is
completed or cancelled and retained evidence is handed off.
