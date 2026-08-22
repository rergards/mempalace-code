"""mining.kg_extract — .NET project, solution, XAML, and source type-relationship KG extraction."""

import re
from pathlib import Path

from ..source_io import is_regular_source_path, read_regular_text

# File extensions that trigger KG triple extraction during mining.
_KG_EXTRACT_EXTENSIONS = frozenset(
    {".csproj", ".fsproj", ".vbproj", ".sln", ".xaml", ".cs", ".fs", ".fsi", ".vb", ".py"}
)

# .sln project-line regex: captures (project_name, relative_path)
_SLN_PROJECT_RE = re.compile(
    r'Project\("[^"]*"\)\s*=\s*"([^"]+)",\s*"([^"]+)"',
    re.IGNORECASE,
)

# Extensions that identify real project files within a solution (vs. SolutionFolders)
_SLN_PROJECT_EXTS = frozenset({".csproj", ".fsproj", ".vbproj"})

# =============================================================================
# .NET SOURCE FILE TYPE-RELATIONSHIP EXTRACTION
# =============================================================================

# Ordered matcher list for C# type declarations with inheritance/implementation.
# Most-specific patterns first (record struct > record class > bare record > struct > interface > class).
# Each tuple: (compiled_regex, type_kind) — type_kind drives predicate assignment.
# Regex groups: group(1) = type name, group(2) = raw base-type list (post-processed below).
_CSHARP_TYPE_REL_MATCHERS = [
    # record struct — must precede struct and bare record
    (
        re.compile(
            r"^\s*(?:(?:public|private|protected|internal|static|abstract|sealed|partial|"
            r"new|unsafe|readonly)\s+)*"
            r"record\s+struct\s+"
            r"(\w+)"
            r"(?:<[^>]*>)?"
            r"(?:\s*\([^)]*\))?"
            r"\s*:\s*"
            r"(.+)",
            re.MULTILINE,
        ),
        "struct",
    ),
    # record class — must precede class and bare record
    (
        re.compile(
            r"^\s*(?:(?:public|private|protected|internal|static|abstract|sealed|partial|"
            r"new|unsafe)\s+)*"
            r"record\s+class\s+"
            r"(\w+)"
            r"(?:<[^>]*>)?"
            r"(?:\s*\([^)]*\))?"
            r"\s*:\s*"
            r"(.+)",
            re.MULTILINE,
        ),
        "class",
    ),
    # bare record (implicitly a record class)
    (
        re.compile(
            r"^\s*(?:(?:public|private|protected|internal|static|abstract|sealed|partial|"
            r"new|unsafe)\s+)*"
            r"record\s+"
            r"(\w+)"
            r"(?:<[^>]*>)?"
            r"(?:\s*\([^)]*\))?"
            r"\s*:\s*"
            r"(.+)",
            re.MULTILINE,
        ),
        "class",
    ),
    # struct — before class (struct cannot inherit classes in C#, only implements interfaces)
    (
        re.compile(
            r"^\s*(?:(?:public|private|protected|internal|static|abstract|sealed|partial|"
            r"new|unsafe|readonly)\s+)*"
            r"struct\s+"
            r"(\w+)"
            r"(?:<[^>]*>)?"
            r"\s*:\s*"
            r"(.+)",
            re.MULTILINE,
        ),
        "struct",
    ),
    # interface — before class
    (
        re.compile(
            r"^\s*(?:(?:public|private|protected|internal|new)\s+)*"
            r"interface\s+"
            r"(\w+)"
            r"(?:<[^>]*>)?"
            r"\s*:\s*"
            r"(.+)",
            re.MULTILINE,
        ),
        "interface",
    ),
    # class (covers sealed, abstract, static, partial, etc.)
    (
        re.compile(
            r"^\s*(?:(?:public|private|protected|internal|static|abstract|sealed|partial|"
            r"new|unsafe)\s+)*"
            r"class\s+"
            r"(\w+)"
            r"(?:<[^>]*>)?"
            r"\s*:\s*"
            r"(.+)",
            re.MULTILINE,
        ),
        "class",
    ),
]


def _split_base_list(base_str: str) -> list:
    """Split a C# base-type list at depth-0 commas, respecting <> nesting.

    Correctly handles nested generics like ``Dictionary<string, List<int>>``
    where inner commas are type-argument separators, not base-type separators.
    """
    parts = []
    depth = 0
    start = 0
    for i, ch in enumerate(base_str):
        if ch == "<":
            depth += 1
        elif ch == ">":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append(base_str[start:i].strip())
            start = i + 1
    parts.append(base_str[start:].strip())
    return [p for p in parts if p]


def _join_continuation_lines(text: str) -> str:
    """Join C# continuation lines for multi-line base-type declarations.

    When a line ends with ':' or ',' (after rstrip), the next non-empty line's
    stripped content is merged onto it with a single space.  Merging continues
    while the accumulated line still ends with ','.  Stops early when the next
    non-empty line starts with '{' or is a bare ';'.
    """
    lines = text.splitlines()
    result: list = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.rstrip()
        if stripped.endswith(":") or stripped.endswith(","):
            accumulated = stripped
            j = i + 1
            while j < len(lines):
                next_stripped = lines[j].strip()
                if not next_stripped:
                    j += 1
                    continue
                if next_stripped.startswith("{") or next_stripped == ";":
                    break
                accumulated = accumulated + " " + next_stripped
                j += 1
                if not accumulated.rstrip().endswith(","):
                    break
            result.append(accumulated)
            i = j
        else:
            result.append(line)
            i += 1
    return "\n".join(result)


def _csharp_type_rels(filepath: Path) -> list:
    """Extract inheritance/implementation triples from a C# source file.

    Strips block and line comments first to avoid false-positive declarations.
    Returns a list of (subject, predicate, object) tuples.
    """
    try:
        text = read_regular_text(filepath, encoding="utf-8", errors="ignore")
    except OSError:
        return []
    # Strip block comments, then line comments to suppress false-positive declarations.
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = re.sub(r"//[^\n]*", "", text)
    # Join continuation lines so multi-line base-type declarations are matched by the
    # single-line patterns in _CSHARP_TYPE_REL_MATCHERS.
    text = _join_continuation_lines(text)
    triples = []
    seen: set = set()
    for pattern, type_kind in _CSHARP_TYPE_REL_MATCHERS:
        for m in pattern.finditer(text):
            type_name = m.group(1)
            base_list_str = m.group(2)
            # Truncate at generic constraints, block open, statement terminator, or comment.
            for stop in (" where ", "{", ";", "//"):
                idx = base_list_str.find(stop)
                if idx != -1:
                    base_list_str = base_list_str[:idx]
            for base_raw in _split_base_list(base_list_str):
                # Strip generic suffix: IEquatable<Point> -> IEquatable
                base_name = base_raw.split("<")[0].strip()
                if not base_name or not base_name[0].isalpha():
                    continue
                if type_kind == "struct":
                    pred = "implements"
                elif type_kind == "interface":
                    pred = "extends"
                elif len(base_name) >= 2 and base_name[0] == "I" and base_name[1].isupper():
                    pred = "implements"
                else:
                    pred = "inherits"
                key = (type_name, pred, base_name)
                if key not in seen:
                    seen.add(key)
                    triples.append(key)
    return triples


# Module-level compiled patterns for F# line-by-line scanning.
# Allow leading whitespace so that types defined inside explicit modules (indented) are matched.
_FS_TYPE_DECL_RE = re.compile(r"^\s*type\s+(\w+)")
_FS_MODULE_DECL_RE = re.compile(r"^\s*module\s+\w+")
_FS_INHERIT_RE = re.compile(r"^\s+inherit\s+(\w+)")
_FS_IFACE_RE = re.compile(r"^\s+interface\s+(\w+)")


def _fsharp_type_rels(filepath: Path) -> list:
    """Extract inheritance/implementation triples from an F# source file.

    Scans for ``type Name`` declarations (at any indentation level, including types
    inside explicit modules), then collects indented ``inherit Base`` and
    ``interface IFoo with`` lines within the type's scope (until the next
    ``type`` or ``module`` declaration, or EOF).
    """
    try:
        text = read_regular_text(filepath, encoding="utf-8", errors="ignore")
    except OSError:
        return []
    triples = []
    seen: set = set()
    current_type = None
    for line in text.splitlines():
        m = _FS_TYPE_DECL_RE.match(line)
        if m:
            current_type = m.group(1)
            continue
        if _FS_MODULE_DECL_RE.match(line):
            current_type = None
            continue
        if current_type is None:
            continue
        m = _FS_INHERIT_RE.match(line)
        if m:
            key = (current_type, "inherits", m.group(1))
            if key not in seen:
                seen.add(key)
                triples.append(key)
            continue
        m = _FS_IFACE_RE.match(line)
        if m:
            key = (current_type, "implements", m.group(1))
            if key not in seen:
                seen.add(key)
                triples.append(key)
    return triples


# Module-level compiled patterns for VB.NET line-by-line scanning.
_VB_CLASS_RE = re.compile(
    r"^\s*(?:(?:Protected\s+Friend|Private\s+Protected|Public|Private|Protected|Friend)\s+)?"
    r"(?:(?:Partial|MustInherit|NotInheritable|Shadows)\s+)*"
    r"Class\s+(\w+)",
    re.IGNORECASE,
)
_VB_STRUCT_RE = re.compile(
    r"^\s*(?:(?:Protected\s+Friend|Private\s+Protected|Public|Private|Protected|Friend)\s+)?"
    r"(?:(?:Partial|Shadows)\s+)*"
    r"Structure\s+(\w+)",
    re.IGNORECASE,
)
_VB_IFACE_DECL_RE = re.compile(
    r"^\s*(?:(?:Protected\s+Friend|Private\s+Protected|Public|Private|Protected|Friend)\s+)?"
    r"(?:(?:Partial|Shadows)\s+)*"
    r"Interface\s+(\w+)",
    re.IGNORECASE,
)
_VB_INHERITS_RE = re.compile(r"^\s*Inherits\s+(\w+)", re.IGNORECASE)
_VB_IMPLEMENTS_RE = re.compile(r"^\s*Implements\s+(.+)", re.IGNORECASE)
_VB_END_RE = re.compile(r"^\s*End\s+(?:Class|Structure|Interface)\b", re.IGNORECASE)


def _vbnet_type_rels(filepath: Path) -> list:
    """Extract inheritance/implementation triples from a VB.NET source file.

    Scans for Class/Structure/Interface declarations, then collects ``Inherits``
    and ``Implements`` lines within the block (until the matching ``End`` statement).
    """
    try:
        text = read_regular_text(filepath, encoding="utf-8", errors="ignore")
    except OSError:
        return []
    triples = []
    seen: set = set()
    current_type = None
    current_kind = None
    for line in text.splitlines():
        if _VB_END_RE.match(line):
            current_type = None
            current_kind = None
            continue
        m = _VB_CLASS_RE.match(line)
        if m:
            current_type = m.group(1)
            current_kind = "class"
            continue
        m = _VB_STRUCT_RE.match(line)
        if m:
            current_type = m.group(1)
            current_kind = "struct"
            continue
        m = _VB_IFACE_DECL_RE.match(line)
        if m:
            current_type = m.group(1)
            current_kind = "interface"
            continue
        if current_type is None:
            continue
        m = _VB_INHERITS_RE.match(line)
        if m:
            base = m.group(1).strip()
            pred = "extends" if current_kind == "interface" else "inherits"
            key = (current_type, pred, base)
            if key not in seen:
                seen.add(key)
                triples.append(key)
            continue
        m = _VB_IMPLEMENTS_RE.match(line)
        if m:
            for iface_raw in m.group(1).split(","):
                # Strip VB.NET generic suffix: IEquatable(Of T) -> IEquatable
                iface = iface_raw.strip().split("(")[0].strip()
                if iface:
                    key = (current_type, "implements", iface)
                    if key not in seen:
                        seen.add(key)
                        triples.append(key)
    return triples


# Compiled patterns for Python type-relationship extraction.
_PY_CLASS_RE = re.compile(r"^\s*class\s+(\w+)\s*\(([^)]*)\)\s*:", re.MULTILINE)
_PY_IMPORT_RE = re.compile(r"^import\s+(.+)", re.MULTILINE)
_PY_MODULE_TOKEN_RE = re.compile(r"^[\w][\w.]*$")
_PY_FROM_IMPORT_RE = re.compile(r"^from\s+([a-zA-Z][\w.]*)\s+import\s+", re.MULTILINE)
# Base class names that receive the 'implements' predicate in Python.
_PY_ABC_BASES = frozenset({"ABC", "ABCMeta", "Protocol"})


def _python_type_rels(filepath: Path) -> list:
    """Extract inheritance/implementation and import triples from a Python source file.

    Strips ``#`` line comments first to avoid false-positive declarations inside comments.
    Returns a list of (subject, predicate, object) tuples.

    Predicates:
      - ``implements``: class inherits from ABC, ABCMeta, or Protocol
      - ``inherits``: class inherits from any other named base class
      - ``depends_on``: module imports another module (``import x`` and ``from x import``)

    Relative imports (``from . import x``, ``from ..foo import bar``) are skipped.
    Multiline class declarations are out of scope; single-line covers >95% of real Python.
    """
    try:
        text = read_regular_text(filepath, encoding="utf-8", errors="ignore")
    except OSError:
        return []
    # Strip # line comments to avoid matching class declarations inside comments.
    text = re.sub(r"#[^\n]*", "", text)
    triples = []
    seen: set = set()

    # Module name: filename stem, or parent directory name for __init__.py.
    stem = filepath.stem
    module_name = filepath.parent.name if stem == "__init__" else stem

    # Class inheritance extraction.
    for m in _PY_CLASS_RE.finditer(text):
        type_name = m.group(1)
        # Pre-strip generic type parameters before splitting by comma to avoid
        # comma-split inside brackets (e.g. Generic[K, V] → Generic, not Generic + V]).
        bases_str = re.sub(r"\[.*?\]", "", m.group(2))
        for base_raw in bases_str.split(","):
            # Strip trailing ] left by nested generics (e.g. Mapping[str, Tuple[int]]).
            base_raw = base_raw.strip().rstrip("]").strip()
            if not base_raw:
                continue
            # Skip keyword arguments: metaclass=ABCMeta, total=False, etc.
            if "=" in base_raw:
                continue
            base_name = base_raw
            if not base_name or not base_name[0].isalpha():
                continue
            pred = "implements" if base_name in _PY_ABC_BASES else "inherits"
            key = (type_name, pred, base_name)
            if key not in seen:
                seen.add(key)
                triples.append(key)

    # Import extraction — emit depends_on triples for module-level imports.
    for m in _PY_IMPORT_RE.finditer(text):
        # Drop anything after ';' so "import os; print()" still yields os, matching
        # pre-multi-module behavior. Subsequent statements on the line are not parsed.
        content = m.group(1).split(";", 1)[0]
        for segment in content.split(","):
            # Strip optional "as <alias>" suffix, then whitespace.
            mod = segment.split(" as ")[0].strip()
            if not _PY_MODULE_TOKEN_RE.match(mod):
                continue
            key = (module_name, "depends_on", mod)
            if key not in seen:
                seen.add(key)
                triples.append(key)
    for m in _PY_FROM_IMPORT_RE.finditer(text):
        key = (module_name, "depends_on", m.group(1))
        if key not in seen:
            seen.add(key)
            triples.append(key)

    return triples


def extract_type_relationships(filepath: Path) -> list:
    """Extract interface-implementation, inheritance, and import triples from source files.

    Supports C# (.cs), F# (.fs/.fsi), VB.NET (.vb), and Python (.py). Uses regex-based
    heuristics (no semantic analysis). Returns a list of (subject, predicate, object) tuples.

    Predicates:
      - ``implements``: class/record/struct implements an interface (C#/VB: I-prefix heuristic;
        Python: base is ABC, ABCMeta, or Protocol)
      - ``inherits``: class/record inherits a base class
      - ``extends``: interface extends another interface (C#/VB only)
      - ``depends_on``: Python module imports another module
    """
    ext = filepath.suffix.lower()
    if ext == ".cs":
        return _csharp_type_rels(filepath)
    if ext in (".fs", ".fsi"):
        return _fsharp_type_rels(filepath)
    if ext == ".vb":
        return _vbnet_type_rels(filepath)
    if ext == ".py":
        return _python_type_rels(filepath)
    return []


def parse_dotnet_project_file(filepath: Path) -> list:
    """Parse a .csproj/.fsproj/.vbproj file and return KG triples.

    Returns a list of (subject, predicate, object) tuples.
    Project name is derived from the filename stem.
    Uses stdlib xml.etree.ElementTree; no extra dependencies.
    """
    import xml.etree.ElementTree as ET

    project_name = filepath.stem
    triples = []

    try:
        content = read_regular_text(filepath, encoding="utf-8", errors="replace")
        root = ET.fromstring(content)
    except (ET.ParseError, OSError):
        return triples

    for elem in root.iter():
        # Strip MSBuild namespace prefix if present (e.g. {http://schemas.microsoft.com/...})
        tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag

        if tag == "TargetFramework":
            val = (elem.text or "").strip()
            if val:
                triples.append((project_name, "targets_framework", val))

        elif tag == "TargetFrameworks":
            # Multi-target: <TargetFrameworks>net8.0;net6.0</TargetFrameworks>
            for fw in (elem.text or "").split(";"):
                fw = fw.strip()
                if fw:
                    triples.append((project_name, "targets_framework", fw))

        elif tag == "OutputType":
            val = (elem.text or "").strip()
            if val:
                triples.append((project_name, "has_output_type", val))

        elif tag == "PackageReference":
            name = elem.get("Include", "").strip()
            version = elem.get("Version", "").strip()
            if name:
                obj = f"{name}@{version}" if version else name
                triples.append((project_name, "depends_on", obj))

        elif tag == "ProjectReference":
            include = elem.get("Include", "").strip()
            if include:
                ref_name = Path(include.replace("\\", "/")).stem
                triples.append((project_name, "references_project", ref_name))

    return triples


def parse_sln_file(filepath: Path) -> list:
    """Parse a .sln file and return KG triples.

    Returns a list of (subject, predicate, object) tuples.
    Only real project entries (.csproj/.fsproj/.vbproj) emit triples —
    SolutionFolder entries are excluded.
    Solution name is derived from the filename stem.
    """
    solution_name = filepath.stem
    triples = []

    try:
        content = read_regular_text(filepath, encoding="utf-8", errors="replace")
    except OSError:
        return triples

    for match in _SLN_PROJECT_RE.finditer(content):
        project_name = match.group(1)
        project_path_str = match.group(2)
        suffix = Path(project_path_str.replace("\\", "/")).suffix.lower()
        if suffix in _SLN_PROJECT_EXTS:
            triples.append((solution_name, "contains_project", project_name))

    return triples


# =============================================================================
# XAML FILE PARSING — KG triple extraction
# =============================================================================

# XAML namespace URI for the core XAML language (x: prefix by convention).
_XAML_NS = "http://schemas.microsoft.com/winfx/2006/xaml"

# d:DataContext design-time binding — e.g. d:DataContext="{d:DesignInstance Type=vm:MainViewModel}"
_XAML_D_DATACONTEXT_RE = re.compile(
    r'd:DataContext="\{d:DesignInstance\s+(?:Type=)?(?:[\w]+:)?(\w+)',
    re.IGNORECASE,
)

# StaticResource and DynamicResource references inside attribute values
_XAML_RESOURCE_RE = re.compile(r"\{(?:Static|Dynamic)Resource\s+(\w+)\}")

# Command binding — Command="{Binding SaveCommand}" or Command="{Binding Path=SaveCommand}"
_XAML_COMMAND_RE = re.compile(r'Command\s*=\s*"\{Binding\s+(?:Path=)?(\w+)\}"')


def parse_xaml_file(filepath: Path) -> list:
    """Parse a .xaml file and return KG triples.

    Returns a list of (subject, predicate, object) tuples.
    Subject is the view name: short name from x:Class or filename stem.
    Uses xml.etree.ElementTree for structured traversal (x:Class, x:Name, plain Name=,
    DataContext element syntax) and regex for markup extension values
    ({Binding}, {StaticResource}, {DynamicResource}, d:DataContext) that
    ET treats as opaque attribute strings.
    """
    import xml.etree.ElementTree as ET

    triples = []

    try:
        content = read_regular_text(filepath, encoding="utf-8", errors="replace")
    except OSError:
        return triples

    if not content.strip():
        return triples

    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return triples

    # Determine view name: x:Class short name or filename stem
    view_name = filepath.stem
    xclass_attr = f"{{{_XAML_NS}}}Class"
    raw_class = root.get(xclass_attr, "")
    if not raw_class:
        # Fallback: scan first 5 lines for raw x:Class text (namespace edge cases)
        for line in content.splitlines()[:5]:
            m = re.search(r'x:Class="([\w.]+)"', line)
            if m:
                raw_class = m.group(1)
                break
    if raw_class:
        view_name = raw_class.rsplit(".", 1)[-1]

    # 1. Code-behind link (only when an adjacent .xaml.cs file exists on disk)
    code_behind = filepath.parent / (filepath.name + ".cs")
    if is_regular_source_path(code_behind):
        triples.append((view_name, "has_code_behind", code_behind.name))

    # 2. ViewModel from element DataContext:
    #    <Window.DataContext><local:MainViewModel /></Window.DataContext>
    for elem in root.iter():
        tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
        if tag.endswith(".DataContext"):
            for child in elem:
                child_tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                # Strip namespace prefix (e.g. "local:MainViewModel" → "MainViewModel")
                vm_name = child_tag.rsplit(":", 1)[-1] if ":" in child_tag else child_tag
                if vm_name:
                    triples.append((view_name, "binds_viewmodel", vm_name))

    # 3. Named controls (x:Name or plain Name= attribute)
    # WPF's FrameworkElement exposes both as equivalent shorthands; collect both
    # into a set per element so a duplicate value on the same element emits only one triple.
    xname_attr = f"{{{_XAML_NS}}}Name"
    for elem in root.iter():
        names: set = set()
        xname_val = elem.get(xname_attr, "")
        if xname_val:
            names.add(xname_val)
        plain_name_val = elem.get("Name", "")
        if plain_name_val:
            names.add(plain_name_val)
        for name_val in names:
            triples.append((view_name, "has_named_control", name_val))

    # 4. ViewModel from d:DataContext design-time attribute (regex — markup extension)
    m = _XAML_D_DATACONTEXT_RE.search(content)
    if m:
        vm_name = m.group(1)
        existing_vms = {t[2] for t in triples if t[0] == view_name and t[1] == "binds_viewmodel"}
        if vm_name not in existing_vms:
            triples.append((view_name, "binds_viewmodel", vm_name))

    # 5. Resource references (StaticResource and DynamicResource — deduplicated)
    seen_resources: set = set()
    for rm in _XAML_RESOURCE_RE.finditer(content):
        key = rm.group(1)
        if key not in seen_resources:
            triples.append((view_name, "references_resource", key))
            seen_resources.add(key)

    # 6. Command bindings (deduplicated)
    seen_commands: set = set()
    for cm in _XAML_COMMAND_RE.finditer(content):
        cmd = cm.group(1)
        if cmd not in seen_commands:
            triples.append((view_name, "uses_command", cmd))
            seen_commands.add(cmd)

    return triples
