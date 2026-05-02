"""
architecture.py — Post-mining architecture extraction pass for MemPalace.

Scans source files after mining to produce higher-level KG facts:
  - (<type>, "is_pattern", "Service" | "Repository" | "Controller" | "ViewModel" | "Factory")
  - (<type>, "is_layer",   "UI" | "Business" | "Data" | "Infrastructure")
  - (<type>, "in_namespace", <namespace>)
  - (<type>, "in_project",   <project>)
  - (<namespace>, "in_project", <project>)

These are queryable via mempalace_kg_query:
  - "Show all services":   entity="Service",  direction="incoming" (filter predicate=is_pattern)
  - "Show data layer":     entity="Data",     direction="incoming" (filter predicate=is_layer)
  - "Types in namespace":  entity="Foo.Bar",  direction="incoming" (filter predicate=in_namespace)

Config block in mempalace.yaml:

  architecture:
    enabled: true          # set false to disable entirely
    patterns:
      - name: Service
        suffixes: [Service]
        type_names: []     # optional explicit names (e.g. AuditHandler)
      - name: Repository
        suffixes: [Repository]
    layers:
      - name: UI
        namespace_globs: ["*.UI", "*.Web", "*.Presentation"]
        type_suffixes: [Controller, ViewModel]
        priority: 1
      - name: Business
        namespace_globs: ["*.Application", "*.Domain"]
        type_suffixes: [Service]
        priority: 2

Omitting the architecture: block entirely uses the built-in defaults.
Invalid rule entries are silently ignored; the pass continues with valid rules.
"""

import fnmatch
import re
from pathlib import Path

# Predicates owned by this pass.  Only these are expired before re-emission.
ARCH_PREDICATES = ("is_pattern", "is_layer", "in_namespace", "in_project")

# Stable prefix for namespace→project sentinel source_file values.
_NS_PROJECT_SENTINEL = "__arch_ns_project__"


def namespace_project_source_file(project_name: str) -> str:
    """Return the sentinel source_file string for a namespace→project triple.

    Each wing/project gets a distinct sentinel so that
    ``invalidate_arch_by_project_root`` can expire only the current wing's
    namespace→project triples without touching other wings'.
    """
    return f"{_NS_PROJECT_SENTINEL}:{project_name}"

# ── Default rules (common .NET conventions) ──────────────────────────────────

DEFAULT_PATTERNS = [
    {"name": "Service", "suffixes": ["Service"], "type_names": []},
    {"name": "Repository", "suffixes": ["Repository"], "type_names": []},
    {"name": "Controller", "suffixes": ["Controller"], "type_names": []},
    {"name": "ViewModel", "suffixes": ["ViewModel", "VM"], "type_names": []},
    {"name": "Factory", "suffixes": ["Factory"], "type_names": []},
]

DEFAULT_LAYERS = [
    {
        "name": "UI",
        "namespace_globs": ["*.UI", "*.Web", "*.Presentation"],
        "type_suffixes": ["Controller", "ViewModel"],
        "priority": 1,
    },
    {
        "name": "Business",
        "namespace_globs": ["*.Application", "*.Domain"],
        "type_suffixes": ["Service"],
        "priority": 2,
    },
    {
        "name": "Data",
        "namespace_globs": ["*.Data", "*.Persistence"],
        "type_suffixes": ["Repository"],
        "priority": 3,
    },
    {
        "name": "Infrastructure",
        "namespace_globs": ["*.Infrastructure"],
        "type_suffixes": [],
        "priority": 4,
    },
]


# ── Config parsing ────────────────────────────────────────────────────────────


def load_arch_config(raw_config) -> dict:
    """Parse the ``architecture:`` block from a mempalace.yaml config dict.

    Returns a normalised dict with keys ``enabled``, ``patterns``, ``layers``.
    Invalid rule entries are silently dropped; falls back to built-in defaults
    when the whole section is missing or malformed.
    """
    if not isinstance(raw_config, dict):
        return {"enabled": True, "patterns": list(DEFAULT_PATTERNS), "layers": list(DEFAULT_LAYERS)}
    arch = raw_config.get("architecture", {})
    if not isinstance(arch, dict):
        return {"enabled": True, "patterns": list(DEFAULT_PATTERNS), "layers": list(DEFAULT_LAYERS)}

    enabled = arch.get("enabled", True)
    if not isinstance(enabled, bool):
        enabled = True

    patterns = _parse_patterns(arch.get("patterns"))
    layers = _parse_layers(arch.get("layers"))

    return {"enabled": enabled, "patterns": patterns, "layers": layers}


def _parse_patterns(raw) -> list:
    if not isinstance(raw, list):
        return list(DEFAULT_PATTERNS)
    result = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        suffixes = entry.get("suffixes", [])
        if not isinstance(suffixes, list):
            continue
        type_names = entry.get("type_names", [])
        if not isinstance(type_names, list):
            type_names = []
        result.append(
            {
                "name": name.strip(),
                "suffixes": [s for s in suffixes if isinstance(s, str)],
                "type_names": [t for t in type_names if isinstance(t, str)],
            }
        )
    return result if result else list(DEFAULT_PATTERNS)


def _parse_layers(raw) -> list:
    if not isinstance(raw, list):
        return list(DEFAULT_LAYERS)
    result = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        namespace_globs = entry.get("namespace_globs", [])
        if not isinstance(namespace_globs, list):
            continue
        type_suffixes = entry.get("type_suffixes", [])
        if not isinstance(type_suffixes, list):
            type_suffixes = []
        priority = entry.get("priority", 99)
        if not isinstance(priority, (int, float)):
            priority = 99
        result.append(
            {
                "name": name.strip(),
                "namespace_globs": [g for g in namespace_globs if isinstance(g, str)],
                "type_suffixes": [s for s in type_suffixes if isinstance(s, str)],
                "priority": int(priority),
            }
        )
    return result if result else list(DEFAULT_LAYERS)


# ── Source-file scanning ──────────────────────────────────────────────────────

_CS_NAMESPACE_RE = re.compile(r"^\s*namespace\s+([\w.]+)", re.MULTILINE)
_CS_TYPE_RE = re.compile(
    r"^\s*(?:(?:public|private|protected|internal|sealed|abstract|static"
    r"|partial|new|readonly|unsafe|override|virtual|extern)\s+)*"
    r"(?:class|struct|interface|enum|record)\s+(\w+)",
    re.MULTILINE,
)

_FS_TYPE_RE = re.compile(r"^\s*type\s+(\w+)", re.MULTILINE)

_VB_NAMESPACE_RE = re.compile(r"^\s*Namespace\s+([\w.]+)", re.MULTILINE | re.IGNORECASE)
_VB_TYPE_RE = re.compile(
    r"^\s*(?:(?:Public|Private|Protected|Friend|MustInherit|NotInheritable"
    r"|Partial|Shadows)\s+)*"
    r"(?:Class|Structure|Interface|Enum)\s+(\w+)",
    re.MULTILINE | re.IGNORECASE,
)

_PY_CLASS_RE = re.compile(r"^\s*class\s+(\w+)", re.MULTILINE)

_ARCH_SOURCE_EXTENSIONS = frozenset({".cs", ".fs", ".fsi", ".vb", ".py"})


def extract_type_inventory(files: list, project_root: Path) -> list:
    """Scan source files and return a list of type-info dicts.

    Each dict has keys: ``type_name``, ``namespace``, ``source_file``.
    Only ``.cs``, ``.fs``/``.fsi``, ``.vb``, and ``.py`` files are scanned.
    Files that cannot be read are silently skipped.
    """
    results = []
    for filepath in files:
        fp = Path(filepath)
        ext = fp.suffix.lower()
        if ext not in _ARCH_SOURCE_EXTENSIONS:
            continue
        try:
            text = fp.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if ext == ".cs":
            _scan_cs(fp, text, results)
        elif ext in (".fs", ".fsi"):
            _scan_fs(fp, text, results)
        elif ext == ".vb":
            _scan_vb(fp, text, results)
        elif ext == ".py":
            _scan_py(fp, text, project_root, results)
    return results


def _scan_cs(filepath: Path, text: str, out: list) -> None:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = re.sub(r"//[^\n]*", "", text)
    namespace = ""
    m = _CS_NAMESPACE_RE.search(text)
    if m:
        namespace = m.group(1)
    for m in _CS_TYPE_RE.finditer(text):
        name = m.group(1)
        if name and name[0].isupper():
            out.append({"type_name": name, "namespace": namespace, "source_file": str(filepath)})


def _scan_fs(filepath: Path, text: str, out: list) -> None:
    namespace = ""
    m = _CS_NAMESPACE_RE.search(text)
    if m:
        namespace = m.group(1)
    for m in _FS_TYPE_RE.finditer(text):
        name = m.group(1)
        if name and name[0].isupper():
            out.append({"type_name": name, "namespace": namespace, "source_file": str(filepath)})


def _scan_vb(filepath: Path, text: str, out: list) -> None:
    namespace = ""
    m = _VB_NAMESPACE_RE.search(text)
    if m:
        namespace = m.group(1)
    for m in _VB_TYPE_RE.finditer(text):
        name = m.group(1)
        if name and name[0].isupper():
            out.append({"type_name": name, "namespace": namespace, "source_file": str(filepath)})


def _scan_py(filepath: Path, text: str, project_root: Path, out: list) -> None:
    try:
        rel = filepath.relative_to(project_root)
        parts = rel.parent.parts
        namespace = ".".join(parts) if parts else ""
    except ValueError:
        namespace = ""
    text = re.sub(r"#[^\n]*", "", text)
    for m in _PY_CLASS_RE.finditer(text):
        name = m.group(1)
        if name and name[0].isupper():
            out.append({"type_name": name, "namespace": namespace, "source_file": str(filepath)})


# ── Pattern and layer matching ────────────────────────────────────────────────


def detect_patterns(type_name: str, patterns: list) -> list:
    """Return pattern names that apply to *type_name* (non-exclusive).

    Matching order per pattern:
      1. Explicit ``type_names`` override — exact string match.
      2. ``suffixes`` — substring match (``suffix in type_name`` and
         ``type_name != suffix`` to skip trivial single-word matches).
    """
    matched = []
    for p in patterns:
        name = p.get("name", "")
        if not name:
            continue
        if type_name in p.get("type_names", []):
            if name not in matched:
                matched.append(name)
            continue
        for suffix in p.get("suffixes", []):
            if suffix and isinstance(suffix, str) and suffix in type_name and type_name != suffix:
                if name not in matched:
                    matched.append(name)
                break
    return matched


def detect_layer(type_name: str, namespace: str, layers: list) -> str | None:
    """Return the single layer name for *type_name* / *namespace*, or ``None``.

    Layer selection is exclusive — at most one is_layer fact per type.
    Priority: lower ``priority`` number wins.  Namespace glob matching
    is evaluated before type-suffix matching so that an explicit namespace
    placement always beats a name-based heuristic.
    """
    sorted_layers = sorted(layers, key=lambda lr: (lr.get("priority", 99), lr.get("name", "")))

    for layer in sorted_layers:
        for glob in layer.get("namespace_globs", []):
            if namespace and isinstance(glob, str) and fnmatch.fnmatch(namespace, glob):
                return layer["name"]

    for layer in sorted_layers:
        for suffix in layer.get("type_suffixes", []):
            if suffix and isinstance(suffix, str) and suffix in type_name and type_name != suffix:
                return layer["name"]

    return None


# ── KG emission ───────────────────────────────────────────────────────────────


def run_arch_pass(inventory: list, arch_config: dict, project_name: str, kg) -> int:
    """Emit architecture KG triples for all types in *inventory*.

    Returns the number of new triples written (dedup-skipped triples
    are not counted since add_triple returns the existing ID for those).

    Before calling this function, the caller should expire stale arch facts for
    the current project by calling ``kg.invalidate_arch_by_project_root`` with
    ``list(ARCH_PREDICATES)``, the project root path, and
    ``sentinels=[namespace_project_source_file(project_name)]``.  This scopes
    invalidation to the current wing so that other wings' arch facts survive
    sequential single-wing mines.
    """
    if not arch_config.get("enabled", True):
        return 0

    patterns = arch_config.get("patterns", DEFAULT_PATTERNS)
    layers = arch_config.get("layers", DEFAULT_LAYERS)

    emitted = 0
    seen_ns_project = set()

    for entry in inventory:
        type_name = entry["type_name"]
        namespace = entry["namespace"]
        source_file = entry["source_file"]

        for pattern_name in detect_patterns(type_name, patterns):
            tid = kg.add_triple(type_name, "is_pattern", pattern_name, source_file=source_file)
            if tid:
                emitted += 1

        layer = detect_layer(type_name, namespace, layers)
        if layer:
            tid = kg.add_triple(type_name, "is_layer", layer, source_file=source_file)
            if tid:
                emitted += 1

        if namespace:
            tid = kg.add_triple(type_name, "in_namespace", namespace, source_file=source_file)
            if tid:
                emitted += 1

            ns_proj_key = (namespace, project_name)
            if ns_proj_key not in seen_ns_project:
                seen_ns_project.add(ns_proj_key)
                tid = kg.add_triple(
                    namespace,
                    "in_project",
                    project_name,
                    source_file=namespace_project_source_file(project_name),
                )
                if tid:
                    emitted += 1

        tid = kg.add_triple(type_name, "in_project", project_name, source_file=source_file)
        if tid:
            emitted += 1

    return emitted
