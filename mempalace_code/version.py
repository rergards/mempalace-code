"""Single source of truth for the MemPalace package version.

Reads from pyproject.toml in a source checkout, or package metadata when installed.
Falls back to a hardcoded value for direct execution without metadata.
"""

try:
    import tomllib
    from importlib.metadata import version
    from pathlib import Path

    _pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    if _pyproject.exists():
        __version__ = tomllib.loads(_pyproject.read_text(encoding="utf-8"))["project"]["version"]
    else:
        __version__ = version("mempalace-code")
except Exception:
    __version__ = "0.0.0-dev"
