slug: MINE-EAGER-EMBED-INIT
round: 1
date: 2026-04-14
commit_range: 530688f..ea070e6
findings:
  - id: F-1
    title: "convo_miner.mine_convos() does not call warmup() before batch processing"
    severity: info
    location: "mempalace/convo_miner.py:290"
    claim: >
      mine_convos() calls get_collection() and then flush_batch() without a
      warmup() call, so HuggingFace model-loading output could appear mid-batch
      when running mempalace mine --mode convos. This is the same UX issue the
      task was created to fix — but only in the code-mining path.
    decision: dismissed
    fix: ~
  # Dismissal rationale: explicitly scoped out in the MINE-EAGER-EMBED-INIT plan
  # ("convo_miner.py — does not call mine(); its embedding path is separate").
  # convo_miner has no "Loading embedding model..." / "Model ready." phase prints,
  # so there is no bracket to guarantee output ordering within. Adding warmup()
  # there is a separate, independent UX improvement with its own scope.

totals:
  fixed: 0
  backlogged: 0
  dismissed: 1
fixes_applied: []
new_backlog: []
