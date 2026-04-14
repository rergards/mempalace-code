slug: STORE-CHROMA-DELETE-WING-LIMIT
round: 1
date: 2026-04-14
commit_range: a9c526f..c974a72
findings:
  - id: F-1
    title: "No ChromaStore-specific unit test for delete_wing with limit wrapper"
    severity: info
    location: "tests/test_storage.py"
    claim: >
      All existing delete_wing tests use the LanceDB-backed open_store fixture. There is no
      test that instantiates ChromaStore directly and verifies that delete_wing fetches via
      self.get() (i.e. with limit=10000) rather than self._col.get(). The fix is mechanically
      correct and trivially verified by inspection, but the gap means a future regression
      (e.g. someone reintroducing the raw call) would not be caught by the test suite.
    decision: dismissed
    fix: ~
    # Dismissed: ChromaDB is the deprecated backend (opt-in via [chroma] extra). Adding a
    # ChromaStore-specific test would require chromadb as a test dependency and a conditional
    # skip marker. The fix is a 1-line change that is trivially correct by inspection; the
    # cost of a dedicated test outweighs the benefit on a deprecated code path.

totals:
  fixed: 0
  backlogged: 0
  dismissed: 1

fixes_applied: []

new_backlog: []
