"""mining.symbols — Per-language symbol extraction patterns and extract_symbol()."""

import re

# Per-language extraction patterns: list of (compiled_regex, symbol_type).
# Each regex has exactly one capture group for the symbol name.
# Ordered most-specific first within each language.

_PY_EXTRACT = [
    (re.compile(r"^(?:async\s+)?def\s+(\w+)", re.MULTILINE), "function"),
    (re.compile(r"^class\s+(\w+)", re.MULTILINE), "class"),
]

_TS_EXTRACT = [
    (re.compile(r"^export\s+default\s+(?:async\s+)?function\s+(\w+)", re.MULTILINE), "function"),
    (re.compile(r"^export\s+default\s+class\s+(\w+)", re.MULTILINE), "class"),
    (re.compile(r"^(?:export\s+)?(?:async\s+)?function\s+(\w+)", re.MULTILINE), "function"),
    (re.compile(r"^(?:export\s+)?class\s+(\w+)", re.MULTILINE), "class"),
    (re.compile(r"^(?:export\s+)?interface\s+(\w+)", re.MULTILINE), "interface"),
    (re.compile(r"^(?:export\s+)?type\s+(\w+)\s*[=<]", re.MULTILINE), "type"),
    (re.compile(r"^(?:export\s+)?enum\s+(\w+)", re.MULTILINE), "enum"),
    (re.compile(r"^(?:export\s+)?const\s+(\w+)\s*[:=]", re.MULTILINE), "const"),
]

_TS_IMPORT_RE = re.compile(r"^(?:import\s|from\s|require\s*\()", re.MULTILINE)

_GO_EXTRACT = [
    (re.compile(r"^func\s+\(.*?\)\s+(\w+)", re.MULTILINE), "method"),
    (re.compile(r"^func\s+(\w+)", re.MULTILINE), "function"),
    (re.compile(r"^type\s+(\w+)\s+struct", re.MULTILINE), "struct"),
    (re.compile(r"^type\s+(\w+)\s+interface", re.MULTILINE), "interface"),
    (re.compile(r"^type\s+(\w+)\b", re.MULTILINE), "type"),
]

_RUST_EXTRACT = [
    (re.compile(r"^(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?fn\s+(\w+)", re.MULTILINE), "function"),
    (re.compile(r"^(?:pub(?:\([^)]*\))?\s+)?struct\s+(\w+)", re.MULTILINE), "struct"),
    (re.compile(r"^(?:pub(?:\([^)]*\))?\s+)?enum\s+(\w+)", re.MULTILINE), "enum"),
    (re.compile(r"^(?:pub(?:\([^)]*\))?\s+)?trait\s+(\w+)", re.MULTILINE), "trait"),
    (re.compile(r"^(?:pub(?:\([^)]*\))?\s+)?impl(?:\s*<[^>]*>)?\s+(\w+)", re.MULTILINE), "impl"),
    (re.compile(r"^(?:pub(?:\([^)]*\))?\s+)?mod\s+(\w+)", re.MULTILINE), "mod"),
    (re.compile(r"^(?:pub(?:\([^)]*\))?\s+)?type\s+(\w+)", re.MULTILINE), "type"),
]

_C_EXTRACT = [
    (re.compile(r"^struct\s+(\w+)", re.MULTILINE), "struct"),
    (re.compile(r"^enum\s+(\w+)", re.MULTILINE), "enum"),
    # heuristic: word chars, optional *, then name( — matches most top-level C defs
    # [\s*]+ allows pointer return types like `char *func()` with no space before name
    (re.compile(r"^[\w][\w\s*]+[\s*]+(\w+)\s*\([^;]*\)\s*\{", re.MULTILINE), "function"),
]

_CPP_EXTRACT = [
    (re.compile(r"^class\s+(\w+)", re.MULTILINE), "class"),
    (re.compile(r"^struct\s+(\w+)", re.MULTILINE), "struct"),
    (re.compile(r"^enum\s+(?:class\s+)?(\w+)", re.MULTILINE), "enum"),
    # [\s*]+ allows pointer return types like `std::string *getName()`
    (re.compile(r"^[\w][\w\s*:<>]+[\s*]+(\w+)\s*\([^;]*\)\s*\{", re.MULTILINE), "function"),
]

_JAVA_EXTRACT = [
    # @interface must precede class/interface checks (annotation type declaration)
    (re.compile(r"^(?:(?:public|protected)\s+)?@interface\s+(\w+)", re.MULTILINE), "annotation"),
    # record before class (Java 16+; record Foo(...) doesn't start with 'class')
    (
        re.compile(
            r"^(?:(?:public|protected|private|abstract|final|static|sealed|non-sealed|strictfp)\s+)*record\s+(\w+)",
            re.MULTILINE,
        ),
        "record",
    ),
    (
        re.compile(
            r"^(?:(?:public|protected|private|abstract|final|static|sealed|non-sealed|strictfp)\s+)*interface\s+(\w+)",
            re.MULTILINE,
        ),
        "interface",
    ),
    (
        re.compile(
            r"^(?:(?:public|protected|private|abstract|final|static|sealed|non-sealed|strictfp)\s+)*enum\s+(\w+)",
            re.MULTILINE,
        ),
        "enum",
    ),
    (
        re.compile(
            r"^(?:(?:public|protected|private|abstract|final|static|sealed|non-sealed|strictfp)\s+)*class\s+(\w+)",
            re.MULTILINE,
        ),
        "class",
    ),
    # method: modifiers are optional so package-private methods are extracted.
    # Statement keywords are excluded because the zero-modifier path can otherwise
    # resemble return/call statements inside a chunk.
    (
        re.compile(
            r"^(?!(?:return|if|for|while|switch|catch|throw|new|else|do|try|case|assert|break|continue)\b)(?:(?:public|private|protected|static|final|abstract|synchronized|native|default|transient|volatile)\s+)*(?:<[^>]+>\s+)?[\w<>\[\],? ]+(?:\[\])*\s+(\w+)\s*\(",
            re.MULTILINE,
        ),
        "method",
    ),
]

_KOTLIN_EXTRACT = [
    # Most-specific compound keywords first — must precede plain `class`/`interface`/`object`.
    (re.compile(r"data\s+class\s+(\w+)", re.MULTILINE), "data_class"),
    (re.compile(r"sealed\s+class\s+(\w+)", re.MULTILINE), "sealed_class"),
    (re.compile(r"sealed\s+interface\s+(\w+)", re.MULTILINE), "sealed_interface"),
    # enum class (Kotlin uses `enum class`, not bare `enum`)
    (re.compile(r"enum\s+class\s+(\w+)", re.MULTILINE), "enum"),
    # interface/class before companion_object — companion objects appear *inside* class chunks,
    # so checking class/interface first avoids misclassifying an enclosing class as companion_object.
    (
        re.compile(
            r"^(?:(?:public|internal|protected|private|abstract|open|final|override|inline|infix|operator|tailrec|suspend|external|expect|actual)\s+)*interface\s+(\w+)",
            re.MULTILINE,
        ),
        "interface",
    ),
    (
        re.compile(
            r"^(?:(?:public|internal|protected|private|abstract|open|final|override|inline|infix|operator|tailrec|suspend|external|expect|actual|inner|value|annotation)\s+)*class\s+(\w+)",
            re.MULTILINE,
        ),
        "class",
    ),
    # companion object — capture optional name (unnamed companions return "")
    (re.compile(r"companion\s+object\s*(\w*)", re.MULTILINE), "companion_object"),
    # standalone object declarations — after companion_object to avoid partial match on "object Foo" inside "companion object Foo"
    (re.compile(r"object\s+(\w+)", re.MULTILINE), "object"),
    # fun — optional type params (e.g. `fun <T> identity(…)`) and optional receiver type
    # (e.g. `fun String.isEmpty()` → `isEmpty`, `fun <T> List<T>.map()` → `map`).
    # Uses (?:[^<>]|<[^<>]*>)* instead of [^>]+ to handle depth-2 generic nesting, e.g.
    # `fun <T : Comparable<T>> …` and `fun Map<String, List<Int>>.flatten()`.
    (
        re.compile(
            r"^(?:(?:public|internal|protected|private|abstract|open|final|override|inline|infix|operator|tailrec|suspend|external|expect|actual)\s+)*fun\s+(?:<(?:[^<>]|<[^<>]*>)*>\s+)?(?:\w+(?:<(?:[^<>]|<[^<>]*>)*>)?\.)?(\w+)",
            re.MULTILINE,
        ),
        "function",
    ),
    (re.compile(r"typealias\s+(\w+)", re.MULTILINE), "typealias"),
]

_CSHARP_EXTRACT = [
    # record struct — most specific; must precede struct and bare record.
    # ^\s* + modifiers anchors to line start so "record" in comments/strings is never matched.
    (
        re.compile(
            r"^\s*(?:(?:public|private|protected|internal|static|abstract|sealed|partial|new|unsafe|readonly)\s+)*"
            r"record\s+struct\s+(\w+)",
            re.MULTILINE,
        ),
        "record",
    ),
    # record class — must precede class and bare record
    (
        re.compile(
            r"^\s*(?:(?:public|private|protected|internal|static|abstract|sealed|partial|new|unsafe)\s+)*"
            r"record\s+class\s+(\w+)",
            re.MULTILINE,
        ),
        "record",
    ),
    # bare record Foo (implicitly a record class)
    (
        re.compile(
            r"^\s*(?:(?:public|private|protected|internal|static|abstract|sealed|partial|new|unsafe)\s+)*"
            r"record\s+(\w+)",
            re.MULTILINE,
        ),
        "record",
    ),
    # enum — before class/struct; ^\s* handles members indented inside namespace blocks
    (
        re.compile(
            r"^\s*(?:(?:public|private|protected|internal|new)\s+)*enum\s+(\w+)",
            re.MULTILINE,
        ),
        "enum",
    ),
    # struct — before class (more specific keyword)
    (
        re.compile(
            r"^\s*(?:(?:public|private|protected|internal|static|new|readonly|unsafe)\s+)*struct\s+(\w+)",
            re.MULTILINE,
        ),
        "struct",
    ),
    # interface — before class
    (
        re.compile(
            r"^\s*(?:(?:public|private|protected|internal|new)\s+)*interface\s+(\w+)",
            re.MULTILINE,
        ),
        "interface",
    ),
    # class (covers sealed, abstract, static, partial, etc.)
    (
        re.compile(
            r"^\s*(?:(?:public|private|protected|internal|static|abstract|sealed|partial|new|unsafe)\s+)*"
            r"class\s+(\w+)",
            re.MULTILINE,
        ),
        "class",
    ),
    # event — before methods; event keyword is unique anchor
    (
        re.compile(
            r"^\s*(?:(?:public|private|protected|internal|static|virtual|override|sealed|new|abstract)\s+)*"
            r"event\s+[\w<>\[\],? ]+\s+(\w+)",
            re.MULTILINE,
        ),
        "event",
    ),
    # property: at least one modifier, anchored by trailing { or =>
    (
        re.compile(
            r"^\s*(?:(?:public|private|protected|internal|static|abstract|virtual|override|sealed|new|extern|unsafe)\s+)+"
            r"[\w<>\[\],? ]+(?:\[\])*\s+(\w+)\s*(?:\{|=>)",
            re.MULTILINE,
        ),
        "property",
    ),
    # method/constructor: at least one modifier; return type optional for constructors
    (
        re.compile(
            r"^\s*(?:(?:public|private|protected|internal|static|abstract|virtual|override|sealed|new|extern|unsafe|async|partial)\s+)+"
            r"(?:[\w<>\[\],? ]+\s+)?(\w+)\s*[\(<]",
            re.MULTILINE,
        ),
        "method",
    ),
]

_FSHARP_EXTRACT = [
    # Discriminated union: type Foo = | ... or type Foo =\n    | ...
    # Most specific — must precede record (type = {) and type catch-all.
    (re.compile(r"^type\s+(\w+)\s*=\s*(?:\||\n\s*\|)", re.MULTILINE), "union"),
    # Record: type Foo = {
    (re.compile(r"^type\s+(\w+)\s*=\s*\{", re.MULTILINE), "record"),
    # Interface with [<Interface>] attribute on preceding line
    (
        re.compile(r"\[<Interface>\][^\n]*\n\s*type\s+(\w+)", re.MULTILINE | re.IGNORECASE),
        "interface",
    ),
    # Interface: type Foo = interface
    (re.compile(r"^type\s+(\w+)\s*=\s*interface", re.MULTILINE | re.IGNORECASE), "interface"),
    # Module
    (re.compile(r"^module\s+(\w+)", re.MULTILINE), "module"),
    # Exception
    (re.compile(r"^exception\s+(\w+)", re.MULTILINE), "exception"),
    # Type (catch-all: class, struct, abbreviation, etc.) — after all specific type patterns
    (re.compile(r"^type\s+(\w+)", re.MULTILINE), "type"),
    # Member function (indented: member this.Foo or member x.Foo)
    (re.compile(r"^\s*member\s+(?:\w+)\.(\w+)", re.MULTILINE), "method"),
    # Top-level let binding (function or value)
    (re.compile(r"^let\s+(?:rec\s+)?(?:inline\s+)?(\w+)", re.MULTILINE), "function"),
]

_VBNET_EXTRACT = [
    # Enum — before structure/class to avoid false matches on e.g. `Class EnumHelper`
    (
        re.compile(
            r"^\s*(?:(?:Protected\s+Friend|Private\s+Protected|Public|Private|Protected|Friend)\s+)?"
            r"(?:(?:Shared|Shadows|Partial)\s+)*Enum\s+(\w+)",
            re.MULTILINE | re.IGNORECASE,
        ),
        "enum",
    ),
    # Structure — before class
    (
        re.compile(
            r"^\s*(?:(?:Protected\s+Friend|Private\s+Protected|Public|Private|Protected|Friend)\s+)?"
            r"(?:(?:Partial|Shadows)\s+)*Structure\s+(\w+)",
            re.MULTILINE | re.IGNORECASE,
        ),
        "struct",
    ),
    # Interface — before class
    (
        re.compile(
            r"^\s*(?:(?:Protected\s+Friend|Private\s+Protected|Public|Private|Protected|Friend)\s+)?"
            r"(?:(?:Partial|Shadows)\s+)*Interface\s+(\w+)",
            re.MULTILINE | re.IGNORECASE,
        ),
        "interface",
    ),
    # Module — limited access (Public or Friend only)
    (
        re.compile(
            r"^\s*(?:(?:Public|Friend)\s+)?Module\s+(\w+)",
            re.MULTILINE | re.IGNORECASE,
        ),
        "module",
    ),
    # Class
    (
        re.compile(
            r"^\s*(?:(?:Protected\s+Friend|Private\s+Protected|Public|Private|Protected|Friend)\s+)?"
            r"(?:(?:MustInherit|NotInheritable|Partial|Shadows)\s+)*Class\s+(\w+)",
            re.MULTILINE | re.IGNORECASE,
        ),
        "class",
    ),
    # Property — before Sub/Function
    (
        re.compile(
            r"^\s*(?:(?:Protected\s+Friend|Private\s+Protected|Public|Private|Protected|Friend)\s+)?"
            r"(?:(?:Shared|Default|ReadOnly|WriteOnly|Shadows|Overridable|NotOverridable|Overrides|Overloads)\s+)*"
            r"Property\s+(\w+)",
            re.MULTILINE | re.IGNORECASE,
        ),
        "property",
    ),
    # Sub/Function
    (
        re.compile(
            r"^\s*(?:(?:Protected\s+Friend|Private\s+Protected|Public|Private|Protected|Friend)\s+)?"
            r"(?:(?:Shared|Overridable|MustOverride|NotOverridable|Overrides|Overloads|Async|Static|Default|Shadows)\s+)*"
            r"(?:Sub|Function)\s+(\w+)",
            re.MULTILINE | re.IGNORECASE,
        ),
        "method",
    ),
]

_SWIFT_EXTRACT = [
    # extension — capture type name; `where` constraints and generics are ignored.
    # Must precede class/struct to avoid matching `extension` inside class modifiers.
    (
        re.compile(
            r"^(?:@\w+(?:\([^)]*\))?\s+)*"
            r"(?:(?:public|private|fileprivate|internal|open|final)\s+)*"
            r"extension\s+(\w+)",
            re.MULTILINE,
        ),
        "extension",
    ),
    # actor — first-class concurrency primitive (Swift 5.5+)
    (
        re.compile(
            r"^(?:@\w+(?:\([^)]*\))?\s+)*"
            r"(?:(?:public|private|fileprivate|internal|open|final|distributed)\s+)*"
            r"actor\s+(\w+)",
            re.MULTILINE,
        ),
        "actor",
    ),
    # protocol — before class (both are nominal types)
    (
        re.compile(
            r"^(?:@\w+(?:\([^)]*\))?\s+)*"
            r"(?:(?:public|private|fileprivate|internal)\s+)*"
            r"protocol\s+(\w+)",
            re.MULTILINE,
        ),
        "protocol",
    ),
    # enum — before struct/class (avoids swallowing `indirect` prefix)
    (
        re.compile(
            r"^(?:@\w+(?:\([^)]*\))?\s+)*"
            r"(?:(?:public|private|fileprivate|internal|indirect)\s+)*"
            r"enum\s+(\w+)",
            re.MULTILINE,
        ),
        "enum",
    ),
    # struct
    (
        re.compile(
            r"^(?:@\w+(?:\([^)]*\))?\s+)*"
            r"(?:(?:public|private|fileprivate|internal|final)\s+)*"
            r"struct\s+(\w+)",
            re.MULTILINE,
        ),
        "struct",
    ),
    # class — covers `final class`, `open class`, bare `class`, etc.
    # Negative lookahead prevents matching `class func` or `class var` where `class`
    # acts as a declaration modifier rather than introducing a type declaration.
    (
        re.compile(
            r"^(?:@\w+(?:\([^)]*\))?\s+)*"
            r"(?:(?:public|private|fileprivate|internal|open|final)\s+)*"
            r"class\s+(?!(?:func|var|let|struct|enum|protocol|actor|extension|typealias)\b)(\w+)",
            re.MULTILINE,
        ),
        "class",
    ),
    # func — optional modifiers including `class func`, `static func`, `async func`.
    # Distributed actor methods may also use `distributed func`.
    # Generic type params appear AFTER the name in Swift (`func foo<T>(...)`), so no
    # pre-name generic arm is needed; `(\w+)` captures the name directly after `func `.
    (
        re.compile(
            r"^(?:@\w+(?:\([^)]*\))?\s+)*"
            r"(?:(?:public|private|fileprivate|internal|open|final|static|class|override|"
            r"mutating|nonmutating|nonisolated|async|distributed)\s+)*"
            r"func\s+(\w+)",
            re.MULTILINE,
        ),
        "function",
    ),
    # typealias
    (
        re.compile(
            r"^(?:@\w+(?:\([^)]*\))?\s+)*"
            r"(?:(?:public|private|fileprivate|internal)\s+)*"
            r"typealias\s+(\w+)",
            re.MULTILINE,
        ),
        "typealias",
    ),
]

_XAML_EXTRACT = [
    # Extract view name from root element's x:Class attribute (fully-qualified → short name).
    # Only the first chunk (root element) will match; subsequent chunks get ("", "").
    (re.compile(r'x:Class="(?:[\w.]+\.)?(\w+)"'), "view"),
]

# PHP extraction patterns.
# Order matters: interface → trait → enum → class → function → namespace (last).
# namespace uses [\w\\]+ to capture qualified names like App\Http\Controllers.
# abstract/final/readonly are valid class/interface/trait/enum modifiers.
# namespace is last so that when a small namespace chunk merges with a class chunk,
# the class/interface/trait/enum takes priority as the primary symbol.
# A pure namespace-only chunk still extracts as 'namespace' because no other pattern matches.
_PHP_EXTRACT = [
    # interface — before class (both are type declarations; interface is more specific)
    (
        re.compile(
            r"^(?:(?:abstract|final|readonly)\s+)*interface\s+(\w+)",
            re.MULTILINE,
        ),
        "interface",
    ),
    # trait — before class
    (
        re.compile(
            r"^(?:(?:abstract|final|readonly)\s+)*trait\s+(\w+)",
            re.MULTILINE,
        ),
        "trait",
    ),
    # enum (PHP 8.1+) — optional backing type (`: string`, `: int`) is ignored
    (
        re.compile(
            r"^(?:(?:abstract|final|readonly)\s+)*enum\s+(\w+)",
            re.MULTILINE,
        ),
        "enum",
    ),
    # class — covers abstract class, final class, readonly class (PHP 8.2+)
    (
        re.compile(
            r"^(?:(?:abstract|final|readonly)\s+)*class\s+(\w+)",
            re.MULTILINE,
        ),
        "class",
    ),
    # function — standalone functions and methods (access/static modifiers optional)
    (
        re.compile(
            r"^(?:(?:public|private|protected|static|abstract|final)\s+)*function\s+(\w+)",
            re.MULTILINE,
        ),
        "function",
    ),
    # namespace — last; only extracted when no type declaration is present in the chunk.
    # Uses [\w\\]+ to capture fully-qualified names like App\Http\Controllers.
    (re.compile(r"^namespace\s+([\w\\]+)", re.MULTILINE), "namespace"),
]

# Scala extraction patterns (.scala and .sc files).
# Order is strict: case_class before class, case_object before object (plan §Pattern ordering).
# type alias requires a following `=` so type params in generic signatures are never matched.
_SCALA_MODIFIERS = (
    r"(?:@\w+(?:\([^)]*\))?\s+)*"
    r"(?:(?:private|protected|final|sealed|abstract|override|implicit|lazy|inline|opaque|open)"
    r"(?:\[[\w.]+\])?\s+)*"
)

_SCALA_EXTRACT = [
    # case class — before class (most specific; avoids class swallowing the case form)
    (
        re.compile(
            r"^" + _SCALA_MODIFIERS + r"case\s+class\s+(\w+)",
            re.MULTILINE,
        ),
        "case_class",
    ),
    # case object — before object
    (
        re.compile(
            r"^" + _SCALA_MODIFIERS + r"case\s+object\s+(\w+)",
            re.MULTILINE,
        ),
        "case_object",
    ),
    # trait
    (
        re.compile(
            r"^" + _SCALA_MODIFIERS + r"trait\s+(\w+)",
            re.MULTILINE,
        ),
        "trait",
    ),
    # object — standalone singleton object declarations
    (
        re.compile(
            r"^" + _SCALA_MODIFIERS + r"object\s+(\w+)",
            re.MULTILINE,
        ),
        "object",
    ),
    # class — covers implicit class, sealed abstract class, open class, etc.
    (
        re.compile(
            r"^" + _SCALA_MODIFIERS + r"class\s+(\w+)",
            re.MULTILINE,
        ),
        "class",
    ),
    # enum (Scala 3)
    (
        re.compile(
            r"^" + _SCALA_MODIFIERS + r"enum\s+(\w+)",
            re.MULTILINE,
        ),
        "enum",
    ),
    # def — covers implicit def, override def, inline def, etc.
    (
        re.compile(
            r"^" + _SCALA_MODIFIERS + r"def\s+(\w+)",
            re.MULTILINE,
        ),
        "function",
    ),
    # type alias — the `[^=\n]*=` suffix handles type params of arbitrary nesting depth while
    # requiring an `=` so that abstract type members (type T <: Bound) are not matched.
    (
        re.compile(
            r"^" + _SCALA_MODIFIERS + r"type\s+(\w+)[^=\n]*=",
            re.MULTILINE,
        ),
        "type",
    ),
]

# Dart extraction patterns (.dart files).
# Order is strict (per plan §Pattern ordering):
#   1. extension type — before extension (Dart 3.3+; zero-cost wrapper distinct from extension)
#   2. mixin class    — before class and mixin (mixin here is a modifier on class)
#   3. mixin          — before class
#   4. enum / typedef — disjoint keywords
#   5. class          — with optional Dart 3 modifier chain
#   6. factory constructor — unique `factory` anchor keyword
#   7. typed top-level function — loosest pattern, last
_DART_MODIFIERS = r"(?:@\w+(?:\([^)]*\))?\s+)*"
_DART_CLASS_MOD = r"(?:(?:abstract|base|final|interface|sealed|mixin)\s+)*"

_DART_EXTRACT = [
    # extension type (Dart 3.3+) — distinct from plain extension
    (
        re.compile(
            r"^" + _DART_MODIFIERS + _DART_CLASS_MOD + r"extension\s+type\s+(\w+)",
            re.MULTILINE,
        ),
        "extension_type",
    ),
    # plain extension — named extension on a type
    (
        re.compile(
            r"^" + _DART_MODIFIERS + _DART_CLASS_MOD + r"extension\s+(\w+)\s+on\b",
            re.MULTILINE,
        ),
        "extension",
    ),
    # mixin class — before class and plain mixin (mixin is a class modifier here)
    (
        re.compile(
            r"^"
            + _DART_MODIFIERS
            + r"(?:(?:abstract|base|final|interface|sealed)\s+)*mixin\s+class\s+(\w+)",
            re.MULTILINE,
        ),
        "class",
    ),
    # plain mixin (standalone mixin declaration)
    (
        re.compile(
            r"^" + _DART_MODIFIERS + r"(?:base\s+)?mixin\s+(\w+)\b",
            re.MULTILINE,
        ),
        "mixin",
    ),
    # enum
    (
        re.compile(
            r"^" + _DART_MODIFIERS + r"enum\s+(\w+)",
            re.MULTILINE,
        ),
        "enum",
    ),
    # typedef — emits symbol_type='type' (consistent with Scala/Swift typealias)
    (
        re.compile(
            r"^typedef\s+(\w+)",
            re.MULTILINE,
        ),
        "type",
    ),
    # class with optional Dart 3 modifier chain
    (
        re.compile(
            r"^" + _DART_MODIFIERS + _DART_CLASS_MOD + r"class\s+(\w+)",
            re.MULTILINE,
        ),
        "class",
    ),
    # factory constructor — const or plain factory; captures ClassName or ClassName.named
    (
        re.compile(
            r"^\s*(?:const\s+)?factory\s+(\w+(?:\.\w+)?)\s*[(<]",
            re.MULTILINE,
        ),
        "constructor",
    ),
    # typed top-level function — requires explicit return type; uses explicit lowercase primitives
    # (int/double/bool/num/dynamic/never) to avoid matching Dart keywords (const/var/final/return)
    # as false-positive return types.
    (
        re.compile(
            r"^(?:(?:external|static|abstract)\s+)*"
            r"(?:void|int|double|num|bool|dynamic|never"
            r"|Future(?:<[^>]*>)?|Stream(?:<[^>]*>)?|[A-Z]\w*(?:<[^>]*>)?)"
            r"\??\s+(\w+)\s*(?:<[^>]*>)?\s*\(",
            re.MULTILINE,
        ),
        "function",
    ),
]

# Lua extraction patterns (.lua files) — most-specific first (colon/dot before plain function).
_LUA_EXTRACT = [
    (re.compile(r"^local\s+function\s+(\w+)\s*\(", re.MULTILINE), "local_function"),
    (re.compile(r"^function\s+(\w+:\w+)\s*\(", re.MULTILINE), "method"),
    (re.compile(r"^function\s+(\w+\.\w+)\s*\(", re.MULTILINE), "method"),
    (re.compile(r"^function\s+(\w+)\s*\(", re.MULTILINE), "function"),
    (re.compile(r"^(?:local\s+)?([A-Z]\w*)\s*=\s*\{\}", re.MULTILINE), "module"),
]

# Ansible: task keys that are NOT the module name
_ANSIBLE_NON_MODULE_KEYS = frozenset(
    {
        "name",
        "register",
        "when",
        "loop",
        "with_items",
        "with_list",
        "with_dict",
        "with_fileglob",
        "notify",
        "tags",
        "become",
        "become_user",
        "become_method",
        "vars",
        "block",
        "rescue",
        "always",
        "ignore_errors",
        "failed_when",
        "changed_when",
        "no_log",
        "delegate_to",
        "run_once",
        "until",
        "retries",
        "delay",
        "listen",
        "any_errors_fatal",
        "environment",
        "check_mode",
        "diff",
        "module_defaults",
    }
)

# Regex for extracting name/hosts from Ansible YAML text (tolerates Jinja delimiters in values)
_ANSIBLE_NAME_RE = re.compile(r"^\s*-?\s*name\s*:\s*(.+)", re.MULTILINE)
_ANSIBLE_HOSTS_RE = re.compile(r"^\s*(?:-\s+)?hosts\s*:\s*(.+)", re.MULTILINE)
# Module key: indented 2 spaces from list item, word chars followed by colon
_ANSIBLE_MODULE_KEY_RE = re.compile(r"^  (\w+)\s*:", re.MULTILINE)


def _extract_ansible_task_module(content: str) -> str:
    """Scan task text for the module key (first non-meta key at 2-space indent)."""
    for m in _ANSIBLE_MODULE_KEY_RE.finditer(content):
        key = m.group(1)
        if key not in _ANSIBLE_NON_MODULE_KEYS:
            return key
    return ""


def _extract_ansible_play_symbol(content: str) -> tuple:
    """Extract (symbol_name, symbol_type) from an Ansible play chunk."""
    name = ""
    name_m = _ANSIBLE_NAME_RE.search(content)
    if name_m:
        name = name_m.group(1).strip().strip("'\"")
    hosts = ""
    hosts_m = _ANSIBLE_HOSTS_RE.search(content)
    if hosts_m:
        hosts = hosts_m.group(1).strip().strip("'\"")
    if name and hosts:
        return (f"{name} hosts={hosts}", "ansible_play")
    if name:
        return (name, "ansible_play")
    if hosts:
        return (f"hosts={hosts}", "ansible_play")
    return ("", "ansible_play")


def _extract_ansible_task_symbol(content: str) -> tuple:
    """Extract (symbol_name, symbol_type) from an Ansible task chunk."""
    name = ""
    name_m = _ANSIBLE_NAME_RE.search(content)
    if name_m:
        name = name_m.group(1).strip().strip("'\"")
    module = _extract_ansible_task_module(content)
    if name and module:
        return (f"{name} [{module}]", "ansible_task")
    if name:
        return (name, "ansible_task")
    if module:
        return (module, "ansible_task")
    return ("", "ansible_task")


def _extract_ansible_handler_symbol(content: str) -> tuple:
    """Extract (symbol_name, symbol_type) from an Ansible handler chunk."""
    name = ""
    name_m = _ANSIBLE_NAME_RE.search(content)
    if name_m:
        name = name_m.group(1).strip().strip("'\"")
    module = _extract_ansible_task_module(content)
    if name and module:
        return (f"{name} [{module}]", "ansible_handler")
    if name:
        return (name, "ansible_handler")
    return ("", "ansible_handler")


def _extract_ansible_symbol(content: str) -> tuple:
    """Extract Ansible symbol from chunk content, inferring the type from content structure."""
    # INI inventory: section headers like [webservers] at column 0
    if re.search(r"^\[", content, re.MULTILINE):
        return ("", "ansible_inventory")
    # Inventory: no semantic symbol
    if not content.strip().startswith("- "):
        # Mapping-style: could be vars/inventory
        if re.search(r"^\s*(all|ungrouped)\s*:", content, re.MULTILINE):
            return ("", "ansible_inventory")
        return ("", "ansible_vars")
    # List-style: play (has hosts:) or task
    if _ANSIBLE_HOSTS_RE.search(content):
        return _extract_ansible_play_symbol(content)
    return _extract_ansible_task_symbol(content)


_RB_EXTRACT = [
    (re.compile(r"^\s*module\s+([A-Z]\w*(?:::[A-Z]\w*)*)", re.MULTILINE), "module"),
    # class follows module so nested scopes still surface the outer namespace first.
    (re.compile(r"^\s*class\s+([A-Z]\w*(?:::[A-Z]\w*)*)", re.MULTILINE), "class"),
    # Methods: regular, singleton, predicate, and bang forms.
    (
        re.compile(r"^\s*def\s+(?:self\.)?([a-z_]\w*[!?=]?)", re.MULTILINE),
        "method",
    ),
    (
        re.compile(r"^\s*attr_(?:reader|writer|accessor)\s+(?::)?([a-z_]\w*)", re.MULTILINE),
        "attr",
    ),
    (re.compile(r"^\s*attr\b\s+(?::)?([a-z_]\w*)", re.MULTILINE), "attr"),
    (
        re.compile(r"^\s*([A-Z]\w*(?:::[A-Z]\w*)*)\s*=", re.MULTILINE),
        "constant",
    ),
]

_LANG_EXTRACT_MAP = {
    "python": _PY_EXTRACT,
    "typescript": _TS_EXTRACT,
    "javascript": _TS_EXTRACT,
    "tsx": _TS_EXTRACT,
    "jsx": _TS_EXTRACT,
    "go": _GO_EXTRACT,
    "rust": _RUST_EXTRACT,
    "c": _C_EXTRACT,
    "cpp": _CPP_EXTRACT,
    "java": _JAVA_EXTRACT,
    "kotlin": _KOTLIN_EXTRACT,
    "csharp": _CSHARP_EXTRACT,
    "fsharp": _FSHARP_EXTRACT,
    "vbnet": _VBNET_EXTRACT,
    "swift": _SWIFT_EXTRACT,
    "xaml": _XAML_EXTRACT,
    "php": _PHP_EXTRACT,
    "scala": _SCALA_EXTRACT,
    "dart": _DART_EXTRACT,
    "lua": _LUA_EXTRACT,
    "ruby": _RB_EXTRACT,
}


def _extract_k8s_symbol(content: str) -> tuple:
    """Extract kind and metadata.name from a single K8s manifest document."""
    kind_m = re.search(r"^kind:\s*(\w+)", content, re.MULTILINE)
    if not kind_m:
        return ("", "")
    kind = kind_m.group(1)
    name_m = re.search(r"^\s{2}name:\s*(\S+)", content, re.MULTILINE)
    if name_m:
        return (f"{kind}/{name_m.group(1)}", kind.lower())
    return (kind, kind.lower())


# Matches a line consisting entirely of a Go template expression (with optional surrounding whitespace)
_GO_TEMPLATE_ONLY_LINE = re.compile(r"^\s*\{\{.*?\}\}\s*$")


def _extract_helm_chart_symbol(content: str) -> tuple:
    """Extract chart name from Chart.yaml content. Returns (HelmChart/<name>, helm_chart)."""
    m = re.search(r"^name:\s*(\S+)", content, re.MULTILINE)
    if not m:
        return ("", "helm_chart")
    name = m.group(1).strip("'\"")
    return (f"HelmChart/{name}", "helm_chart")


def _extract_helm_template_symbol(content: str) -> tuple:
    """Extract kind and name from a Helm template document, tolerating Go template expressions.

    Lines that are purely Go template control blocks (e.g. {{- if ... }}) are filtered out
    before scanning. If metadata.name contains {{ it is considered templated and the symbol
    falls back to kind-only.
    """
    visible_lines = [line for line in content.splitlines() if not _GO_TEMPLATE_ONLY_LINE.match(line)]
    visible = "\n".join(visible_lines)

    kind_m = re.search(r"^kind:\s*(\w+)", visible, re.MULTILINE)
    if not kind_m:
        return ("", "")
    kind = kind_m.group(1)

    name_m = re.search(r"^\s{2}name:\s*(\S+)", visible, re.MULTILINE)
    if name_m:
        name_val = name_m.group(1)
        if "{{" not in name_val:
            return (f"{kind}/{name_val}", kind.lower())

    return (kind, kind.lower())


def extract_symbol(content: str, language: str) -> tuple:
    """
    Extract the primary symbol defined in a code chunk.
    Returns (symbol_name, symbol_type) or ("", "") if none found.
    Non-code languages (markdown, text, json, yaml, unknown, etc.) return ("", "").
    TS/JS import-only chunks return ("", "import").
    """
    if language == "kubernetes":
        return _extract_k8s_symbol(content)

    if language == "ansible":
        return _extract_ansible_symbol(content)

    patterns = _LANG_EXTRACT_MAP.get(language)
    if patterns is None:
        return ("", "")

    # TS/JS: detect import-only chunks (first non-empty line starts with an import keyword)
    is_import_chunk = False
    if language in ("typescript", "javascript", "tsx", "jsx"):
        first_non_empty = next((line for line in content.splitlines() if line.strip()), "")
        is_import_chunk = bool(_TS_IMPORT_RE.match(first_non_empty.strip()))

    for pattern, sym_type in patterns:
        m = re.search(pattern, content)
        if m:
            return (m.group(1), sym_type)

    return ("", "import") if is_import_chunk else ("", "")
