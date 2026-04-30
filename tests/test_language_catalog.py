"""Contract tests for shared language catalog metadata."""

from mempalace import language_catalog as catalog
from mempalace import miner


def test_catalog_preserves_current_detection_labels():
    must_preserve = {
        "python",
        "javascript",
        "jsx",
        "typescript",
        "tsx",
        "go",
        "rust",
        "ruby",
        "java",
        "kotlin",
        "csharp",
        "fsharp",
        "vbnet",
        "swift",
        "xml",
        "dotnet-solution",
        "xaml",
        "shell",
        "sql",
        "markdown",
        "text",
        "json",
        "yaml",
        "toml",
        "html",
        "css",
        "csv",
        "c",
        "cpp",
        "php",
        "scala",
        "dart",
        "terraform",
        "hcl",
        "gotemplate",
        "jinja2",
        "conf",
        "ini",
        "make",
        "dockerfile",
        "kubernetes",
        "perl",
    }

    assert must_preserve <= catalog.detected_languages()
    assert catalog.extension_language_map() == miner.EXTENSION_LANG_MAP
    assert catalog.filename_language_map() == miner.FILENAME_LANG_MAP
    assert catalog.known_filenames() == miner.KNOWN_FILENAMES
    assert catalog.readable_extensions() == miner.READABLE_EXTENSIONS
    assert list(catalog.shebang_patterns()) == miner.SHEBANG_PATTERNS


def test_catalog_keeps_non_extension_boundaries_explicit():
    extension_map = catalog.extension_language_map()
    filename_map = catalog.filename_language_map()
    detector_only = catalog.detected_languages() - catalog.searchable_languages()

    assert filename_map == {
        "Dockerfile": "dockerfile",
        "Containerfile": "dockerfile",
        "Makefile": "make",
        "GNUmakefile": "make",
        "Vagrantfile": "ruby",
    }
    assert all(filename not in extension_map for filename in filename_map)
    assert "kubernetes" in catalog.searchable_languages()
    assert "kubernetes" in catalog.detected_languages()
    assert "kubernetes" not in extension_map.values()
    assert {"xml", "perl", "kotlin"} <= detector_only
    assert not any(
        hasattr(catalog, name)
        for name in ("SCAN_EXCLUDE_CONFIG", "SCAN_EXCLUDES", "SCAN_EXCLUDE_PATTERNS")
    )


def test_catalog_readable_and_searchable_sets_stay_in_sync():
    extension_map = catalog.extension_language_map()

    assert set(extension_map) <= catalog.readable_extensions()
    assert not catalog.readable_extensions() - set(extension_map)
    assert catalog.searchable_languages() <= catalog.detected_languages()


def test_catalog_helpers_return_independent_containers():
    extension_map = catalog.extension_language_map()
    extension_map[".zzz"] = "zlang"
    assert ".zzz" not in catalog.extension_language_map()

    filename_map = catalog.filename_language_map()
    filename_map["Justfile"] = "make"
    assert "Justfile" not in catalog.filename_language_map()

    filenames = catalog.known_filenames()
    filenames.add("Justfile")
    assert "Justfile" not in catalog.known_filenames()

    readable = catalog.readable_extensions()
    readable.add(".zzz")
    assert ".zzz" not in catalog.readable_extensions()

    searchable = catalog.searchable_languages()
    searchable.add("zlang")
    assert "zlang" not in catalog.searchable_languages()


def test_searchable_language_helpers_are_sorted_and_parseable():
    labels = catalog.sorted_searchable_languages()
    csv = catalog.searchable_language_csv()

    assert labels == tuple(sorted(catalog.searchable_languages()))
    assert [part.strip() for part in csv.split(",")] == list(labels)
    assert catalog.code_search_language_description().endswith(csv)
