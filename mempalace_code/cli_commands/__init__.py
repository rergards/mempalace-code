"""CLI command handler package for mempalace-code.

Each module owns a focused group of command handlers.  Import handler
functions from the relevant sub-module; do NOT import heavy runtime
dependencies (FastEmbed, ONNX Runtime, LanceDB, watcher) at module level.
"""
