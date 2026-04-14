"""Unit tests for detect_language() in miner.py."""

from pathlib import Path

import pytest

from mempalace.miner import detect_language


# =============================================================================
# Extension-based detection
# =============================================================================


@pytest.mark.parametrize(
    "ext,expected",
    [
        (".py", "python"),
        (".js", "javascript"),
        (".jsx", "jsx"),
        (".ts", "typescript"),
        (".tsx", "tsx"),
        (".go", "go"),
        (".rs", "rust"),
        (".rb", "ruby"),
        (".java", "java"),
        (".sh", "shell"),
        (".sql", "sql"),
        (".md", "markdown"),
        (".txt", "text"),
        (".json", "json"),
        (".yaml", "yaml"),
        (".yml", "yaml"),
        (".toml", "toml"),
        (".html", "html"),
        (".css", "css"),
        (".csv", "csv"),
        (".c", "c"),
        (".h", "c"),
        (".cpp", "cpp"),
        (".hpp", "cpp"),
    ],
)
def test_extension_detection(ext, expected):
    filepath = Path(f"some/file{ext}")
    assert detect_language(filepath) == expected


def test_unknown_extension_returns_unknown():
    filepath = Path("some/file.xyz")
    assert detect_language(filepath) == "unknown"


def test_extensionless_no_shebang_returns_unknown():
    filepath = Path("Makefile")
    assert detect_language(filepath, "") == "unknown"


# =============================================================================
# Shebang fallback
# =============================================================================


@pytest.mark.parametrize(
    "shebang,expected",
    [
        ("#!/usr/bin/python", "python"),
        ("#!/usr/bin/python3", "python"),
        ("#!/usr/bin/python3.9", "python"),
        ("#!/usr/bin/env python3", "python"),
        ("#!/usr/bin/env python", "python"),
        ("#!/usr/bin/node", "javascript"),
        ("#!/usr/bin/env node", "javascript"),
        ("#!/usr/bin/nodejs", "javascript"),
        ("#!/usr/bin/env nodejs", "javascript"),
        ("#!/usr/bin/ruby", "ruby"),
        ("#!/usr/bin/env ruby", "ruby"),
        ("#!/bin/bash", "shell"),
        ("#!/bin/sh", "shell"),
        ("#!/bin/zsh", "shell"),
        ("#!/usr/bin/env bash", "shell"),
        ("#!/usr/bin/perl", "perl"),
        ("#!/usr/bin/env perl", "perl"),
    ],
)
def test_shebang_detection(shebang, expected):
    filepath = Path("script")  # no extension
    content = f"{shebang}\nsome content here\n"
    assert detect_language(filepath, content) == expected


def test_shebang_with_env_wrapper_python3():
    """#!/usr/bin/env python3 should be detected as python."""
    filepath = Path("run")
    content = "#!/usr/bin/env python3\nprint('hello')\n"
    assert detect_language(filepath, content) == "python"


def test_shebang_with_interpreter_flags():
    """Shebangs with flags after interpreter name should still detect correctly.

    Bug fixed in harden round-1: the previous parser used parts[-1] which
    resolved to the flag ('-u', '-O', etc.) rather than the interpreter.
    """
    cases = [
        ("#!/usr/bin/python3 -u", "python"),
        ("#!/usr/bin/python -O", "python"),
        ("#!/usr/bin/env python3 -O", "python"),
        ("#!/bin/bash -e", "shell"),
        ("#!/bin/sh -x", "shell"),
    ]
    for shebang, expected in cases:
        filepath = Path("script")
        content = f"{shebang}\nsome content\n"
        assert detect_language(filepath, content) == expected, f"Failed for: {shebang!r}"


def test_shebang_unknown_interpreter_returns_unknown():
    filepath = Path("run")
    content = "#!/usr/bin/awk -f\nsome content\n"
    assert detect_language(filepath, content) == "unknown"


def test_empty_content_no_extension_returns_unknown():
    filepath = Path("noext")
    assert detect_language(filepath, "") == "unknown"


# =============================================================================
# Extension takes precedence over shebang
# =============================================================================


def test_extension_wins_over_shebang():
    """When a file has a recognized extension, shebang is irrelevant."""
    filepath = Path("script.py")
    content = "#!/usr/bin/env node\nprint('python file with node shebang')\n"
    assert detect_language(filepath, content) == "python"
