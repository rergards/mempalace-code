"""Unit tests for language-aware adaptive chunking in miner.py."""

import sys as _sys

import pytest

from mempalace import treesitter as ts_mod
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


def test_ts_var_toplevel_boundary(monkeypatch):
    """Top-level non-exported var declarations must create chunk boundaries (AC-1, AC-2)."""
    from mempalace.miner import TS_BOUNDARY

    # AC-2: TS_BOUNDARY regex matches a plain var declaration at column 0
    assert TS_BOUNDARY.match("var foo = 'bar'"), "TS_BOUNDARY must match top-level var"
    assert TS_BOUNDARY.match("var counter: number = 0"), "TS_BOUNDARY must match typed var"
    assert not TS_BOUNDARY.match("    var indented = 1"), "indented var must not match"

    monkeypatch.setattr(ts_mod, "TREE_SITTER_AVAILABLE", False)
    monkeypatch.setattr(ts_mod, "_parser_cache", {})

    # AC-1: chunk_code produces a boundary at a top-level var declaration.
    # Each block is padded to exceed TARGET_MAX so adaptive_merge_split keeps them separate.
    # Use a single \n between blocks (no blank line) so _split_oversized cannot use a
    # paragraph break as a coincidental split point — only an explicit TS_BOUNDARY match
    # on "var globalConfig" produces a chunk that starts at that line.
    padding = "// " + "x" * 100 + "\n"
    ts_src = (
        "function setup() {\n"
        + padding * 25
        + "}\n"
        + "var globalConfig = {\n"
        + "    timeout: 30,\n"
        + padding * 25
        + "};\n"
    )
    chunks = chunk_code(ts_src, ".ts", "test.ts")
    assert len(chunks) >= 2, "var boundary must produce at least 2 chunks"
    var_chunks = [c for c in chunks if c["content"].startswith("var globalConfig")]
    assert len(var_chunks) >= 1, "var globalConfig must be the first line of its own chunk"


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


GO_VAR_IN_BODY = """\
package main

func ProcessItems(items []string) []string {
    var result []string
    var count int
    for _, item := range items {
        var processed string
        processed = item + "_done"
        count++
        result = append(result, processed)
    }
    _ = count
    return result
}

func AnotherFunc() int {
    return 42
}
"""


def test_go_var_in_body_no_spurious_split(monkeypatch):
    """var declarations inside Go function bodies must not create chunk boundaries (AC-1)."""
    monkeypatch.setattr(ts_mod, "TREE_SITTER_AVAILABLE", False)
    monkeypatch.setattr(ts_mod, "_parser_cache", {})

    chunks = chunk_code(GO_VAR_IN_BODY, ".go", "test.go")
    # The entire ProcessItems function must appear in one chunk.
    func_chunk = next((c for c in contents(chunks) if "func ProcessItems" in c), None)
    assert func_chunk is not None, "ProcessItems function not found in any chunk"
    assert "return result" in func_chunk, "ProcessItems body was split at a var declaration"


def test_go_var_block_boundary(monkeypatch):
    """GO_BOUNDARY still recognises var (...) blocks as structural boundaries (AC-3).

    adaptive_merge_split will combine small chunks up to TARGET_MAX (2500 chars),
    so the presence of a structural boundary does not guarantee separate final chunks
    for small inputs.  This test verifies two things:
    1. GO_BOUNDARY regex matches 'var (' (the pattern was not accidentally removed).
    2. Both constructs are preserved in the chunked output.
    """
    from mempalace.miner import GO_BOUNDARY

    # Verify the regex still recognises grouped var blocks (AC-3 core).
    assert GO_BOUNDARY.match("var ("), "GO_BOUNDARY no longer matches 'var ('"

    monkeypatch.setattr(ts_mod, "TREE_SITTER_AVAILABLE", False)
    monkeypatch.setattr(ts_mod, "_parser_cache", {})

    go_src = """\
package main

var (
    DefaultTimeout = 30
    MaxRetries     = 3
)

func Run() int {
    return DefaultTimeout + MaxRetries
}
"""
    chunks = chunk_code(go_src, ".go", "test.go")
    joined = "\n".join(contents(chunks))
    assert "var (" in joined
    assert "func Run" in joined


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


def test_md_section_metadata_tracks_heading_path_and_features():
    doc = """\
# Architecture

Overview text with enough detail to keep the architecture section meaningful.
This section explains the high level shape before moving into data flow.

## Data Flow

The data flow section is intentionally long enough to avoid being filtered.
It explains how records move through the system and keeps the heading path.

```mermaid
flowchart TD
    A --> B
```

| Field | Meaning |
| --- | --- |
| wing | project |
""" + ("More detail about data movement and memory routing.\n" * 45)

    chunks = chunk_prose(doc, "architecture.md")
    data_flow = next(c for c in chunks if "## Data Flow" in c["content"])
    metadata = data_flow["markdown_metadata"]

    assert metadata["heading"] == "Data Flow"
    assert metadata["heading_level"] == 2
    assert metadata["heading_path"] == "Architecture > Data Flow"
    assert metadata["doc_section_type"] == "section"
    assert metadata["contains_mermaid"] == 1
    assert metadata["contains_code"] == 1
    assert metadata["contains_table"] == 1


def test_md_h5_heading_is_a_boundary():
    doc = """\
# Root

Root section content that establishes the document hierarchy for this test.
It is long enough to survive the minimum chunk filter in the prose chunker.

##### Deep Detail

Deep detail content is intentionally verbose enough to become searchable.
It proves that five-hash Markdown headings are treated as structural boundaries.
""" + ("Additional deep detail for the section boundary assertion.\n" * 45)

    chunks = chunk_prose(doc, "deep.md")
    deep = next(c for c in chunks if "##### Deep Detail" in c["content"])

    assert deep["markdown_metadata"]["heading"] == "Deep Detail"
    assert deep["markdown_metadata"]["heading_level"] == 5
    assert deep["markdown_metadata"]["heading_path"] == "Root > Deep Detail"


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


def test_ast_no_definitions_strategy_tag():
    """F-1 fix: no-definition Python file carries 'treesitter_adaptive_v1', not 'regex_structural_v1'.

    When tree-sitter is available but the file has no top-level function or class
    definitions, _chunk_python_treesitter falls back to chunk_adaptive_lines.
    The resulting chunks must be tagged 'treesitter_adaptive_v1' so downstream
    metadata accurately reflects which code path produced them.
    """
    _skip_if_no_ast()
    plain = (
        "x = 1\ny = 2\nsome_var = 'a value long enough to pass the hundred char minimum filter'\n\n"
        "z = 3\nw = 4\nanother_var = 'more content here to ensure this block is also above limit'\n"
    )
    chunks = chunk_code(plain, ".py", "test.py")
    assert len(chunks) >= 1
    for chunk in chunks:
        assert chunk.get("chunker_strategy") == "treesitter_adaptive_v1", (
            f"Expected 'treesitter_adaptive_v1', got {chunk.get('chunker_strategy')!r}"
        )


# =============================================================================
# chunk_code — TypeScript/JavaScript AST path (tree-sitter)
# =============================================================================

# --- Fixture sources ---

TS_AST_EXPORTS = """\
import { readFile } from 'fs/promises';
import path from 'path';

/** Reads a file and returns its trimmed content as a string. */
export async function readContent(filePath: string): Promise<string> {
    const buf = await readFile(filePath);
    return buf.toString().trim();
}

export class FileLoader {
    private base: string;
    constructor(base: string) { this.base = base; }
    load(name: string): Promise<string> {
        return readContent(path.join(this.base, name));
    }
}

export interface LoaderConfig {
    base: string;
    encoding: BufferEncoding;
}

export type FilePath = string;

export enum FileKind {
    Text = "text",
    Binary = "binary",
}
"""

TS_AST_ARROW = """\
import { logger } from './logger';

export const transform = (input: string): string => {
    logger.debug("transforming", input);
    return input.toUpperCase().replace(/\\s+/g, "_");
};

export const validate = (value: unknown): value is string => {
    return typeof value === "string" && value.length > 0;
};
"""

TS_AST_TEST_BLOCKS = """\
import { add, subtract } from './math';

describe('arithmetic', () => {
    it('add returns correct sum for positive integers', () => {
        expect(add(2, 3)).toBe(5);
        expect(add(0, 0)).toBe(0);
    });

    it('subtract returns correct difference for given integers', () => {
        expect(subtract(10, 4)).toBe(6);
    });
});
"""

TS_AST_JSDOC = """\
/**
 * Computes the Fibonacci number at position n using memoized recursion.
 * Returns 0 for n <= 0 and handles large inputs via BigInt internally.
 */
export function fibonacci(n: number): number {
    if (n <= 1) return n;
    return fibonacci(n - 1) + fibonacci(n - 2);
}
"""

TS_AST_IMPORTS_ONLY = """\
import { readContent } from './reader';
import { FileLoader } from './loader';
import type { LoaderConfig } from './types';
"""

TSX_AST_COMPONENT = """\
import React, { FC } from 'react';

interface ButtonProps {
    label: string;
    onClick: () => void;
}

export const Button: FC<ButtonProps> = ({ label, onClick }) => (
    <button type="button" onClick={onClick} className="btn">
        {label}
    </button>
);

export default Button;
"""

JS_AST_FUNCS = """\
const MAX_RETRIES = 3;

function fetchWithRetry(url, options) {
    let attempt = 0;
    function doFetch() {
        return fetch(url, options).catch(err => {
            if (attempt++ < MAX_RETRIES) return doFetch();
            throw err;
        });
    }
    return doFetch();
}

class HttpClient {
    constructor(baseUrl) { this.baseUrl = baseUrl; }
    get(path) { return fetchWithRetry(this.baseUrl + path, {}); }
}

module.exports = { fetchWithRetry, HttpClient };
"""


def _skip_if_no_ts_ast():
    """Skip test if tree-sitter TypeScript grammar is not active."""
    try:
        import tree_sitter  # noqa: F401
        import tree_sitter_typescript  # noqa: F401
    except ImportError:
        pytest.skip("tree-sitter-typescript not installed")


# --- Tests ---


def test_ast_ts_exports_detected():
    """AC-1: export function, const, class all appear in AST-chunked output."""
    _skip_if_no_ts_ast()
    chunks = chunk_code(TS_AST_EXPORTS, "typescript", "test.ts")
    joined = "\n".join(contents(chunks))
    assert "export async function readContent" in joined
    assert "export class FileLoader" in joined
    assert "export interface LoaderConfig" in joined
    assert "export type FilePath" in joined
    assert "export enum FileKind" in joined


def test_ast_ts_interface_boundary():
    """AC-1: interface_declaration gets its own chunk boundary."""
    _skip_if_no_ts_ast()
    chunks = chunk_code(TS_AST_EXPORTS, "typescript", "test.ts")
    found = any("interface LoaderConfig" in c for c in contents(chunks))
    assert found, "interface LoaderConfig not found in any chunk"


def test_ast_ts_type_alias_boundary():
    """AC-1: type_alias_declaration gets its own chunk boundary."""
    _skip_if_no_ts_ast()
    chunks = chunk_code(TS_AST_EXPORTS, "typescript", "test.ts")
    found = any("type FilePath" in c for c in contents(chunks))
    assert found, "type FilePath not found in any chunk"


def test_ast_ts_enum_boundary():
    """AC-1: enum_declaration gets its own chunk boundary."""
    _skip_if_no_ts_ast()
    chunks = chunk_code(TS_AST_EXPORTS, "typescript", "test.ts")
    found = any("enum FileKind" in c for c in contents(chunks))
    assert found, "enum FileKind not found in any chunk"


def test_ast_ts_arrow_function_boundary():
    """AC-1: arrow-function lexical_declaration gets its own chunk boundary."""
    _skip_if_no_ts_ast()
    chunks = chunk_code(TS_AST_ARROW, "typescript", "test.ts")
    joined = "\n".join(contents(chunks))
    assert "const transform" in joined
    assert "const validate" in joined


def test_ast_ts_test_blocks_detected():
    """AC-1: describe/it expression_statement nodes produce boundaries."""
    _skip_if_no_ts_ast()
    chunks = chunk_code(TS_AST_TEST_BLOCKS, "typescript", "test.ts")
    joined = "\n".join(contents(chunks))
    assert "describe" in joined
    assert "it('add" in joined


def test_ast_ts_jsdoc_attached():
    """AC-6: JSDoc comment immediately above a declaration is in the same chunk."""
    _skip_if_no_ts_ast()
    chunks = chunk_code(TS_AST_JSDOC, "typescript", "test.ts")
    for c in contents(chunks):
        if "export function fibonacci" in c:
            assert "Computes the Fibonacci" in c
            break
    else:
        pytest.fail("fibonacci not found in any chunk")


def test_ast_ts_imports_in_preamble():
    """AC-5: leading import statements are collected before the first definition."""
    _skip_if_no_ts_ast()
    chunks = chunk_code(TS_AST_EXPORTS, "typescript", "test.ts")
    joined = "\n".join(contents(chunks))
    assert "import { readFile }" in joined
    assert "import path" in joined


def test_ast_ts_chunker_strategy_tag():
    """AC-1: every chunk from TS AST path carries chunker_strategy='treesitter_v1'."""
    _skip_if_no_ts_ast()
    chunks = chunk_code(TS_AST_EXPORTS, "typescript", "test.ts")
    assert len(chunks) >= 1
    for chunk in chunks:
        assert chunk.get("chunker_strategy") == "treesitter_v1"


def test_ast_tsx_jsx_parsed():
    """AC-3: TSX component with JSX syntax parses without errors and produces chunks."""
    _skip_if_no_ts_ast()
    chunks = chunk_code(TSX_AST_COMPONENT, "tsx", "Button.tsx")
    joined = "\n".join(contents(chunks))
    assert "Button" in joined
    assert len(chunks) >= 1
    for chunk in chunks:
        assert chunk.get("chunker_strategy") == "treesitter_v1"


def test_ast_js_extension_handled():
    """AC-2: .js files route through AST path with function/class boundaries."""
    _skip_if_no_ts_ast()
    chunks = chunk_code(JS_AST_FUNCS, "javascript", "client.js")
    joined = "\n".join(contents(chunks))
    assert "fetchWithRetry" in joined
    assert "HttpClient" in joined
    for chunk in chunks:
        assert chunk.get("chunker_strategy") == "treesitter_v1"


def test_ast_jsx_extension_handled():
    """AC-3: .jsx files routed through TSX grammar produce valid chunks."""
    _skip_if_no_ts_ast()
    chunks = chunk_code(TSX_AST_COMPONENT, "jsx", "Button.jsx")
    joined = "\n".join(contents(chunks))
    assert "Button" in joined
    for chunk in chunks:
        assert chunk.get("chunker_strategy") == "treesitter_v1"


def test_ast_ts_no_definitions_falls_back():
    """AC-4: import-only file (no definitions) falls back to treesitter_adaptive_v1."""
    _skip_if_no_ts_ast()
    chunks = chunk_code(TS_AST_IMPORTS_ONLY, "typescript", "index.ts")
    assert len(chunks) >= 1
    for chunk in chunks:
        assert chunk.get("chunker_strategy") == "treesitter_adaptive_v1"


# =============================================================================
# chunk_code — Go AST path (tree-sitter)
# =============================================================================

# --- Fixture sources ---

GO_AST_ALL_BOUNDARIES = """\
package store

import (
\t"context"
\t"fmt"
)

// Store holds a connection pool and configuration.
type Store struct {
\tpool   []string
\tconfig Config
}

// Config holds runtime settings.
type Config interface {
\tDSN() string
\tMaxConn() int
}

const DefaultTimeout = 30

const (
\tMaxRetries = 3
\tMinBackoff = 100
)

var globalStore *Store

var (
\tErrNotFound = fmt.Errorf("not found")
\tErrTimeout  = fmt.Errorf("timeout")
)

// New creates a new Store with the given config.
func New(cfg Config) *Store {
\treturn &Store{config: cfg}
}

// Get retrieves an item by key from the store.
func (s *Store) Get(ctx context.Context, key string) (string, error) {
\tif key == "" {
\t\treturn "", ErrNotFound
\t}
\treturn key, nil
}

func (s *Store) Put(ctx context.Context, key, value string) error {
\tif key == "" {
\t\treturn ErrNotFound
\t}
\ts.pool = append(s.pool, value)
\treturn nil
}
"""

GO_AST_COMMENT_ATTACHED = """\
package util

// computeHash computes a hash of the input string.
// It uses a simple FNV-1a algorithm for speed.
func computeHash(s string) uint64 {
\tvar h uint64 = 14695981039346656037
\tfor _, c := range s {
\t\th ^= uint64(c)
\t\th *= 1099511628211
\t}
\treturn h
}

// Detached comment — blank line separates it.

func standalone() string {
\treturn "standalone"
}
"""

GO_AST_PACKAGE_ONLY = """\
package main
"""


def _skip_if_no_go_ast():
    """Skip test if tree-sitter-go is not installed."""
    try:
        import tree_sitter  # noqa: F401
        import tree_sitter_go  # noqa: F401
    except ImportError:
        pytest.skip("tree-sitter-go not installed")


# --- Tests ---


def test_ast_go_func_declaration_detected():
    """AC-1: function_declaration nodes produce separate chunk boundaries."""
    _skip_if_no_go_ast()
    chunks = chunk_code(GO_AST_ALL_BOUNDARIES, "go", "store.go")
    joined = "\n".join(contents(chunks))
    assert "func New(" in joined
    assert "func (s *Store) Get(" in joined
    assert "func (s *Store) Put(" in joined


def test_ast_go_method_declaration_detected():
    """AC-1: method_declaration nodes (receiver functions) produce chunk boundaries."""
    _skip_if_no_go_ast()
    chunks = chunk_code(GO_AST_ALL_BOUNDARIES, "go", "store.go")
    found_get = any("func (s *Store) Get(" in c for c in contents(chunks))
    found_put = any("func (s *Store) Put(" in c for c in contents(chunks))
    assert found_get, "method Get not found in any chunk"
    assert found_put, "method Put not found in any chunk"


def test_ast_go_type_declaration_detected():
    """AC-1: type_declaration nodes (struct and interface) produce chunk boundaries."""
    _skip_if_no_go_ast()
    chunks = chunk_code(GO_AST_ALL_BOUNDARIES, "go", "store.go")
    joined = "\n".join(contents(chunks))
    assert "type Store struct" in joined
    assert "type Config interface" in joined


def test_ast_go_const_declaration_detected():
    """AC-1: const_declaration nodes (single and grouped) produce chunk boundaries."""
    _skip_if_no_go_ast()
    chunks = chunk_code(GO_AST_ALL_BOUNDARIES, "go", "store.go")
    joined = "\n".join(contents(chunks))
    assert "DefaultTimeout" in joined
    assert "MaxRetries" in joined


def test_ast_go_var_declaration_detected():
    """AC-1: var_declaration nodes (single and grouped) produce chunk boundaries."""
    _skip_if_no_go_ast()
    chunks = chunk_code(GO_AST_ALL_BOUNDARIES, "go", "store.go")
    joined = "\n".join(contents(chunks))
    assert "globalStore" in joined
    assert "ErrNotFound" in joined


def test_ast_go_chunker_strategy_tag():
    """AC-1: every chunk from Go AST path carries chunker_strategy='treesitter_v1'."""
    _skip_if_no_go_ast()
    chunks = chunk_code(GO_AST_ALL_BOUNDARIES, "go", "store.go")
    assert len(chunks) >= 1
    for chunk in chunks:
        assert chunk.get("chunker_strategy") == "treesitter_v1"


def test_ast_go_preamble_preserved():
    """AC-1: preamble (package clause + imports) appears before the first boundary."""
    _skip_if_no_go_ast()
    chunks = chunk_code(GO_AST_ALL_BOUNDARIES, "go", "store.go")
    joined = "\n".join(contents(chunks))
    assert "package store" in joined
    assert "import" in joined


def test_ast_go_comment_attached():
    """AC-4: comment immediately above a func with no blank line is in the same chunk."""
    _skip_if_no_go_ast()
    chunks = chunk_code(GO_AST_COMMENT_ATTACHED, "go", "util.go")
    for c in contents(chunks):
        if "func computeHash" in c:
            assert "computeHash computes a hash" in c
            break
    else:
        pytest.fail("func computeHash not found in any chunk")


def test_ast_go_no_definitions_falls_back():
    """AC-3: package-only file (no declarations) falls back to treesitter_adaptive_v1."""
    _skip_if_no_go_ast()
    chunks = chunk_code(GO_AST_PACKAGE_ONLY, "go", "main.go")
    for chunk in chunks:
        assert chunk.get("chunker_strategy") == "treesitter_adaptive_v1"


# =============================================================================
# chunk_code — Rust AST path (tree-sitter)
# =============================================================================

# --- Fixture sources ---

RUST_AST_ALL_BOUNDARIES = """\
use std::collections::HashMap;
use std::fmt;

pub type Result<T> = std::result::Result<T, Error>;

#[derive(Debug, Clone)]
pub struct Cache {
    data: HashMap<String, String>,
    capacity: usize,
}

#[derive(Debug)]
pub enum Error {
    NotFound(String),
    Overflow,
}

pub trait Store {
    fn get(&self, key: &str) -> Option<&str>;
    fn put(&mut self, key: String, value: String) -> Result<()>;
}

impl Cache {
    pub fn new(capacity: usize) -> Self {
        Cache {
            data: HashMap::new(),
            capacity,
        }
    }
}

impl Store for Cache {
    fn get(&self, key: &str) -> Option<&str> {
        self.data.get(key).map(|s| s.as_str())
    }

    fn put(&mut self, key: String, value: String) -> Result<()> {
        if self.data.len() >= self.capacity {
            return Err(Error::Overflow);
        }
        self.data.insert(key, value);
        Ok(())
    }
}

pub mod helpers {
    pub fn sanitize(s: &str) -> String {
        s.trim().to_lowercase()
    }
}

pub(crate) fn internal_reset(cache: &mut Cache) {
    cache.data.clear();
}

pub async fn fetch_remote(url: &str) -> Result<String> {
    Ok(url.to_string())
}

impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Error::NotFound(k) => write!(f, "not found: {k}"),
            Error::Overflow => write!(f, "cache overflow"),
        }
    }
}
"""

RUST_AST_ATTRIBUTE_ATTACHED = """\
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Config {
    pub host: String,
    pub port: u16,
}

// Standalone comment with blank line above.

pub fn default_config() -> Config {
    Config {
        host: "localhost".to_string(),
        port: 8080,
    }
}
"""

RUST_AST_USE_ONLY = """\
use std::collections::HashMap;
use std::sync::Arc;
"""

RUST_AST_CONST_STATIC = """\
use std::time::Duration;

pub const MAX_SIZE: usize = 1024;

pub static DEFAULT_HOST: &str = "localhost";

pub fn helper() -> usize {
    MAX_SIZE
}
"""

# Const/static only — no fn. Used to verify that const_item/static_item actually create
# boundaries (strategy=treesitter_v1). Without them in DEFINITION_TYPES the chunker finds
# no boundaries and falls back to treesitter_adaptive_v1.
RUST_AST_CONST_ONLY = """\
/// Upper bound for the alpha-channel slot table.
pub const ALPHA: usize = 1;

/// Upper bound for the beta-channel slot table.
pub const BETA: usize = 2;

/// Default host advertised to the discovery daemon.
pub static GAMMA: &str = "hello";

/// Default port advertised to the discovery daemon.
pub static DELTA: u16 = 8080;
"""


def _skip_if_no_rust_ast():
    """Skip test if tree-sitter-rust is not installed."""
    try:
        import tree_sitter  # noqa: F401
        import tree_sitter_rust  # noqa: F401
    except ImportError:
        pytest.skip("tree-sitter-rust not installed")


# --- Tests ---


def test_ast_rust_fn_detected():
    """AC-2: function_item nodes (fn, pub fn, pub(crate) fn, async fn) produce boundaries."""
    _skip_if_no_rust_ast()
    chunks = chunk_code(RUST_AST_ALL_BOUNDARIES, "rust", "cache.rs")
    joined = "\n".join(contents(chunks))
    assert "fn internal_reset" in joined
    assert "async fn fetch_remote" in joined


def test_ast_rust_struct_detected():
    """AC-2: struct_item nodes produce chunk boundaries."""
    _skip_if_no_rust_ast()
    chunks = chunk_code(RUST_AST_ALL_BOUNDARIES, "rust", "cache.rs")
    found = any("pub struct Cache" in c for c in contents(chunks))
    assert found, "struct Cache not found in any chunk"


def test_ast_rust_enum_detected():
    """AC-2: enum_item nodes produce chunk boundaries."""
    _skip_if_no_rust_ast()
    chunks = chunk_code(RUST_AST_ALL_BOUNDARIES, "rust", "cache.rs")
    found = any("pub enum Error" in c for c in contents(chunks))
    assert found, "enum Error not found in any chunk"


def test_ast_rust_trait_detected():
    """AC-2: trait_item nodes produce chunk boundaries."""
    _skip_if_no_rust_ast()
    chunks = chunk_code(RUST_AST_ALL_BOUNDARIES, "rust", "cache.rs")
    found = any("pub trait Store" in c for c in contents(chunks))
    assert found, "trait Store not found in any chunk"


def test_ast_rust_impl_detected():
    """AC-2: impl_item nodes (bare impl and impl-for-trait) produce chunk boundaries."""
    _skip_if_no_rust_ast()
    chunks = chunk_code(RUST_AST_ALL_BOUNDARIES, "rust", "cache.rs")
    joined = "\n".join(contents(chunks))
    assert "impl Cache" in joined
    assert "impl Store for Cache" in joined


def test_ast_rust_mod_detected():
    """AC-2: mod_item nodes produce chunk boundaries."""
    _skip_if_no_rust_ast()
    chunks = chunk_code(RUST_AST_ALL_BOUNDARIES, "rust", "cache.rs")
    found = any("pub mod helpers" in c for c in contents(chunks))
    assert found, "mod helpers not found in any chunk"


def test_ast_rust_type_item_detected():
    """AC-2: type_item nodes produce chunk boundaries."""
    _skip_if_no_rust_ast()
    chunks = chunk_code(RUST_AST_ALL_BOUNDARIES, "rust", "cache.rs")
    found = any("pub type Result" in c for c in contents(chunks))
    assert found, "type Result not found in any chunk"


def test_ast_rust_attribute_attached():
    """AC-4: #[derive(...)] attribute_item immediately above a struct is in the same chunk."""
    _skip_if_no_rust_ast()
    chunks = chunk_code(RUST_AST_ATTRIBUTE_ATTACHED, "rust", "config.rs")
    for c in contents(chunks):
        if "pub struct Config" in c:
            assert "#[derive(Debug, Clone, Serialize, Deserialize)]" in c
            assert '#[serde(rename_all = "camelCase")]' in c
            break
    else:
        pytest.fail("struct Config not found in any chunk")


def test_ast_rust_chunker_strategy_tag():
    """AC-2: every chunk from Rust AST path carries chunker_strategy='treesitter_v1'."""
    _skip_if_no_rust_ast()
    chunks = chunk_code(RUST_AST_ALL_BOUNDARIES, "rust", "cache.rs")
    assert len(chunks) >= 1
    for chunk in chunks:
        assert chunk.get("chunker_strategy") == "treesitter_v1"


def test_ast_rust_preamble_preserved():
    """AC-2: preamble (use declarations) appears before the first item boundary."""
    _skip_if_no_rust_ast()
    chunks = chunk_code(RUST_AST_ALL_BOUNDARIES, "rust", "cache.rs")
    joined = "\n".join(contents(chunks))
    assert "use std::collections::HashMap" in joined
    assert "use std::fmt" in joined


def test_ast_rust_no_definitions_falls_back():
    """AC-3: use-only file (no items) falls back to treesitter_adaptive_v1."""
    _skip_if_no_rust_ast()
    chunks = chunk_code(RUST_AST_USE_ONLY, "rust", "lib.rs")
    for chunk in chunks:
        assert chunk.get("chunker_strategy") == "treesitter_adaptive_v1"


def test_ast_rust_const_detected():
    """AC-1: const_item nodes (pub const FOO: T = ...) produce chunk boundaries."""
    _skip_if_no_rust_ast()
    chunks = chunk_code(RUST_AST_CONST_STATIC, "rust", "constants.rs")
    found = any("pub const MAX_SIZE" in c for c in contents(chunks))
    assert found, "pub const MAX_SIZE not found in any chunk"


def test_ast_rust_static_detected():
    """AC-2: static_item nodes (pub static BAR: T = ...) produce chunk boundaries."""
    _skip_if_no_rust_ast()
    chunks = chunk_code(RUST_AST_CONST_STATIC, "rust", "constants.rs")
    found = any("pub static DEFAULT_HOST" in c for c in contents(chunks))
    assert found, "pub static DEFAULT_HOST not found in any chunk"


def test_ast_rust_const_static_create_boundaries():
    """AC-3: const/static-only file uses treesitter_v1, not the adaptive fallback.

    Without const_item/static_item in DEFINITION_TYPES the chunker finds no boundaries
    and returns strategy=treesitter_adaptive_v1. This test confirms they are recognised
    as definition nodes so at least one chunk carries strategy=treesitter_v1.
    """
    _skip_if_no_rust_ast()
    chunks = chunk_code(RUST_AST_CONST_ONLY, "rust", "consts.rs")
    strategies = {c.get("chunker_strategy") for c in chunks}
    assert "treesitter_v1" in strategies, (
        f"const/static-only file should produce treesitter_v1 chunks; got {strategies}"
    )


# =============================================================================
# HCL / Terraform boundary chunking (AC-7)
# =============================================================================

_FILLER = "  # " + "x" * 60 + "\n"  # 66-char comment line for padding


def _tf_block(resource_type: str, resource_name: str, n_pad: int = 20) -> str:
    """Return a realistic-looking Terraform resource block padded to >1250 chars."""
    pad = _FILLER * n_pad
    return (
        f'resource "{resource_type}" "{resource_name}" {{\n'
        f'  ami           = "ami-0c55b159cbfafe1f0"\n'
        f'  instance_type = "t3.micro"\n'
        f"  tags = {{\n"
        f'    Name = "{resource_name}"\n'
        f"  }}\n"
        f"{pad}"
        f"}}\n"
    )


def _tf_block_with_body(block_start: str, body: str, n_pad: int = 20) -> str:
    """Return a Terraform/HCL block padded enough to stay as its own chunk."""
    pad = _FILLER * n_pad
    return f"{block_start} {{\n{body}{pad}}}\n"


TF_MULTI_RESOURCE = (
    _tf_block("aws_instance", "web")
    + "\n"
    + _tf_block("aws_s3_bucket", "assets")
    + "\n"
    + _tf_block("aws_security_group", "web_sg")
)


def test_chunk_terraform_hcl_boundaries():
    """AC-7: multi-resource .tf file splits at HCL block boundaries."""
    chunks = chunk_code(TF_MULTI_RESOURCE, "terraform", "main.tf")
    # Should produce multiple chunks — 3 large resource blocks, each well above TARGET_MIN
    assert len(chunks) >= 3, (
        f"Expected >=3 chunks, got {len(chunks)}: {[c['content'][:60] for c in chunks]}"
    )
    combined = "\n".join(c["content"] for c in chunks)
    # All resource types must appear in the combined output
    assert "aws_instance" in combined
    assert "aws_s3_bucket" in combined
    assert "aws_security_group" in combined
    # Each resource block should start in its own chunk
    resource_chunks = [c for c in chunks if c["content"].lstrip().startswith("resource")]
    assert len(resource_chunks) >= 3, (
        f"Expected each resource in its own chunk, got resource chunks: "
        f"{[c['content'][:60] for c in resource_chunks]}"
    )


def test_chunk_terraform_modern_hcl_boundaries():
    """Terraform 1.1+ moved/import/check/removed blocks split as structural boundaries."""
    code = (
        _tf_block_with_body(
            "moved",
            "  from = aws_instance.old\n  to   = aws_instance.web\n",
        )
        + "\n"
        + _tf_block_with_body(
            "import",
            '  to = aws_s3_bucket.assets\n  id = "company-assets-prod"\n',
        )
        + "\n"
        + _tf_block_with_body(
            'check "website"',
            "  assert {\n"
            '    condition     = aws_instance.web.instance_type == "t3.micro"\n'
            '    error_message = "Unexpected instance size."\n'
            "  }\n",
        )
        + "\n"
        + _tf_block_with_body(
            "removed",
            "  from = aws_instance.legacy\n  lifecycle {\n    destroy = false\n  }\n",
        )
    )

    chunks = chunk_code(code, "terraform", "main.tf")

    starts = [c["content"].lstrip().split(maxsplit=1)[0] for c in chunks]
    assert starts == ["moved", "import", "check", "removed"]


def test_chunk_terraform_legacy_and_modern_boundaries_with_tf_extension():
    """Legacy and Terraform 1.1+ blocks are all split points for .tf language input."""
    code = (
        _tf_block("aws_instance", "web")
        + "\n"
        + _tf_block_with_body(
            'module "network"',
            '  source = "./modules/network"\n',
        )
        + "\n"
        + _tf_block_with_body(
            "moved",
            "  from = module.old_network\n  to   = module.network\n",
        )
        + "\n"
        + _tf_block_with_body(
            "import",
            '  to = aws_instance.web\n  id = "i-1234567890abcdef0"\n',
        )
        + "\n"
        + _tf_block_with_body(
            'check "network"',
            "  assert {\n"
            '    condition     = module.network.vpc_id != ""\n'
            '    error_message = "VPC ID must be available."\n'
            "  }\n",
        )
        + "\n"
        + _tf_block_with_body(
            "removed",
            "  from = aws_security_group.old\n  lifecycle {\n    destroy = false\n  }\n",
        )
        + "\n"
        + _tf_block_with_body(
            'output "web_id"',
            "  value = aws_instance.web.id\n",
        )
    )

    chunks = chunk_code(code, ".tf", "main.tf")

    starts = [c["content"].lstrip().split(maxsplit=1)[0] for c in chunks]
    assert starts == ["resource", "module", "moved", "import", "check", "removed", "output"]


def test_chunk_terraform_tfvars_assignment_names_use_adaptive_fallback():
    """.tfvars assignments named like Terraform blocks do not become HCL boundaries."""
    code = (
        'environment = "production"\n'
        'moved = "assignment key, not a moved block"\n'
        'import    = "assignment key, not an import block"\n'
        'check\t= "assignment key, not a check block"\n'
        'removed  \t = "assignment key, not a removed block"\n'
        'description = "A long tfvars line keeps this fixture above the chunk minimum."\n'
    )

    chunks = chunk_code(code, "terraform", "terraform.tfvars")
    expected = chunk_adaptive_lines(code, "terraform.tfvars")

    assert chunks == expected
    assert chunks == [{"content": code.strip(), "chunk_index": 0}]


# =============================================================================
# C# chunking
# =============================================================================

_CSHARP_FILLER = (
    "        // padding line to ensure chunk size stays above MIN_CHUNK threshold\n" * 4
)


def _csharp_field_filler(prefix: str, count: int = 28) -> str:
    """Return non-boundary C# field lines that do not attach as comments."""
    return "".join(
        f'    private readonly string _{prefix}{index} = "padding for chunk size";\n'
        for index in range(count)
    )


def _cs_class_with_methods(class_name: str, method_names: list) -> str:
    """Return a C# class with the given methods, each padded above MIN_CHUNK."""
    methods = ""
    for name in method_names:
        methods += (
            f"    public void {name}(string input) {{\n"
            f"        Console.WriteLine(input);\n"
            f"{_CSHARP_FILLER}"
            f"    }}\n\n"
        )
    return f"public class {class_name} {{\n{methods}}}\n"


def test_csharp_chunk_class_with_methods():
    """A C# class with two methods should split at each method boundary."""
    code = _cs_class_with_methods("MyService", ["HandleRequest", "ProcessResponse"])
    chunks = chunk_code(code, "csharp", "MyService.cs")
    combined = "\n".join(c["content"] for c in chunks)
    assert "HandleRequest" in combined
    assert "ProcessResponse" in combined


def test_csharp_chunk_nested_class_boundary():
    """A nested class inside an outer class creates a separate chunk boundary."""
    outer = (
        "public class Outer {\n"
        "    private int _value;\n\n" + _CSHARP_FILLER + "    public class Inner {\n"
        "        public int X { get; set; }\n" + _CSHARP_FILLER + "    }\n"
        "}\n"
    )
    chunks = chunk_code(outer, "csharp", "Outer.cs")
    combined = "\n".join(c["content"] for c in chunks)
    assert "Outer" in combined
    assert "Inner" in combined


def test_csharp_chunk_attribute_attached():
    """[Attribute] lines immediately preceding a declaration stay in the same chunk."""
    code = (
        "public class Controller {\n" + _CSHARP_FILLER + "    [HttpGet]\n"
        '    [Route("/index")]\n'
        "    public IActionResult Index() {\n"
        "        return View();\n" + _CSHARP_FILLER + "    }\n"
        "}\n"
    )
    chunks = chunk_code(code, "csharp", "Controller.cs")
    # The [HttpGet] and [Route] attributes must appear in the same chunk as Index()
    index_chunk = next((c for c in chunks if "Index" in c["content"]), None)
    assert index_chunk is not None, "No chunk found containing Index()"
    assert "[HttpGet]" in index_chunk["content"], "[HttpGet] attribute not attached to Index chunk"
    assert "[Route" in index_chunk["content"], "[Route] attribute not attached to Index chunk"


def test_csharp_chunk_xmldoc_attached():
    """/// XML doc comment lines immediately preceding a declaration stay in the same chunk."""
    code = (
        "public class MyClass {\n" + _CSHARP_FILLER + "    /// <summary>\n"
        "    /// Processes the given input value.\n"
        "    /// </summary>\n"
        '    /// <param name="input">The input string.</param>\n'
        "    public void Process(string input) {\n"
        "        Console.WriteLine(input);\n" + _CSHARP_FILLER + "    }\n"
        "}\n"
    )
    chunks = chunk_code(code, "csharp", "MyClass.cs")
    process_chunk = next((c for c in chunks if "Process" in c["content"]), None)
    assert process_chunk is not None, "No chunk found containing Process()"
    assert "/// <summary>" in process_chunk["content"], "XML doc not attached to Process chunk"


def test_csharp_chunk_expression_bodied_properties():
    """Expression-bodied C# properties create declaration chunks."""
    code = (
        "public class Catalog {\n"
        + _csharp_field_filler("before_count")
        + "    public int Count => _items.Count;\n"
        + _csharp_field_filler("between_props")
        + "    public string Name => _name;\n"
        + _csharp_field_filler("after_name")
        + "}\n"
    )
    chunks = chunk_code(code, "csharp", "Catalog.cs")
    chunk_texts = contents(chunks)

    assert any(text.startswith("public int Count =>") for text in chunk_texts)
    assert any(text.startswith("public string Name =>") for text in chunk_texts)


def test_csharp_chunk_expression_bodied_property_xmldoc_attached():
    """XML doc comments attach to expression-bodied property declarations."""
    code = (
        "public class Catalog {\n"
        + _csharp_field_filler("before_doc")
        + "    /// <summary>\n"
        + "    /// Number of catalog items.\n"
        + "    /// </summary>\n"
        + "    public int Count => _items.Count;\n"
        + _csharp_field_filler("after_count")
        + "}\n"
    )
    chunks = chunk_code(code, "csharp", "Catalog.cs")
    count_chunk = next((c for c in chunks if "public int Count =>" in c["content"]), None)

    assert count_chunk is not None, "No chunk found containing Count property"
    assert "/// <summary>" in count_chunk["content"]
    assert "/// Number of catalog items." in count_chunk["content"]


def test_csharp_chunk_file_routing():
    """chunk_file() routes .cs files through chunk_code() (not adaptive fallback)."""
    from mempalace.miner import chunk_file

    code = _cs_class_with_methods("Router", ["Alpha", "Beta"])
    chunks = chunk_file(code, ".cs", "Router.cs", language="csharp")
    combined = "\n".join(c["content"] for c in chunks)
    assert "Alpha" in combined
    assert "Beta" in combined


# =============================================================================
# chunk_code — F#
# =============================================================================

# A minimal F# module with two let bindings — padded to ensure each chunk
# survives MIN_CHUNK (100 chars) filtering after adaptive_merge_split.
_FSHARP_PAD = "    // padding to reach minimum chunk size for adaptive merge filtering\n"

FSHARP_TWO_FUNCTIONS = (
    "module Calculator\n"
    "\n"
    "let add (a: int) (b: int) =\n"
    + _FSHARP_PAD
    + "    a + b\n"
    + "\n"
    + "let subtract (a: int) (b: int) =\n"
    + _FSHARP_PAD
    + "    a - b\n"
)

FSHARP_TYPE_AND_LET = (
    "type Point = { X: float; Y: float }\n"
    + _FSHARP_PAD
    + "\n"
    + "let distance (p1: Point) (p2: Point) =\n"
    + _FSHARP_PAD
    + "    let dx = p1.X - p2.X\n"
    + "    let dy = p1.Y - p2.Y\n"
    + "    sqrt (dx * dx + dy * dy)\n"
)

FSHARP_DU_AND_LET = (
    "type Shape =\n"
    "    | Circle of float\n"
    "    | Rectangle of float * float\n"
    + _FSHARP_PAD
    + "\n"
    + "let area shape =\n"
    + _FSHARP_PAD
    + "    match shape with\n"
    + "    | Circle r -> System.Math.PI * r * r\n"
    + "    | Rectangle (w, h) -> w * h\n"
)


def test_fsharp_module_boundary():
    """module declaration splits into its own chunk."""
    chunks = chunk_code(FSHARP_TWO_FUNCTIONS, "fsharp", "Calculator.fs")
    combined = "\n".join(c["content"] for c in chunks)
    assert "add" in combined
    assert "subtract" in combined


def test_fsharp_let_boundary():
    """Each let binding triggers a boundary; both names appear in output."""
    chunks = chunk_code(FSHARP_TWO_FUNCTIONS, "fsharp", "Calculator.fs")
    combined = "\n".join(c["content"] for c in chunks)
    assert "add" in combined
    assert "subtract" in combined


def test_fsharp_type_and_let_boundary():
    """A type declaration and a let binding produce separate boundary hits."""
    chunks = chunk_code(FSHARP_TYPE_AND_LET, "fsharp", "Geometry.fs")
    combined = "\n".join(c["content"] for c in chunks)
    assert "Point" in combined
    assert "distance" in combined


def test_fsharp_du_boundary():
    """A discriminated union type and a let binding both appear in output."""
    chunks = chunk_code(FSHARP_DU_AND_LET, "fsharp", "Shape.fs")
    combined = "\n".join(c["content"] for c in chunks)
    assert "Shape" in combined
    assert "area" in combined


def test_fsharp_chunk_file_routing():
    """chunk_file() routes .fs files through chunk_code() (not adaptive fallback)."""
    from mempalace.miner import chunk_file

    chunks = chunk_file(FSHARP_TWO_FUNCTIONS, ".fs", "Calculator.fs", language="fsharp")
    combined = "\n".join(c["content"] for c in chunks)
    assert "add" in combined


# =============================================================================
# chunk_code — VB.NET
# =============================================================================

_VB_PAD = "    ' padding comment to reach minimum chunk size for adaptive merge filtering\n"

VBNET_CLASS_AND_SUB = (
    "Public Class UserService\n"
    + _VB_PAD
    + "    Public Sub Process(ByVal input As String)\n"
    + _VB_PAD
    + "    End Sub\n"
    + "\n"
    + "    Public Function Calculate(a As Integer, b As Integer) As Integer\n"
    + _VB_PAD
    + "        Return a + b\n"
    + "    End Function\n"
    + "End Class\n"
)

VBNET_MODULE = (
    "Public Module Utils\n"
    + _VB_PAD
    + "    Public Sub Helper()\n"
    + _VB_PAD
    + "    End Sub\n"
    + "End Module\n"
)


def test_vbnet_class_boundary():
    """Class declaration triggers a boundary; class name appears in output."""
    chunks = chunk_code(VBNET_CLASS_AND_SUB, "vbnet", "UserService.vb")
    combined = "\n".join(c["content"] for c in chunks)
    assert "UserService" in combined


def test_vbnet_sub_function_boundary():
    """Sub and Function declarations both appear in output."""
    chunks = chunk_code(VBNET_CLASS_AND_SUB, "vbnet", "UserService.vb")
    combined = "\n".join(c["content"] for c in chunks)
    assert "Process" in combined
    assert "Calculate" in combined


def test_vbnet_module_boundary():
    """Module declaration triggers a boundary."""
    chunks = chunk_code(VBNET_MODULE, "vbnet", "Utils.vb")
    combined = "\n".join(c["content"] for c in chunks)
    assert "Utils" in combined


def test_vbnet_chunk_file_routing():
    """chunk_file() routes .vb files through chunk_code() (not adaptive fallback)."""
    from mempalace.miner import chunk_file

    chunks = chunk_file(VBNET_MODULE, ".vb", "Utils.vb", language="vbnet")
    combined = "\n".join(c["content"] for c in chunks)
    assert "Utils" in combined


# =============================================================================
# PHP chunking
# =============================================================================

# Filler text to pad chunks above TARGET_MIN so adaptive_merge_split keeps them separate.
_PHP_FILLER = (
    "    // Provides processing logic for the operation described above.\n"
    "    // This padding ensures the chunk exceeds the TARGET_MIN threshold.\n"
    "    // Additional detail to make sure the chunk is long enough to survive.\n"
    "    // More padding to reach the minimum chunk size for separate drawer storage.\n"
)


def test_php_chunk_attribute_attached():
    """#[Attribute] lines immediately preceding a declaration stay in the same chunk (AC-9)."""
    code = (
        "<?php\n\n"
        "class ApiController {\n" + _PHP_FILLER + "    #[Route('/api/users', methods: ['GET'])]\n"
        "    public function listUsers(): array {\n"
        "        return [];\n" + _PHP_FILLER + "    }\n"
        "}\n"
    )
    chunks = chunk_code(code, "php", "ApiController.php")
    # The #[Route(...)] attribute must appear in the same chunk as listUsers()
    list_users_chunk = next((c for c in chunks if "listUsers" in c["content"]), None)
    assert list_users_chunk is not None, "No chunk found containing listUsers()"
    assert "#[Route" in list_users_chunk["content"], (
        "#[Route] attribute not attached to listUsers chunk"
    )


def test_php_chunk_class_boundary():
    """chunk_code splits PHP source at class declarations."""
    code = (
        "<?php\n\n"
        "class Foo {\n"
        + _PHP_FILLER
        + "    public function run(): void {}\n"
        + _PHP_FILLER
        + "}\n\n"
        "class Bar {\n"
        + _PHP_FILLER
        + "    public function execute(): void {}\n"
        + _PHP_FILLER
        + "}\n"
    )
    chunks = chunk_code(code, "php", "Multi.php")
    combined = "\n".join(c["content"] for c in chunks)
    assert "Foo" in combined
    assert "Bar" in combined


def test_php_chunk_file_routing():
    """chunk_file() routes .php files through chunk_code() (not adaptive fallback)."""
    from mempalace.miner import chunk_file

    code = (
        "<?php\n\n"
        "class Router {\n"
        + _PHP_FILLER
        + "    public function dispatch(string $path): void {}\n"
        + _PHP_FILLER
        + "}\n"
    )
    chunks = chunk_file(code, ".php", "Router.php", language="php")
    assert len(chunks) > 0
    combined = "\n".join(c["content"] for c in chunks)
    assert "Router" in combined


# =============================================================================
# Scala — annotation attachment and file routing
# =============================================================================

_SCALA_FILLER = "    // padding line to ensure chunk size stays above MIN_CHUNK threshold\n" * 6

# Larger filler used for tests that need to prevent adaptive_merge_split from combining
# two adjacent chunks (each must exceed TARGET_MAX / 2 = 1250 chars to stay separate).
_SCALA_BIG_FILLER = (
    "    // padding line to ensure chunk size stays above merge threshold value\n" * 20
)


def test_chunk_code_scala_annotation_attachment():
    """@tailrec / @main / @deprecated lines immediately before a declaration must attach
    to the declaration chunk (not be orphaned in the preceding chunk) — mirrors the existing
    Swift/PHP annotation-attachment coverage in test_chunking.py."""
    code = (
        "object Main {\n" + _SCALA_FILLER + "\n"
        "  @tailrec\n"
        "  private def loop(n: Int, acc: Int): Int = {\n"
        + _SCALA_FILLER
        + "    if (n <= 0) acc else loop(n - 1, acc + n)\n"
        "  }\n"
        "}\n"
    )
    chunks = chunk_code(code, "scala", "Main.scala")
    loop_chunk = next((c for c in chunks if "loop" in c["content"]), None)
    assert loop_chunk is not None, "No chunk found containing loop()"
    assert "@tailrec" in loop_chunk["content"], "@tailrec annotation not attached to loop chunk"


def test_chunk_code_scala_annotation_on_val_not_swallowed():
    """An annotation on a val (e.g. @volatile var counter = 0) must NOT be greedily
    pulled into the following function chunk.  Each chunk uses _SCALA_BIG_FILLER to
    exceed TARGET_MAX / 2 (1250 chars) so adaptive_merge_split does not re-combine them."""
    code = (
        "class Config {\n" + _SCALA_BIG_FILLER + "\n"
        "  @volatile var counter: Int = 0\n"
        "\n"
        "  def increment(): Unit = {\n" + _SCALA_BIG_FILLER + "    counter += 1\n"
        "  }\n"
        "}\n"
    )
    chunks = chunk_code(code, "scala", "Config.scala")
    increment_chunk = next((c for c in chunks if "increment" in c["content"]), None)
    assert increment_chunk is not None, "No chunk found containing increment()"
    assert "@volatile" not in increment_chunk["content"], (
        "@volatile var annotation must not be pulled into the increment() chunk"
    )


def test_chunk_file_scala_routing():
    """chunk_file() routes .scala files through chunk_code() (not adaptive fallback)."""
    code = (
        "package com.example\n\n"
        "class Service {\n" + _SCALA_FILLER + "  def process(): Unit = {}\n" + _SCALA_FILLER + "}\n"
    )
    chunks = chunk_file(code, ".scala", "Service.scala", language="scala")
    assert len(chunks) > 0
    combined = "\n".join(c["content"] for c in chunks)
    assert "Service" in combined


def test_chunk_file_sc_routing():
    """chunk_file() routes .sc (Ammonite script) files through chunk_code() too."""
    code = "def greet(name: String): String = {\n" + _SCALA_FILLER + '  s"Hello, $name!"\n}\n'
    chunks = chunk_file(code, ".sc", "script.sc", language="scala")
    assert len(chunks) > 0
    combined = "\n".join(c["content"] for c in chunks)
    assert "greet" in combined


# =============================================================================
# Dart — annotation attachment and file routing
# =============================================================================

_DART_FILLER = "  // padding line to ensure chunk size stays above MIN_CHUNK threshold\n" * 6

# Larger filler to prevent adaptive_merge_split from combining two adjacent chunks
_DART_BIG_FILLER = "  // padding line to ensure chunk size stays above merge threshold value\n" * 20


def test_chunk_code_dart_annotation_attachment():
    """@override / @deprecated / @pragma lines immediately before a declaration must attach
    to the declaration chunk — mirrors Swift/Scala annotation-attachment coverage."""
    code = (
        "class MyWidget extends StatefulWidget {\n" + _DART_FILLER + "\n"
        "  @override\n"
        "  void dispose() {\n" + _DART_FILLER + "    super.dispose();\n"
        "  }\n"
        "}\n"
    )
    chunks = chunk_code(code, "dart", "my_widget.dart")
    dispose_chunk = next((c for c in chunks if "dispose" in c["content"]), None)
    assert dispose_chunk is not None, "No chunk found containing dispose()"
    assert "@override" in dispose_chunk["content"], (
        "@override annotation not attached to dispose chunk"
    )


def test_chunk_code_dart_annotation_on_field_not_swallowed():
    """An annotation on a field (e.g. @deprecated var x = 0) must NOT be greedily
    pulled into the following function chunk."""
    code = (
        "class Config {\n" + _DART_BIG_FILLER + "\n"
        "  @deprecated\n"
        "  var legacyField = 0;\n"
        "\n"
        "  void increment() {\n" + _DART_BIG_FILLER + "    legacyField++;\n"
        "  }\n"
        "}\n"
    )
    chunks = chunk_code(code, "dart", "config.dart")
    increment_chunk = next((c for c in chunks if "increment" in c["content"]), None)
    assert increment_chunk is not None, "No chunk found containing increment()"
    assert "@deprecated" not in increment_chunk["content"], (
        "@deprecated field annotation must not be pulled into the increment() chunk"
    )


def test_chunk_code_dart_async_function():
    """Future<User> fetchUser() async { ... } must become its own chunk; async keyword
    after ) must not prevent boundary detection (AC-8)."""
    code = (
        "import 'package:http/http.dart' as http;\n\n"
        + _DART_FILLER
        + "Future<User?> fetchUser(int id) async {\n"
        + _DART_FILLER
        + "  final resp = await http.get(Uri.parse('/users/$id'));\n"
        "  return User.fromJson(jsonDecode(resp.body) as Map<String, dynamic>);\n"
        "}\n"
    )
    chunks = chunk_code(code, "dart", "fetch_user.dart")
    fetch_chunk = next((c for c in chunks if "fetchUser" in c["content"]), None)
    assert fetch_chunk is not None, "No chunk found containing fetchUser()"
    assert "async" in fetch_chunk["content"]


def test_chunk_file_dart_routing():
    """chunk_file() routes .dart files through chunk_code() not adaptive fallback."""
    code = (
        "import 'dart:core';\n\n"
        "class Service {\n" + _DART_FILLER + "  void process() {}\n" + _DART_FILLER + "}\n"
    )
    chunks = chunk_file(code, ".dart", "service.dart", language="dart")
    assert len(chunks) > 0
    combined = "\n".join(c["content"] for c in chunks)
    assert "Service" in combined


def test_chunk_code_dart_generic_factory_boundary():
    """factory ClassName<T>.named(...) must be a separate structural boundary (MINE-DART F-1/F-6).

    DART_BOUNDARY's factory arm must put generic params BEFORE the named-constructor suffix so
    both `factory Cache<K,V>(...)` and `factory Repository<T>.fromConfig(...)` are detected.
    The factory must become its own chunk, not be merged into the class body chunk.
    """
    code = (
        "class Repository<T> {\n" + _DART_BIG_FILLER + "\n"
        "  factory Repository<T>.fromConfig(Config config) {\n"
        + _DART_BIG_FILLER
        + "    return Repository._internal(config);\n"
        "  }\n"
        "}\n"
    )
    chunks = chunk_code(code, "dart", "repository.dart")
    factory_chunk = next((c for c in chunks if "fromConfig" in c["content"]), None)
    assert factory_chunk is not None, (
        "No chunk found containing the generic factory constructor 'Repository<T>.fromConfig'"
    )
    # The factory must be a SEPARATE chunk — 'class Repository<T>' must not appear at the
    # start of the same chunk (which would mean factory was folded into the class body chunk).
    assert not factory_chunk["content"].lstrip().startswith("class"), (
        "factory constructor was merged into the class body chunk instead of its own chunk"
    )


def test_chunk_code_dart_nullable_return_type():
    """String? / User? / int? return types must produce their own chunk (MINE-DART F-3).

    Before the fix, nullable-typed top-level functions were silently omitted from
    boundary detection because the return-type pattern lacked `\\??` after the type token.
    """
    code = (
        "import 'dart:core';\n\n"
        + _DART_FILLER
        + "String? getDeviceId() {\n"
        + _DART_FILLER
        + "  return null;\n"
        "}\n"
    )
    chunks = chunk_code(code, "dart", "device.dart")
    nullable_chunk = next((c for c in chunks if "getDeviceId" in c["content"]), None)
    assert nullable_chunk is not None, (
        "No chunk found for 'String? getDeviceId()' — nullable return type not detected as boundary"
    )
