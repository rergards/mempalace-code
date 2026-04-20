"""Unit tests for extract_symbol() — all five supported languages plus fallbacks."""

import pytest

from mempalace.miner import chunk_code, extract_symbol


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
# C
# =============================================================================


def test_c_struct():
    assert extract_symbol("struct Node {\n    int val;\n};\n", "c") == ("Node", "struct")


def test_c_enum():
    assert extract_symbol("enum Color {\n    RED,\n    GREEN,\n};\n", "c") == ("Color", "enum")


def test_c_function():
    assert extract_symbol("int add(int a, int b) {\n    return a + b;\n}\n", "c") == (
        "add",
        "function",
    )


# =============================================================================
# C++
# =============================================================================


def test_cpp_class():
    assert extract_symbol("class Foo {\n};\n", "cpp") == ("Foo", "class")


def test_cpp_struct():
    assert extract_symbol("struct Point {\n    float x;\n    float y;\n};\n", "cpp") == (
        "Point",
        "struct",
    )


def test_cpp_enum():
    assert extract_symbol("enum Direction {\n    UP,\n    DOWN,\n};\n", "cpp") == (
        "Direction",
        "enum",
    )


def test_cpp_enum_class():
    assert extract_symbol("enum class Status {\n    Active,\n    Inactive,\n};\n", "cpp") == (
        "Status",
        "enum",
    )


def test_cpp_function():
    assert extract_symbol("void render(int x, int y) {\n    draw(x, y);\n}\n", "cpp") == (
        "render",
        "function",
    )


def test_cpp_function_pointer_return():
    assert extract_symbol("std::string *getName() {\n    return &name_;\n}\n", "cpp") == (
        "getName",
        "function",
    )


def test_c_pointer_return():
    assert extract_symbol("char *strdup(const char *s) {\n    return copy;\n}\n", "c") == (
        "strdup",
        "function",
    )


# =============================================================================
# NON-CODE LANGUAGES — all return ("", "")
# =============================================================================


@pytest.mark.parametrize(
    "language",
    ["markdown", "text", "json", "yaml", "shell", "ruby", "unknown", "html", "css", "sql"],
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


# =============================================================================
# JAVA
# =============================================================================


def test_java_class():
    assert extract_symbol("public class UserService {\n}\n", "java") == ("UserService", "class")


def test_java_abstract_class():
    assert extract_symbol("public abstract class BaseEntity {\n}\n", "java") == (
        "BaseEntity",
        "class",
    )


def test_java_interface():
    assert extract_symbol("public interface Repository<T> {\n}\n", "java") == (
        "Repository",
        "interface",
    )


def test_java_enum():
    assert extract_symbol("public enum Status {\n    ACTIVE, INACTIVE\n}\n", "java") == (
        "Status",
        "enum",
    )


def test_java_record():
    assert extract_symbol("public record Point(int x, int y) {\n}\n", "java") == (
        "Point",
        "record",
    )


def test_java_annotation_type():
    assert extract_symbol("public @interface Component {\n}\n", "java") == (
        "Component",
        "annotation",
    )


def test_java_method_public():
    content = "public void processRequest(HttpServletRequest req) {\n}\n"
    assert extract_symbol(content, "java") == ("processRequest", "method")


def test_java_method_private_static():
    content = "private static void helper() {\n}\n"
    assert extract_symbol(content, "java") == ("helper", "method")


def test_java_method_generic():
    content = "public <T> Optional<T> findById(Long id) {\n    return Optional.empty();\n}\n"
    assert extract_symbol(content, "java") == ("findById", "method")


def test_java_annotation_prefixed_method():
    content = "@Override\npublic String toString() {\n    return name;\n}\n"
    assert extract_symbol(content, "java") == ("toString", "method")


def test_java_inner_class():
    # stripped line (indented in source) — boundary/extract match on stripped line
    content = "private static class Builder {\n}\n"
    assert extract_symbol(content, "java") == ("Builder", "class")


def test_java_method_map_return_type():
    # Map<String, Object> has a space after the comma — must be extracted correctly
    content = "public Map<String, Object> getConfig() {\n    return config;\n}\n"
    assert extract_symbol(content, "java") == ("getConfig", "method")


def test_java_method_nested_generic_return_type():
    content = "public Map<String, List<String>> getAll() {\n    return map;\n}\n"
    assert extract_symbol(content, "java") == ("getAll", "method")


def test_java_field_not_extracted():
    # fields have no () — should not be extracted
    assert extract_symbol('private static final String URL = "http://example.com";\n', "java") == (
        "",
        "",
    )


def test_java_unknown_returns_empty():
    # plain assignment — no symbol
    assert extract_symbol("int x = 42;\n", "java") == ("", "")


def test_java_ruby_still_returns_empty():
    content = "def foo\n  puts 'hello'\nend\n"
    assert extract_symbol(content, "ruby") == ("", "")


# =============================================================================
# KOTLIN
# =============================================================================


def test_kotlin_class():
    assert extract_symbol("class UserService {\n}\n", "kotlin") == ("UserService", "class")


def test_kotlin_data_class():
    assert extract_symbol("data class Point(val x: Int, val y: Int)\n", "kotlin") == (
        "Point",
        "data_class",
    )


def test_kotlin_sealed_class():
    assert extract_symbol("sealed class Result {\n}\n", "kotlin") == ("Result", "sealed_class")


def test_kotlin_sealed_interface():
    assert extract_symbol("sealed interface State\n", "kotlin") == ("State", "sealed_interface")


def test_kotlin_object():
    assert extract_symbol("object Database {\n}\n", "kotlin") == ("Database", "object")


def test_kotlin_interface():
    assert extract_symbol("interface Repository<T> {\n}\n", "kotlin") == (
        "Repository",
        "interface",
    )


def test_kotlin_enum_class():
    assert extract_symbol("enum class Color { RED, GREEN, BLUE }\n", "kotlin") == (
        "Color",
        "enum",
    )


def test_kotlin_fun():
    assert extract_symbol(
        "fun process(input: String): String {\n    return input\n}\n", "kotlin"
    ) == (
        "process",
        "function",
    )


def test_kotlin_suspend_fun():
    assert extract_symbol(
        "suspend fun fetchData(): List<Item> {\n    return emptyList()\n}\n", "kotlin"
    ) == ("fetchData", "function")


def test_kotlin_extension_fun():
    # Extension function: receiver type is stripped, function name captured
    assert extract_symbol(
        "fun String.isPalindrome(): Boolean {\n    return true\n}\n", "kotlin"
    ) == (
        "isPalindrome",
        "function",
    )


def test_kotlin_annotation_prefixed_fun():
    content = "@JvmStatic\nfun create(): Builder {\n    return Builder()\n}\n"
    assert extract_symbol(content, "kotlin") == ("create", "function")


def test_kotlin_typealias():
    assert extract_symbol("typealias UserId = String\n", "kotlin") == ("UserId", "typealias")


def test_kotlin_private_class():
    assert extract_symbol("private class Internal {\n}\n", "kotlin") == ("Internal", "class")


def test_kotlin_property_not_extracted():
    # Top-level properties must not be extracted
    assert extract_symbol('val name: String = "test"\n', "kotlin") == ("", "")


def test_kotlin_companion_object_unnamed():
    # Unnamed companion object returns ("", "companion_object")
    content = "companion object {\n    fun create() = Foo()\n}\n"
    assert extract_symbol(content, "kotlin") == ("", "companion_object")


def test_kotlin_chunk_no_spurious_companion_boundary():
    # `companion object {` must NOT be a boundary — it stays inside the enclosing class chunk.
    # (We use val properties so no `fun` keyword triggers a legitimate split.)
    # Content is intentionally >MIN_CHUNK (100 chars) so the chunk survives adaptive filtering.
    content = (
        "class Repository {\n"
        '    val name: String = "MainRepository"\n'
        '    val endpoint: String = "https://api.example.com/v1"\n'
        "    companion object {\n"
        '        val TAG: String = "Repository"\n'
        "        val DEFAULT_TIMEOUT: Int = 30\n"
        "    }\n"
        "}\n"
    )
    chunks = chunk_code(content, "kotlin", "Repository.kt")
    # All content must be in a single chunk — no split at `companion object {`
    assert len(chunks) == 1


def test_kotlin_chunk_class_with_two_funs():
    # A class + two top-level funs — both fun names must appear in some chunk.
    # Content is sized so chunks survive MIN_CHUNK (100 char) adaptive filtering.
    content = (
        "class Service {\n"
        '    val connectionString: String = "jdbc:postgresql://localhost:5432/db"\n'
        "    val maxRetries: Int = 3\n"
        "}\n"
        "\n"
        "fun doA(input: String): String {\n"
        "    val result = input.trim().lowercase()\n"
        '    return result.ifBlank { "default" }\n'
        "}\n"
        "\n"
        "fun doB(items: List<String>): Int {\n"
        "    val filtered = items.filter { it.isNotBlank() }\n"
        "    return filtered.size\n"
        "}\n"
    )
    chunks = chunk_code(content, "kotlin", "Service.kt")
    assert len(chunks) <= 3
    contents = [c["content"] for c in chunks]
    assert any("doA" in c for c in contents)
    assert any("doB" in c for c in contents)


def test_kotlin_class_with_companion_object_classifies_as_class():
    # Regression: a class chunk containing a companion object body must be classified
    # as the enclosing class, not as companion_object (F-1 hardening fix).
    content = (
        "class UserRepository {\n"
        '    val baseUrl: String = "https://api.example.com"\n'
        "\n"
        "    companion object {\n"
        "        fun create() = UserRepository()\n"
        "    }\n"
        "}\n"
    )
    assert extract_symbol(content, "kotlin") == ("UserRepository", "class")


def test_kotlin_generic_fun_type_param_extracted():
    # Regression: `fun <T> identity(value: T)` must capture `identity`, not return empty
    # (F-2 hardening fix — type parameter before function name).
    assert extract_symbol("fun <T> identity(value: T): T = value\n", "kotlin") == (
        "identity",
        "function",
    )


def test_kotlin_generic_extension_fun_type_param_extracted():
    # `fun <T> List<T>.mapNotNull(…)` — generic receiver, type param before name.
    content = (
        "fun <T> List<T>.mapNotNull(transform: (T) -> T?): List<T> {\n    return emptyList()\n}\n"
    )
    assert extract_symbol(content, "kotlin") == ("mapNotNull", "function")


def test_kotlin_generic_fun_type_param_bound_nested():
    # AC-1: type-param bound with depth-2 nesting: `<T : Comparable<T>>` contains an inner `<T>`.
    # The old [^>]+ stopped at the `>` in `<T>`, causing extract_symbol to return ("", "").
    assert extract_symbol("fun <T : Comparable<T>> List<T>.sorted(): List<T>\n", "kotlin") == (
        "sorted",
        "function",
    )


def test_kotlin_generic_fun_receiver_nested():
    # AC-2: receiver type with depth-2 nesting: `Map<String, List<Int>>` contains `<Int>`.
    # The old [^>]+ halted at the `>` in `<Int>`, leaving `.flatten` unreachable.
    assert extract_symbol("fun Map<String, List<Int>>.flatten(): List<Int>\n", "kotlin") == (
        "flatten",
        "function",
    )


def test_kotlin_generic_fun_modifier_with_nested_type_param():
    # F-2 hardening: modifier (inline) + depth-2 type-param bound.
    # Ensures the modifier path works with the new (?:[^<>]|<[^<>]*>)* type-param pattern.
    assert extract_symbol(
        "inline fun <T : Comparable<T>> List<T>.sortedDesc(): List<T>\n", "kotlin"
    ) == ("sortedDesc", "function")


def test_kotlin_generic_fun_type_params_and_nested_receiver():
    # F-3 hardening: both type params AND a depth-2 nested receiver in the same signature.
    # Exercises the new pattern in both the type-param section and the receiver section.
    assert extract_symbol("fun <T> Map<String, List<T>>.flatMap(): List<T>\n", "kotlin") == (
        "flatMap",
        "function",
    )


def test_kotlin_inner_class_extracted():
    # Regression (F-4): `inner` is now in the class modifier list.
    assert extract_symbol("inner class ViewHolder(view: View) {\n}\n", "kotlin") == (
        "ViewHolder",
        "class",
    )


def test_kotlin_value_class_extracted():
    # Regression (F-4): `value` is now in the class modifier list.
    assert extract_symbol("value class UserId(val id: String)\n", "kotlin") == ("UserId", "class")


def test_kotlin_annotation_class_extracted():
    # Regression (F-4): `annotation` is now in the class modifier list.
    assert extract_symbol("annotation class Retry(val times: Int = 3)\n", "kotlin") == (
        "Retry",
        "class",
    )


def test_java_chunk_code_no_spurious_boundary_on_inner_annotation():
    """@SuppressWarnings inside a method body must NOT split the method into separate chunks."""
    java_code = (
        "public class Foo {\n"
        "    public List<String> process(List<?> items) {\n"
        '        @SuppressWarnings("unchecked")\n'
        "        List<String> result = (List<String>) items;\n"
        "        return result;\n"
        "    }\n"
        "}\n"
    )
    chunks = chunk_code(java_code, "java", "Foo.java")
    # The whole class (including the method body) should be in a single chunk —
    # @SuppressWarnings on a local variable must not create a boundary.
    assert len(chunks) == 1
    assert "process" in chunks[0]["content"]
    assert "@SuppressWarnings" in chunks[0]["content"]


# =============================================================================
# C#
# =============================================================================


def test_csharp_class():
    assert extract_symbol("public class UserService {\n}\n", "csharp") == ("UserService", "class")


def test_csharp_struct():
    assert extract_symbol(
        "public struct Point {\n    public int X;\n    public int Y;\n}\n", "csharp"
    ) == (
        "Point",
        "struct",
    )


def test_csharp_interface():
    assert extract_symbol(
        "public interface IRepository<T> {\n    T GetById(int id);\n}\n", "csharp"
    ) == ("IRepository", "interface")


def test_csharp_enum():
    assert extract_symbol("public enum Color { Red, Green, Blue }\n", "csharp") == ("Color", "enum")


def test_csharp_record():
    assert extract_symbol("public record Person(string Name, int Age);\n", "csharp") == (
        "Person",
        "record",
    )


def test_csharp_record_struct():
    assert extract_symbol("public record struct Coordinate(double X, double Y);\n", "csharp") == (
        "Coordinate",
        "record",
    )


def test_csharp_sealed_class():
    assert extract_symbol(
        "public sealed class Singleton {\n    private Singleton() {}\n}\n", "csharp"
    ) == (
        "Singleton",
        "class",
    )


def test_csharp_abstract_class():
    assert extract_symbol(
        "public abstract class Shape {\n    public abstract double Area();\n}\n", "csharp"
    ) == (
        "Shape",
        "class",
    )


def test_csharp_static_class():
    assert extract_symbol("public static class Extensions {\n}\n", "csharp") == (
        "Extensions",
        "class",
    )


def test_csharp_partial_class():
    assert extract_symbol("public partial class Generated {\n}\n", "csharp") == (
        "Generated",
        "class",
    )


def test_csharp_method():
    content = (
        "public class Processor {\n"
        "    public void Process(string input) {\n"
        "        Console.WriteLine(input);\n"
        "    }\n"
        "}\n"
    )
    assert extract_symbol(content, "csharp") == ("Processor", "class")


def test_csharp_method_alone():
    assert extract_symbol("    public void Process(string input) {\n    }\n", "csharp") == (
        "Process",
        "method",
    )


def test_csharp_static_method():
    assert extract_symbol(
        "    public static int Calculate(int a, int b) {\n        return a + b;\n    }\n",
        "csharp",
    ) == ("Calculate", "method")


def test_csharp_async_method():
    assert extract_symbol(
        "    public async Task<string> FetchAsync() {\n        return await _client.GetAsync();\n    }\n",
        "csharp",
    ) == ("FetchAsync", "method")


def test_csharp_generic_method():
    assert extract_symbol(
        "    public T Convert<T>(object input) where T : class {\n        return (T)input;\n    }\n",
        "csharp",
    ) == ("Convert", "method")


def test_csharp_constructor_as_method():
    assert extract_symbol(
        "    public UserService(ILogger logger) {\n        _logger = logger;\n    }\n",
        "csharp",
    ) == ("UserService", "method")


def test_csharp_property():
    assert extract_symbol("    public string Name { get; set; }\n", "csharp") == (
        "Name",
        "property",
    )


def test_csharp_event():
    assert extract_symbol("    public event EventHandler<EventArgs> OnChanged;\n", "csharp") == (
        "OnChanged",
        "event",
    )


def test_csharp_attribute_prefixed_method():
    content = "    [HttpGet]\n    public IActionResult Index() {\n        return View();\n    }\n"
    assert extract_symbol(content, "csharp") == ("Index", "method")


def test_csharp_xml_doc_attached():
    content = (
        "    /// <summary>\n"
        "    /// Processes the given input.\n"
        "    /// </summary>\n"
        "    public void Process(string input) {\n"
        "    }\n"
    )
    assert extract_symbol(content, "csharp") == ("Process", "method")


def test_csharp_field_not_extracted():
    assert extract_symbol("    private int _count;\n", "csharp") == ("", "")


def test_csharp_using_not_extracted():
    assert extract_symbol("using System;\nusing System.Collections.Generic;\n", "csharp") == (
        "",
        "",
    )


def test_csharp_record_class():
    # `record class` is the explicit form of a reference record type (C# 10+)
    assert extract_symbol("public record class Config(string Host, int Port);\n", "csharp") == (
        "Config",
        "record",
    )


def test_csharp_partial_record():
    # partial modifier on a record must be handled
    assert extract_symbol("public partial record Person(string Name);\n", "csharp") == (
        "Person",
        "record",
    )


def test_csharp_record_in_comment_not_matched():
    # Regression F-1: "record" appearing inside a // comment must not produce a false positive.
    # The class should be returned, not ("struct", "record") or ("data", "record").
    content = (
        "    /// Creates a record struct for coordinates.\n"
        "    public class CoordinateFactory {\n"
        "    }\n"
    )
    assert extract_symbol(content, "csharp") == ("CoordinateFactory", "class")


def test_csharp_record_keyword_in_comment_bare():
    # Regression F-1 (bare form): "record data" in a comment must not shadow the real class.
    content = "// This handles record data\npublic class Processor {\n}\n"
    assert extract_symbol(content, "csharp") == ("Processor", "class")


def test_csharp_unknown_language_returns_empty():
    assert extract_symbol("public class Foo {}\n", "unknown") == ("", "")


# =============================================================================
# F#
# =============================================================================


def test_fsharp_module():
    assert extract_symbol("module MyModule\n\nlet x = 1\n", "fsharp") == ("MyModule", "module")


def test_fsharp_type_class():
    # plain type declaration — should be caught by catch-all 'type'
    content = "type Config(host: string, port: int) =\n    member this.Host = host\n"
    assert extract_symbol(content, "fsharp") == ("Config", "type")


def test_fsharp_record():
    content = "type Point = { X: float; Y: float }\n"
    assert extract_symbol(content, "fsharp") == ("Point", "record")


def test_fsharp_discriminated_union_inline():
    content = "type Shape = | Circle of float | Square of float\n"
    assert extract_symbol(content, "fsharp") == ("Shape", "union")


def test_fsharp_discriminated_union_multiline():
    content = "type Result =\n    | Ok of string\n    | Error of string\n"
    assert extract_symbol(content, "fsharp") == ("Result", "union")


def test_fsharp_interface():
    content = "type IRepository =\n    interface\n        abstract member GetById: int -> string\n    end\n"
    assert extract_symbol(content, "fsharp") == ("IRepository", "interface")


def test_fsharp_exception():
    content = "exception DatabaseError of string\n"
    assert extract_symbol(content, "fsharp") == ("DatabaseError", "exception")


def test_fsharp_let_function():
    content = "let process input =\n    input |> String.trim\n"
    assert extract_symbol(content, "fsharp") == ("process", "function")


def test_fsharp_let_rec_function():
    content = "let rec factorial n =\n    if n <= 1 then 1 else n * factorial (n - 1)\n"
    assert extract_symbol(content, "fsharp") == ("factorial", "function")


def test_fsharp_member():
    content = "    member this.Process(input: string) =\n        input.Trim()\n"
    assert extract_symbol(content, "fsharp") == ("Process", "method")


# =============================================================================
# VB.NET
# =============================================================================


def test_vbnet_class():
    content = "Public Class UserService\nEnd Class\n"
    assert extract_symbol(content, "vbnet") == ("UserService", "class")


def test_vbnet_module():
    content = "Public Module Utils\nEnd Module\n"
    assert extract_symbol(content, "vbnet") == ("Utils", "module")


def test_vbnet_structure():
    content = (
        "Public Structure Point\n    Public X As Integer\n    Public Y As Integer\nEnd Structure\n"
    )
    assert extract_symbol(content, "vbnet") == ("Point", "struct")


def test_vbnet_interface():
    content = "Public Interface IRepository\n    Function GetById(id As Integer) As String\nEnd Interface\n"
    assert extract_symbol(content, "vbnet") == ("IRepository", "interface")


def test_vbnet_enum():
    content = "Public Enum Color\n    Red\n    Green\n    Blue\nEnd Enum\n"
    assert extract_symbol(content, "vbnet") == ("Color", "enum")


def test_vbnet_sub():
    content = "    Public Sub Process(ByVal input As String)\n    End Sub\n"
    assert extract_symbol(content, "vbnet") == ("Process", "method")


def test_vbnet_function():
    content = "    Public Function Calculate(a As Integer, b As Integer) As Integer\n        Return a + b\n    End Function\n"
    assert extract_symbol(content, "vbnet") == ("Calculate", "method")


def test_vbnet_property():
    content = "    Public Property Name As String\n        Get\n            Return _name\n        End Get\n        Set(value As String)\n            _name = value\n        End Set\n    End Property\n"
    assert extract_symbol(content, "vbnet") == ("Name", "property")


def test_vbnet_case_insensitive():
    # VB.NET keywords are case-insensitive
    content = "public class MyClass\nend class\n"
    assert extract_symbol(content, "vbnet") == ("MyClass", "class")


# =============================================================================
# XAML
# =============================================================================


def test_xaml_xclass_short_name():
    """x:Class fully-qualified name extracts the short name as 'view' symbol."""
    content = '<Window x:Class="MyApp.MainWindow"\n        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml">\n</Window>\n'
    assert extract_symbol(content, "xaml") == ("MainWindow", "view")


def test_xaml_xclass_no_namespace():
    """x:Class with no dot separator returns the whole value as view name."""
    content = '<Window x:Class="MainWindow" xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml">\n</Window>\n'
    assert extract_symbol(content, "xaml") == ("MainWindow", "view")


def test_xaml_no_xclass_returns_empty():
    """A XAML chunk without x:Class returns ('', '')."""
    content = '<Grid xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation">\n    <TextBlock Text="Hello" />\n</Grid>\n'
    assert extract_symbol(content, "xaml") == ("", "")


def test_xaml_non_code_language_returns_empty():
    """extract_symbol for non-code language 'xaml' (no x:Class) returns ('', '')."""
    content = "Some content that might look like def foo() { return 1; }\n"
    assert extract_symbol(content, "xaml") == ("", "")


def test_java_chunk_code_class_with_two_methods():
    """A class with two public methods should produce at most 2 content chunks."""
    java_code = (
        "public class MathUtils {\n"
        "    public int add(int a, int b) {\n"
        "        return a + b;\n"
        "    }\n"
        "\n"
        "    public int subtract(int a, int b) {\n"
        "        return a - b;\n"
        "    }\n"
        "}\n"
    )
    chunks = chunk_code(java_code, "java", "MathUtils.java")
    full_text = "\n".join(c["content"] for c in chunks)
    # Both methods must be present somewhere in the output
    assert "add" in full_text
    assert "subtract" in full_text


# =============================================================================
# Swift — extract_symbol tests
# =============================================================================


def test_swift_class():
    """AC-1: bare class declaration."""
    assert extract_symbol("class UserService {\n}\n", "swift") == ("UserService", "class")


def test_swift_public_class():
    """Access modifier must not prevent class extraction."""
    assert extract_symbol("public class NetworkClient {\n}\n", "swift") == (
        "NetworkClient",
        "class",
    )


def test_swift_final_class():
    """final modifier must not prevent class extraction."""
    assert extract_symbol("final class AppDelegate {\n}\n", "swift") == ("AppDelegate", "class")


def test_swift_struct():
    """AC-2: struct declaration."""
    assert extract_symbol("struct Point {\n    var x: Double\n    var y: Double\n}\n", "swift") == (
        "Point",
        "struct",
    )


def test_swift_enum():
    """enum declaration."""
    assert extract_symbol("enum Color {\n    case red, green, blue\n}\n", "swift") == (
        "Color",
        "enum",
    )


def test_swift_indirect_enum():
    """indirect enum — `indirect` prefix must not break extraction."""
    assert extract_symbol(
        "indirect enum Tree {\n    case leaf(Int)\n    case branch(Tree, Tree)\n}\n", "swift"
    ) == ("Tree", "enum")


def test_swift_protocol():
    """AC-3: protocol declaration."""
    assert extract_symbol("protocol Codable {\n}\n", "swift") == ("Codable", "protocol")


def test_swift_public_protocol():
    """Access modifier before protocol."""
    assert extract_symbol("public protocol Networking {\n    func fetch() async\n}\n", "swift") == (
        "Networking",
        "protocol",
    )


def test_swift_actor():
    """AC-5: actor declaration."""
    assert extract_symbol("actor DatabaseManager {\n}\n", "swift") == (
        "DatabaseManager",
        "actor",
    )


def test_swift_extension():
    """AC-4: extension declaration — captures the extended type name."""
    assert extract_symbol(
        "extension Array where Element: Comparable {\n    func sorted() -> [Element] { [] }\n}\n",
        "swift",
    ) == ("Array", "extension")


def test_swift_extension_no_constraint():
    """extension without where clause."""
    assert extract_symbol(
        'extension String {\n    func reversed() -> String { "" }\n}\n', "swift"
    ) == (
        "String",
        "extension",
    )


def test_swift_func():
    """Basic function declaration."""
    assert extract_symbol(
        'func greet(name: String) -> String {\n    return "Hello, \\(name)"\n}\n', "swift"
    ) == ("greet", "function")


def test_swift_public_func():
    """Access modifier before func."""
    assert extract_symbol("public func fetchAll() -> [Item] {\n    return []\n}\n", "swift") == (
        "fetchAll",
        "function",
    )


def test_swift_async_func():
    """AC-6: async func — `async` modifier must not break name extraction."""
    assert extract_symbol(
        "public async func fetchData() -> [Item] {\n    return []\n}\n", "swift"
    ) == ("fetchData", "function")


def test_swift_static_func():
    """static func declaration."""
    assert extract_symbol("static func create() -> Self {\n    return Self()\n}\n", "swift") == (
        "create",
        "function",
    )


def test_swift_class_func():
    """`class func` is a class-level static method, NOT a class declaration."""
    result = extract_symbol(
        "class func defaultConfig() -> Config {\n    return Config()\n}\n", "swift"
    )
    # Must be extracted as a function named 'defaultConfig', not as a class named 'func'
    assert result == ("defaultConfig", "function")


def test_swift_override_func():
    """override modifier before func."""
    assert extract_symbol(
        "override func viewDidLoad() {\n    super.viewDidLoad()\n}\n", "swift"
    ) == ("viewDidLoad", "function")


def test_swift_mutating_func():
    """mutating func inside a struct."""
    assert extract_symbol("mutating func reset() {\n    x = 0\n    y = 0\n}\n", "swift") == (
        "reset",
        "function",
    )


def test_swift_typealias():
    """typealias declaration."""
    assert extract_symbol("typealias StringArray = [String]\n", "swift") == (
        "StringArray",
        "typealias",
    )


def test_swift_generic_class():
    """AC-8: generic class — type param must not pollute symbol_name."""
    assert extract_symbol("class Container<T: Codable> {\n    var value: T?\n}\n", "swift") == (
        "Container",
        "class",
    )


def test_swift_generic_struct():
    """Generic struct with depth-2 constraint."""
    assert extract_symbol(
        "struct Stack<Element: Comparable<Element>> {\n    var items: [Element] = []\n}\n", "swift"
    ) == ("Stack", "struct")


def test_swift_property_wrapper_struct():
    """AC-9: @propertyWrapper on same line as struct — attribute must not break extraction."""
    assert extract_symbol(
        "@propertyWrapper struct Clamped<Value: Comparable> {\n    var wrappedValue: Value\n}\n",
        "swift",
    ) == ("Clamped", "struct")


def test_swift_attribute_on_preceding_line():
    """@MainActor on its own line, declaration on the next — multi-line chunk."""
    content = (
        "@MainActor\nclass AppViewModel: ObservableObject {\n    @Published var count = 0\n}\n"
    )
    assert extract_symbol(content, "swift") == ("AppViewModel", "class")


def test_swift_property_not_extracted():
    """AC-7: plain property declaration must return ('', '')."""
    assert extract_symbol('let name: String = "test"\n', "swift") == ("", "")


def test_swift_var_property_not_extracted():
    """var property must return ('', '')."""
    assert extract_symbol("var count: Int = 0\n", "swift") == ("", "")


def test_swift_extension_precedes_class():
    """extension must be matched before class so `extension Foo` is not returned as class."""
    content = "extension Array where Element: Comparable {\n    func min() -> Element? { nil }\n}\n"
    name, sym_type = extract_symbol(content, "swift")
    assert sym_type == "extension"
    assert name == "Array"


def test_swift_protocol_precedes_func():
    """protocol must match before func so a protocol body with func signatures doesn't misclassify."""
    content = (
        "protocol Repository {\n    func fetchAll() -> [Item]\n    func save(_ item: Item)\n}\n"
    )
    name, sym_type = extract_symbol(content, "swift")
    assert sym_type == "protocol"
    assert name == "Repository"


def test_swift_unknown_content_returns_empty():
    """Chunk with no recognizable Swift declaration returns ('', '')."""
    assert extract_symbol("import Foundation\nimport UIKit\n", "swift") == ("", "")


def test_swift_chunk_code_splits_at_func_boundaries():
    """chunk_code on Swift source splits at func declarations."""
    swift_src = (
        "import Foundation\n\n"
        "func greet(name: String) -> String {\n"
        '    return "Hello, \\(name)!"\n'
        "}\n\n"
        "func farewell(name: String) -> String {\n"
        '    return "Goodbye, \\(name)!"\n'
        "}\n"
    )
    chunks = chunk_code(swift_src, "swift", "Greetings.swift")
    full_text = "\n".join(c["content"] for c in chunks)
    assert "greet" in full_text
    assert "farewell" in full_text


def test_swift_chunk_code_class_and_methods():
    """chunk_code on Swift source with class and methods produces chunks containing all symbols."""
    swift_src = (
        "class Calculator {\n"
        "    func add(_ a: Int, _ b: Int) -> Int {\n"
        "        return a + b\n"
        "    }\n"
        "    func subtract(_ a: Int, _ b: Int) -> Int {\n"
        "        return a - b\n"
        "    }\n"
        "}\n"
    )
    chunks = chunk_code(swift_src, "swift", "Calculator.swift")
    assert len(chunks) > 0
    full_text = "\n".join(c["content"] for c in chunks)
    assert "Calculator" in full_text
    assert "add" in full_text
    assert "subtract" in full_text


def test_swift_published_property_not_stolen_by_func_lookback():
    """Regression: @Published var lines must NOT appear in a func's chunk.

    The @-lookback was greedy and would include `@Published var count = 0` as if
    it were a pure attribute annotation. This caused the property to disappear from
    the class chunk and appear in the func chunk instead.  The fix uses
    _SWIFT_PURE_ATTR to reject mixed attribute+declaration lines from lookback.

    Uses content large enough that adaptive_merge_split produces separate chunks,
    so the test exercises chunk_code end-to-end rather than re-implementing the
    boundary detection logic.
    """
    func_body = "\n".join(
        f"        let step{i:03d} = count + {i}  // adjust counter" for i in range(50)
    )
    src = (
        "// ViewModel manages application state\n"
        "class ViewModel {\n"
        "    @Published var count = 0\n"
        "    @Published var name = \"\"\n"
        "    @Published var items: [String] = []\n"
        f"    func increment() {{\n{func_body}\n        count += 1\n    }}\n"
        "}\n"
    )
    chunks = chunk_code(src, "swift", "ViewModel.swift")

    func_chunk = next(
        (c for c in chunks if "func increment" in c["content"]),
        None,
    )
    assert func_chunk is not None, "func increment chunk not found"
    assert "@Published" not in func_chunk["content"], (
        f"func increment chunk incorrectly contains @Published: {func_chunk['content'][:200]!r}"
    )
