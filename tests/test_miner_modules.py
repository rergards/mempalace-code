"""Import-contract tests for the mining module split.

Verifies that mempalace_code.miner remains a stable compatibility surface
and that each mining sub-module owns the symbols it is responsible for.
"""

import inspect


def test_miner_compatibility_exports_existing_import_surface():
    """AC-1: All CLI/watcher/test-facing names remain importable from mempalace_code.miner."""
    import re

    from mempalace_code.miner import (
        # chunkers — boundary regexes and helpers
        EXTENSION_LANG_MAP,
        GO_BOUNDARY,
        HARD_MAX,
        INIT_MARKERS,
        KNOWN_FILENAMES,
        MIN_CHUNK,
        PROJECT_MARKERS,
        READABLE_EXTENSIONS,
        SKIP_DIRS,
        SKIP_FILENAMES,
        SWIFT_BOUNDARY,
        TARGET_MAX,
        TARGET_MIN,
        TS_BOUNDARY,
        GitignoreMatcher,
        ScanFilterRules,
        _build_csproj_room_map,
        _chunk_k8s_manifest,
        _detect_batch_size,
        _detect_sln_wing,
        _subtree_glob_prefix,
        adaptive_merge_split,
        add_drawers_batch,
        chunk_adaptive_lines,
        chunk_code,
        chunk_file,
        chunk_prose,
        derive_wing_name,
        detect_language,
        detect_projects,
        detect_room,
        # symbols
        extract_symbol,
        # kg_extract
        extract_type_relationships,
        get_batch_size,
        load_config,
        mine,
        parse_dotnet_project_file,
        parse_sln_file,
        parse_xaml_file,
        process_file,
        resolve_wing_for_project,
        scan_project,
        status,
    )

    # callables must be callable
    for name, obj in [
        ("mine", mine),
        ("scan_project", scan_project),
        ("detect_room", detect_room),
        ("detect_language", detect_language),
        ("chunk_file", chunk_file),
        ("chunk_code", chunk_code),
        ("chunk_prose", chunk_prose),
        ("chunk_adaptive_lines", chunk_adaptive_lines),
        ("adaptive_merge_split", adaptive_merge_split),
        ("extract_symbol", extract_symbol),
        ("get_batch_size", get_batch_size),
        ("add_drawers_batch", add_drawers_batch),
        ("process_file", process_file),
        ("status", status),
        ("detect_projects", detect_projects),
        ("derive_wing_name", derive_wing_name),
        ("resolve_wing_for_project", resolve_wing_for_project),
        ("load_config", load_config),
        ("parse_sln_file", parse_sln_file),
        ("parse_xaml_file", parse_xaml_file),
        ("parse_dotnet_project_file", parse_dotnet_project_file),
        ("extract_type_relationships", extract_type_relationships),
        ("_detect_batch_size", _detect_batch_size),
        ("_detect_sln_wing", _detect_sln_wing),
        ("_build_csproj_room_map", _build_csproj_room_map),
        ("_chunk_k8s_manifest", _chunk_k8s_manifest),
        ("_subtree_glob_prefix", _subtree_glob_prefix),
    ]:
        assert callable(obj), f"miner.{name} must be callable"

    # constants must be the right type
    assert isinstance(MIN_CHUNK, int)
    assert isinstance(TARGET_MIN, int)
    assert isinstance(TARGET_MAX, int)
    assert isinstance(HARD_MAX, int)
    assert isinstance(SKIP_DIRS, (set, frozenset))
    assert isinstance(SKIP_FILENAMES, (set, frozenset))
    assert isinstance(PROJECT_MARKERS, frozenset)
    assert isinstance(INIT_MARKERS, frozenset)
    assert isinstance(EXTENSION_LANG_MAP, dict)
    assert isinstance(KNOWN_FILENAMES, (set, frozenset))
    assert isinstance(READABLE_EXTENSIONS, (set, frozenset))
    assert isinstance(SWIFT_BOUNDARY, re.Pattern)
    assert isinstance(TS_BOUNDARY, re.Pattern)
    assert isinstance(GO_BOUNDARY, re.Pattern)

    # ScanFilterRules must be a NamedTuple-like class
    assert inspect.isclass(GitignoreMatcher)
    assert hasattr(ScanFilterRules, "_fields")


def test_miner_shim_imports_from_mining_submodules():
    """Each name on mempalace_code.miner actually comes from a mining.* sub-module."""
    import mempalace_code.miner as miner_shim
    import mempalace_code.mining.batching as batching_mod
    import mempalace_code.mining.chunkers as chunkers_mod
    import mempalace_code.mining.kg_extract as kg_mod
    import mempalace_code.mining.languages as lang_mod
    import mempalace_code.mining.orchestrator as orch_mod
    import mempalace_code.mining.projects as proj_mod
    import mempalace_code.mining.scanner as scanner_mod
    import mempalace_code.mining.symbols as symbols_mod

    # Verify identity: shim exports are the same objects as owning module exports
    assert miner_shim.mine is orch_mod.mine
    assert miner_shim.scan_project is scanner_mod.scan_project
    assert miner_shim.detect_language is lang_mod.detect_language
    assert miner_shim.chunk_file is chunkers_mod.chunk_file
    assert miner_shim.extract_symbol is symbols_mod.extract_symbol
    assert miner_shim.get_batch_size is batching_mod.get_batch_size
    assert miner_shim.add_drawers_batch is orch_mod.add_drawers_batch
    assert miner_shim.detect_projects is proj_mod.detect_projects
    assert miner_shim.parse_sln_file is kg_mod.parse_sln_file


def test_mining_package_is_internal():
    """mining sub-modules are importable but miner.py is the stable public surface."""
    import mempalace_code.mining.batching
    import mempalace_code.mining.chunkers
    import mempalace_code.mining.kg_extract
    import mempalace_code.mining.languages
    import mempalace_code.mining.orchestrator
    import mempalace_code.mining.projects
    import mempalace_code.mining.scanner
    import mempalace_code.mining.symbols

    # Each sub-module has the right module name
    assert mempalace_code.mining.batching.__name__ == "mempalace_code.mining.batching"
    assert mempalace_code.mining.scanner.__name__ == "mempalace_code.mining.scanner"
    assert mempalace_code.mining.orchestrator.__name__ == "mempalace_code.mining.orchestrator"


def test_scanner_module_owns_scan_filter_rules():
    """ScanFilterRules is defined in the scanner module, not the shim."""
    from mempalace_code.mining.scanner import ScanFilterRules

    assert hasattr(ScanFilterRules, "_fields")
    assert "skip_dirs" in ScanFilterRules._fields
    assert "skip_files" in ScanFilterRules._fields
    assert "skip_globs" in ScanFilterRules._fields


def test_batching_module_owns_batch_size_cache():
    """_batch_size cache variable lives in mining.batching, not the miner shim."""
    import mempalace_code.mining.batching as batching_mod

    assert hasattr(batching_mod, "_batch_size")
    # The shim does NOT have a _batch_size attribute
    import mempalace_code.miner as miner_shim

    assert not hasattr(miner_shim, "_batch_size")


def test_orchestrator_owns_mine_function():
    """mine() is defined in mining.orchestrator."""
    from mempalace_code.mining.orchestrator import mine

    assert callable(mine)
    sig = inspect.signature(mine)
    assert "project_dir" in sig.parameters
    assert "palace_path" in sig.parameters
    assert "kg" in sig.parameters


def test_projects_module_owns_detect_room():
    """detect_room() is defined in mining.projects."""
    from mempalace_code.mining.projects import detect_room

    assert callable(detect_room)
    sig = inspect.signature(detect_room)
    assert "filepath" in sig.parameters
    assert "rooms" in sig.parameters


def test_chunkers_module_owns_chunk_file():
    """chunk_file() is defined in mining.chunkers and returns chunk dicts."""
    from mempalace_code.mining.chunkers import MIN_CHUNK, chunk_file

    content = "def foo():\n    return 1\n\n\ndef bar():\n    return 2\n" * 10
    chunks = chunk_file(content, ".py", "test.py", language="python")
    assert isinstance(chunks, list)
    assert len(chunks) > 0
    source_lines = content.split("\n")
    for chunk in chunks:
        assert "content" in chunk
        assert "chunk_index" in chunk
        assert len(chunk["content"]) <= MIN_CHUNK * 40
        span = source_lines[chunk["line_start"] - 1 : chunk["line_end"]]
        assert chunk["content"] == "\n".join(span)
