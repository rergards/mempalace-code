"""The shipped NOTICE keeps the upstream MIT copyright and permission notice.

The upstream MIT license requires its copyright notice and permission notice in
all copies or substantial portions of the software. NOTICE is the file that
carries them; `scripts/release_artifact_gate.py` already requires NOTICE in the
wheel's license files, so this test only guards the text itself.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parent.parent

UPSTREAM_COPYRIGHT = "Copyright (c) 2026 MemPalace Contributors"
UPSTREAM_PERMISSION_GRANT = (
    "Permission is hereby granted, free of charge, to any person obtaining a copy\n"
    'of this software and associated documentation files (the "Software"), to deal\n'
    "in the Software without restriction"
)
UPSTREAM_PERMISSION_CONDITION = (
    "The above copyright notice and this permission notice shall be included in all\n"
    "copies or substantial portions of the Software."
)


def test_notice_carries_the_upstream_mit_notice_verbatim():
    notice = (ROOT / "NOTICE").read_text(encoding="utf-8")

    assert "MIT License" in notice
    assert UPSTREAM_COPYRIGHT in notice
    assert UPSTREAM_PERMISSION_GRANT in notice
    assert UPSTREAM_PERMISSION_CONDITION in notice
    assert 'THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND' in notice
