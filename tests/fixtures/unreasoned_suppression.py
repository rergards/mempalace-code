"""
Negative fixture for tests/test_type_suppressions.py.

This file intentionally contains unreasoned type suppression lines that the
suppression-policy scanner must reject. It is NOT part of the enforced set —
the scanner excludes tests/fixtures/ and asserts that this file fails the check.
"""

x: int = "hello"  # type: ignore
y: str = 1  # pyright: ignore
z: list = None  # type: ignore[assignment]
