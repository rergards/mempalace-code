slug: BACKUP-AUTOMATED-RETENTION-DEFAULTS
phase: polish
date: 2026-05-22
commit_range: cfe6f3d..8f45a27
reverted: false
findings:
  - id: P-1
    title: "Local datetime/_dt and MagicMock imports inside test methods"
    category: volume
    location: "tests/test_backup.py:836,865,893,1278"
    evidence: "from datetime import datetime as _dt / from unittest.mock import MagicMock, patch appear at the top of each new test body in TestManagedRetention"
    decision: dismissed
    reason: "Pre-existing file convention — identical pattern used in lines 656, 686, 723 which pre-date this task. Rewriting it would be style preference, not slop removal."

  - id: P-2
    title: "Redundant import json inside test function"
    category: volume
    location: "tests/test_config.py:443"
    evidence: "'import json' inside test_negative_file_config_retain_count_is_not_explicit; json is already imported at module level (line 1)"
    decision: fixed
    fix: "Removed the in-function 'import json' line; module-level import is sufficient"

totals:
  fixed: 1
  dismissed: 1
fixes_applied:
  - "Removed redundant 'import json' from test_negative_file_config_retain_count_is_not_explicit in tests/test_config.py"
