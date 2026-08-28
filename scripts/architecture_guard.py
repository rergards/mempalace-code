#!/usr/bin/env python3
"""
architecture_guard.py — Stdlib AST import-boundary guard for mempalace-code layers.

Parses repository Python source with ``ast`` (never imports ``mempalace_code``
itself) and builds a file-level import graph scoped to ``mempalace_code/``,
``mempalace/``, and ``scripts/``. Tests are excluded from production-boundary
enforcement — negative cases use synthetic fixture roots instead.

Layers (see ``LAYER_RULES`` / ``LAYER_NAMES``):
    core, storage, mining, cli, mcp, scripts

Enforces the minimum architecture boundary: protected layers (``storage``,
``mining`` — which includes ``config.py`` and ``miner.py``/``mining/**``) must
not have a static runtime import path into ``cli`` or ``mcp``. Direct and
transitive violations are both reported, each
with the file-level hop path that produced them.

Import cycles among runtime (non-``TYPE_CHECKING``) edges are detected and
reported separately from boundary violations. Imports written under
``if TYPE_CHECKING:`` are collected as a separate, non-fatal review bucket —
they never count toward boundary violations or cycles.

Usage:
    python scripts/architecture_guard.py --root .
    python scripts/architecture_guard.py --root . --print-layers
"""

from __future__ import annotations

import argparse
import ast
import sys
from dataclasses import dataclass
from pathlib import Path

# ─── Public layer configuration ───────────────────────────────────────────────

LAYER_NAMES: tuple[str, ...] = (
    "core",
    "storage",
    "mining",
    "cli",
    "mcp",
    "scripts",
)

# Ordered, most-specific-first. Each entry: (layer, exact rel-posix files, path prefixes).
# A file that matches no rule falls back to "core".
LAYER_RULES: tuple[tuple[str, frozenset[str], tuple[str, ...]], ...] = (
    (
        "cli",
        frozenset({"mempalace_code/cli.py"}),
        ("mempalace_code/cli_commands/",),
    ),
    (
        "mcp",
        frozenset({"mempalace_code/mcp_server.py", "mempalace/mcp_server.py"}),
        ("mempalace_code/mcp/",),
    ),
    (
        "mining",
        frozenset({"mempalace_code/miner.py"}),
        ("mempalace_code/mining/",),
    ),
    (
        "storage",
        frozenset({"mempalace_code/storage.py", "mempalace_code/config.py"}),
        (),
    ),
    (
        "scripts",
        frozenset(),
        ("scripts/",),
    ),
)

# Directories scanned for the production import graph. Tests are intentionally
# excluded — negative cases build synthetic fixture roots instead.
SCAN_ROOTS: tuple[str, ...] = ("mempalace_code", "mempalace", "scripts")

# Layers whose modules must not have a static runtime import path into
# FORBIDDEN_TARGET_LAYERS. This is the minimum task boundary — "core" utility
# modules are classified but not enforced (e.g. mempalace_code/__init__.py
# legitimately re-exports the CLI entry point).
PROTECTED_LAYERS: frozenset[str] = frozenset({"storage", "mining"})
FORBIDDEN_TARGET_LAYERS: frozenset[str] = frozenset({"cli", "mcp"})


def repo_root() -> Path:
    """Repository root — the parent of this script's ``scripts/`` directory."""
    return Path(__file__).resolve().parent.parent


def classify_layer(rel_posix: str) -> str:
    """Classify a repo-relative POSIX path into one of LAYER_NAMES."""
    for layer, exact, prefixes in LAYER_RULES:
        if rel_posix in exact or any(rel_posix.startswith(prefix) for prefix in prefixes):
            return layer
    return "core"


# ─── Import graph data model ───────────────────────────────────────────────────


@dataclass(frozen=True)
class ImportEdge:
    source: str
    target: str
    lineno: int
    type_checking: bool


@dataclass(frozen=True)
class Violation:
    source: str
    target: str
    source_layer: str
    target_layer: str
    path: tuple[str, ...]


@dataclass(frozen=True)
class TypeCheckingImport:
    source: str
    target: str
    lineno: int


@dataclass(frozen=True)
class GuardResult:
    layers: dict[str, list[str]]
    violations: list[Violation]
    cycles: list[list[str]]
    type_checking_imports: list[TypeCheckingImport]

    @property
    def ok(self) -> bool:
        return not self.violations and not self.cycles


# ─── Module resolution ─────────────────────────────────────────────────────────


def _module_dotted_name(rel: Path) -> str:
    parts = list(rel.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _base_package(rel: Path) -> str:
    dotted = _module_dotted_name(rel)
    if rel.name == "__init__.py":
        return dotted
    parts = dotted.split(".")
    return ".".join(parts[:-1])


def _resolve_relative(base_package: str, level: int, module: str | None) -> str:
    parts = base_package.split(".") if base_package else []
    drop = level - 1
    if drop > 0:
        parts = parts[: max(len(parts) - drop, 0)]
    prefix = ".".join(parts)
    if module:
        return f"{prefix}.{module}" if prefix else module
    return prefix


def _is_type_checking_guard(test: ast.expr) -> bool:
    if isinstance(test, ast.Name) and test.id == "TYPE_CHECKING":
        return True
    return isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"


class _ImportVisitor(ast.NodeVisitor):
    """Collects file-level import edges, distinguishing TYPE_CHECKING-only imports.

    Static AST inspection only — a lazy import nested inside a function body is
    still visited, since it is still a real runtime import statement. Only
    ``importlib.import_module()`` calls (not ``Import``/``ImportFrom`` nodes)
    are invisible to this visitor.
    """

    def __init__(self, source_rel: str, base_package: str, manifest: dict[str, str]) -> None:
        self.source_rel = source_rel
        self.base_package = base_package
        self.manifest = manifest
        self.edges: list[ImportEdge] = []
        self._tc_depth = 0

    def visit_If(self, node: ast.If) -> None:
        guarded = _is_type_checking_guard(node.test)
        if guarded:
            self._tc_depth += 1
        for child in node.body:
            self.visit(child)
        if guarded:
            self._tc_depth -= 1
        for child in node.orelse:
            self.visit(child)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            target = self.manifest.get(alias.name)
            if target:
                self._add_edge(target, node.lineno)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.level:
            target_package = _resolve_relative(self.base_package, node.level, node.module)
        else:
            target_package = node.module or ""
        if not target_package:
            return

        if node.module:
            target_file = self.manifest.get(target_package)
            if target_file:
                self._add_edge(target_file, node.lineno)
            return

        added_any = False
        for alias in node.names:
            candidate = f"{target_package}.{alias.name}"
            target_file = self.manifest.get(candidate)
            if target_file:
                self._add_edge(target_file, node.lineno)
                added_any = True
        if not added_any:
            target_file = self.manifest.get(target_package)
            if target_file:
                self._add_edge(target_file, node.lineno)

    def _add_edge(self, target_rel: str, lineno: int) -> None:
        if target_rel == self.source_rel:
            return
        self.edges.append(ImportEdge(self.source_rel, target_rel, lineno, self._tc_depth > 0))


# ─── Graph construction ────────────────────────────────────────────────────────


def _collect_source_files(root: Path) -> list[Path]:
    files: set[Path] = set()
    for scan_root in SCAN_ROOTS:
        base = root / scan_root
        if base.is_dir():
            files.update(base.rglob("*.py"))
    return sorted(files)


def _shortest_paths_to_forbidden(
    source: str, graph: dict[str, list[str]], layer_of: dict[str, str]
) -> list[list[str]]:
    from collections import deque

    visited = {source}
    queue: deque[list[str]] = deque([[source]])
    found: list[list[str]] = []
    while queue:
        path = queue.popleft()
        node = path[-1]
        for nxt in graph.get(node, []):
            if nxt in visited:
                continue
            visited.add(nxt)
            new_path = path + [nxt]
            if layer_of.get(nxt) in FORBIDDEN_TARGET_LAYERS:
                found.append(new_path)
                continue
            queue.append(new_path)
    return found


def _find_cycles(graph: dict[str, list[str]]) -> list[list[str]]:
    color: dict[str, int] = {}
    stack: list[str] = []
    cycles: list[list[str]] = []

    def dfs(node: str) -> None:
        color[node] = 1
        stack.append(node)
        for nxt in graph.get(node, []):
            state = color.get(nxt, 0)
            if state == 0:
                dfs(nxt)
            elif state == 1:
                idx = stack.index(nxt)
                cycles.append(stack[idx:] + [nxt])
        stack.pop()
        color[node] = 2

    for node in sorted(graph):
        if color.get(node, 0) == 0:
            dfs(node)
    return cycles


def evaluate(root: Path) -> GuardResult:
    """Build the import graph for ``root`` and evaluate boundary/cycle rules."""
    root = root.resolve()
    files = _collect_source_files(root)

    rels: list[Path] = [f.relative_to(root) for f in files]
    manifest: dict[str, str] = {_module_dotted_name(rel): rel.as_posix() for rel in rels}

    layer_of: dict[str, str] = {}
    layers: dict[str, list[str]] = {name: [] for name in LAYER_NAMES}
    for rel in rels:
        rel_posix = rel.as_posix()
        layer = classify_layer(rel_posix)
        layer_of[rel_posix] = layer
        layers[layer].append(rel_posix)
    for name in layers:
        layers[name].sort()

    graph: dict[str, list[str]] = {}
    type_checking_imports: list[TypeCheckingImport] = []
    for rel in rels:
        rel_posix = rel.as_posix()
        source_path = root / rel
        tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(rel))
        visitor = _ImportVisitor(rel_posix, _base_package(rel), manifest)
        visitor.visit(tree)

        runtime_targets = []
        for edge in visitor.edges:
            if edge.type_checking:
                type_checking_imports.append(
                    TypeCheckingImport(edge.source, edge.target, edge.lineno)
                )
            else:
                runtime_targets.append(edge.target)
        graph[rel_posix] = sorted(set(runtime_targets))

    violations: list[Violation] = []
    for rel_posix in sorted(layer_of):
        layer = layer_of[rel_posix]
        if layer not in PROTECTED_LAYERS:
            continue
        for path in _shortest_paths_to_forbidden(rel_posix, graph, layer_of):
            violations.append(
                Violation(
                    source=rel_posix,
                    target=path[-1],
                    source_layer=layer,
                    target_layer=layer_of[path[-1]],
                    path=tuple(path),
                )
            )

    cycles = _find_cycles(graph)

    type_checking_imports.sort(key=lambda t: (t.source, t.target, t.lineno))

    return GuardResult(
        layers=layers,
        violations=violations,
        cycles=cycles,
        type_checking_imports=type_checking_imports,
    )


# ─── Reporting ──────────────────────────────────────────────────────────────────


def format_layers(result: GuardResult) -> str:
    lines: list[str] = []
    for name in LAYER_NAMES:
        files = result.layers.get(name, [])
        lines.append(f"{name} ({len(files)}):")
        for f in files:
            lines.append(f"  - {f}")
    return "\n".join(lines)


def format_report(result: GuardResult) -> str:
    lines: list[str] = []
    if result.violations:
        lines.append(f"Forbidden layer imports ({len(result.violations)}):")
        for v in result.violations:
            lines.append(f"  - {v.source_layer}:{v.source} -> {v.target_layer}:{v.target}")
            lines.append(f"      path: {' -> '.join(v.path)}")
    if result.cycles:
        lines.append(f"Import cycles ({len(result.cycles)}):")
        for cycle in result.cycles:
            lines.append(f"  - {' -> '.join(cycle)}")
    if result.type_checking_imports:
        lines.append(
            f"TYPE_CHECKING-only imports ({len(result.type_checking_imports)}) [review only]:"
        )
        for t in result.type_checking_imports:
            lines.append(f"  - {t.source}:{t.lineno} -> {t.target}")
    total_files = sum(len(v) for v in result.layers.values())
    if result.ok:
        lines.append(
            f"architecture-guard: OK ({total_files} files scanned, 0 boundary violations, 0 cycles)"
        )
    else:
        lines.append(
            f"architecture-guard: FAIL ({len(result.violations)} boundary violations, "
            f"{len(result.cycles)} cycles)"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Stdlib AST import-boundary guard for mempalace-code layers."
    )
    parser.add_argument(
        "--root", type=Path, default=repo_root(), help="Repository root to inspect."
    )
    parser.add_argument(
        "--print-layers",
        action="store_true",
        help="Print the resolved layer map (layer name -> matched file paths) and exit 0.",
    )
    args = parser.parse_args(argv)

    result = evaluate(args.root)

    if args.print_layers:
        print(format_layers(result))
        return 0

    print(format_report(result), file=sys.stderr if not result.ok else sys.stdout)
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
