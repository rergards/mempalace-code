"""Exercise actual reader and MCP pagination with inert indexed rows."""
import argparse
import ast
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import types


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    args = parser.parse_args()
    package = types.ModuleType("audit_reader_source")
    package.__path__ = [str((args.source / "mempalace_code").resolve())]
    sys.modules[package.__name__] = package
    spec = importlib.util.spec_from_file_location("audit_reader_source.reader", args.source / "mempalace_code/reader.py")
    reader = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = reader
    spec.loader.exec_module(reader)
    class IndexedRows:
        def __init__(self, paths):
            self.paths = paths
        def get(self, where=None, include=None, limit=10000, **kwargs):
            value = where["source_file"]
            allowed = value["$in"] if isinstance(value, dict) else [value]
            indexes = [i for i, path in enumerate(self.paths) if path in allowed][:limit]
            return {"ids": [str(i) for i in indexes], "documents": [f"indexed line {i}" for i in indexes],
                    "metadatas": [{"source_file": self.paths[i], "chunk_index": i, "line_start": i+1, "line_end": i+1} for i in indexes]}
        def count_by(self, column):
            return {path: self.paths.count(path) for path in set(self.paths)}
    store = IndexedRows(["/fixture/big.py"] * 10001)
    runtime = types.SimpleNamespace(_get_store=lambda: store)
    scope = {"__package__": "audit_reader_source.mcp.tools", "runtime": runtime,
             "FILE_CONTEXT_DEFAULT_LIMIT": 20, "FILE_CONTEXT_MAX_LIMIT": 100}
    tree = ast.parse((args.source / "mempalace_code/mcp/tools/search.py").read_text())
    owner = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "tool_file_context")
    module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), owner], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), "frozen-file-context", "exec"), scope)
    page = scope["tool_file_context"]("/fixture/big.py", limit=100, offset=9900)
    result = {"indexedChunks": len(store.paths), "reportedTotal": page["total"], "lastPageChunks": len(page["chunks"]),
              "nextOffset": page["next_offset"], "unreachableChunks": len(store.paths)-page["total"]}
    assert result == {"indexedChunks": 10001, "reportedTotal": 10000, "lastPageChunks": 100, "nextOffset": None, "unreachableChunks": 1}
    store.paths = ["/fixture/big.py"] * 9999
    control = scope["tool_file_context"]("/fixture/big.py", limit=100, offset=9900)
    assert control["total"] == 9999 and len(control["chunks"]) == 99 and control["next_offset"] is None
    result["belowCapControlTotal"] = control["total"]
    raw = Path(__file__).resolve().parents[1] / ".raw/mempalace-2026-10-02"
    raw.mkdir(parents=True, exist_ok=True)
    previous = Path.cwd()
    with tempfile.TemporaryDirectory(prefix="reader-contract-", dir=raw) as folder:
        scratch = Path(folder)
        first = str(scratch / "auth.py")
        second = str(scratch / "other/auth.py")
        store.paths = [first, second]
        try:
            os.chdir(scratch)
            chosen = reader.resolve_source_rows(store, "auth.py")
            assert isinstance(chosen, reader.SourceRows) and chosen.source_file == first
            neutral = scratch / "neutral"
            neutral.mkdir()
            os.chdir(neutral)
            ambiguous = reader.resolve_source_rows(store, "auth.py")
            assert ambiguous["error"] == "ambiguous_source"
        finally:
            os.chdir(previous)
        result["cwdExactPrecedenceObserved"] = True
        result["neutralCwdControl"] = ambiguous["error"]
    print(json.dumps({"source": str(args.source), "paginationDefectReproduced": True, "checks": result}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
