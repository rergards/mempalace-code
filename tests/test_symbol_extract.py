"""Unit tests for extract_symbol() — all five supported languages plus fallbacks."""

import pytest

from mempalace.miner import extract_symbol


# =============================================================================
# PYTHON
# =============================================================================


def test_py_def():
    assert extract_symbol("def my_func():\n    pass\n", "python") == ("my_func", "function")


def test_py_async_def():
    assert extract_symbol("async def fetch_data():\n    pass\n", "python") == (
        "fetch_data",
        "function",
    )


def test_py_class():
    assert extract_symbol("class MyClass:\n    pass\n", "python") == ("MyClass", "class")


def test_py_decorated_function():
    content = "@property\ndef value(self):\n    return self._value\n"
    assert extract_symbol(content, "python") == ("value", "function")


def test_py_decorated_class():
    content = "@dataclass\nclass Config:\n    host: str\n    port: int\n"
    assert extract_symbol(content, "python") == ("Config", "class")


def test_py_multiline_signature():
    content = "def process(\n    input_data: list,\n    output_path: str,\n) -> None:\n    pass\n"
    assert extract_symbol(content, "python") == ("process", "function")


# =============================================================================
# TYPESCRIPT
# =============================================================================


def test_ts_function():
    assert extract_symbol("function handleAuth(req, res) {\n}\n", "typescript") == (
        "handleAuth",
        "function",
    )


def test_ts_async_function():
    assert extract_symbol("async function loadUser(id: string) {\n}\n", "typescript") == (
        "loadUser",
        "function",
    )


def test_ts_class():
    assert extract_symbol("class UserService {\n}\n", "typescript") == ("UserService", "class")


def test_ts_interface():
    assert extract_symbol("interface User {\n  id: string;\n}\n", "typescript") == (
        "User",
        "interface",
    )


def test_ts_type_alias():
    assert extract_symbol("type UserId = string;\n", "typescript") == ("UserId", "type")


def test_ts_generic_type():
    assert extract_symbol("type Result<T> = { data: T };\n", "typescript") == ("Result", "type")


def test_ts_enum():
    assert extract_symbol("enum Direction {\n  Up,\n  Down,\n}\n", "typescript") == (
        "Direction",
        "enum",
    )


def test_ts_const():
    assert extract_symbol("const API_URL = 'https://api.example.com';\n", "typescript") == (
        "API_URL",
        "const",
    )


def test_ts_const_arrow():
    assert extract_symbol(
        "const handleClick = () => {\n  console.log('clicked');\n};\n", "typescript"
    ) == ("handleClick", "const")


def test_ts_export_function():
    assert extract_symbol("export function formatDate(d: Date): string {\n}\n", "typescript") == (
        "formatDate",
        "function",
    )


def test_ts_export_default_function():
    assert extract_symbol(
        "export default function HomePage() {\n  return <div/>;\n}\n", "typescript"
    ) == ("HomePage", "function")


def test_ts_export_default_class():
    assert extract_symbol("export default class App {\n}\n", "typescript") == ("App", "class")


def test_ts_export_interface():
    assert extract_symbol("export interface Config {\n  timeout: number;\n}\n", "typescript") == (
        "Config",
        "interface",
    )


def test_ts_export_enum():
    assert extract_symbol("export enum Status {\n  Active,\n  Inactive,\n}\n", "typescript") == (
        "Status",
        "enum",
    )


def test_ts_import_only_chunk():
    content = "import React from 'react';\nimport { useState } from 'react';\n"
    assert extract_symbol(content, "typescript") == ("", "import")


def test_ts_from_import_chunk():
    content = "from './utils' import { helper };\n"
    assert extract_symbol(content, "typescript") == ("", "import")


# =============================================================================
# JAVASCRIPT
# =============================================================================


def test_js_function():
    assert extract_symbol(
        "function greet(name) {\n  return 'Hello ' + name;\n}\n", "javascript"
    ) == (
        "greet",
        "function",
    )


def test_js_class():
    assert extract_symbol(
        "class Animal {\n  constructor(name) { this.name = name; }\n}\n", "javascript"
    ) == (
        "Animal",
        "class",
    )


def test_js_const():
    assert extract_symbol("const MAX_RETRIES = 3;\n", "javascript") == ("MAX_RETRIES", "const")


def test_js_import_only_chunk():
    content = "import lodash from 'lodash';\nimport _ from 'underscore';\n"
    assert extract_symbol(content, "javascript") == ("", "import")


# =============================================================================
# GO
# =============================================================================


def test_go_func():
    assert extract_symbol("func NewServer(addr string) *Server {\n}\n", "go") == (
        "NewServer",
        "function",
    )


def test_go_method():
    content = "func (s *Server) Start() error {\n  return nil\n}\n"
    assert extract_symbol(content, "go") == ("Start", "method")


def test_go_method_value_receiver():
    content = "func (r Rect) Area() float64 {\n  return r.Width * r.Height\n}\n"
    assert extract_symbol(content, "go") == ("Area", "method")


def test_go_type_struct():
    assert extract_symbol("type Config struct {\n  Host string\n  Port int\n}\n", "go") == (
        "Config",
        "struct",
    )


def test_go_type_interface():
    assert extract_symbol("type Handler interface {\n  ServeHTTP(w, r)\n}\n", "go") == (
        "Handler",
        "interface",
    )


def test_go_type_scalar():
    assert extract_symbol("type MyInt int\n", "go") == ("MyInt", "type")


def test_go_type_func():
    assert extract_symbol("type Handler func(http.ResponseWriter, *http.Request)\n", "go") == (
        "Handler",
        "type",
    )


def test_go_type_alias():
    assert extract_symbol("type Alias = Original\n", "go") == ("Alias", "type")


# =============================================================================
# RUST
# =============================================================================


def test_rust_fn():
    assert extract_symbol("fn main() {\n}\n", "rust") == ("main", "function")


def test_rust_pub_fn():
    assert extract_symbol("pub fn new() -> Self {\n  Self {}\n}\n", "rust") == ("new", "function")


def test_rust_pub_crate_fn():
    assert extract_symbol("pub(crate) fn internal_helper() {\n}\n", "rust") == (
        "internal_helper",
        "function",
    )


def test_rust_async_fn():
    assert extract_symbol("async fn fetch(url: &str) -> Result<(), Error> {\n}\n", "rust") == (
        "fetch",
        "function",
    )


def test_rust_pub_async_fn():
    assert extract_symbol("pub async fn run() {\n}\n", "rust") == ("run", "function")


def test_rust_struct():
    assert extract_symbol("struct Point {\n  x: f64,\n  y: f64,\n}\n", "rust") == (
        "Point",
        "struct",
    )


def test_rust_pub_struct():
    assert extract_symbol("pub struct Config {\n  pub host: String,\n}\n", "rust") == (
        "Config",
        "struct",
    )


def test_rust_struct_with_derive():
    content = "#[derive(Debug, Clone)]\npub struct Config {\n  pub host: String,\n}\n"
    assert extract_symbol(content, "rust") == ("Config", "struct")


def test_rust_enum():
    assert extract_symbol("enum Color {\n  Red,\n  Green,\n  Blue,\n}\n", "rust") == (
        "Color",
        "enum",
    )


def test_rust_pub_enum():
    assert extract_symbol("pub enum Status {\n  Active,\n  Inactive,\n}\n", "rust") == (
        "Status",
        "enum",
    )


def test_rust_trait():
    assert extract_symbol("trait Drawable {\n  fn draw(&self);\n}\n", "rust") == (
        "Drawable",
        "trait",
    )


def test_rust_pub_trait():
    assert extract_symbol("pub trait Display {\n  fn fmt(&self) -> String;\n}\n", "rust") == (
        "Display",
        "trait",
    )


def test_rust_impl():
    assert extract_symbol(
        "impl Config {\n  pub fn new() -> Self {\n    Self {}\n  }\n}\n", "rust"
    ) == (
        "Config",
        "impl",
    )


def test_rust_impl_trait_for():
    assert extract_symbol(
        "impl Display for Config {\n  fn fmt(&self) -> String { String::new() }\n}\n", "rust"
    ) == (
        "Display",
        "impl",
    )


def test_rust_mod():
    assert extract_symbol("mod utils {\n  pub fn helper() {}\n}\n", "rust") == ("utils", "mod")


def test_rust_pub_mod():
    assert extract_symbol("pub mod api {\n  pub fn handler() {}\n}\n", "rust") == ("api", "mod")


def test_rust_type_alias():
    assert extract_symbol("type Result<T> = std::result::Result<T, Error>;\n", "rust") == (
        "Result",
        "type",
    )


def test_rust_pub_super_fn():
    assert extract_symbol("pub(super) fn parent_helper() {\n}\n", "rust") == (
        "parent_helper",
        "function",
    )


def test_rust_pub_super_struct():
    assert extract_symbol("pub(super) struct InternalData {\n  x: i32,\n}\n", "rust") == (
        "InternalData",
        "struct",
    )


def test_rust_generic_impl():
    assert extract_symbol(
        "impl<T> Config<T> {\n  pub fn new() -> Self { Self {} }\n}\n", "rust"
    ) == ("Config", "impl")


def test_rust_generic_impl_with_bound():
    assert extract_symbol(
        "impl<T: Debug> Display for Config<T> {\n  fn fmt(&self) -> String { String::new() }\n}\n",
        "rust",
    ) == ("Display", "impl")


# =============================================================================
# NON-CODE LANGUAGES — all return ("", "")
# =============================================================================


@pytest.mark.parametrize(
    "language",
    ["markdown", "text", "json", "yaml", "shell", "ruby", "java", "unknown", "html", "css", "sql"],
)
def test_non_code_language_returns_empty(language):
    content = "Some content that might look like def foo() { return 1; }\n"
    assert extract_symbol(content, language) == ("", "")


# =============================================================================
# EDGE CASES
# =============================================================================


def test_empty_content_returns_empty():
    assert extract_symbol("", "python") == ("", "")


def test_comment_only_chunk_returns_empty():
    content = "# This is a comment\n# Another comment\n"
    assert extract_symbol(content, "python") == ("", "")


def test_ts_declaration_wins_over_import():
    """A chunk that starts with an import but also has a function declaration."""
    content = "import { helper } from './utils';\n\nfunction doWork() {\n  helper();\n}\n"
    assert extract_symbol(content, "typescript") == ("doWork", "function")


# =============================================================================
# TSX / JSX — new canonical names
# =============================================================================


def test_tsx_function_symbol():
    assert extract_symbol("export function MyComponent() {\n  return null;\n}\n", "tsx") == (
        "MyComponent",
        "function",
    )


def test_tsx_class_symbol():
    assert extract_symbol("class MyWidget {\n}\n", "tsx") == ("MyWidget", "class")


def test_tsx_import_only_returns_import():
    content = "import React from 'react';\nimport { FC } from 'react';\n"
    assert extract_symbol(content, "tsx") == ("", "import")


def test_jsx_function_symbol():
    assert extract_symbol("export function Button() {\n  return null;\n}\n", "jsx") == (
        "Button",
        "function",
    )


def test_jsx_import_only_returns_import():
    content = "import React from 'react';\n"
    assert extract_symbol(content, "jsx") == ("", "import")
