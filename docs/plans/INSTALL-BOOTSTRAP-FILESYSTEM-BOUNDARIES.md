---
slug: INSTALL-BOOTSTRAP-FILESYSTEM-BOUNDARIES
status: completed
authority: non_authoritative
goal: "Make bootstrap fail closed on launcher collisions, unsafe venv paths, and non-commit Git refs before package mutation."
risk: high
risk_note: "The public remote installer executes environment-selected interpreters and mutates package and launcher paths; a boundary error can execute foreign code or overwrite user-owned files."
files:
  - path: scripts/bootstrap.sh
    change: "Validate venv path components and ownership before reuse, require verified interpreter prefix and launcher ownership, accept only 40-hex Git commits, and create the canonical launcher without replacing collisions."
  - path: docs/AGENT_INSTALL.md
    change: "Require commit-pinned bootstrap and Git-package refs, document the fail-closed path and launcher recovery checks, and remove claims that a tag-shaped ref is immutable."
  - path: tests/test_installed_artifact_behavior.py
    change: "Extend the existing disposable-HOME bootstrap harness with filesystem, interpreter-prefix, retry, race, and ref-boundary regressions while retaining install-owner coverage."
acceptance:
  - id: AC-1
    when: "Bootstrap encounters a regular file, directory, FIFO, or unrelated symlink at the disposable HOME canonical launcher path."
    then: "It exits nonzero, preserves the colliding node and its content or target unchanged, and prints one exact ls -ld inspection/recovery command for the reported path."
  - id: AC-2
    when: "MEMPALACE_VENV is relative, has a symlinked component, is not an invoking-user-owned directory, or names an existing environment whose Python prefix or launcher ownership does not match."
    then: "Bootstrap exits before invoking that environment's package installer and reports the exact rejected path; a valid absolute, non-symlink, invoking-user-owned environment is the only reusable case."
  - id: AC-3
    when: "Bootstrap is repeated after success, interrupted before launcher publication, or loses a launcher-creation race to another filesystem node."
    then: "An already-correct launcher is accepted idempotently, an unrelated node is never replaced, and completion output is emitted only after the selected environment and launchers pass post-state verification."
  - id: AC-4
    when: "Unattended bootstrap or Git package installation is requested through the documented path."
    then: "The consumed bootstrap and package refs are 40-hex commits, tag-shaped, moved, abbreviated, or malformed refs fail before package mutation, and documentation does not describe a regex-shaped tag as immutable."
  - id: AC-5
    when: "The focused negative bootstrap matrix exercises relative paths, symlinked venvs and parents, foreign or stale prefixes, launcher collision node types, duplicate runs, and moved or malformed refs."
    then: "Every unsafe case exits nonzero without overwriting the launcher or executing package mutation through the rejected environment, while safe duplicate execution remains idempotent."
  - id: AC-6
    when: "The existing uv, pipx, project, and bootstrap install-owner behavioral checks run after the hardening change."
    then: "All supported install owners still resolve and verify their own launchers, and custom bootstrap venv documentation still derives the matching launcher path."
out_of_scope:
  - "Adding another installer, launcher manager, shared helper module, or configuration mode."
  - "Replacing the existing optional mempalace alias policy or taking ownership of unrelated launchers."
  - "Adding a protected-tag registry or GitHub API dependency; Git bootstrap inputs are narrowed to commit IDs."
  - "Changing uv, pipx, project-install, PyPI publishing, package-version, update, model-download, MCP, or palace-storage behavior."
  - "Editing backlog metadata, committing, pushing, publishing, or performing runner-owned finalization."
contract_policy:
  flow: full_spdd
  reason: "Strict security fix on a public remote installer with filesystem ownership, interpreter execution, package mutation, and retry boundaries."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: strict
  requirements:
    - id: REQ-1
      statement: "Canonical launcher publication must preserve every pre-existing unrelated filesystem node and provide exact recovery output."
      source: "backlog contract AC-1 and AC-3"
      acceptance_ids: [AC-1, AC-3]
    - id: REQ-2
      statement: "Only an absolute, non-symlink, invoking-user-owned venv with a matching Python prefix and owned launchers may be reused for package execution."
      source: "backlog contract AC-2 and AC-5"
      acceptance_ids: [AC-2, AC-5]
    - id: REQ-3
      statement: "Bootstrap creation, publication, retry, and completion reporting must be race-bounded and idempotent."
      source: "backlog contract AC-3 and AC-5"
      acceptance_ids: [AC-3, AC-5]
    - id: REQ-4
      statement: "Direct remote bootstrap and Git package installation must consume 40-hex commits and reject tag shape as proof of immutability."
      source: "backlog contract AC-4 and AC-5"
      acceptance_ids: [AC-4, AC-5]
    - id: REQ-5
      statement: "Existing install-owner selection and launcher derivation must remain compatible."
      source: "backlog contract AC-6"
      acceptance_ids: [AC-6]
  surfaces:
    - name: "Bootstrap installer"
      kind: cli
      paths: ["scripts/bootstrap.sh"]
      expected_behavior: "Fail before rejected-environment package execution, use commit-pinned Git inputs, publish only an absent or already-correct canonical launcher, and report completion only from a verified post-state."
    - name: "Agent bootstrap runbook"
      kind: cli
      paths: ["docs/AGENT_INSTALL.md"]
      expected_behavior: "Supply commit-only unattended commands and exact read-only recovery checks consistent with the script's path, owner, launcher, and ref boundaries."
    - name: "Installed-artifact bootstrap regressions"
      kind: internal
      paths: ["tests/test_installed_artifact_behavior.py"]
      expected_behavior: "Exercise the script in disposable homes with controlled fake Python and package-install contours, including unsafe node types, stale environments, refs, retries, and collision races."
  invariants:
    - id: INV-1
      statement: "Bootstrap never removes, truncates, renames, or force-replaces an existing canonical launcher node."
      applies_to: ["scripts/bootstrap.sh", "tests/test_installed_artifact_behavior.py"]
    - id: INV-2
      statement: "PyPI remains the default source and rejects a supplied Git ref before venv or package mutation."
      applies_to: ["scripts/bootstrap.sh", "tests/test_installed_artifact_behavior.py"]
    - id: INV-3
      statement: "The optional mempalace alias remains untouched when already present or resolved elsewhere."
      applies_to: ["scripts/bootstrap.sh"]
    - id: INV-4
      statement: "uv, pipx, project, and bootstrap remain separate selected install owners whose post-install checks use their resolved launchers."
      applies_to: ["docs/AGENT_INSTALL.md", "tests/test_installed_artifact_behavior.py"]
    - id: INV-5
      statement: "Bootstrap tests use disposable homes and fake package contours and never mutate the operator's real venv or user launcher directory."
      applies_to: ["tests/test_installed_artifact_behavior.py"]
  risks:
    - id: RISK-1
      risk: "A check-then-create race could replace or bless a node introduced after validation."
      mitigation: "Publish with Python os.symlink(target, link_name), whose single symlink syscall fails with EEXIST for every destination node type instead of treating a directory as a container; classify an EEXIST result, accept only the exact expected symlink, and verify the published target before success output."
    - id: RISK-2
      risk: "A syntactically safe venv path could redirect through a symlinked parent or foreign existing environment."
      mitigation: "Lexically require an absolute path, reject symlinks and irregular nodes, and reject any ancestor whose ownership, mode, or sticky-entry semantics let an identity other than root or the invoking UID replace the next component. Acquire an atomic invoking-user-owned sibling lock directory, record component device/inode identities, and retain the lock while revalidating those identities through package execution."
    - id: RISK-3
      risk: "A stale venv launcher could execute code from a different environment despite a matching directory name."
      mitigation: "Under the retained lock and authorized-parent predicate, validate the venv, bin directory, Python link and resolved interpreter device/inode, owner, and prefix before every execution; reject an attacker-writable parent or any identity change before package mutation, then require the same identities and installed-launcher checks before publication."
    - id: RISK-4
      risk: "Release-tag movement could change downloaded or installed code between review and execution."
      mitigation: "Accept and document only full 40-hex commits for remote bootstrap and Git package refs; reject tag-shaped and abbreviated refs before package mutation."
    - id: RISK-5
      risk: "Hardening could break custom venv launcher derivation or other documented install owners."
      mitigation: "Retain the existing install-owner tests and custom bootstrap venv documentation regression alongside the new boundary matrix."
  verification:
    - id: VER-1
      owner: provider
      command: "python -m pytest tests/test_installed_artifact_behavior.py::test_bootstrap_refuses_unowned_launcher_nodes -q"
      proves: "Regular files, directories, FIFOs, and unrelated symlinks remain unchanged and yield the exact recovery command."
      acceptance_ids: [AC-1]
    - id: VER-2
      owner: provider
      command: "python -m pytest tests/test_installed_artifact_behavior.py::test_bootstrap_rejects_unsafe_venv_paths_before_execution tests/test_installed_artifact_behavior.py::test_bootstrap_rejects_foreign_existing_venv_before_package_execution -q"
      proves: "Relative, redirected, attacker-writable, foreign-owned, stale-prefix, identity-changed, and wrong-launcher environments stop before their package execution path."
      acceptance_ids: [AC-2, AC-5]
    - id: VER-3
      owner: provider
      command: "python -m pytest tests/test_installed_artifact_behavior.py::test_bootstrap_launcher_publication_is_race_bounded_and_idempotent -q"
      proves: "The atomic bootstrap lock serializes duplicate runs, stale or replaced locks fail closed, launcher collision races do not overwrite or populate unrelated nodes, and partial execution is not reported as current."
      acceptance_ids: [AC-3, AC-5]
    - id: VER-4
      owner: provider
      command: "python -m pytest tests/test_installed_artifact_behavior.py::test_bootstrap_requires_full_commit_refs_before_package_mutation tests/test_installed_artifact_behavior.py::test_runbook_bootstrap_uses_consumed_commit_refs -q"
      proves: "The script and unattended runbook consume full commits and reject tag-shaped, moved, abbreviated, and malformed refs before package mutation."
      acceptance_ids: [AC-4, AC-5]
    - id: VER-5
      owner: provider
      command: "python -m pytest tests/test_installed_artifact_behavior.py::test_bootstrap_negative_filesystem_boundary_matrix -q"
      proves: "The complete required negative matrix preserves rejected venvs and launcher nodes while the safe duplicate case succeeds."
      acceptance_ids: [AC-5]
    - id: VER-6
      owner: provider
      command: "python -m pytest tests/test_installed_artifact_behavior.py::test_install_methods_validate_with_owning_launcher tests/test_installed_artifact_behavior.py::test_bootstrap_snippets_derive_launcher_from_custom_venv -q"
      proves: "Existing uv, pipx, project, and bootstrap owner guidance and custom-vvenv launcher derivation remain intact."
      acceptance_ids: [AC-6]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        owner: provider
        command: "python -m pytest tests/test_installed_artifact_behavior.py::test_install_methods_validate_with_owning_launcher -q"
        proves: "The existing install-owner selection contract remains green after the bootstrap boundary change."
        acceptance_ids: [AC-6]
---

## Design Notes

- Validate source/ref inputs and the lexical venv path before creating directories. Require a leading `/`; do not expand a relative value, `~`, or an alternate spelling into an accepted target.
- Establish the venv authority boundary before its first mutation. Walk every existing component with `lstat`; reject symlinks and irregular nodes. For each directory that can replace the next component, require root or invoking-UID ownership with no group/world write permission, or sticky-directory semantics plus an already-existing next entry owned by the invoking UID. Reject a missing child under an attacker-writable ancestor. The invoking UID is the installation authority; an unrelated UID must have no rename or replacement route.
- Create any missing pre-venv components one at a time with atomic `mkdir` and mode `0700` beneath the last authorized existing parent, accepting `EEXIST` only after the same ownership, mode, type, and device/inode classification. Then serialize duplicate or reordered bootstrap attempts with an atomic sibling lock directory under the authorized venv parent. Require the lock to be invoking-UID-owned, mode `0700`, and bound to a per-run token; a pre-existing lock fails with its exact `ls -ld -- <lock path>` inspection command. A trap removes only the lock whose recorded device/inode and token still match, so stale or replaced locks are preserved for explicit recovery.
- While holding the lock, record device/inode identities for every venv component and for the venv, `bin`, `bin/python` link, and resolved interpreter. Create a missing venv with umask `077` under the already-authorized parent, then record the new identities. Before every venv-interpreter or package invocation and again afterward, require the complete recorded chain and resolved interpreter identity to match. The access predicate removes foreign replacement authority, the lock serializes cooperating same-UID bootstrap runs, and any observed identity change fails before the next execution or publication.
- For an existing venv, also require invoking-UID ownership of the venv, `bin/python`, and any existing `mempalace-code` or `mempalace-code-mcp` launcher. Under the retained authority predicate and lock, run the identity-checked Python only to obtain a machine-readable `sys.prefix`; require its canonical prefix to equal the selected canonical venv, then recheck and use that same path with `-m pip` instead of trusting a stale `bin/pip` launcher.
- Keep path classification, locking, and mutation in `scripts/bootstrap.sh`; do not add a helper module or a second installer owner. The selected system Python may provide portable `lstat`, UID, mode, device/inode, and lock-token probes as bounded bootstrap internals.
- Publish the canonical launcher by passing target and destination as data to Python `os.symlink(target, link_name)`. This maps to one no-clobber symlink syscall on Linux and macOS: a regular file, directory, FIFO, symlink, or race winner at the exact destination returns `EEXIST` and cannot become a container target. On `EEXIST`, reclassify the destination and accept only a symlink whose resolved target exactly matches the selected venv launcher. Every other node stops with the documented `ls -ld -- <exact path>` recovery command and remains untouched. Use the same primitive for the optional alias publication without changing its existing leave-present policy.
- Verify both installed launchers, the venv prefix, and the canonical symlink target after installation. Emit `Done`, `Owner`, and current-environment output only after those checks; a retry after earlier package mutation is allowed to repair the same verified venv but cannot claim another environment.
- Narrow `MEMPALACE_GIT_REF`, `BOOTSTRAP_REF`, and documented Git `PACKAGE_REF` to 40 hexadecimal characters. A release tag may be resolved by an operator outside this flow, but the unattended command receives and consumes the resulting commit only. This closes moved-tag ambiguity without a new API, credential, or protection-policy dependency.
- Extend `_run_bootstrap` with controlled fake executables and marker files inside each disposable test directory so tests can prove which interpreter/package path ran without network access or operator-state mutation. Include attacker-writable-parent rejection, component/interpreter identity changes between checkpoints, lock contention and stale/replaced-lock preservation, and a directory collision that proves no nested symlink is created. Use bounded subprocess timeouts for FIFO and race cases.
- Command context basis: `pyproject.toml` declares pytest under the repository test configuration, and the existing bootstrap coverage is already in `tests/test_installed_artifact_behavior.py`; focused node IDs and the owning test module therefore run from the repository root with `python -m pytest`.
