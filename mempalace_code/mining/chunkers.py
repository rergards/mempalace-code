"""mining.chunkers — Boundary regexes and chunking strategies for all supported languages."""

import re
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
)

EXTENSION_LANG_MAP = extension_language_map()

_HELM_VALUES_NAME_RE = re.compile(r"^values.*\.ya?ml$")

MIN_CHUNK = 100  # chars — skip tiny fragments
TARGET_MIN = 400  # chars — merge threshold for small chunks
TARGET_MAX = 2500  # chars — ideal max for a logical unit
HARD_MAX = 4000  # chars — absolute max before forced split

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
# CHUNKING — strategies
# =============================================================================


_YAML_BLOCK_SCALAR_RE = re.compile(r"(?::\s*|^\s*-\s*)[|>](?:[1-9]?[+-]?|[+-]?[1-9]?)?\s*(?:#.*)?$")


def _split_yaml_documents(content: str) -> list[str]:
    """Split YAML documents on top-level --- markers, ignoring block scalar content."""
    docs: list[list[str]] = [[]]
    in_block_scalar = False
    block_parent_indent = 0

    for line in content.splitlines():
        stripped = line.strip()
        indent = len(line) - len(line.lstrip(" "))

        if in_block_scalar:
            if not stripped or indent > block_parent_indent:
                docs[-1].append(line)
                continue
            in_block_scalar = False

        if indent == 0 and stripped == "---":
            docs.append([])
            continue

        docs[-1].append(line)
        if _YAML_BLOCK_SCALAR_RE.search(line):
            in_block_scalar = True
            block_parent_indent = indent

    return ["\n".join(doc) for doc in docs]


def _chunk_k8s_manifest(content: str, source_file: str) -> list:
    """Split a K8s YAML file on --- document separators, one chunk per resource."""
    raw_docs = _split_yaml_documents(content)
    all_chunks = []
    for doc in raw_docs:
        doc = doc.strip()
        if len(doc) < MIN_CHUNK:
            continue
        symbol_name, symbol_type = _extract_k8s_symbol(doc)
        for chunk in adaptive_merge_split([doc], source_file):
            chunk["symbol_name"] = symbol_name
            chunk["symbol_type"] = symbol_type
            all_chunks.append(chunk)
    # Re-index chunk_index across all documents
    return [
        {
            "content": c["content"],
            "chunk_index": i,
            "symbol_name": c["symbol_name"],
            "symbol_type": c["symbol_type"],
        }
        for i, c in enumerate(all_chunks)
    ]


def _chunk_helm_chart(content: str, source_file: str) -> list:
    """Chunk a Helm Chart.yaml as a single metadata chunk."""
    stripped = content.strip()
    if len(stripped) < MIN_CHUNK:
        return []
    symbol_name, symbol_type = _extract_helm_chart_symbol(stripped)
    sub_chunks = adaptive_merge_split([stripped], source_file)
    for chunk in sub_chunks:
        chunk["symbol_name"] = symbol_name
        chunk["symbol_type"] = symbol_type
    return [
        {
            "content": c["content"],
            "chunk_index": i,
            "symbol_name": c["symbol_name"],
            "symbol_type": c["symbol_type"],
        }
        for i, c in enumerate(sub_chunks)
    ]


def _chunk_helm_values(content: str, source_file: str) -> list:
    """Chunk a Helm values YAML by top-level key sections."""
    try:
        parsed = yaml.safe_load(content)
        if not isinstance(parsed, dict) or not parsed:
            raise ValueError("Not a non-empty YAML mapping")
        top_keys = list(parsed.keys())
    except Exception:
        top_keys = None

    if top_keys is None:
        fallback = chunk_adaptive_lines(content, source_file)
        for chunk in fallback:
            chunk["symbol_type"] = "helm_values"
            chunk["symbol_name"] = ""
        return fallback

    # Find line positions of each top-level key (at column 0)
    lines = content.splitlines(keepends=True)
    boundaries: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        if not line or line[0].isspace() or line.startswith("#"):
            continue
        m = re.match(r"^([a-zA-Z_][a-zA-Z0-9_\-]*)\s*:", line)
        if m and m.group(1) in top_keys:
            boundaries.append((i, m.group(1)))

    if not boundaries:
        stripped = content.strip()
        if len(stripped) >= MIN_CHUNK:
            return [{"content": stripped, "chunk_index": 0, "symbol_type": "helm_values", "symbol_name": ""}]
        return []

    all_chunks: list[dict] = []
    for idx, (start_line, key) in enumerate(boundaries):
        end_line = boundaries[idx + 1][0] if idx + 1 < len(boundaries) else len(lines)
        section = "".join(lines[start_line:end_line]).strip()
        if len(section) < MIN_CHUNK:
            continue
        sub_chunks = adaptive_merge_split([section], source_file)
        for chunk in sub_chunks:
            chunk["symbol_name"] = f"values.{key}"
            chunk["symbol_type"] = "helm_values"
        all_chunks.extend(sub_chunks)

    if not all_chunks:
        # All sections were below MIN_CHUNK (e.g. flat scalar-only values files).
        # Fall back to a single full-file chunk so the file is not silently skipped.
        stripped = content.strip()
        if len(stripped) >= MIN_CHUNK:
            return [{"content": stripped, "chunk_index": 0, "symbol_type": "helm_values", "symbol_name": ""}]
        return []

    return [
        {
            "content": c["content"],
            "chunk_index": i,
            "symbol_name": c["symbol_name"],
            "symbol_type": c["symbol_type"],
        }
        for i, c in enumerate(all_chunks)
    ]


def _chunk_helm_template(content: str, source_file: str) -> list:
    """Chunk a Helm template file, tolerating Go template delimiters."""
    raw_docs = _split_yaml_documents(content)
    all_chunks: list[dict] = []
    for doc in raw_docs:
        doc = doc.strip()
        if len(doc) < MIN_CHUNK:
            continue
        symbol_name, symbol_type = _extract_helm_template_symbol(doc)
        sub_chunks = adaptive_merge_split([doc], source_file)
        for chunk in sub_chunks:
            chunk["symbol_name"] = symbol_name
            chunk["symbol_type"] = symbol_type
        all_chunks.extend(sub_chunks)
    return [
        {
            "content": c["content"],
            "chunk_index": i,
            "symbol_name": c["symbol_name"],
            "symbol_type": c["symbol_type"],
        }
        for i, c in enumerate(all_chunks)
    ]


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


def _chunk_ansible_playbook(content: str, source_file: str) -> list:
    """Chunk an Ansible playbook: one chunk per top-level play, preserving verbatim text."""
    play_texts = _split_ansible_list_items(content)

    if not play_texts:
        stripped = content.strip()
        if stripped:
            sym_name, sym_type = _extract_ansible_play_symbol(stripped)
            return [{"content": stripped, "chunk_index": 0, "symbol_name": sym_name, "symbol_type": sym_type}]
        return []

    return [
        {
            "content": play_text,
            "chunk_index": i,
            "symbol_name": sym_name,
            "symbol_type": sym_type,
        }
        for i, play_text in enumerate(play_texts)
        if play_text
        for sym_name, sym_type in [_extract_ansible_play_symbol(play_text)]
    ]


def _chunk_ansible_role_tasks(content: str, source_file: str, role_name: str, role_dir: str) -> list:
    """Chunk a role tasks or handlers file: one chunk per list item, preserving verbatim text."""
    task_texts = _split_ansible_list_items(content)

    if not task_texts:
        stripped = content.strip()
        if stripped:
            sym_type = "ansible_handler" if role_dir == "handlers" else "ansible_task"
            return [{"content": stripped, "chunk_index": 0, "symbol_name": role_name, "symbol_type": sym_type}]
        return []

    chunks = []
    for i, task_text in enumerate(task_texts):
        if not task_text:
            continue
        if role_dir == "handlers":
            sym_name, sym_type = _extract_ansible_handler_symbol(task_text)
        else:
            sym_name, sym_type = _extract_ansible_task_symbol(task_text)
        if not sym_name:
            sym_name = role_name
        chunks.append({"content": task_text, "chunk_index": i, "symbol_name": sym_name, "symbol_type": sym_type})
    return chunks


def _chunk_ansible_role_vars(content: str, source_file: str, role_name: str) -> list:
    """Chunk a role vars or defaults file as a single unit tagged ansible_vars."""
    stripped = content.strip()
    if not stripped:
        return []
    return [{"content": stripped, "chunk_index": 0, "symbol_name": role_name, "symbol_type": "ansible_vars"}]


def _chunk_ansible_inventory(content: str, source_file: str) -> list:
    """Chunk an Ansible inventory file as a single file-level chunk (no host/group parsing)."""
    stripped = content.strip()
    if not stripped:
        return []
    return [{"content": stripped, "chunk_index": 0, "symbol_name": "", "symbol_type": "ansible_inventory"}]


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


def chunk_file(content: str, ext: str, source_file: str, language: str | None = None) -> list:
    """Dispatcher — route to the right chunking strategy based on language."""
    # .csproj/.fsproj/.vbproj: verbatim project-XML chunker (ext-based, before language lookup
    # so the generic XML fallback is preserved for all other XML files as per design notes).
    if ext in _DOTNET_PROJECT_FILE_EXTS:
        return _chunk_dotnet_project_xml(content, source_file)

    if language is None:
        language = EXTENSION_LANG_MAP.get(ext, "unknown")

    if language in (
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
    ):
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


def _chunk_python_treesitter(parser, content: str, source_file: str) -> list:
    """
    AST-aware Python chunker using tree-sitter.

    Extracts function_definition, class_definition, and decorated_definition
    nodes as chunk boundaries. Attaches immediately adjacent leading comment
    siblings (no blank-line gap) to their definition. Feeds raw text chunks
    through adaptive_merge_split() and tags each result with
    chunker_strategy='treesitter_v1'.

    Falls back to chunk_adaptive_lines() when no definition nodes are found
    (e.g. plain-assignment modules).
    """
    DEFINITION_TYPES = frozenset(
        {"function_definition", "class_definition", "decorated_definition"}
    )

    source_bytes = content.encode("utf-8")
    tree = parser.parse(source_bytes)
    children = tree.root_node.children

    # Build boundary_indices: for each definition node, track the start child
    # index after pulling in any immediately preceding comment siblings.
    boundary_indices: list = []
    for i, child in enumerate(children):
        if child.type in DEFINITION_TYPES:
            start_i = i
            j = i - 1
            while j >= 0:
                prev = children[j]
                if prev.type == "comment":
                    # No blank line between this comment and the node after it?
                    gap = source_bytes[prev.end_byte : children[j + 1].start_byte]
                    if b"\n\n" in gap:
                        break
                    start_i = j
                    j -= 1
                else:
                    break
            boundary_indices.append(start_i)

    if not boundary_indices:
        # No top-level definitions found (e.g. plain-assignment module).
        # Tag explicitly so _collect_specs_for_file doesn't mislabel as
        # regex_structural_v1 — the regex structural path was never executed.
        fallback = chunk_adaptive_lines(content, source_file)
        for chunk in fallback:
            chunk["chunker_strategy"] = "treesitter_adaptive_v1"
        return fallback

    raw_chunks: list = []

    # Preamble: all content before the first boundary (imports, module docstring, etc.)
    first_start_byte = children[boundary_indices[0]].start_byte
    if first_start_byte > 0:
        preamble = source_bytes[:first_start_byte].decode("utf-8").strip()
        if preamble:
            raw_chunks.append(preamble)

    # Each definition chunk: from its start_byte to the next boundary's start_byte
    for k, start_child_idx in enumerate(boundary_indices):
        start_byte = children[start_child_idx].start_byte
        end_byte = (
            children[boundary_indices[k + 1]].start_byte
            if k + 1 < len(boundary_indices)
            else len(source_bytes)
        )
        text = source_bytes[start_byte:end_byte].decode("utf-8").strip()
        if text:
            raw_chunks.append(text)

    merged = adaptive_merge_split(raw_chunks, source_file)
    for chunk in merged:
        chunk["chunker_strategy"] = "treesitter_v1"
    return merged


def _chunk_typescript_treesitter(parser, content: str, source_file: str) -> list:
    """
    AST-aware TypeScript/JavaScript/TSX/JSX chunker using tree-sitter.

    Extracts top-level export_statement, function_declaration, class_declaration,
    interface_declaration, type_alias_declaration, enum_declaration,
    lexical_declaration, and expression_statement nodes as chunk boundaries.
    Leading import_statement nodes are collected into a preamble chunk. Attaches
    immediately adjacent leading comment siblings (no blank-line gap) to their
    definition. Feeds raw text chunks through adaptive_merge_split() and tags
    each result with chunker_strategy='treesitter_v1'.

    Falls back to chunk_adaptive_lines() when no definition nodes are found
    (e.g. barrel files that only re-export or pure-import files).
    """
    DEFINITION_TYPES = frozenset(
        {
            "export_statement",
            "function_declaration",
            "class_declaration",
            "interface_declaration",
            "type_alias_declaration",
            "enum_declaration",
            "lexical_declaration",
            "expression_statement",
        }
    )

    source_bytes = content.encode("utf-8")
    tree = parser.parse(source_bytes)
    children = tree.root_node.children

    # Build boundary_indices: for each definition node, track the start child
    # index after pulling in any immediately preceding comment siblings.
    boundary_indices: list = []
    for i, child in enumerate(children):
        if child.type in DEFINITION_TYPES:
            start_i = i
            j = i - 1
            while j >= 0:
                prev = children[j]
                if prev.type == "comment":
                    # No blank line between this comment and the node after it?
                    gap = source_bytes[prev.end_byte : children[j + 1].start_byte]
                    if b"\n\n" in gap:
                        break
                    start_i = j
                    j -= 1
                else:
                    break
            boundary_indices.append(start_i)

    if not boundary_indices:
        # No top-level definitions found (e.g. barrel/config file with only imports).
        fallback = chunk_adaptive_lines(content, source_file)
        for chunk in fallback:
            chunk["chunker_strategy"] = "treesitter_adaptive_v1"
        return fallback

    raw_chunks: list = []

    # Preamble: all content before the first boundary (imports, license header, etc.)
    first_start_byte = children[boundary_indices[0]].start_byte
    if first_start_byte > 0:
        preamble = source_bytes[:first_start_byte].decode("utf-8").strip()
        if preamble:
            raw_chunks.append(preamble)

    # Each definition chunk: from its start_byte to the next boundary's start_byte
    for k, start_child_idx in enumerate(boundary_indices):
        start_byte = children[start_child_idx].start_byte
        end_byte = (
            children[boundary_indices[k + 1]].start_byte
            if k + 1 < len(boundary_indices)
            else len(source_bytes)
        )
        text = source_bytes[start_byte:end_byte].decode("utf-8").strip()
        if text:
            raw_chunks.append(text)

    merged = adaptive_merge_split(raw_chunks, source_file)
    for chunk in merged:
        chunk["chunker_strategy"] = "treesitter_v1"
    return merged


def _chunk_go_treesitter(parser, content: str, source_file: str) -> list:
    """
    AST-aware Go chunker using tree-sitter.

    Extracts function_declaration, method_declaration, type_declaration,
    const_declaration, and var_declaration nodes as chunk boundaries.
    Attaches immediately adjacent leading comment siblings (no blank-line
    gap) to their declaration. Feeds raw text chunks through
    adaptive_merge_split() and tags each result with
    chunker_strategy='treesitter_v1'.

    Falls back to chunk_adaptive_lines() when no declaration nodes are
    found (e.g. package-only files).
    """
    DEFINITION_TYPES = frozenset(
        {
            "function_declaration",
            "method_declaration",
            "type_declaration",
            "const_declaration",
            "var_declaration",
        }
    )

    source_bytes = content.encode("utf-8")
    tree = parser.parse(source_bytes)
    children = tree.root_node.children

    # Build boundary_indices: for each declaration node, track the start child
    # index after pulling in any immediately preceding comment siblings.
    boundary_indices: list = []
    for i, child in enumerate(children):
        if child.type in DEFINITION_TYPES:
            start_i = i
            j = i - 1
            while j >= 0:
                prev = children[j]
                if prev.type == "comment":
                    # No blank line between this comment and the node after it?
                    gap = source_bytes[prev.end_byte : children[j + 1].start_byte]
                    if b"\n\n" in gap:
                        break
                    start_i = j
                    j -= 1
                else:
                    break
            boundary_indices.append(start_i)

    if not boundary_indices:
        fallback = chunk_adaptive_lines(content, source_file)
        for chunk in fallback:
            chunk["chunker_strategy"] = "treesitter_adaptive_v1"
        return fallback

    raw_chunks: list = []

    # Preamble: all content before the first boundary (package clause, imports, etc.)
    first_start_byte = children[boundary_indices[0]].start_byte
    if first_start_byte > 0:
        preamble = source_bytes[:first_start_byte].decode("utf-8").strip()
        if preamble:
            raw_chunks.append(preamble)

    # Each declaration chunk: from its start_byte to the next boundary's start_byte
    for k, start_child_idx in enumerate(boundary_indices):
        start_byte = children[start_child_idx].start_byte
        end_byte = (
            children[boundary_indices[k + 1]].start_byte
            if k + 1 < len(boundary_indices)
            else len(source_bytes)
        )
        text = source_bytes[start_byte:end_byte].decode("utf-8").strip()
        if text:
            raw_chunks.append(text)

    merged = adaptive_merge_split(raw_chunks, source_file)
    for chunk in merged:
        chunk["chunker_strategy"] = "treesitter_v1"
    return merged


def _chunk_rust_treesitter(parser, content: str, source_file: str) -> list:
    """
    AST-aware Rust chunker using tree-sitter.

    Extracts function_item, struct_item, enum_item, trait_item, impl_item,
    mod_item, type_item, const_item, and static_item nodes as chunk boundaries. Attaches immediately
    adjacent leading attribute_item (#[...]) and comment siblings (no
    blank-line gap) to their item — critical because tree-sitter-rust keeps
    #[derive(...)] as a separate attribute_item sibling rather than wrapping
    it with the item. Feeds raw text chunks through adaptive_merge_split()
    and tags each result with chunker_strategy='treesitter_v1'.

    Falls back to chunk_adaptive_lines() when no item nodes are found.
    """
    DEFINITION_TYPES = frozenset(
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

    source_bytes = content.encode("utf-8")
    tree = parser.parse(source_bytes)
    children = tree.root_node.children

    boundary_indices: list = []
    for i, child in enumerate(children):
        if child.type in DEFINITION_TYPES:
            start_i = i
            j = i - 1
            while j >= 0:
                prev = children[j]
                if prev.type in ("attribute_item", "comment", "line_comment", "block_comment"):
                    gap = source_bytes[prev.end_byte : children[j + 1].start_byte]
                    if b"\n\n" in gap:
                        break
                    start_i = j
                    j -= 1
                else:
                    break
            boundary_indices.append(start_i)

    if not boundary_indices:
        fallback = chunk_adaptive_lines(content, source_file)
        for chunk in fallback:
            chunk["chunker_strategy"] = "treesitter_adaptive_v1"
        return fallback

    raw_chunks: list = []

    first_start_byte = children[boundary_indices[0]].start_byte
    if first_start_byte > 0:
        preamble = source_bytes[:first_start_byte].decode("utf-8").strip()
        if preamble:
            raw_chunks.append(preamble)

    for k, start_child_idx in enumerate(boundary_indices):
        start_byte = children[start_child_idx].start_byte
        end_byte = (
            children[boundary_indices[k + 1]].start_byte
            if k + 1 < len(boundary_indices)
            else len(source_bytes)
        )
        text = source_bytes[start_byte:end_byte].decode("utf-8").strip()
        if text:
            raw_chunks.append(text)

    merged = adaptive_merge_split(raw_chunks, source_file)
    for chunk in merged:
        chunk["chunker_strategy"] = "treesitter_v1"
    return merged


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
    )

    lines = content.split("\n")
    boundaries = []
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

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            if in_import_block:
                in_import_block = False
            continue

        if TS_IMPORT.match(stripped) and is_ts_js:
            if not in_import_block:
                boundaries.append(("import", i))
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
            boundaries.append(("decl", comment_start))

    if not boundaries:
        return chunk_adaptive_lines(content, source_file)

    raw_chunks = []

    # Preamble before the first boundary (file header, license, etc.)
    if boundaries[0][1] > 0:
        preamble = "\n".join(lines[: boundaries[0][1]]).strip()
        if preamble:
            raw_chunks.append(preamble)

    for idx, (_kind, start) in enumerate(boundaries):
        end = boundaries[idx + 1][1] if idx + 1 < len(boundaries) else len(lines)
        text = "\n".join(lines[start:end]).strip()
        if text:
            raw_chunks.append(text)

    # adaptive_merge_split handles final MIN_CHUNK filtering and merging of small pieces.
    return adaptive_merge_split(raw_chunks, source_file)


def chunk_prose(content: str, source_file: str) -> list:
    """
    Split prose at markdown heading boundaries (#–######).
    Falls back to paragraph chunking if no headings are found.
    """
    lines = content.split("\n")
    heading_lines = [i for i, line in enumerate(lines) if HEADING_MD.match(line.strip())]

    if not heading_lines:
        # Paragraph fallback — let adaptive_merge_split handle MIN_CHUNK filtering.
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", content) if p.strip()]
        return adaptive_merge_split(paragraphs, source_file) if paragraphs else []

    raw_chunks = []
    heading_stack = {}

    # Preamble before the first heading
    if heading_lines[0] > 0:
        preamble = "\n".join(lines[: heading_lines[0]]).strip()
        if preamble:
            raw_chunks.append(
                {
                    "content": preamble,
                    "markdown_metadata": _markdown_section_metadata(preamble, "", 0, []),
                }
            )

    for idx, start in enumerate(heading_lines):
        end = heading_lines[idx + 1] if idx + 1 < len(heading_lines) else len(lines)
        section = "\n".join(lines[start:end]).strip()
        if section:
            match = HEADING_MD.match(lines[start].strip())
            level = len(match.group(1)) if match else 0
            heading = _clean_markdown_heading(match.group(2)) if match else ""
            heading_stack = {k: v for k, v in heading_stack.items() if k < level}
            if level:
                heading_stack[level] = heading
            heading_path = [heading_stack[k] for k in sorted(heading_stack)]
            raw_chunks.append(
                {
                    "content": section,
                    "markdown_metadata": _markdown_section_metadata(
                        section, heading, level, heading_path
                    ),
                }
            )

    return adaptive_merge_split_sections(raw_chunks, source_file)


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


def adaptive_merge_split_sections(raw_chunks: list, source_file: str) -> list:
    """
    Markdown-aware variant of adaptive_merge_split().
    Preserves section metadata while merging small sections and splitting large ones.
    """
    if not raw_chunks:
        return []

    result = []
    buffer = ""
    buffer_meta = None

    for item in raw_chunks:
        chunk = item["content"]
        metadata = item.get("markdown_metadata", {})
        if len(chunk) > HARD_MAX:
            if buffer.strip():
                result.append({"content": buffer.strip(), "markdown_metadata": buffer_meta or {}})
                buffer = ""
                buffer_meta = None
            for split in _split_oversized(chunk):
                result.append({"content": split, "markdown_metadata": metadata})
        elif len(buffer) + len(chunk) + 2 <= TARGET_MAX:
            buffer = f"{buffer}\n\n{chunk}" if buffer else chunk
            buffer_meta = (
                _merge_markdown_metadata(buffer_meta, metadata) if buffer_meta else dict(metadata)
            )
        else:
            if buffer.strip():
                result.append({"content": buffer.strip(), "markdown_metadata": buffer_meta or {}})
            buffer = chunk
            buffer_meta = dict(metadata)

    if buffer.strip():
        result.append({"content": buffer.strip(), "markdown_metadata": buffer_meta or {}})

    filtered = [item for item in result if len(item["content"]) >= MIN_CHUNK]
    return [
        {
            "content": item["content"],
            "chunk_index": i,
            "markdown_metadata": item["markdown_metadata"],
        }
        for i, item in enumerate(filtered)
    ]


def _merge_markdown_metadata(left: dict, right: dict) -> dict:
    """Merge metadata when adjacent short Markdown sections share one drawer."""
    left = left or {}
    right = right or {}
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


def chunk_adaptive_lines(content: str, source_file: str) -> list:
    """
    Fallback for files without dedicated structural patterns.
    Split at blank lines with adaptive sizing.
    """
    blocks = re.split(r"\n\s*\n", content)
    raw = [b.strip() for b in blocks if len(b.strip()) >= MIN_CHUNK]
    if not raw:
        if len(content.strip()) >= MIN_CHUNK:
            return [{"content": content.strip(), "chunk_index": 0}]
        return []
    return adaptive_merge_split(raw, source_file)


def _chunk_dotnet_project_xml(content: str, source_file: str) -> list:
    """
    Verbatim chunker for .csproj / .fsproj / .vbproj files.

    Emits the entire file as a single chunk so that PackageReference,
    ProjectReference, and TargetFramework blocks are co-embedded rather than
    split into sub-MIN_CHUNK fragments by blank-line splitting in the generic
    fallback. Tags with chunker_strategy='dotnet_project_xml_v1'.
    """
    stripped = content.strip()
    if len(stripped) < MIN_CHUNK:
        return []
    return [
        {
            "content": stripped,
            "chunk_index": 0,
            "chunker_strategy": "dotnet_project_xml_v1",
        }
    ]


def adaptive_merge_split(raw_chunks: list, source_file: str) -> list:
    """
    Post-process raw chunks:
    - Merge adjacent small chunks (< TARGET_MIN) up to TARGET_MAX.
    - Split oversized chunks (> HARD_MAX) at paragraph/line sub-boundaries.
    Returns list of {"content": str, "chunk_index": int}.
    """
    if not raw_chunks:
        return []

    result = []
    buffer = ""

    for chunk in raw_chunks:
        if len(chunk) > HARD_MAX:
            if buffer.strip():
                result.append(buffer.strip())
                buffer = ""
            result.extend(_split_oversized(chunk))
        elif len(buffer) + len(chunk) + 2 <= TARGET_MAX:
            buffer = f"{buffer}\n\n{chunk}" if buffer else chunk
        else:
            if buffer.strip():
                result.append(buffer.strip())
            buffer = chunk

    if buffer.strip():
        result.append(buffer.strip())

    filtered = [text for text in result if len(text) >= MIN_CHUNK]
    return [{"content": text, "chunk_index": i} for i, text in enumerate(filtered)]


def _split_oversized(text: str) -> list:
    """Split a chunk exceeding HARD_MAX at the best available sub-boundary."""
    # Try paragraph breaks first
    parts = re.split(r"\n\s*\n", text)
    if len(parts) > 1:
        merged = []
        buf = ""
        for part in parts:
            if len(buf) + len(part) + 2 <= TARGET_MAX:
                buf = f"{buf}\n\n{part}" if buf else part
            else:
                if buf.strip():
                    merged.append(buf.strip())
                buf = part
        if buf.strip():
            merged.append(buf.strip())
        return merged

    # Fall back to line-based splitting
    lines_list = text.split("\n")
    merged = []
    buf = ""
    for line in lines_list:
        if len(buf) + len(line) + 1 <= TARGET_MAX:
            buf = f"{buf}\n{line}" if buf else line
        else:
            if buf.strip():
                merged.append(buf.strip())
            buf = line
    if buf.strip():
        merged.append(buf.strip())
    return merged
