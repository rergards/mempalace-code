---
slug: REL-WATCH-READY-SIGINT-RACE
goal: "Make SIGINT delivered during watch-ready emission exit every watcher cleanly without a traceback or leaked signal handlers."
risk: low
risk_note: "The change only widens the existing KeyboardInterrupt/finally lifecycle around two watcher loops and adds a focused regression test."
files:
  - path: mempalace_code/watcher.py
    change: "Move watch-ready emission inside the existing interrupt-catching and handler-restoring lifecycle for watch_and_mine and watch_all."
  - path: tests/test_watcher.py
    change: "Add a deterministic ready-to-SIGINT regression covering clean exit, rejected FIFO startup, and signal-handler restoration."
acceptance:
  - id: AC-1
    when: "watch_and_mine or watch_all reaches watch-ready and its mocked watch iterator then ends normally"
    then: "the command emits one watch-ready state followed by the normal zero-change shutdown summary and exits without traceback output"
  - id: AC-2
    when: "the watch iterator raises a non-interrupt runtime error after watch-ready"
    then: "the runtime error remains observable to the caller and every watcher-installed signal handler is restored"
  - id: AC-3
    when: "watch_and_mine starts on a disposable FIFO-only project and a monkeypatched watch-ready emission sends SIGINT to the current process"
    then: "the call returns normally, reports the rejected FIFO and normal shutdown summary, emits no Traceback or KeyboardInterrupt text, and restores the pre-run signal handlers"
out_of_scope:
  - "Changing watcher startup state text, signal support, exit codes, or operation-lock ownership."
  - "Changing non-regular source discovery or the installed release-readiness scenario."
contract_policy:
  flow: lite_compact
  reason: "All five axes are low: the behavior delta, ownership, test surface, rollout, and rollback are each local and reversible; no auth, data, migration, provider, or pipeline boundary is touched."
  sync_gate: may_skip_when_existing_checks_cover
  verification_path: automated
---

## Design Notes

- Existing owner: `_WatcherShutdownSignals` owns graceful SIGTERM/SIGHUP setup and restoration, while `watch_and_mine()` and `watch_all()` own Ctrl-C handling around their watch loops. Extend those same owners; add no helper, state owner, dependency, or alternate shutdown path.
- Put `_emit_run_state(run_id, "watch-ready")` at the start of each entrypoint's existing `try` block. Preserve ordering: handlers are installed before readiness, readiness precedes `watchfiles.watch(...)`, `KeyboardInterrupt` is swallowed, handlers restore in `finally`, and the normal stop summary prints afterward.
- Apply the same lifecycle boundary to both entrypoints because they duplicate the same ready/loop/interrupt sequence. Leaving either emission outside its `try` would retain the same race under the same owner.
- Add the exact regression to `TestWatcherShutdownSignals` using a disposable project whose only candidate source is a FIFO. Monkeypatch `_emit_run_state` so only `state == "watch-ready"` first emits the normal state line and then calls `os.kill(os.getpid(), signal.SIGINT)`; keep the real process handler behavior so the test fails on the original race.
- Assert captured stdout/stderr contains the FIFO rejection diagnostic and normal zero-cycle stop summary, contains no `Traceback` or `KeyboardInterrupt`, and that supported signal handlers match their pre-call values after return. The test must not enter `watchfiles.watch`; patch it with a fail-fast assertion to prove interruption occurs at the boundary.
- Preserve the existing non-interrupt failure contract with `test_watch_iteration_error_restores_every_handler`; a `RuntimeError` from the iterator must still escape after restoration.
- Reuse ledger: graceful watcher shutdown | `_WatcherShutdownSignals`, `watch_and_mine`, `watch_all` | existing signal registration/restoration and iteration-error tests | SIGINT can arrive before the current catch boundary | extend.
- Cheapest decisive falsifier: run `python -m pytest tests/test_watcher.py -q -k 'watch_ready_sigint or watch_iteration_error_restores_every_handler or entrypoints_register_deliver_and_restore_supported_signals'`; the new SIGINT case must fail before the lifecycle move and pass afterward. Then run the complete `tests/test_watcher.py` module to detect watcher regressions.
