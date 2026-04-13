"""Unit tests for language-aware adaptive chunking in miner.py."""

import sys as _sys

import pytest

from mempalace.miner import (
    HARD_MAX,
    MIN_CHUNK,
    TARGET_MAX,
    adaptive_merge_split,
    chunk_adaptive_lines,
    chunk_code,
    chunk_file,
    chunk_prose,
)


# =============================================================================
# Helpers
# =============================================================================


def contents(chunks):
    return [c["content"] for c in chunks]


def indices(chunks):
    return [c["chunk_index"] for c in chunks]


# =============================================================================
# chunk_code — Python
# =============================================================================


PYTHON_TWO_FUNCS = """\
def foo():
    \"\"\"Compute the foo result by iterating over a range.\"\"\"
    result = []
    for i in range(10):
        result.append(i * 2)
    return result


def bar():
    \"\"\"Compute the bar result by filtering even numbers from a range.\"\"\"
    return [x for x in range(20) if x % 2 == 0]
"""

PYTHON_CLASS_AND_METHODS = """\
class MyClass:
    \"\"\"A simple example class that holds a numeric value.

    Provides a basic history-tracking integer wrapper for demonstration
    purposes. The class is intentionally verbose to stay above MIN_CHUNK.
    \"\"\"

    DEFAULT_VALUE: int = 0
    MAX_HISTORY: int = 100

    def __init__(self, initial: int = 0):
        \"\"\"Initialise the instance with a starting value.\"\"\"
        self.x = initial
        self._history = []

    def method(self):
        \"\"\"Return the current value and record it in history.\"\"\"
        self._history.append(self.x)
        return self.x
"""

PYTHON_DECORATOR = """\
@property
def value(self):
    \"\"\"Return the underlying private value of this instance.\"\"\"
    return self._value


@value.setter
def value(self, v):
    \"\"\"Set the underlying private value, validating that it is non-negative.\"\"\"
    if v < 0:
        raise ValueError("value must be non-negative")
    self._value = v
"""

PYTHON_WITH_DOCSTRING_COMMENT = """\
# A module-level comment immediately above the function — must stay attached.
def documented():
    \"\"\"Does something meaningful that justifies the comment above.\"\"\"
    items = [i ** 2 for i in range(15)]
    return sum(items)
"""


def test_python_two_functions_no_boundary_crossing():
    chunks = chunk_code(PYTHON_TWO_FUNCS, ".py", "test.py")
    joined = "\n".join(contents(chunks))
    # Both functions are present in the output
    assert "def foo" in joined
    assert "def bar" in joined
    # Neither chunk contains parts of both functions (or they're merged small ones)
    for c in contents(chunks):
        # If a chunk contains both defs it must be a merged small chunk (total < TARGET_MAX)
        if "def foo" in c and "def bar" in c:
            assert len(c) <= TARGET_MAX


def test_python_class_produces_chunk():
    chunks = chunk_code(PYTHON_CLASS_AND_METHODS, ".py", "test.py")
    joined = "\n".join(contents(chunks))
    assert "class MyClass" in joined
    assert "def __init__" in joined


def test_python_decorator_starts_new_boundary():
    # Decorators act as boundary markers separating code units.
    # The short decorator lines themselves (<MIN_CHUNK) may be filtered out,
    # but the decorated function bodies must be present.
    chunks = chunk_code(PYTHON_DECORATOR, ".py", "test.py")
    joined = "\n".join(contents(chunks))
    assert "def value" in joined
    assert "self._value" in joined


def test_python_adjacent_comment_attached():
    chunks = chunk_code(PYTHON_WITH_DOCSTRING_COMMENT, ".py", "test.py")
    # The comment immediately above def should be in the same chunk as the def
    for c in contents(chunks):
        if "def documented" in c:
            assert "A module-level comment" in c
            break


def test_python_no_boundaries_falls_back_to_adaptive():
    # A file with no def/class/@ at line start falls back to blank-line splitting.
    # Content must be >= MIN_CHUNK to survive the filter.
    plain = (
        "x = 1\ny = 2\nsome_var = 'a value long enough to pass the hundred char minimum filter'\n\n"
        "z = 3\nw = 4\nanother_var = 'more content here to ensure this block is also above limit'\n"
    )
    chunks = chunk_code(plain, ".py", "test.py")
    assert len(chunks) >= 1


def test_python_empty_file():
    chunks = chunk_code("", ".py", "test.py")
    assert chunks == []


# =============================================================================
# chunk_code — TypeScript / JavaScript
# =============================================================================

TS_EXPORTS = """\
import React, { FC, ReactNode } from 'react';
import { useState, useEffect, useCallback } from 'react';

export function Foo(): JSX.Element {
    const [count, setCount] = useState(0);
    useEffect(() => { setCount(c => c + 1); }, []);
    return <div className="foo">count is {count}</div>;
}

export const bar = (): number => {
    const values = [1, 2, 3, 4, 5];
    return values.reduce((acc, v) => acc + v, 0);
};

export class Baz {
    private name: string;
    constructor(name: string) {
        this.name = name;
    }
    greet(): string {
        return `Hello from ${this.name}`;
    }
}
"""

TS_TEST_BLOCKS = """\
describe('math suite', () => {
    it('addition passes with positive numbers', () => {
        expect(1 + 1).toBe(2);
        expect(10 + 5).toBe(15);
    });

    it('subtraction yields correct result', () => {
        expect(10 - 3).toBe(7);
        expect(0 - 5).toBe(-5);
    });

    it('multiplication works as expected', () => {
        expect(3 * 4).toBe(12);
    });
});
"""

TS_JSDOC = """\
/**
 * Adds two numbers together and returns their sum.
 * Handles both integer and floating-point inputs correctly.
 */
export function add(a: number, b: number): number {
    if (typeof a !== 'number' || typeof b !== 'number') {
        throw new TypeError('Both arguments must be numbers');
    }
    return a + b;
}
"""


def test_ts_imports_grouped():
    chunks = chunk_code(TS_EXPORTS, ".ts", "test.ts")
    joined = "\n".join(contents(chunks))
    # Both imports should be present
    assert "import React" in joined
    assert "import { useState" in joined
    # Exports should be present
    assert "export function Foo" in joined
    assert "export const bar" in joined
    assert "export class Baz" in joined


def test_ts_no_chunk_splits_single_export():
    chunks = chunk_code(TS_EXPORTS, ".ts", "test.ts")
    # Each top-level export should not be split across two chunks
    for c in contents(chunks):
        if "export function Foo" in c:
            assert "count is {count}" in c


def test_ts_test_blocks_detected():
    chunks = chunk_code(TS_TEST_BLOCKS, ".ts", "test.ts")
    joined = "\n".join(contents(chunks))
    assert "describe" in joined
    assert "it('addition" in joined


def test_ts_jsdoc_attached_to_declaration():
    chunks = chunk_code(TS_JSDOC, ".ts", "test.ts")
    for c in contents(chunks):
        if "export function add" in c:
            assert "Adds two numbers" in c
            break


def test_js_extension_handled():
    simple_js = """\
function hello() {
    // Greet the user with a friendly message on the console output
    const message = "Hello from the hello function — this has enough content now";
    console.log(message);
    return message;
}

function world() {
    // Return a world greeting message with sufficient length for chunking
    const message = "World greeting from the world function — also has enough content";
    console.log(message);
    return message;
}
"""
    chunks = chunk_code(simple_js, ".js", "test.js")
    joined = "\n".join(contents(chunks))
    assert "function hello" in joined
    assert "function world" in joined


def test_tsx_extension_handled():
    chunks = chunk_code(TS_EXPORTS, ".tsx", "test.tsx")
    assert len(chunks) >= 1


# =============================================================================
# chunk_code — Go
# =============================================================================

GO_FUNCS = """\
package main

import "fmt"

func Foo() int {
    result := 0
    for i := 0; i < 10; i++ {
        result += i
    }
    fmt.Printf("Foo result: %d\\n", result)
    return result
}

func Bar() string {
    parts := []string{"hello", "world", "from", "go"}
    joined := ""
    for _, p := range parts {
        joined += p + " "
    }
    return joined
}

type MyStruct struct {
    X   int
    Y   int
    Tag string
}
"""


def test_go_func_boundaries():
    chunks = chunk_code(GO_FUNCS, ".go", "test.go")
    joined = "\n".join(contents(chunks))
    assert "func Foo" in joined
    assert "func Bar" in joined
    assert "type MyStruct" in joined


def test_go_no_split_across_func():
    chunks = chunk_code(GO_FUNCS, ".go", "test.go")
    for c in contents(chunks):
        if "func Foo" in c:
            assert "return result" in c


# =============================================================================
# chunk_prose — Markdown
# =============================================================================

MD_DOC = """\
# Introduction

This is the introduction section with enough text to pass the minimum chunk size filter.
It covers the background and motivation for the project and sets the scene for what follows.

## Section One

Content for section one — this section has substantial detail about the first topic.
It includes multiple sentences to ensure it exceeds the minimum chunk threshold of 100 chars.

## Section Two

Content for section two describes a different aspect of the system in adequate detail.
Multiple sentences ensure that this section is large enough to be retained as a chunk.

### Subsection

Nested content here provides additional granular information under section two.
This subsection also has enough text to be treated as a valid chunk on its own.
"""

MD_NO_HEADINGS = """\
Just some plain text without any headings — this paragraph has enough content to be kept.
It is long enough to pass the minimum chunk size filter used by the chunking logic.

Another paragraph here that also has sufficient length to be stored as a drawer chunk.
It adds more detail about a related topic without any structural heading markers.

And a third paragraph that rounds out the document with a final set of observations.
"""


def test_md_heading_boundaries():
    chunks = chunk_prose(MD_DOC, "doc.md")
    joined = "\n".join(contents(chunks))
    assert "Introduction" in joined
    assert "Section One" in joined
    assert "Section Two" in joined


def test_md_each_section_not_split():
    chunks = chunk_prose(MD_DOC, "doc.md")
    for c in contents(chunks):
        if "## Section One" in c:
            assert "Content for section one" in c


def test_md_no_headings_falls_back_to_paragraphs():
    chunks = chunk_prose(MD_NO_HEADINGS, "doc.md")
    joined = "\n".join(contents(chunks))
    assert "plain text" in joined
    assert "Another paragraph" in joined


def test_md_empty():
    chunks = chunk_prose("", "doc.md")
    assert chunks == []


# =============================================================================
# chunk_adaptive_lines — fallback
# =============================================================================

YAML_CONTENT = """\
name: my_project
version: 1.0.0
description: A sample project configuration file used for testing adaptive chunking.

dependencies:
  - requests>=2.28.0
  - pyyaml>=6.0
  - sentence-transformers>=2.2.0
  - lancedb>=0.17.0

dev:
  - pytest>=7.0
  - ruff>=0.4.0
  - mypy>=1.0
"""

JSON_LIKE = '{"key": "value", "nested": {"a": 1, "b": 2}, "extra": "padding content here"}\n' * 5


def test_adaptive_lines_blank_line_splitting():
    chunks = chunk_adaptive_lines(YAML_CONTENT, "config.yaml")
    assert len(chunks) >= 1
    joined = "\n".join(contents(chunks))
    assert "name: my_project" in joined


def test_adaptive_lines_single_block():
    # A single block >= MIN_CHUNK with no blank lines
    single = "key: value\nother: thing\nmore: content\nextra: padding to reach minimum size\n" * 2
    chunks = chunk_adaptive_lines(single, "config.yaml")
    assert len(chunks) >= 1


def test_adaptive_lines_empty():
    chunks = chunk_adaptive_lines("", "config.yaml")
    assert chunks == []


# =============================================================================
# chunk_file — dispatcher
# =============================================================================


def test_dispatcher_routes_py():
    # Use realistic Python content above MIN_CHUNK
    chunks = chunk_file(PYTHON_TWO_FUNCS, ".py", "f.py")
    assert len(chunks) >= 1


def test_dispatcher_routes_ts():
    chunks = chunk_file(TS_EXPORTS, ".ts", "f.ts")
    assert len(chunks) >= 1


def test_dispatcher_routes_go():
    chunks = chunk_file(GO_FUNCS, ".go", "f.go")
    assert len(chunks) >= 1


def test_dispatcher_routes_md():
    chunks = chunk_file(MD_DOC, ".md", "doc.md")
    assert len(chunks) >= 1


def test_dispatcher_routes_yaml_to_adaptive():
    chunks = chunk_file(YAML_CONTENT, ".yaml", "config.yaml")
    assert len(chunks) >= 1


def test_dispatcher_routes_json_to_adaptive():
    chunks = chunk_file(JSON_LIKE, ".json", "data.json")
    assert len(chunks) >= 1


def test_dispatcher_routes_sh_to_adaptive():
    sh = (
        "#!/bin/bash\n"
        "# This script sets up the development environment for local testing.\n\n"
        "echo 'Setting up environment — installing dependencies and running checks'\n\n"
        "pip install -e '.[dev]'\n"
        "ruff check mempalace/ tests/\n"
        "pytest tests/ -x -q\n"
    )
    chunks = chunk_file(sh, ".sh", "run.sh")
    assert len(chunks) >= 1


# =============================================================================
# adaptive_merge_split — merge and split behaviour
# =============================================================================


def test_merge_small_chunks():
    # Two 200-char chunks should be merged into one (combined < TARGET_MAX)
    small = "x" * 200
    chunks = adaptive_merge_split([small, small], "f.py")
    assert len(chunks) == 1
    assert len(chunks[0]["content"]) == 200 + 2 + 200  # "x"*200 + "\n\n" + "x"*200


def test_no_merge_when_combined_exceeds_target_max():
    # Two chunks that together exceed TARGET_MAX should stay separate
    big = "x" * (TARGET_MAX // 2 + 10)
    chunks = adaptive_merge_split([big, big], "f.py")
    assert len(chunks) == 2


def test_oversized_chunk_split():
    # A chunk exceeding HARD_MAX with paragraph breaks should be split
    para = ("y" * 500 + "\n\n") * 10  # ~5020 chars, well above HARD_MAX=4000
    chunks = adaptive_merge_split([para], "f.py")
    assert len(chunks) >= 2
    for c in chunks:
        assert len(c["content"]) <= TARGET_MAX + 10  # allow minor overshoot from last para


def test_oversized_single_line_returned_as_is():
    # A single minified line with no breaks should be stored as-is
    minified = "a" * (HARD_MAX + 100)
    chunks = adaptive_merge_split([minified], "f.py")
    assert len(chunks) == 1
    assert len(chunks[0]["content"]) == HARD_MAX + 100


def test_chunk_index_is_sequential():
    raws = ["a" * 150, "b" * 150, "c" * 150]
    chunks = adaptive_merge_split(raws, "f.py")
    assert indices(chunks) == list(range(len(chunks)))


def test_chunk_index_sequential_when_oversized_produces_tiny_tail():
    """chunk_index must be sequential even when _split_oversized emits a filtered-out tiny tail."""
    # Build an oversized chunk whose last paragraph is < MIN_CHUNK.
    # Two 2500-char paragraphs force _split_oversized to flush each separately;
    # the 99-char tail (< MIN_CHUNK=100) cannot merge with the second paragraph
    # (2500+99+2=2601 > TARGET_MAX=2500) so it lands in result as a tiny item.
    big_para = "x" * 2500
    tiny_tail = "y" * (MIN_CHUNK - 1)
    oversized = f"{big_para}\n\n{big_para}\n\n{tiny_tail}"  # total > HARD_MAX
    normal = "z" * 200

    chunks = adaptive_merge_split([oversized, normal], "f.py")
    ids = indices(chunks)
    assert ids == list(range(len(ids))), f"Non-sequential chunk_index: {ids}"


def test_tiny_chunks_below_min_skipped():
    raws = ["x" * (MIN_CHUNK - 1)]  # below MIN_CHUNK — should be filtered out
    chunks = adaptive_merge_split(raws, "f.py")
    assert chunks == []


def test_empty_raw_chunks():
    assert adaptive_merge_split([], "f.py") == []


# =============================================================================
# chunk_code — Rust
# =============================================================================

RUST_FUNCS = """\
use std::fmt;

fn add(a: i32, b: i32) -> i32 {
    // Add two integers and return the result with verbose logging
    let result = a + b;
    println!("add({}, {}) = {}", a, b, result);
    result
}

pub fn multiply(a: i32, b: i32) -> i32 {
    // Multiply two integers and return the product with verbose logging
    let result = a * b;
    println!("multiply({}, {}) = {}", a, b, result);
    result
}

pub(crate) fn subtract(a: i32, b: i32) -> i32 {
    // Subtract b from a and return the difference with verbose logging
    let result = a - b;
    println!("subtract({}, {}) = {}", a, b, result);
    result
}

pub async fn fetch_data(url: &str) -> String {
    // Async function that simulates fetching data from a remote URL
    println!("Fetching data from: {}", url);
    format!("data_from_{}", url)
}

struct Point {
    x: f64,
    y: f64,
}

pub struct Rectangle {
    width: f64,
    height: f64,
}

enum Color {
    Red,
    Green,
    Blue,
}

impl Point {
    fn distance(&self, other: &Point) -> f64 {
        let dx = self.x - other.x;
        let dy = self.y - other.y;
        (dx * dx + dy * dy).sqrt()
    }
}

trait Shape {
    fn area(&self) -> f64;
    fn perimeter(&self) -> f64;
}

mod geometry {
    pub fn pi() -> f64 {
        std::f64::consts::PI
    }
}

type Result<T> = std::result::Result<T, String>;
"""

RUST_WITH_ATTRIBUTE = """\
#[derive(Debug, Clone)]
pub struct Config {
    pub name: String,
    pub value: i32,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_config_creation() {
        let c = Config { name: "test".to_string(), value: 42 };
        assert_eq!(c.value, 42);
    }
}
"""

RUST_PUB_CRATE = """\
pub(crate) fn internal_helper(x: i32) -> i32 {
    // Internal helper function visible only within the crate
    let doubled = x * 2;
    let adjusted = doubled + 1;
    println!("internal_helper({}) = {}", x, adjusted);
    adjusted
}

pub(crate) struct InternalState {
    counter: u32,
    active: bool,
}
"""


def test_rust_fn_boundaries():
    chunks = chunk_code(RUST_FUNCS, ".rs", "test.rs")
    joined = "\n".join(contents(chunks))
    assert "fn add" in joined
    assert "pub fn multiply" in joined
    assert "pub(crate) fn subtract" in joined
    assert "pub async fn fetch_data" in joined


def test_rust_struct_enum_trait_detected():
    chunks = chunk_code(RUST_FUNCS, ".rs", "test.rs")
    joined = "\n".join(contents(chunks))
    assert "struct Point" in joined
    assert "enum Color" in joined
    assert "impl Point" in joined
    assert "trait Shape" in joined


def test_rust_mod_and_type_detected():
    chunks = chunk_code(RUST_FUNCS, ".rs", "test.rs")
    joined = "\n".join(contents(chunks))
    assert "mod geometry" in joined
    assert "type Result" in joined


def test_rust_attribute_macro_starts_boundary():
    chunks = chunk_code(RUST_WITH_ATTRIBUTE, ".rs", "test.rs")
    joined = "\n".join(contents(chunks))
    assert "derive(Debug" in joined
    assert "pub struct Config" in joined


def test_rust_pub_crate_fn_detected():
    chunks = chunk_code(RUST_PUB_CRATE, ".rs", "test.rs")
    joined = "\n".join(contents(chunks))
    assert "pub(crate) fn internal_helper" in joined
    assert "pub(crate) struct InternalState" in joined


def test_rust_via_language_string():
    """chunk_code() with language='rust' produces the same results as with ext='.rs'."""
    chunks_ext = chunk_code(RUST_FUNCS, ".rs", "test.rs")
    chunks_lang = chunk_code(RUST_FUNCS, "rust", "test.rs")
    assert contents(chunks_ext) == contents(chunks_lang)


# =============================================================================
# chunk_file — language parameter routing
# =============================================================================


def test_dispatcher_language_python():
    """chunk_file() with explicit language='python' routes to code chunking."""
    chunks = chunk_file(PYTHON_TWO_FUNCS, "", "f.py", language="python")
    joined = "\n".join(contents(chunks))
    assert "def foo" in joined
    assert "def bar" in joined


def test_dispatcher_language_typescript():
    chunks = chunk_file(TS_EXPORTS, "", "f.ts", language="typescript")
    assert len(chunks) >= 1
    joined = "\n".join(contents(chunks))
    assert "export function Foo" in joined


def test_dispatcher_language_rust():
    chunks = chunk_file(RUST_FUNCS, "", "f.rs", language="rust")
    assert len(chunks) >= 1
    joined = "\n".join(contents(chunks))
    assert "fn add" in joined


def test_dispatcher_language_markdown():
    chunks = chunk_file(MD_DOC, "", "doc.md", language="markdown")
    assert len(chunks) >= 1
    joined = "\n".join(contents(chunks))
    assert "Introduction" in joined


def test_dispatcher_language_unknown_falls_back():
    chunks = chunk_file(YAML_CONTENT, "", "config.yaml", language="unknown")
    assert len(chunks) >= 1


def test_dispatcher_language_overrides_ext():
    """When language is provided, it overrides the ext-based dispatch."""
    # .json extension would go to adaptive, but language="python" should route to code
    chunks = chunk_file(PYTHON_TWO_FUNCS, ".json", "weird.json", language="python")
    joined = "\n".join(contents(chunks))
    assert "def foo" in joined


# =============================================================================
# chunk_code — Python AST path (tree-sitter, Python 3.10+ only)
# =============================================================================


PYTHON_DECORATED_FUNCS = """\
@property
def computed_value(self):
    \"\"\"Return the computed value derived from internal state and history.\"\"\"
    total = sum(self._history) if self._history else 0
    return self._base + total


@computed_value.setter
def computed_value(self, v):
    \"\"\"Set the base value, validating it is a non-negative integer input.\"\"\"
    if not isinstance(v, int) or v < 0:
        raise ValueError("computed_value must be a non-negative integer")
    self._base = v
"""

PYTHON_PREAMBLE_WITH_IMPORTS = """\
\"\"\"Module docstring describing the purpose of this Python module file.\"\"\"

import os
import sys
from pathlib import Path
from typing import Optional, List


def main(args: List[str]) -> int:
    \"\"\"Entry point for the command-line interface of this module.\"\"\"
    for arg in args:
        path = Path(arg)
        if path.exists():
            print(f"Found: {path}")
    return 0


def helper(value: Optional[int] = None) -> str:
    \"\"\"Convert an optional integer to its string representation safely.\"\"\"
    return str(value) if value is not None else "none"
"""

PYTHON_NESTED_CLASS = """\
class Outer:
    \"\"\"An outer class that contains a nested inner class definition.

    This class demonstrates that tree-sitter top-level chunking keeps the
    entire outer class — including any nested classes — as one unit.
    \"\"\"

    class Inner:
        \"\"\"Inner class nested inside Outer — must stay in the same chunk.\"\"\"

        def inner_method(self):
            \"\"\"Return a constant string from the inner class method body.\"\"\"
            return "inner"

    def outer_method(self):
        \"\"\"Return a constant string from the outer class method body.\"\"\"
        return "outer"
"""

PYTHON_COMMENT_ATTACHED = """\
import logging

logger = logging.getLogger(__name__)


# This leading comment must be attached to the function directly below it.
# It spans two lines and has no blank line between it and the def keyword.
def process(data):
    \"\"\"Process the given data and return a transformed result string.\"\"\"
    logger.info("processing %d items", len(data))
    return [str(x) for x in data]


# A detached comment with a blank line below it.

def standalone():
    \"\"\"This function has a detached comment above — not attached to it.\"\"\"
    return []
"""


def _skip_if_no_ast():
    """Skip test if tree-sitter Python AST path is not active."""
    if _sys.version_info < (3, 10):
        pytest.skip("tree-sitter-python requires Python 3.10+")
    try:
        import tree_sitter  # noqa: F401
        import tree_sitter_python  # noqa: F401
    except ImportError:
        pytest.skip("tree-sitter-python not installed")


def test_ast_decorated_functions_detected():
    """AC-1: decorated_definition nodes produce separate chunk boundaries."""
    _skip_if_no_ast()
    chunks = chunk_code(PYTHON_DECORATED_FUNCS, ".py", "test.py")
    joined = "\n".join(contents(chunks))
    assert "def computed_value" in joined
    assert "self._base" in joined


def test_ast_chunker_strategy_tag():
    """AC-1/AC-4: chunks from AST path carry chunker_strategy='treesitter_v1'."""
    _skip_if_no_ast()
    chunks = chunk_code(PYTHON_TWO_FUNCS, ".py", "test.py")
    assert len(chunks) >= 1
    for chunk in chunks:
        assert chunk.get("chunker_strategy") == "treesitter_v1"


def test_ast_preamble_content_preserved():
    """AC-5: preamble (imports, module docstring) appears in the output."""
    _skip_if_no_ast()
    chunks = chunk_code(PYTHON_PREAMBLE_WITH_IMPORTS, ".py", "test.py")
    joined = "\n".join(contents(chunks))
    assert "import os" in joined
    assert "def main" in joined
    assert "def helper" in joined


def test_ast_nested_class_stays_together():
    """AC-1: nested inner class is not split from its outer class."""
    _skip_if_no_ast()
    chunks = chunk_code(PYTHON_NESTED_CLASS, ".py", "test.py")
    joined = "\n".join(contents(chunks))
    assert "class Outer" in joined
    assert "class Inner" in joined
    # The inner class must not appear in a chunk that does not also contain Outer
    for c in contents(chunks):
        if "class Inner" in c:
            assert "class Outer" in c


def test_ast_leading_comment_attached_to_def():
    """AC-6: comments immediately above a def with no blank line are in the same chunk."""
    _skip_if_no_ast()
    chunks = chunk_code(PYTHON_COMMENT_ATTACHED, ".py", "test.py")
    for c in contents(chunks):
        if "def process" in c:
            assert "This leading comment must be attached" in c
            break
    else:
        pytest.fail("def process not found in any chunk")


def test_ast_empty_file_returns_empty():
    """AC-1: empty Python file produces no chunks via AST path."""
    _skip_if_no_ast()
    chunks = chunk_code("", ".py", "test.py")
    assert chunks == []


def test_ast_no_definitions_falls_back_to_adaptive():
    """AC-2 complement: Python file with no def/class still produces chunks."""
    _skip_if_no_ast()
    plain = (
        "x = 1\ny = 2\nsome_var = 'a value long enough to pass the hundred char minimum filter'\n\n"
        "z = 3\nw = 4\nanother_var = 'more content here to ensure this block is also above limit'\n"
    )
    chunks = chunk_code(plain, ".py", "test.py")
    assert len(chunks) >= 1
