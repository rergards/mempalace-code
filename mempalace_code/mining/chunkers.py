"""mining.chunkers — Boundary regexes and chunking strategies for all supported languages."""

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from ..language_catalog import extension_language_map
from ..treesitter import get_parser
from .symbols import (
    _extract_ansible_handler_symbol,
    _extract_ansible_play_symbol,
    _extract_ansible_task_symbol,
    _extract_helm_chart_symbol,
    _extract_helm_template_symbol,
    _extract_k8s_symbol,
    extract_symbol,
)

EXTENSION_LANG_MAP = extension_language_map()

_HELM_VALUES_NAME_RE = re.compile(r"^values.*\.ya?ml$")

MIN_CHUNK = 100  # chars — blocks below this always merge into a neighbour (never dropped)
TARGET_MIN = 400  # chars — unnamed declarations smaller than this together may share a chunk
TARGET_MAX = 2500  # chars — ideal max for a logical unit
HARD_MAX = 4000  # chars — absolute max before forced split

# Chunker strategy identifiers stored on every mined drawer. Bump the suffix whenever
# chunk boundaries or stored text change: the next incremental mine re-chunks every
# file whose drawers carry an identifier outside FILE_CHUNKER_STRATEGIES.
STRATEGY_REGEX_STRUCTURAL = "regex_structural_v3"
STRATEGY_TREESITTER = "treesitter_v3"
STRATEGY_TREESITTER_ADAPTIVE = "treesitter_adaptive_v2"
STRATEGY_DOTNET_PROJECT_XML = "dotnet_project_xml_v2"
FILE_CHUNKER_STRATEGIES = frozenset(
    {
        STRATEGY_REGEX_STRUCTURAL,
        STRATEGY_TREESITTER,
        STRATEGY_TREESITTER_ADAPTIVE,
        STRATEGY_DOTNET_PROJECT_XML,
    }
)

# Extensions routed through the verbatim project-XML chunker
_DOTNET_PROJECT_FILE_EXTS = frozenset({".csproj", ".fsproj", ".vbproj"})

# =============================================================================
# CHUNKING — boundary regexes
# =============================================================================

# TypeScript / JavaScript structural boundaries
TS_BOUNDARY = re.compile(
    r"^(?:"
    r"export\s+(?:default\s+)?(?:async\s+)?(?:function|class|interface|type|enum|const|let|var)\b"
    r"|(?:async\s+)?function\s+\w+"
    r"|class\s+\w+"
    r"|interface\s+\w+"
    r"|type\s+\w+\s*[=<]"
    r"|enum\s+\w+"
    r"|const\s+\w+\s*[:=]"
    r"|let\s+\w+\s*[:=]"
    r"|var\s+\w+\s*[:=]"
    r"|(?:describe|it|test|beforeEach|afterEach|beforeAll|afterAll)\s*\("
    r"|module\.exports"
    r"|exports\.\w+"
    r")",
    re.MULTILINE,
)

# Import block detection for TS/JS (group all imports together)
TS_IMPORT = re.compile(r"^(?:import\s|from\s|require\s*\()", re.MULTILINE)

# Python structural boundaries
PY_BOUNDARY = re.compile(
    r"^(?:"
    r"(?:async\s+)?def\s+\w+"
    r"|class\s+\w+"
    r"|@\w+"
    r")",
    re.MULTILINE,
)

# Go structural boundaries
GO_BOUNDARY = re.compile(
    r"^(?:"
    r"func\s+(?:\(.*?\)\s*)?\w+"
    r"|type\s+\w+"
    r"|var\s+\("
    r"|const\s+\("
    r")",
    re.MULTILINE,
)

# Rust structural boundaries
RUST_BOUNDARY = re.compile(
    r"^(?:"
    r"(?:pub(?:\(crate\))?\s+)?(?:async\s+)?fn\s+\w+"
    r"|(?:pub(?:\(crate\))?\s+)?(?:struct|enum|trait|impl|mod|type)\s+\w+"
    r"|#\["
    r")",
    re.MULTILINE,
)

# Java structural boundaries — matches against stripped lines (indented methods inside classes).
# Deliberately excludes bare `@\w+` to avoid spurious boundaries on annotations inside method
# bodies (e.g. @SuppressWarnings("unchecked") on a local variable).  Class-level annotations
# will appear in the preamble or be merged by adaptive_merge_split.
JAVA_BOUNDARY = re.compile(
    r"^(?:"
    r"(?:(?:public|protected|private|abstract|final|static|sealed|non-sealed|strictfp)\s+)*(?:class|interface|enum|record)\s+\w+"
    r"|(?:(?:public|protected)\s+)?@interface\s+\w+"
    r"|(?:(?:public|private|protected|static|final|abstract|synchronized|native|default|transient|volatile)\s+)+(?:<[^>]+>\s+)?[\w<>\[\],? ]+(?:\[\])*\s+\w+\s*\("
    r")",
    re.MULTILINE,
)

# Kotlin structural boundaries — matches against stripped lines.
# Deliberately excludes `companion object` to avoid splitting enclosing class chunks.
# Properties (val/var) are also excluded — too noisy as boundaries.
KOTLIN_BOUNDARY = re.compile(
    r"^(?:"
    r"(?:(?:public|internal|protected|private|abstract|final|open|sealed|data|inner|value|annotation)\s+)*(?:class|interface|object)\s+\w+"
    r"|(?:(?:public|internal|protected|private)\s+)*enum\s+class\s+\w+"
    r"|(?:(?:public|internal|protected|private|abstract|open|final|override|inline|infix|operator|tailrec|suspend|external|expect|actual)\s+)*fun\s+"
    r"|(?:(?:public|internal|protected|private)\s+)*typealias\s+\w+"
    r")",
    re.MULTILINE,
)

# C# structural boundaries — matches against stripped lines (members are indented inside
# classes/namespaces). Requires at least one access modifier for methods/properties to avoid
# false positives on field declarations and local variables.
# Deliberately excludes: namespace declarations (wrap entire files), bare field declarations
# (too noisy), using directives (import-like), and #region/#endregion (IDE-only markers).
CSHARP_BOUNDARY = re.compile(
    r"^(?:"
    # Type declarations: class, struct, interface, record (covers partial, sealed, abstract, static)
    r"(?:(?:public|private|protected|internal|static|abstract|sealed|partial|new|unsafe)\s+)*"
    r"(?:class|struct|interface|record)\s+\w+"
    # Enum (bare enum, not 'enum class' like Kotlin)
    r"|(?:(?:public|private|protected|internal|new)\s+)*enum\s+\w+"
    # Events — event keyword is the unique anchor
    r"|(?:(?:public|private|protected|internal|static|virtual|override|sealed|new|abstract)\s+)*event\s+"
    # Methods and constructors: at least one modifier required; return type optional for constructors
    r"|(?:(?:public|private|protected|internal|static|abstract|virtual|override|sealed|new|extern|unsafe|async|partial)\s+)+"
    r"(?:[\w<>\[\],?\s]+\s+)?\w+\s*[\(<]"
    # Properties: at least one modifier, distinguished from fields by trailing { or =>
    r"|(?:(?:public|private|protected|internal|static|abstract|virtual|override|sealed|new|extern|unsafe)\s+)+"
    r"[\w<>\[\],? ]+(?:\[\])*\s+\w+\s*(?:\{|=>)"
    r")",
    re.MULTILINE,
)

# F# structural boundaries — top-level and member declarations.
# F# is whitespace-significant; top-level declarations start at column 0,
# members may be indented. All boundary types are matched.
FSHARP_BOUNDARY = re.compile(
    r"^(?:"
    r"module\s+\w+"
    r"|type\s+\w+"
    r"|let\s+(?:rec\s+)?(?:inline\s+)?\w+"
    r"|member\s+(?:\w+)\.\w+"
    r"|interface\s+\w+"
    r"|exception\s+\w+"
    r")",
    re.MULTILINE,
)

# VB.NET structural boundaries. VB.NET keywords are case-insensitive.
# Boundaries fire at the *opening* declaration; End Class / End Sub are not boundaries.
VBNET_BOUNDARY = re.compile(
    r"^(?:"
    # Class with optional access + type modifiers
    r"(?:(?:Public|Private|Protected\s+Friend|Private\s+Protected|Protected|Friend)\s+)?"
    r"(?:(?:MustInherit|NotInheritable|Partial)\s+)*"
    r"Class\s+\w+"
    # Module
    r"|(?:(?:Public|Friend)\s+)?Module\s+\w+"
    # Structure
    r"|(?:(?:Public|Private|Protected|Friend)\s+)?Structure\s+\w+"
    # Interface
    r"|(?:(?:Public|Private|Protected|Friend)\s+)?Interface\s+\w+"
    # Enum
    r"|(?:(?:Public|Private|Protected|Friend)\s+)?Enum\s+\w+"
    # Sub/Function with optional access + method modifiers
    r"|(?:(?:Public|Private|Protected\s+Friend|Private\s+Protected|Protected|Friend)\s+)?"
    r"(?:(?:Shared|Overridable|MustOverride|NotOverridable|Overrides|Overloads|Async|Static)\s+)*"
    r"(?:Sub|Function)\s+\w+"
    # Property
    r"|(?:(?:Public|Private|Protected|Friend)\s+)?(?:(?:Shared|ReadOnly|WriteOnly)\s+)?Property\s+\w+"
    r")",
    re.MULTILINE | re.IGNORECASE,
)

# Swift structural boundaries.
# Handles: class, struct, enum, protocol, actor, extension, func, typealias.
# Excludes var/let properties (too noisy, same rationale as Kotlin).
# Optional inline attribute prefix (e.g. `@propertyWrapper struct Clamped`) is
# handled by the `(?:@\w+...)*` arm so single-line annotation+declaration lines
# are correctly detected as boundaries.
SWIFT_BOUNDARY = re.compile(
    r"^(?:@\w+(?:\([^)]*\))?\s+)*"
    r"(?:(?:public|private|fileprivate|internal|open|final|static|class|override|"
    r"mutating|nonmutating|nonisolated|indirect|async|distributed)\s+)*"
    r"(?:class|struct|enum|protocol|actor|extension|func|typealias)\s+",
    re.MULTILINE,
)

# Matches a line that consists only of Swift attribute annotations with no trailing
# declaration (e.g. `@objc`, `@MainActor`, `@available(iOS 14, *)`).
# Used to prevent greedy lookback from swallowing `@Published var x = 0` lines.
_SWIFT_PURE_ATTR = re.compile(r"^(?:@\w+(?:\([^)]*\))?\s*)+$")

# Markdown heading boundaries
HEADING_MD = re.compile(r"^(#{1,6})\s+(.+)", re.MULTILINE)
FENCED_CODE_MD = re.compile(r"^\s*```", re.MULTILINE)
MERMAID_CODE_MD = re.compile(r"^\s*```\s*mermaid\b", re.MULTILINE | re.IGNORECASE)
TABLE_ROW_MD = re.compile(r"^\s*\|.+\|\s*$", re.MULTILINE)

# HCL / Terraform top-level block boundaries
HCL_BOUNDARY = re.compile(
    r"^(?:resource|data|module|variable|output|locals|provider|terraform|moved|import|check|removed)"
    r"(?=\s+[^=\s])",
    re.MULTILINE,
)

# PHP structural boundaries — classes, interfaces, traits, enums, namespaces, functions.
# Handles: abstract/final/readonly class modifiers (PHP 8.2 readonly class),
# PHP 8.1 enums with optional backing type, and access/static modifiers on methods.
PHP_BOUNDARY = re.compile(
    r"^(?:"
    r"(?:(?:abstract|final|readonly)\s+)*(?:class|interface|trait|enum)\s+\w+"
    r"|namespace\s+[\w\\]+"
    r"|(?:(?:public|private|protected|static|abstract|final)\s+)*function\s+\w+"
    r")",
    re.MULTILINE,
)

# Scala structural boundaries (.scala and .sc files).
# Handles: class, case class, object, case object, trait, enum (Scala 3), def, type alias.
# Modifier chain tolerates: private[pkg], protected[pkg], sealed, abstract, final, override,
# implicit, lazy, inline (Scala 3), opaque (Scala 3), open (Scala 3).
# Annotations (@tailrec, @main, etc.) before the modifier chain are also covered.
# val/var/given are intentionally excluded (too noisy as top-level boundaries).
SCALA_BOUNDARY = re.compile(
    r"^(?:@\w+(?:\([^)]*\))?\s+)*"
    r"(?:(?:private|protected|final|sealed|abstract|override|implicit|lazy|inline|opaque|open|case)"
    r"(?:\[[\w.]+\])?\s+)*"
    r"(?:case\s+class|case\s+object|class|object|trait|enum|def|type)\s+\w+",
    re.MULTILINE,
)

# Dart structural boundaries (.dart files).
# Pattern ordering (per plan §Pattern ordering):
#   1. extension type  (Dart 3.3+) — before plain extension
#   2. mixin class     — before class and mixin
#   3. mixin           — before class
#   4. enum / typedef  — disjoint keywords, order flexible
#   5. class           — with optional modifier chain (abstract/base/final/interface/sealed)
#   6. factory constructor — unique `factory` anchor, before generic function arm
#   7. typed top-level function — loosest pattern, last
DART_BOUNDARY = re.compile(
    r"^(?:@\w+(?:\([^)]*\))?\s+)*"
    r"(?:"
    # extension type (Dart 3.3+) — MUST precede plain extension
    r"(?:(?:abstract|base|final|interface|sealed|mixin)\s+)*extension\s+type\s+\w+"
    r"|(?:(?:abstract|base|final|interface|sealed|mixin)\s+)*extension\s+\w+"
    # mixin class — before class and plain mixin
    r"|(?:(?:abstract|base|final|interface|sealed)\s+)*mixin\s+class\s+\w+"
    # plain mixin
    r"|(?:base\s+)?mixin\s+\w+"
    # enum
    r"|enum\s+\w+"
    # typedef
    r"|typedef\s+\w+"
    # class with optional modifier prefix chain
    r"|(?:(?:abstract|base|final|interface|sealed)\s+)*class\s+\w+"
    # factory constructor (const factory or plain factory); generic params before named suffix
    r"|(?:const\s+)?factory\s+\w+(?:<[^>]*>)?(?:\.\w+)?\s*\("
    # typed top-level function: optional modifiers, return type, name, (
    # Return type uses explicit lowercase primitives (int/double/bool/num/dynamic/never) rather
    # than a greedy [a-z]\w* to avoid matching Dart keywords like const/var/final/return.
    r"|(?:(?:external|static|abstract)\s+)*"
    r"(?:void|int|double|num|bool|dynamic|never"
    r"|Future(?:<[^>]*>)?|Stream(?:<[^>]*>)?|[A-Z]\w*(?:<[^>]*>)?)"
    r"\??\s+\w+\s*(?:<[^>]*>)?\s*\("
    r")",
    re.MULTILINE,
)


# Lua structural boundaries.
# Intentionally excludes `local x = function(...)` (anonymous assignment) and
# inline callbacks (function appears mid-line after an argument) to avoid false positives.
# Module table detection requires an uppercase first letter (Lua convention: M, MyMod, Renderer)
# to avoid false boundaries on common local variable patterns like `local result = {}`.
LUA_BOUNDARY = re.compile(
    r"^(?:"
    r"local\s+function\s+\w+\s*\("
    r"|function\s+\w[\w.]*(?::\w+)?\s*\("
    r"|(?:local\s+)?[A-Z]\w*\s*=\s*\{\}"
    r")",
    re.MULTILINE,
)


def get_boundary_pattern(language: str):
    """Return the appropriate structural boundary regex for a language string or file extension."""
    mapping = {
        "python": PY_BOUNDARY,
        ".py": PY_BOUNDARY,
        "typescript": TS_BOUNDARY,
        ".ts": TS_BOUNDARY,
        "tsx": TS_BOUNDARY,
        ".tsx": TS_BOUNDARY,
        "javascript": TS_BOUNDARY,
        ".js": TS_BOUNDARY,
        ".mjs": TS_BOUNDARY,
        ".cjs": TS_BOUNDARY,
        ".mts": TS_BOUNDARY,
        ".cts": TS_BOUNDARY,
        "jsx": TS_BOUNDARY,
        ".jsx": TS_BOUNDARY,
        "go": GO_BOUNDARY,
        ".go": GO_BOUNDARY,
        "rust": RUST_BOUNDARY,
        ".rs": RUST_BOUNDARY,
        "java": JAVA_BOUNDARY,
        ".java": JAVA_BOUNDARY,
        "kotlin": KOTLIN_BOUNDARY,
        ".kt": KOTLIN_BOUNDARY,
        ".kts": KOTLIN_BOUNDARY,
        "csharp": CSHARP_BOUNDARY,
        ".cs": CSHARP_BOUNDARY,
        "fsharp": FSHARP_BOUNDARY,
        ".fs": FSHARP_BOUNDARY,
        ".fsi": FSHARP_BOUNDARY,
        "vbnet": VBNET_BOUNDARY,
        ".vb": VBNET_BOUNDARY,
        "swift": SWIFT_BOUNDARY,
        ".swift": SWIFT_BOUNDARY,
        "terraform": HCL_BOUNDARY,
        ".tf": HCL_BOUNDARY,
        ".tfvars": HCL_BOUNDARY,
        "hcl": HCL_BOUNDARY,
        ".hcl": HCL_BOUNDARY,
        "php": PHP_BOUNDARY,
        ".php": PHP_BOUNDARY,
        "scala": SCALA_BOUNDARY,
        ".scala": SCALA_BOUNDARY,
        ".sc": SCALA_BOUNDARY,
        "dart": DART_BOUNDARY,
        ".dart": DART_BOUNDARY,
        "lua": LUA_BOUNDARY,
        ".lua": LUA_BOUNDARY,
    }
    return mapping.get(language)


# =============================================================================
# CHUNKING — verbatim line spans
# =============================================================================
#
# Every chunker describes a file as an ordered partition of its lines into
# segments (a preamble, one segment per declaration, section, document, or
# blank-line block). ``_assemble`` merges and splits those segments and emits
# chunks whose ``content`` is an exact slice of the source text together with
# its 1-based ``line_start``/``line_end``. Only whitespace-only lines at the
# edges of a chunk are left out, so every non-blank source line lands in
# exactly one chunk and nothing is rewritten, re-indented, or dropped.


class _Lines:
    """The lines of one text plus prefix sums for O(1) span sizes."""

    __slots__ = ("lines", "_prefix")

    def __init__(self, content: str) -> None:
        self.lines = content.split("\n")
        prefix = [0]
        for line in self.lines:
            prefix.append(prefix[-1] + len(line) + 1)
        self._prefix = prefix

    def __len__(self) -> int:
        return len(self.lines)

    def size(self, start: int, end: int) -> int:
        """Characters in lines[start:end] joined with newlines."""
        if end <= start:
            return 0
        return self._prefix[end] - self._prefix[start] - 1

    def is_blank(self, index: int) -> bool:
        return not self.lines[index].strip()

    def text(self, start: int, end: int) -> str:
        return "\n".join(self.lines[start:end])

    def trim(self, start: int, end: int) -> tuple[int, int]:
        """Drop whitespace-only lines from both edges of [start, end)."""
        while start < end and self.is_blank(start):
            start += 1
        while end > start and self.is_blank(end - 1):
            end -= 1
        return start, end


@dataclass
class _Segment:
    """One contiguous line range [start, end) that a chunker identified."""

    start: int
    end: int
    is_def: bool = False
    meta: dict = field(default_factory=dict)


def _segments_from_marks(n_lines: int, marks: list) -> list[_Segment]:
    """Partition lines [0, n_lines) at ``marks`` = [(line, is_def, meta), ...].

    Lines before the first mark form a non-definition preamble segment. Marks on
    the same line collapse to the first one, so the partition never overlaps.
    """
    ordered: list = []
    seen: set[int] = set()
    for line, is_def, meta in sorted(marks, key=lambda mark: mark[0]):
        if 0 <= line < n_lines and line not in seen:
            seen.add(line)
            ordered.append((line, is_def, meta))
    segments: list[_Segment] = []
    first = ordered[0][0] if ordered else n_lines
    if first > 0:
        segments.append(_Segment(0, first))
    for k, (line, is_def, meta) in enumerate(ordered):
        end = ordered[k + 1][0] if k + 1 < len(ordered) else n_lines
        segments.append(_Segment(line, end, is_def, dict(meta)))
    return segments


def _blank_line_block_starts(lines: _Lines, start: int, end: int) -> list[int]:
    """Return the first line of every blank-line separated block in [start, end)."""
    starts = [start] if start < end else []
    for i in range(start + 1, end):
        if not lines.is_blank(i) and lines.is_blank(i - 1):
            starts.append(i)
    return starts


def _blank_line_segments(lines: _Lines, start: int = 0, end: int | None = None) -> list[_Segment]:
    stop = len(lines) if end is None else end
    starts = _blank_line_block_starts(lines, start, stop)
    return [
        _Segment(s, starts[k + 1] if k + 1 < len(starts) else stop) for k, s in enumerate(starts)
    ]


def _split_long_line(index: int, line: str) -> list:
    """Cut one line longer than HARD_MAX into verbatim pieces of at most TARGET_MAX chars."""
    return [
        ("chars", index, offset, min(offset + TARGET_MAX, len(line)))
        for offset in range(0, len(line), TARGET_MAX)
    ]


def _split_block_by_lines(lines: _Lines, start: int, end: int) -> list:
    pieces: list = []
    current: list[int] | None = None
    for i in range(start, end):
        if len(lines.lines[i]) > HARD_MAX:
            if current is not None:
                pieces.append(("span", current[0], current[1]))
                current = None
            pieces.extend(_split_long_line(i, lines.lines[i]))
        elif current is None:
            current = [i, i + 1]
        elif lines.size(current[0], i + 1) <= TARGET_MAX:
            current[1] = i + 1
        else:
            pieces.append(("span", current[0], current[1]))
            current = [i, i + 1]
    if current is not None:
        pieces.append(("span", current[0], current[1]))
    return pieces


def _split_span(lines: _Lines, start: int, end: int) -> list:
    """Split an oversized span at blank lines, then lines, then characters.

    Returns ``("span", start, end)`` line ranges and ``("chars", line, a, b)``
    pieces of a single overlong line; each piece is at most HARD_MAX characters.
    """
    pieces: list = []
    current: list[int] | None = None
    for segment in _blank_line_segments(lines, start, end):
        if lines.size(segment.start, segment.end) > HARD_MAX:
            if current is not None:
                pieces.append(("span", current[0], current[1]))
                current = None
            pieces.extend(_split_block_by_lines(lines, segment.start, segment.end))
        elif current is None:
            current = [segment.start, segment.end]
        elif lines.size(current[0], segment.end) <= TARGET_MAX:
            current[1] = segment.end
        else:
            pieces.append(("span", current[0], current[1]))
            current = [segment.start, segment.end]
    if current is not None:
        pieces.append(("span", current[0], current[1]))
    return pieces


def _merge_segment_meta(left: dict, right: dict) -> dict:
    """Metadata for two merged segments: the named symbol wins (at most one has one)."""
    merged = dict(left)
    if "markdown_metadata" in left or "markdown_metadata" in right:
        merged["markdown_metadata"] = _merge_markdown_metadata(
            left.get("markdown_metadata") or {}, right.get("markdown_metadata") or {}
        )
    if not left.get("symbol_name") and right.get("symbol_name"):
        merged["symbol_name"] = right["symbol_name"]
        merged["symbol_type"] = right.get("symbol_type", "")
    for key, value in right.items():
        merged.setdefault(key, value)
    return merged


def _can_merge(lines: _Lines, buffer: _Segment, segment: _Segment, group_defs: bool) -> bool:
    combined = lines.size(buffer.start, segment.end)
    if buffer.meta.get("symbol_name") and segment.meta.get("symbol_name"):
        # Every named symbol keeps its own drawer, so a symbol_name filter finds it.
        return False
    if buffer.is_def and segment.is_def:
        # Each declaration keeps its own drawer and symbol; only declarations that are
        # tiny together (e.g. one-line constants or getters) share one.
        return group_defs and combined <= TARGET_MIN
    if combined <= TARGET_MAX:
        return True
    smaller = min(lines.size(buffer.start, buffer.end), lines.size(segment.start, segment.end))
    return smaller < MIN_CHUNK and combined <= HARD_MAX


def _assemble(lines: _Lines, segments: list[_Segment], *, group_defs: bool = True) -> list:
    """Merge small segments, split oversized ones, and emit verbatim chunks."""
    chunks: list[dict] = []

    def emit_span(start: int, end: int, meta: dict, continuation: bool) -> None:
        start, end = lines.trim(start, end)
        if start >= end:
            return
        chunk = {
            "content": lines.text(start, end),
            "line_start": start + 1,
            "line_end": end,
            **meta,
        }
        if continuation:
            chunk["continuation"] = True
        chunks.append(chunk)

    def emit_piece(piece: tuple, meta: dict, continuation: bool) -> None:
        if piece[0] == "span":
            emit_span(piece[1], piece[2], meta, continuation)
            return
        # Every piece of an overlong line is kept, even an all-whitespace one, so the
        # pieces of line N rejoin (in chunk_index order) to exactly that line.
        _kind, index, lo, hi = piece
        text = lines.lines[index][lo:hi]
        chunk = {"content": text, "line_start": index + 1, "line_end": index + 1, **meta}
        if continuation:
            chunk["continuation"] = True
        chunks.append(chunk)

    buffer: _Segment | None = None
    for segment in segments:
        if segment.end <= segment.start:
            continue
        if lines.size(segment.start, segment.end) > HARD_MAX:
            start = segment.start
            if buffer is not None:
                if (
                    not buffer.is_def
                    and not buffer.meta.get("symbol_name")
                    and lines.size(buffer.start, buffer.end) < MIN_CHUNK
                ):
                    start = buffer.start  # fold a tiny preamble into the first piece
                else:
                    emit_span(buffer.start, buffer.end, buffer.meta, False)
                buffer = None
            for k, piece in enumerate(_split_span(lines, start, segment.end)):
                emit_piece(piece, segment.meta, k > 0)
            continue
        if buffer is None:
            buffer = _Segment(segment.start, segment.end, segment.is_def, dict(segment.meta))
        elif _can_merge(lines, buffer, segment, group_defs):
            buffer = _Segment(
                buffer.start,
                segment.end,
                buffer.is_def or segment.is_def,
                _merge_segment_meta(buffer.meta, segment.meta),
            )
        else:
            emit_span(buffer.start, buffer.end, buffer.meta, False)
            buffer = _Segment(segment.start, segment.end, segment.is_def, dict(segment.meta))
    if buffer is not None:
        emit_span(buffer.start, buffer.end, buffer.meta, False)

    for i, chunk in enumerate(chunks):
        chunk["chunk_index"] = i
    return chunks


def _with_symbol_defaults(chunks: list, symbol_type: str = "") -> list:
    """Ensure explicit-symbol chunkers emit symbol keys on every chunk."""
    for chunk in chunks:
        chunk.setdefault("symbol_name", "")
        if not chunk.get("symbol_type"):
            chunk["symbol_type"] = symbol_type
    return chunks


def _tag_strategy(chunks: list, strategy: str) -> list:
    for chunk in chunks:
        chunk["chunker_strategy"] = strategy
    return chunks


# =============================================================================
# CHUNKING — strategies
# =============================================================================


_YAML_BLOCK_SCALAR_RE = re.compile(r"(?::\s*|^\s*-\s*)[|>](?:[1-9]?[+-]?|[+-]?[1-9]?)?\s*(?:#.*)?$")


def _yaml_document_marker_lines(lines: list[str]) -> list[int]:
    """Return indices of top-level ``---`` document markers, ignoring block scalars."""
    markers: list[int] = []
    in_block_scalar = False
    block_parent_indent = 0

    for i, line in enumerate(lines):
        stripped = line.strip()
        indent = len(line) - len(line.lstrip(" "))

        if in_block_scalar:
            if not stripped or indent > block_parent_indent:
                continue
            in_block_scalar = False

        if indent == 0 and stripped == "---":
            markers.append(i)
            continue

        if _YAML_BLOCK_SCALAR_RE.search(line):
            in_block_scalar = True
            block_parent_indent = indent

    return markers


def _split_yaml_documents(content: str) -> list[str]:
    """Split YAML documents on top-level --- markers, ignoring block scalar content."""
    lines = content.splitlines()
    docs: list[list[str]] = [[]]
    markers = set(_yaml_document_marker_lines(lines))
    for i, line in enumerate(lines):
        if i in markers:
            docs.append([])
            continue
        docs[-1].append(line)
    return ["\n".join(doc) for doc in docs]


def _yaml_document_segments(lines: _Lines, symbol_for) -> list[_Segment]:
    """One segment per YAML document; each ``---`` marker opens its document."""
    marks = []
    for line in _yaml_document_marker_lines(lines.lines):
        marks.append((line, False, {}))
    segments = _segments_from_marks(len(lines), marks)
    for segment in segments:
        symbol_name, symbol_type = symbol_for(lines.text(segment.start, segment.end))
        segment.meta = {"symbol_name": symbol_name, "symbol_type": symbol_type}
        segment.is_def = bool(symbol_name or symbol_type)
    return segments


def _chunk_k8s_manifest(content: str, source_file: str) -> list:
    """Split a K8s YAML file on --- document separators, one chunk per resource."""
    lines = _Lines(content)
    segments = _yaml_document_segments(lines, _extract_k8s_symbol)
    return _with_symbol_defaults(_assemble(lines, segments, group_defs=False))


def _chunk_helm_chart(content: str, source_file: str) -> list:
    """Chunk a Helm Chart.yaml as a single metadata chunk."""
    lines = _Lines(content)
    symbol_name, symbol_type = _extract_helm_chart_symbol(content)
    segment = _Segment(
        0, len(lines), True, {"symbol_name": symbol_name, "symbol_type": symbol_type}
    )
    return _with_symbol_defaults(_assemble(lines, [segment]), "helm_chart")


_HELM_VALUES_KEY_RE = re.compile(r"^([a-zA-Z_][a-zA-Z0-9_\-]*)\s*:")


def _chunk_helm_values(content: str, source_file: str) -> list:
    """Chunk a Helm values YAML by top-level key sections."""
    try:
        parsed = yaml.safe_load(content)
        if not isinstance(parsed, dict) or not parsed:
            raise ValueError("Not a non-empty YAML mapping")
        top_keys = set(parsed.keys())
    except Exception:
        top_keys = None

    if top_keys is None:
        fallback = chunk_adaptive_lines(content, source_file)
        for chunk in fallback:
            chunk["symbol_type"] = "helm_values"
            chunk["symbol_name"] = ""
        return fallback

    lines = _Lines(content)
    marks = []
    for i, line in enumerate(lines.lines):
        if not line or line[0].isspace() or line.startswith("#"):
            continue
        m = _HELM_VALUES_KEY_RE.match(line)
        if m and m.group(1) in top_keys:
            key = m.group(1)
            marks.append((i, True, {"symbol_name": f"values.{key}", "symbol_type": "helm_values"}))
    segments = _segments_from_marks(len(lines), marks)
    for segment in segments:
        if segment.is_def and lines.size(segment.start, segment.end) < MIN_CHUNK:
            # A one-line scalar key is not worth its own drawer: it merges with its
            # neighbours (keeping the neighbouring section's symbol, if any).
            segment.is_def = False
            segment.meta = {"symbol_name": "", "symbol_type": "helm_values"}
    return _with_symbol_defaults(_assemble(lines, segments, group_defs=False), "helm_values")


def _chunk_helm_template(content: str, source_file: str) -> list:
    """Chunk a Helm template file, tolerating Go template delimiters."""
    lines = _Lines(content)
    segments = _yaml_document_segments(lines, _extract_helm_template_symbol)
    return _with_symbol_defaults(_assemble(lines, segments, group_defs=False))


def _chunk_helm(content: str, source_file: str) -> list:
    """Route a Helm chart file to the appropriate chunker based on filename."""
    name = Path(source_file).name
    if name == "Chart.yaml":
        return _chunk_helm_chart(content, source_file)
    if _HELM_VALUES_NAME_RE.match(name):
        return _chunk_helm_values(content, source_file)
    return _chunk_helm_template(content, source_file)


# =============================================================================
# ANSIBLE CHUNKING
# =============================================================================

# Mirrors the detection regex in languages.py (no circular import — redefined here)
_ANSIBLE_ROLE_CHUNKER_PATH_RE = re.compile(
    r"(?:^|[/\\])roles[/\\]([^/\\]+)[/\\](tasks|handlers|vars|defaults)[/\\]"
)
_ANSIBLE_INVENTORY_FNAME_RE = re.compile(r"^inventory\.(ini|ya?ml)$")


def _split_ansible_list_items(content: str) -> list[str]:
    """Split a YAML list document into top-level list item strings (- at column 0).

    Skips document markers (--- and ...). Handles Jinja delimiters safely since
    it operates on raw text without PyYAML parsing.
    """
    lines = content.splitlines(keepends=True)
    items: list[list[str]] = []
    current: list[str] = []

    for line in lines:
        stripped = line.rstrip("\n\r")
        if stripped.strip() in ("---", "..."):
            continue
        if stripped.startswith("- ") or stripped == "-":
            if current:
                items.append(current)
            current = [line]
        else:
            current.append(line)

    if current:
        items.append(current)

    return ["".join(item).strip() for item in items if "".join(item).strip()]


def _ansible_item_lines(lines: _Lines) -> list[int]:
    """Return the line index of every top-level list item (``-`` at column 0)."""
    return [
        i for i, line in enumerate(lines.lines) if line.startswith("- ") or line.rstrip() == "-"
    ]


def _chunk_ansible_items(content: str, symbol_for, fallback_symbol: tuple) -> list:
    lines = _Lines(content)
    item_lines = _ansible_item_lines(lines)
    if not item_lines:
        segments = [
            _Segment(
                0,
                len(lines),
                True,
                {"symbol_name": fallback_symbol[0], "symbol_type": fallback_symbol[1]},
            )
        ]
        return _with_symbol_defaults(_assemble(lines, segments), fallback_symbol[1])
    marks = []
    for k, line in enumerate(item_lines):
        end = item_lines[k + 1] if k + 1 < len(item_lines) else len(lines)
        symbol_name, symbol_type = symbol_for(lines.text(line, end))
        marks.append((line, True, {"symbol_name": symbol_name, "symbol_type": symbol_type}))
    segments = _segments_from_marks(len(lines), marks)
    return _with_symbol_defaults(_assemble(lines, segments, group_defs=False), fallback_symbol[1])


def _chunk_ansible_playbook(content: str, source_file: str) -> list:
    """Chunk an Ansible playbook: one chunk per top-level play, preserving verbatim text."""
    return _chunk_ansible_items(
        content, _extract_ansible_play_symbol, _extract_ansible_play_symbol(content)
    )


def _chunk_ansible_role_tasks(
    content: str, source_file: str, role_name: str, role_dir: str
) -> list:
    """Chunk a role tasks or handlers file: one chunk per list item, preserving verbatim text."""
    extractor = (
        _extract_ansible_handler_symbol if role_dir == "handlers" else _extract_ansible_task_symbol
    )
    sym_type = "ansible_handler" if role_dir == "handlers" else "ansible_task"

    def symbol_for(text: str) -> tuple:
        sym_name, sym_kind = extractor(text)
        return (sym_name or role_name, sym_kind)

    return _chunk_ansible_items(content, symbol_for, (role_name, sym_type))


def _chunk_whole_file(content: str, symbol_name: str, symbol_type: str) -> list:
    lines = _Lines(content)
    segment = _Segment(
        0, len(lines), True, {"symbol_name": symbol_name, "symbol_type": symbol_type}
    )
    return _with_symbol_defaults(_assemble(lines, [segment]), symbol_type)


def _chunk_ansible_role_vars(content: str, source_file: str, role_name: str) -> list:
    """Chunk a role vars or defaults file as a single unit tagged ansible_vars."""
    return _chunk_whole_file(content, role_name, "ansible_vars")


def _chunk_ansible_inventory(content: str, source_file: str) -> list:
    """Chunk an Ansible inventory file as a single file-level chunk (no host/group parsing)."""
    return _chunk_whole_file(content, "", "ansible_inventory")


def _chunk_ansible(content: str, source_file: str) -> list:
    """Route an Ansible file to the appropriate sub-chunker based on path and filename."""
    m = _ANSIBLE_ROLE_CHUNKER_PATH_RE.search(str(source_file))
    if m:
        role_name = m.group(1)
        role_dir = m.group(2)
        if role_dir in ("vars", "defaults"):
            return _chunk_ansible_role_vars(content, source_file, role_name)
        return _chunk_ansible_role_tasks(content, source_file, role_name, role_dir)

    if _ANSIBLE_INVENTORY_FNAME_RE.match(Path(source_file).name):
        return _chunk_ansible_inventory(content, source_file)

    return _chunk_ansible_playbook(content, source_file)


_CODE_LANGUAGES = frozenset(
    {
        "python",
        "typescript",
        "javascript",
        "tsx",
        "jsx",
        "go",
        "rust",
        "java",
        "kotlin",
        "csharp",
        "fsharp",
        "vbnet",
        "swift",
        "php",
        "scala",
        "dart",
        "lua",
        "terraform",
        "hcl",
    }
)


def chunk_file(content: str, ext: str, source_file: str, language: str | None = None) -> list:
    """Dispatcher — route to the right chunking strategy based on language.

    Every returned chunk carries ``content`` (an exact slice of *content*),
    ``chunk_index``, and the 1-based ``line_start``/``line_end`` of that slice
    within *content*.
    """
    # .csproj/.fsproj/.vbproj: verbatim project-XML chunker (ext-based, before language lookup
    # so the generic XML fallback is preserved for all other XML files as per design notes).
    if ext in _DOTNET_PROJECT_FILE_EXTS:
        return _chunk_dotnet_project_xml(content, source_file)

    if language is None:
        language = EXTENSION_LANG_MAP.get(ext, "unknown")

    if language in _CODE_LANGUAGES:
        return chunk_code(content, language, source_file)
    elif language in ("markdown", "text"):
        return chunk_prose(content, source_file)
    elif language == "kubernetes":
        return _chunk_k8s_manifest(content, source_file)
    elif language == "helm":
        return _chunk_helm(content, source_file)
    elif language == "ansible":
        return _chunk_ansible(content, source_file)
    else:
        return chunk_adaptive_lines(content, source_file)


@dataclass(frozen=True)
class _AstRules:
    """How one tree-sitter grammar marks definitions, containers, and symbol names.

    ``symbol(node, container)`` returns the ``(name, type)`` of a definition node, or
    None for declarations that carry no symbol of their own (constants, statements);
    *container* is the enclosing class/impl node, or None at top level.
    ``members(node)`` returns the body node whose children are a container's members.
    """

    definition_types: frozenset
    member_types: frozenset
    symbol: Callable
    members: Callable
    attach_types: frozenset = frozenset({"comment"})


def _node_text(node) -> str:
    return node.text.decode("utf-8", "replace") if node is not None and node.text else ""


def _node_name(node) -> str:
    return _node_text(node.child_by_field_name("name"))


def _python_definition(node):
    return node.child_by_field_name("definition") if node.type == "decorated_definition" else node


def _python_symbol(node, container):
    inner = _python_definition(node)
    if inner is None:
        return None
    if inner.type == "class_definition":
        return (_node_name(inner), "class")
    if inner.type == "function_definition":
        return (_node_name(inner), "method" if container is not None else "function")
    return None


def _python_members(node):
    inner = _python_definition(node)
    if inner is not None and inner.type == "class_definition":
        return inner.child_by_field_name("body")
    return None


_TS_DECLARATION_TYPES = {
    "function_declaration": "function",
    "generator_function_declaration": "function",
    "class_declaration": "class",
    "abstract_class_declaration": "class",
    "interface_declaration": "interface",
    "type_alias_declaration": "type",
    "enum_declaration": "enum",
}
_TS_FUNCTION_VALUES = frozenset(
    {"arrow_function", "function_expression", "function", "generator_function"}
)


def _ts_declaration(node):
    return node.child_by_field_name("declaration") if node.type == "export_statement" else node


def _ts_symbol(node, container):
    inner = _ts_declaration(node)
    if inner is None:
        return None
    if container is not None:
        if inner.type in ("method_definition", "abstract_method_signature"):
            return (_node_name(inner), "method")
        return None
    if inner.type in _TS_DECLARATION_TYPES:
        return (_node_name(inner), _TS_DECLARATION_TYPES[inner.type])
    if inner.type in ("lexical_declaration", "variable_declaration"):
        # `const handler = (req) => ...` defines a function; plain constants do not.
        for declarator in inner.named_children:
            value = declarator.child_by_field_name("value")
            if declarator.type == "variable_declarator" and value is not None:
                if value.type in _TS_FUNCTION_VALUES:
                    return (_node_name(declarator), "function")
    return None


def _ts_members(node):
    inner = _ts_declaration(node)
    if inner is not None and inner.type in ("class_declaration", "abstract_class_declaration"):
        return inner.child_by_field_name("body")
    return None


def _go_symbol(node, container):
    if node.type == "function_declaration":
        return (_node_name(node), "function")
    if node.type == "method_declaration":
        return (_node_name(node), "method")
    if node.type == "type_declaration":
        spec = next((child for child in node.named_children if child.type == "type_spec"), None)
        if spec is None:
            return None
        kind = spec.child_by_field_name("type")
        kinds = {"struct_type": "struct", "interface_type": "interface"}
        return (_node_name(spec), kinds.get(kind.type if kind is not None else "", "type"))
    return None


_RUST_ITEM_TYPES = {
    "struct_item": "struct",
    "enum_item": "enum",
    "trait_item": "trait",
    "type_item": "type",
}


def _rust_symbol(node, container):
    if node.type in ("function_item", "function_signature_item"):
        in_type = container is not None and container.type in ("impl_item", "trait_item")
        return (_node_name(node), "method" if in_type else "function")
    if node.type in _RUST_ITEM_TYPES:
        return (_node_name(node), _RUST_ITEM_TYPES[node.type])
    if node.type == "impl_item":
        # `impl<K> Cache<K>` and `impl Display for Cache` both name the type, `Cache`.
        implemented = _node_text(node.child_by_field_name("type")).split("<", 1)[0]
        return (implemented.rsplit("::", 1)[-1].strip(), "impl")
    if node.type == "mod_item" and node.child_by_field_name("body") is not None:
        return (_node_name(node), "mod")
    return None


def _rust_members(node):
    if node.type in ("impl_item", "trait_item", "mod_item"):
        return node.child_by_field_name("body")
    return None


def _unwrap_definition(node):
    """The definition inside a Python decorator or TS export wrapper (else *node*)."""
    if node.type == "decorated_definition":
        return _python_definition(node)
    if node.type == "export_statement":
        return _ts_declaration(node)
    return node


def _definition_marks(children, source_bytes: bytes, rules: _AstRules, container=None) -> list:
    """Segment marks for definition nodes among *children*, recursing into containers.

    Each definition starts a segment at its first immediately adjacent leading sibling
    of ``attach_types`` (comments, decorators' attributes; no blank-line gap) and carries
    its symbol. A container (class, impl, trait) keeps a header segment named after it,
    and each member definition in its body starts a segment named after the member.
    """
    types = rules.member_types if container is not None else rules.definition_types
    marks: list = []
    grouped: set[int] = set()  # children that belong to a definition's segment start
    for i, child in enumerate(children):
        if child.type not in types:
            continue
        start_i = i
        j = i - 1
        while j >= 0:
            prev = children[j]
            if prev.type not in rules.attach_types:
                break
            # No blank line between this sibling and the node after it?
            if b"\n\n" in source_bytes[prev.end_byte : children[j + 1].start_byte]:
                break
            start_i = j
            j -= 1
        grouped.update(range(start_i, i + 1))
        symbol = rules.symbol(child, container)
        meta = {"symbol_name": symbol[0], "symbol_type": symbol[1]} if symbol and symbol[0] else {}
        marks.append((children[start_i].start_point[0], True, meta))
        body = rules.members(child)
        if body is not None:
            marks.extend(
                _definition_marks(body.children, source_bytes, rules, _unwrap_definition(child))
            )

    # Code after a definition (a large constant table, an `if __name__` block, class
    # attributes after the methods) starts its own segment: it is not part of that
    # definition, so pieces of it must not be stored or named as its continuation.
    for i in range(1, len(children)):
        prev, child = children[i - 1], children[i]
        if (
            i not in grouped
            and child.is_named
            and prev.type in types
            and child.start_point[0] > prev.end_point[0]
        ):
            marks.append((child.start_point[0], False, {}))
    return marks


def _chunk_treesitter(parser, content: str, source_file: str, rules: _AstRules) -> list:
    """Shared AST chunker: one segment per definition, members of containers included.

    Every function, class, method, and type definition starts its own segment named
    after it (see :func:`_definition_marks`), so ``symbol_name`` finds each of them;
    functions nested inside a function body stay in the enclosing function's segment.
    Content before the first definition forms the preamble. Falls back to
    chunk_adaptive_lines() (tagged treesitter_adaptive) when no definition node is found.
    """
    source_bytes = content.encode("utf-8")
    tree = parser.parse(source_bytes)
    marks = _definition_marks(tree.root_node.children, source_bytes, rules)

    if not marks:
        # No top-level definitions found (e.g. plain-assignment module or barrel file).
        # Tag explicitly so the orchestrator doesn't mislabel as regex_structural — the
        # regex structural path was never executed.
        return _tag_strategy(
            chunk_adaptive_lines(content, source_file), STRATEGY_TREESITTER_ADAPTIVE
        )

    lines = _Lines(content)
    segments = _segments_from_marks(len(lines), marks)
    return _tag_strategy(_assemble(lines, segments), STRATEGY_TREESITTER)


_PYTHON_DEFINITIONS = frozenset({"function_definition", "class_definition", "decorated_definition"})
_PYTHON_RULES = _AstRules(
    definition_types=_PYTHON_DEFINITIONS,
    member_types=_PYTHON_DEFINITIONS,
    symbol=_python_symbol,
    members=_python_members,
)
_TYPESCRIPT_RULES = _AstRules(
    definition_types=frozenset(
        {
            "export_statement",
            "function_declaration",
            "generator_function_declaration",
            "class_declaration",
            "abstract_class_declaration",
            "interface_declaration",
            "type_alias_declaration",
            "enum_declaration",
            "lexical_declaration",
            "expression_statement",
        }
    ),
    member_types=frozenset({"method_definition", "abstract_method_signature"}),
    symbol=_ts_symbol,
    members=_ts_members,
)
_GO_RULES = _AstRules(
    definition_types=frozenset(
        {
            "function_declaration",
            "method_declaration",
            "type_declaration",
            "const_declaration",
            "var_declaration",
        }
    ),
    member_types=frozenset(),
    symbol=_go_symbol,
    members=lambda _node: None,
)
_RUST_DEFINITIONS = frozenset(
    {
        "function_item",
        "struct_item",
        "enum_item",
        "trait_item",
        "impl_item",
        "mod_item",
        "type_item",
        "const_item",
        "static_item",
    }
)
_RUST_RULES = _AstRules(
    definition_types=_RUST_DEFINITIONS,
    member_types=_RUST_DEFINITIONS | {"function_signature_item"},
    symbol=_rust_symbol,
    members=_rust_members,
    attach_types=frozenset({"attribute_item", "comment", "line_comment", "block_comment"}),
)


def _chunk_python_treesitter(parser, content: str, source_file: str) -> list:
    """
    AST-aware Python chunker using tree-sitter.

    Uses function_definition, class_definition, and decorated_definition nodes as
    chunk boundaries, including the methods and nested classes of a class body, and
    attaches immediately adjacent leading comments. Chunks are tagged
    chunker_strategy='treesitter_v3'; files without definitions fall back to
    chunk_adaptive_lines() tagged 'treesitter_adaptive_v2'.
    """
    return _chunk_treesitter(parser, content, source_file, _PYTHON_RULES)


def _chunk_typescript_treesitter(parser, content: str, source_file: str) -> list:
    """
    AST-aware TypeScript/JavaScript/TSX/JSX chunker using tree-sitter.

    Uses top-level export_statement, function_declaration, class_declaration,
    interface_declaration, type_alias_declaration, enum_declaration,
    lexical_declaration, and expression_statement nodes as chunk boundaries, plus
    the methods of a class body; leading imports form the preamble. Falls back to
    chunk_adaptive_lines() for barrel or import-only files.
    """
    return _chunk_treesitter(parser, content, source_file, _TYPESCRIPT_RULES)


def _chunk_go_treesitter(parser, content: str, source_file: str) -> list:
    """
    AST-aware Go chunker using tree-sitter.

    Uses function_declaration, method_declaration, type_declaration,
    const_declaration, and var_declaration nodes as chunk boundaries; the package
    clause and imports form the preamble. Falls back to chunk_adaptive_lines()
    for package-only files.
    """
    return _chunk_treesitter(parser, content, source_file, _GO_RULES)


def _chunk_rust_treesitter(parser, content: str, source_file: str) -> list:
    """
    AST-aware Rust chunker using tree-sitter.

    Uses function_item, struct_item, enum_item, trait_item, impl_item, mod_item,
    type_item, const_item, and static_item nodes as chunk boundaries, including the
    items of impl, trait, and inline mod bodies. Immediately adjacent leading
    attribute_item (#[...]) and comment siblings stay attached — tree-sitter-rust keeps
    #[derive(...)] as a separate sibling. Falls back to chunk_adaptive_lines() when no
    item nodes are found.
    """
    return _chunk_treesitter(parser, content, source_file, _RUST_RULES)


def chunk_code(content: str, language: str, source_file: str) -> list:
    """
    Split code at structural boundaries (function/class/export declarations).
    Groups imports. Attaches leading comments immediately adjacent to declarations.
    Falls back to chunk_adaptive_lines() if no boundaries are detected.

    `language` accepts canonical language strings ("python", "typescript") or
    raw file extensions (".py", ".ts") for backward compatibility.

    When tree-sitter is installed and the language is Python, TypeScript, JavaScript,
    TSX, JSX, Go, or Rust, AST-based chunking is used. All other languages still
    use the regex path below.
    """
    canonical = EXTENSION_LANG_MAP.get(language, language)
    parser = get_parser(canonical)
    if parser is not None:
        if canonical == "python":
            return _chunk_python_treesitter(parser, content, source_file)
        if canonical in ("typescript", "javascript", "tsx", "jsx"):
            return _chunk_typescript_treesitter(parser, content, source_file)
        if canonical == "go":
            return _chunk_go_treesitter(parser, content, source_file)
        if canonical == "rust":
            return _chunk_rust_treesitter(parser, content, source_file)

    boundary = get_boundary_pattern(language)
    if not boundary:
        return chunk_adaptive_lines(content, source_file)

    is_ts_js = language in (
        "typescript",
        "javascript",
        "tsx",
        "jsx",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".mjs",
        ".cjs",
        ".mts",
        ".cts",
    )

    lines = content.split("\n")
    marks = []
    in_import_block = False

    # C# attributes ([HttpGet], [Serializable], etc.) appear immediately before declarations
    # and must be kept in the same chunk. Extend the lookback prefix set for csharp so that
    # lines starting with '[' are treated like comment lines during the lookback scan.
    comment_prefixes = ("//", "/*", "*", "*/", "#", '"""', "'''", "/**")
    if canonical in ("csharp", "fsharp"):
        # C# uses [Attribute], F# uses [<Attribute>] — both start with '['.
        comment_prefixes = comment_prefixes + ("[",)
    if canonical == "swift":
        # Swift uses @Attribute decorators (e.g. @propertyWrapper, @MainActor) before
        # declarations. Extend the lookback so these lines attach to their declaration chunk.
        comment_prefixes = comment_prefixes + ("@",)
    if canonical == "php":
        # PHP 8.1+ uses #[Attribute] syntax immediately before declarations.
        # Extend the lookback so attribute lines attach to their declaration chunk.
        comment_prefixes = comment_prefixes + ("#[",)
    if canonical == "scala":
        # Scala uses @Annotation decorators (e.g. @tailrec, @main, @deprecated) before
        # declarations. Extend the lookback so these lines attach to their declaration chunk.
        comment_prefixes = comment_prefixes + ("@",)
    if canonical == "dart":
        # Dart uses @override, @deprecated, @immutable, @pragma annotations before
        # declarations. Extend the lookback so these lines attach to their declaration chunk.
        comment_prefixes = comment_prefixes + ("@",)
    if canonical == "lua":
        # Lua uses -- for line comments and --[[ for long comments. Add -- so leading
        # comment lines stay attached to the declaration they precede.
        comment_prefixes = comment_prefixes + ("--",)
    if canonical == "python":
        # Decorator lines stay with the def or class they decorate.
        comment_prefixes = comment_prefixes + ("@",)

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            if in_import_block:
                in_import_block = False
            continue

        if TS_IMPORT.match(stripped) and is_ts_js:
            if not in_import_block:
                marks.append((i, False, {}))
                in_import_block = True
            continue
        in_import_block = False

        # For TS/JS, match against the original line so indented `const`/`let` inside
        # function bodies (e.g., `    const x = ...`) don't trigger false boundaries.
        # For Python/Go/Rust, match against the stripped line because methods are indented.
        match_target = line if is_ts_js else stripped
        if boundary.match(match_target):
            # Look back for leading comments immediately adjacent (no blank-line gap).
            comment_start = i
            j = i - 1
            while j >= 0:
                prev = lines[j].strip()
                if prev.startswith(comment_prefixes):
                    # Swift/Scala: reject mixed @Attribute+declaration lines
                    # (e.g. `@Published var count = 0`) — they belong to
                    # the enclosing type body, not to the following func.
                    # Only pure attribute-only lines (e.g. `@MainActor`,
                    # `@objc`, `@available(iOS 14, *)`) should attach.
                    if (
                        canonical in ("swift", "scala", "dart")
                        and prev.startswith("@")
                        and not _SWIFT_PURE_ATTR.match(prev)
                    ):
                        break
                    comment_start = j
                    j -= 1
                else:
                    break  # stop at blank lines or non-comment lines
            marks.append((comment_start, True, {}))

    if not marks:
        return chunk_adaptive_lines(content, source_file)

    text_lines = _Lines(content)
    segments = _segments_from_marks(len(text_lines), marks)
    for segment in segments:
        # Name each declaration from its own text, so two declarations never share a
        # drawer and each one is found by its symbol_name.
        if segment.is_def:
            symbol_name, symbol_type = extract_symbol(
                text_lines.text(segment.start, segment.end), canonical
            )
            if symbol_name:
                segment.meta = {"symbol_name": symbol_name, "symbol_type": symbol_type}
    return _assemble(text_lines, segments)


def chunk_prose(content: str, source_file: str) -> list:
    """
    Split prose at markdown heading boundaries (#–######).
    Falls back to paragraph chunking if no headings are found.
    """
    lines = _Lines(content)
    heading_lines = [i for i, line in enumerate(lines.lines) if HEADING_MD.match(line.strip())]

    if not heading_lines:
        return _assemble(lines, _blank_line_segments(lines))

    marks = []
    heading_stack: dict = {}
    for idx, start in enumerate(heading_lines):
        end = heading_lines[idx + 1] if idx + 1 < len(heading_lines) else len(lines)
        match = HEADING_MD.match(lines.lines[start].strip())
        level = len(match.group(1)) if match else 0
        heading = _clean_markdown_heading(match.group(2)) if match else ""
        heading_stack = {k: v for k, v in heading_stack.items() if k < level}
        if level:
            heading_stack[level] = heading
        heading_path = [heading_stack[k] for k in sorted(heading_stack)]
        section = lines.text(start, end)
        marks.append(
            (
                start,
                False,
                {
                    "markdown_metadata": _markdown_section_metadata(
                        section, heading, level, heading_path
                    )
                },
            )
        )

    segments = _segments_from_marks(len(lines), marks)
    if segments and segments[0].start == 0 and not segments[0].meta:
        preamble = lines.text(segments[0].start, segments[0].end)
        segments[0].meta = {"markdown_metadata": _markdown_section_metadata(preamble, "", 0, [])}
    return _assemble(lines, segments)


def _clean_markdown_heading(heading: str) -> str:
    """Normalize markdown heading text for metadata filters."""
    return heading.strip().strip("#").strip()


def _markdown_section_metadata(
    section: str, heading: str, heading_level: int, heading_path: list
) -> dict:
    """Build compact metadata for a Markdown section."""
    return {
        "heading": heading,
        "heading_level": heading_level,
        "heading_path": " > ".join(heading_path),
        "doc_section_type": _classify_markdown_section(heading),
        "contains_mermaid": int(bool(MERMAID_CODE_MD.search(section))),
        "contains_code": int(bool(FENCED_CODE_MD.search(section))),
        "contains_table": int(bool(TABLE_ROW_MD.search(section))),
    }


def _classify_markdown_section(heading: str) -> str:
    """Classify common technical-document sections from their heading."""
    normalized = heading.lower()
    if not normalized:
        return "preamble"
    if "adr" in normalized or "decision" in normalized or "решени" in normalized:
        return "decision"
    if "architecture" in normalized or "архитект" in normalized:
        return "architecture"
    if "problem" in normalized or "context" in normalized or "зачем" in normalized:
        return "context"
    if "solution" in normalized or "implementation" in normalized or "реализац" in normalized:
        return "implementation"
    if "test" in normalized or "провер" in normalized:
        return "validation"
    if "risk" in normalized or "rollback" in normalized or "риск" in normalized:
        return "risk"
    if "api" in normalized or "reference" in normalized:
        return "reference"
    if "install" in normalized or "usage" in normalized or "quickstart" in normalized:
        return "usage"
    if "benchmark" in normalized or "metric" in normalized:
        return "benchmark"
    if "follow" in normalized or "next" in normalized:
        return "follow_up"
    return "section"


def _merge_markdown_metadata(left: dict, right: dict) -> dict:
    """Merge metadata when adjacent short Markdown sections share one drawer."""
    left = left or {}
    right = right or {}
    if not left:
        return dict(right)
    if not right:
        return dict(left)
    headings = [h for h in (left.get("heading", ""), right.get("heading", "")) if h]
    paths = [p for p in (left.get("heading_path", ""), right.get("heading_path", "")) if p]
    section_types = {
        value
        for value in (left.get("doc_section_type", ""), right.get("doc_section_type", ""))
        if value
    }
    levels = [
        level for level in (left.get("heading_level", 0), right.get("heading_level", 0)) if level
    ]
    return {
        "heading": " | ".join(dict.fromkeys(headings)),
        "heading_level": min(levels) if levels else 0,
        "heading_path": " | ".join(dict.fromkeys(paths)),
        "doc_section_type": next(iter(section_types)) if len(section_types) == 1 else "mixed",
        "contains_mermaid": int(
            bool(left.get("contains_mermaid", 0) or right.get("contains_mermaid", 0))
        ),
        "contains_code": int(bool(left.get("contains_code", 0) or right.get("contains_code", 0))),
        "contains_table": int(
            bool(left.get("contains_table", 0) or right.get("contains_table", 0))
        ),
    }


def adaptive_merge_split_sections(raw_chunks: list, source_file: str) -> list:
    """
    Markdown-aware variant of adaptive_merge_split() for callers holding section texts.

    Sections are treated as consecutive blocks separated by one blank line; small
    sections merge (metadata merged), oversized ones split. No section is dropped.
    """
    if not raw_chunks:
        return []
    texts = [item["content"] for item in raw_chunks]
    lines = _Lines("\n\n".join(texts))
    segments = []
    line = 0
    for item, text in zip(raw_chunks, texts):
        end = min(line + text.count("\n") + 2, len(lines))
        meta = {"markdown_metadata": item.get("markdown_metadata", {})}
        segments.append(_Segment(line, end, False, meta))
        line = end
    return [
        {
            "content": chunk["content"],
            "chunk_index": chunk["chunk_index"],
            "markdown_metadata": chunk.get("markdown_metadata", {}),
        }
        for chunk in _assemble(lines, segments)
    ]


def chunk_adaptive_lines(content: str, source_file: str) -> list:
    """
    Fallback for files without dedicated structural patterns.
    Split at blank lines with adaptive sizing; small blocks merge with their
    neighbours instead of being dropped.
    """
    lines = _Lines(content)
    return _assemble(lines, _blank_line_segments(lines))


def _chunk_dotnet_project_xml(content: str, source_file: str) -> list:
    """
    Verbatim chunker for .csproj / .fsproj / .vbproj files.

    Emits the entire file as a single chunk (split only above HARD_MAX) so that
    PackageReference, ProjectReference, and TargetFramework blocks are co-embedded
    rather than split into fragments by blank-line splitting in the generic fallback.
    Tags with chunker_strategy='dotnet_project_xml_v2'.
    """
    lines = _Lines(content)
    return _tag_strategy(_assemble(lines, [_Segment(0, len(lines))]), STRATEGY_DOTNET_PROJECT_XML)


def adaptive_merge_split(raw_chunks: list, source_file: str) -> list:
    """
    Merge and split text pieces for callers that already hold separate blocks.

    Pieces are treated as consecutive blocks separated by one blank line: small
    adjacent pieces merge (up to TARGET_MAX), oversized ones split at paragraph,
    line, and finally character boundaries so no chunk exceeds HARD_MAX. No piece
    is dropped. Returns list of {"content": str, "chunk_index": int}.
    """
    if not raw_chunks:
        return []
    lines = _Lines("\n\n".join(raw_chunks))
    segments = []
    line = 0
    for text in raw_chunks:
        end = min(line + text.count("\n") + 2, len(lines))
        segments.append(_Segment(line, end))
        line = end
    return [
        {"content": chunk["content"], "chunk_index": chunk["chunk_index"]}
        for chunk in _assemble(lines, segments)
    ]


def _split_oversized(text: str) -> list:
    """Split a chunk exceeding HARD_MAX at the best available sub-boundary."""
    lines = _Lines(text)
    pieces = []
    for piece in _split_span(lines, 0, len(lines)):
        if piece[0] == "span":
            start, end = lines.trim(piece[1], piece[2])
            if start < end:
                pieces.append(lines.text(start, end))
        else:
            _kind, index, lo, hi = piece
            if lines.lines[index][lo:hi].strip():
                pieces.append(lines.lines[index][lo:hi])
    return pieces
