"""Single source of truth for the MemPalace package version.

Reads from package metadata (pyproject.toml) when installed.
Falls back to a hardcoded value for editable installs or direct execution.
"""

try:
    from importlib.metadata import version

    __version__ = version("mempalace-code")
except Exception:
    __version__ = "0.0.0-dev"
