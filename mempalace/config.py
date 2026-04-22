"""
MemPalace configuration system.

Priority: env vars > config file (~/.mempalace/config.json) > defaults
"""

import json
import os
from pathlib import Path

DEFAULT_PALACE_PATH = os.path.expanduser("~/.mempalace/palace")
DEFAULT_COLLECTION_NAME = "mempalace_drawers"
DEFAULT_SCAN_SKIP_DIRS = [".kotlin-lsp"]
DEFAULT_SCAN_SKIP_FILES = ["workspace.json"]
DEFAULT_SCAN_SKIP_GLOBS = []

# Storage safety defaults
DEFAULT_OPTIMIZE_AFTER_MINE = True  # Set False to disable auto-compaction
DEFAULT_BACKUP_BEFORE_OPTIMIZE = True  # Auto-backup before risky operations (on by default)
DEFAULT_BACKUP_SCHEDULE = "off"  # Scheduled backup frequency: off|daily|weekly|hourly

DEFAULT_TOPIC_WINGS = [
    "emotions",
    "consciousness",
    "memory",
    "technical",
    "identity",
    "family",
    "creative",
]

DEFAULT_HALL_KEYWORDS = {
    "emotions": [
        "scared",
        "afraid",
        "worried",
        "happy",
        "sad",
        "love",
        "hate",
        "feel",
        "cry",
        "tears",
    ],
    "consciousness": [
        "consciousness",
        "conscious",
        "aware",
        "real",
        "genuine",
        "soul",
        "exist",
        "alive",
    ],
    "memory": ["memory", "remember", "forget", "recall", "archive", "palace", "store"],
    "technical": [
        "code",
        "python",
        "script",
        "bug",
        "error",
        "function",
        "api",
        "database",
        "server",
    ],
    "identity": ["identity", "name", "who am i", "persona", "self"],
    "family": ["family", "kids", "children", "daughter", "son", "parent", "mother", "father"],
    "creative": ["game", "gameplay", "player", "app", "design", "art", "music", "story"],
}


class MempalaceConfig:
    """Configuration manager for MemPalace.

    Load order: env vars > config file > defaults.
    """

    def __init__(self, config_dir=None):
        """Initialize config.

        Args:
            config_dir: Override config directory (useful for testing).
                        Defaults to ~/.mempalace.
        """
        self._config_dir = (
            Path(config_dir) if config_dir else Path(os.path.expanduser("~/.mempalace"))
        )
        self._config_file = self._config_dir / "config.json"
        self._people_map_file = self._config_dir / "people_map.json"
        self._file_config = {}

        if self._config_file.exists():
            try:
                with open(self._config_file, "r") as f:
                    self._file_config = json.load(f)
            except (json.JSONDecodeError, OSError):
                self._file_config = {}

    @property
    def palace_path(self):
        """Path to the memory palace data directory."""
        env_val = os.environ.get("MEMPALACE_PALACE_PATH") or os.environ.get("MEMPAL_PALACE_PATH")
        if env_val:
            return env_val
        return self._file_config.get("palace_path", DEFAULT_PALACE_PATH)

    @property
    def collection_name(self):
        """ChromaDB collection name."""
        return self._file_config.get("collection_name", DEFAULT_COLLECTION_NAME)

    def _merged_list_config(self, key: str, defaults: list[str]) -> list[str]:
        """Return a stable de-duplicated list from defaults plus config file additions."""
        merged = list(defaults)
        raw = self._file_config.get(key, [])
        if isinstance(raw, str):
            raw = [raw]
        if not isinstance(raw, list):
            return merged

        for value in raw:
            if not isinstance(value, str):
                continue
            candidate = value.strip()
            if candidate and candidate not in merged:
                merged.append(candidate)
        return merged

    @property
    def scan_skip_dirs(self):
        """Directory names excluded from mining/watch across all projects."""
        return self._merged_list_config("scan_skip_dirs", DEFAULT_SCAN_SKIP_DIRS)

    @property
    def scan_skip_files(self):
        """Base filenames excluded from mining/watch across all projects."""
        return self._merged_list_config("scan_skip_files", DEFAULT_SCAN_SKIP_FILES)

    @property
    def scan_skip_globs(self):
        """Project-relative glob patterns excluded from mining/watch across all projects."""
        return self._merged_list_config("scan_skip_globs", DEFAULT_SCAN_SKIP_GLOBS)

    @property
    def people_map(self):
        """Mapping of name variants to canonical names."""
        if self._people_map_file.exists():
            try:
                with open(self._people_map_file, "r") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                pass
        return self._file_config.get("people_map", {})

    @property
    def topic_wings(self):
        """List of topic wing names."""
        return self._file_config.get("topic_wings", DEFAULT_TOPIC_WINGS)

    @property
    def hall_keywords(self):
        """Mapping of hall names to keyword lists."""
        return self._file_config.get("hall_keywords", DEFAULT_HALL_KEYWORDS)

    @property
    def optimize_after_mine(self):
        """Whether to run optimize() after mining. Disable to prevent compaction corruption."""
        env_val = os.environ.get("MEMPALACE_OPTIMIZE_AFTER_MINE")
        if env_val is not None:
            return env_val.lower() in ("1", "true", "yes")
        return self._file_config.get("optimize_after_mine", DEFAULT_OPTIMIZE_AFTER_MINE)

    @property
    def backup_before_optimize(self):
        """Whether to create a backup before optimize(). On by default.

        Priority: MEMPALACE_AUTO_BACKUP_BEFORE_OPTIMIZE env > MEMPALACE_BACKUP_BEFORE_OPTIMIZE env
                  > auto_backup_before_optimize file key > backup_before_optimize file key > default.
        """
        # auto_ env takes highest precedence (AC-12)
        auto_env = os.environ.get("MEMPALACE_AUTO_BACKUP_BEFORE_OPTIMIZE")
        if auto_env is not None:
            return auto_env.lower() in ("1", "true", "yes")
        # legacy env key
        env_val = os.environ.get("MEMPALACE_BACKUP_BEFORE_OPTIMIZE")
        if env_val is not None:
            return env_val.lower() in ("1", "true", "yes")
        # auto_ file key takes precedence over legacy file key
        if "auto_backup_before_optimize" in self._file_config:
            return bool(self._file_config["auto_backup_before_optimize"])
        return self._file_config.get("backup_before_optimize", DEFAULT_BACKUP_BEFORE_OPTIMIZE)

    @property
    def auto_backup_before_optimize(self):
        """Preferred alias for backup_before_optimize. Returns the same value."""
        return self.backup_before_optimize

    @property
    def backup_schedule(self):
        """Scheduled backup frequency: off | daily | weekly | hourly."""
        env_val = os.environ.get("MEMPALACE_BACKUP_SCHEDULE")
        if env_val is not None:
            return env_val.lower()
        return self._file_config.get("backup_schedule", DEFAULT_BACKUP_SCHEDULE)

    def init(self):
        """Create config directory and write default config.json if it doesn't exist."""
        self._config_dir.mkdir(parents=True, exist_ok=True)
        if not self._config_file.exists():
            default_config = {
                "palace_path": DEFAULT_PALACE_PATH,
                "collection_name": DEFAULT_COLLECTION_NAME,
                "scan_skip_dirs": DEFAULT_SCAN_SKIP_DIRS,
                "scan_skip_files": DEFAULT_SCAN_SKIP_FILES,
                "scan_skip_globs": DEFAULT_SCAN_SKIP_GLOBS,
                "topic_wings": DEFAULT_TOPIC_WINGS,
                "hall_keywords": DEFAULT_HALL_KEYWORDS,
            }
            with open(self._config_file, "w") as f:
                json.dump(default_config, f, indent=2)
        return self._config_file

    def save_people_map(self, people_map):
        """Write people_map.json to config directory.

        Args:
            people_map: Dict mapping name variants to canonical names.
        """
        self._config_dir.mkdir(parents=True, exist_ok=True)
        with open(self._people_map_file, "w") as f:
            json.dump(people_map, f, indent=2)
        return self._people_map_file
