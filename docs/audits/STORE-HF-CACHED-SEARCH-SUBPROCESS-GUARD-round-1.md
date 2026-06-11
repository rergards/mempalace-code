slug: STORE-HF-CACHED-SEARCH-SUBPROCESS-GUARD
round: 1
date: 2026-06-11
commit_range: cfb7dcf..16c609a
findings:
  - id: F-1
    title: "AC-3 test missing positive assertion that SentenceTransformer constructor was reached"
    severity: medium
    location: "tests/test_offline.py:450"
    claim: >
      test_offline_search_subprocess_no_online_retry_on_local_cache_error asserted only
      negative conditions (no online_load, no socket_attempt, no metadata_attempt). If the
      subprocess failed for an unrelated reason before _SentenceTransformerEmbedder._load_model
      was reached, the event log would be empty and all three negative assertions would pass
      vacuously, producing a false-positive test. The comment in the test noted that the palace
      must be seeded "so _SentenceTransformerEmbedder is invoked" but no assertion enforced that
      the embedder was actually reached.
    decision: fixed
    fix: >
      Added `assert "constructor" in event_types` before the negative assertions. The fake
      SentenceTransformer records a "constructor" event before raising, so this assertion proves
      the embedder was actually invoked. An empty event log (pre-embedder failure) now causes
      the test to fail with a clear diagnostic message.

  - id: F-2
    title: "sitecustomize socket blocker stores but never calls _orig_create_connection"
    severity: info
    location: "tests/test_offline.py:132"
    claim: >
      _orig_create_connection is captured before replacement but never invoked (the fake always
      raises). This is a dead variable in the generated sitecustomize.py. Since the intent is
      always to block, this is not a bug, only a minor dead-reference.
    decision: dismissed

  - id: F-3
    title: "ssl.SSLSocket.connect bypasses the Python-level socket.socket.connect patch"
    severity: info
    location: "tests/test_offline.py:138"
    claim: >
      sitecustomize patches socket.socket.connect at the Python class level. ssl.SSLSocket
      overrides connect at the C level so SSL connections would not be intercepted by the patch.
      This is intentional defense-in-depth only — the primary guard is the fake sentence_transformers
      and huggingface_hub modules that shadow the real packages. Since the fake modules never connect,
      the SSL gap is not reachable in practice.
    decision: dismissed

totals:
  fixed: 1
  backlogged: 0
  dismissed: 2

fixes_applied:
  - "Added assert 'constructor' in event_types to AC-3 test (test_offline_search_subprocess_no_online_retry_on_local_cache_error) to prevent false-positive on pre-embedder subprocess failure"

new_backlog: []
