"""Replay frozen MCP owners with inert lease/storage dependencies and disposable SQLite."""
import argparse
import ast
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import types


def extract(path, names, scope):
    tree = ast.parse(path.read_text())
    chosen = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in names]
    assert {node.name for node in chosen} == set(names)
    chosen.insert(0, ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0))
    exec(compile(ast.fix_missing_locations(ast.Module(body=chosen, type_ignores=[])), str(path), "exec"), scope)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    args = parser.parse_args()
    raw = Path(__file__).resolve().parents[1] / ".raw/mempalace-2026-10-02"
    raw.mkdir(parents=True, exist_ok=True)
    result = {}
    with tempfile.TemporaryDirectory(prefix="mcp-runtime-check-", dir=raw) as folder:
        scratch = Path(folder)
        palace = scratch / "palace"
        palace.mkdir()
        project = scratch / "project"
        project.mkdir()
        (project / "mempalace.yaml").write_text("project: inert\n")
        package = types.ModuleType("audit_mcp_source")
        package.__path__ = []
        sys.modules[package.__name__] = package
        errors = types.ModuleType("audit_mcp_source.errors")
        class InvalidArgumentError(Exception):
            def __init__(self, message, **kwargs):
                super().__init__(message)
        errors.InvalidArgumentError = InvalidArgumentError
        sys.modules[errors.__name__] = errors
        config = types.ModuleType("audit_mcp_source.config")
        config.expand_palace_path = lambda path: str(Path(path).resolve())
        config.DEFAULT_PALACE_PATH = str(palace)
        config.MempalaceConfig = lambda: types.SimpleNamespace(palace_path=str(palace))
        sys.modules[config.__name__] = config
        kg_path = args.source / "mempalace_code/knowledge_graph.py"
        spec = importlib.util.spec_from_file_location("audit_mcp_source.knowledge_graph", kg_path)
        kg = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = kg
        spec.loader.exec_module(kg)
        kg.DEFAULT_KG_PATH = str(scratch / "absent-legacy.sqlite3")
        runtime = types.ModuleType("audit_mcp_source.mcp.runtime")
        runtime.__package__ = "audit_mcp_source.mcp"
        rt = runtime.__dict__
        rt.update(os=os, _config=config.MempalaceConfig(), _kg=None,
                  no_palace_payload=lambda path: {"error": "no_palace", "palace_path": path})
        extract(args.source / "mempalace_code/mcp/runtime.py",
                ["NoPalaceError", "_palace_dir_exists", "_get_kg", "_mine_quiet", "_degraded_response"], rt)
        miner = types.ModuleType("audit_mcp_source.miner")
        miner.mine = lambda **kwargs: (_ for _ in ()).throw(AssertionError("Mine must not run under rejected lease"))
        sys.modules[miner.__name__] = miner
        class Busy(Exception):
            pass
        class RefusedLease:
            def __enter__(self):
                result["kg_exists_at_rejected_lease_entry"] = (palace / "knowledge_graph.sqlite3").is_file()
                raise Busy("inert lease rejection")
            def __exit__(self, *args):
                return False
        rt.update(palace_write_lease=lambda *args, **kwargs: RefusedLease(),
                  MCP_MINE_LEASE_WAIT_SECONDS=0,
                  logger=types.SimpleNamespace(info=lambda *args: None),
                  palace_busy_response=lambda exc: {"success": False, "hint": "Nothing was written."})
        write_scope = {"Path": Path, "runtime": runtime, "PalaceBusyError": Busy,
                       "InvalidArgumentError": InvalidArgumentError}
        extract(args.source / "mempalace_code/mcp/tools/write.py", ["tool_mine"], write_scope)
        result["kg_exists_before_call"] = (palace / "knowledge_graph.sqlite3").exists()
        result["refused_mine_response"] = write_scope["tool_mine"](str(project))
        result["kg_exists_after_refused_mine"] = (palace / "knowledge_graph.sqlite3").is_file()
        assert result["kg_exists_before_call"] is False
        assert result["kg_exists_at_rejected_lease_entry"] is True
        assert result["kg_exists_after_refused_mine"] is True
        assert result["refused_mine_response"]["success"] is False
        # Actual read-only storage owners, with DB open failure injected at the boundary.
        storage_tree = ast.parse((args.source / "mempalace_code/storage.py").read_text())
        store_class = next(n for n in storage_tree.body if isinstance(n, ast.ClassDef) and n.name == "LanceStore")
        methods = [n for n in store_class.body if isinstance(n, ast.FunctionDef) and n.name in {"_open_or_create", "count_by_pair"}]
        fixture_class = ast.ClassDef(name="FrozenReadStore", bases=[], keywords=[], body=methods, decorator_list=[])
        module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), fixture_class], type_ignores=[])
        scope = {"_LANCE_TABLE": "mempalace_drawers", "logger": types.SimpleNamespace(debug=lambda *args: None)}
        exec(compile(ast.fix_missing_locations(module), "frozen-storage-owners", "exec"), scope)
        fresh = scope["FrozenReadStore"]()
        fresh._read_only = True
        fresh._db = types.SimpleNamespace(open_table=lambda name: (_ for _ in ()).throw(OSError("corrupt table")))
        fresh._table = fresh._open_or_create(False)
        rt.update(open_store=lambda *args, **kwargs: fresh, PalaceReadError=OSError,
                  _degraded_hint=lambda: "health/repair required", _RETRY_HINT="Retry the call: the server has reopened the palace.")
        result["fresh_table_is_none"] = fresh._table is None
        result["unopenable_recovery"] = runtime._degraded_response(OSError("fragment missing"))
        assert fresh._table is None
        assert result["unopenable_recovery"]["hint"] == rt["_RETRY_HINT"]
        rt["open_store"] = lambda *args, **kwargs: (_ for _ in ()).throw(OSError("still broken"))
        result["raising_open_control"] = runtime._degraded_response(OSError("fragment missing"))
        assert result["raising_open_control"]["hint"] == "health/repair required"
        # Actual SQLite-backed cached KG versus the cold no-palace control.
        cached = runtime._get_kg()
        cached.stats()
        palace.rename(scratch / "removed-palace")
        result["cached_kg_returned_after_palace_removed"] = runtime._get_kg() is cached
        try:
            runtime._get_kg().stats()
        except Exception as error:
            result["cached_kg_error_type"] = type(error).__name__
        else:
            raise AssertionError("Expected SQLite failure after palace removal")
        rt["_kg"] = None
        try:
            runtime._get_kg()
        except runtime.NoPalaceError:
            result["cold_kg_control"] = "NoPalaceError"
        else:
            raise AssertionError("Cold access must reject missing palace")
        assert result["cached_kg_returned_after_palace_removed"] is True
        assert result["cached_kg_error_type"] == "OperationalError"
    print(json.dumps({"source": str(args.source), "checks": result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
