# Installed functional acceptance findings

## Socket fixture path correction

`MP-RELEASE-MACOS-SOCKET-PATH` belongs to the existing installed release verifier,
`scripts/release_readiness_gate.py`. The package's source rejection behavior was
unchanged.

The pinned `mempalace-code` 1.15.1 wheel has SHA-256
`bfa4902403102be364aaaa2fcf83f968eb51576b6e50e1f123cab818af12f983`.
Its installed package bytes match the wheel. All 87 Python package files also
match release source `df379c058d00f7255a76dc7f7d36280b3284ea44`.

The published verifier's socket probe binds at 101 bytes, but its next fixture
address is 106 bytes and fails with `AF_UNIX path too long` on macOS. A short-root
control passes the same installed scenario, with four actual socket bindings and
11 CLI invocations. A longer-root regression also shows that the previous probe
could silently omit every socket case.

The corrected owner binds POSIX sockets through an owner-only temporary directory
with a short symbolic link to the same disposable scenario root. The actual
fixture nodes remain at the original source paths. It closes and removes sockets
before removing that alias, including on handled failures. Unexpected probe
errors fail the scenario; only explicit unsupported-socket errors permit omission.

The corrected installed scenario passes with short and 180-byte source roots. All four
socket cases execute, source rejection and lease checks pass, and sockets, aliases
and disposable data are removed. The existing verifier test module passes all
419 tests. The new regression fails against the previous owner and passes after
the correction, including cleanup after a command failure. Ruff checks and
Pyright pass. Independent Astra source review accepts code patch SHA-256
`073cf5f779eb82e2cb93d1969f51c3478b32eff8d28f236516832ed38def557a`.

Recovery uses the existing installed owner:

```bash
python scripts/release_readiness_gate.py --installed-golden-wheel "$WHEEL" --json
```

This focused result does not establish complete release readiness. Full installed
acceptance, installer and platform checks remain separate requirements.

## Direct coverage correction

The installed published verifier reproduces both gaps on the same pinned wheel:
`minimal`, `kg`, `code` and `notes` pass with no primary tool calls, while `full`
calls 29 tools. Its root parser discovers only the wing-migration parent, and its
argv attribution credits a missing-action usage response as execution.

The corrected owner discovers all eight delegated migration actions. Parent
guidance and an operation's help receive no operation credit. The recorder keeps
success, documented refusal, discovery, guidance and daemon-launch classifications;
each scenario checks outcomes before final inventory reconciliation.

Installed stdio checks pass all 64 enabled tool/profile pairs (4 minimal, 8 kg,
11 code, 12 notes and 29 full), with separate disposable palaces. They check
semantic results, mutation post-state, both protocol handshakes, invalid modern
metadata and a valid continuation. Missing tool responses, generic success
responses, missing handshakes and generic handshakes fail regression checks.

Installed CLI migration checks pass inventory, snapshot, apply, classification,
recovery, zero-write merged retry, unchanged recovery retry and synthetic
qualification. Live actions and full-copy qualification receive explicit
missing-authority or missing-inventory refusals; the fixture remains unchanged.
Onboarding also saves synthetic input successfully and preserves that state on
an interrupted retry. Disposable scenario data is removed after these checks.

The affected verifier module passes 421 tests. Ruff lint and formatting, Pyright
and Git whitespace checks pass. Independent Astra source review accepts the
exact frozen verifier candidate. The complete installed suite passes on the
pinned published wheel, including optional extras, inventory reconciliation,
CLI outcomes, profile calls, protocol checks and resource cleanup. The frozen
source snapshot remained unchanged. This evidence qualifies the verifier; the
next package candidate still requires its own wheel-bound release checks.
