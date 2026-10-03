"""Tests for scripts/release_notes.py (GitHub Release notes from CHANGELOG.md)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).parent.parent


def _load():
    spec = importlib.util.spec_from_file_location(
        "release_notes", ROOT / "scripts" / "release_notes.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["release_notes"] = module
    spec.loader.exec_module(module)
    return module


notes = _load()

CHANGELOG = """# Changelog

## Unreleased

- Pending entry that must never ship in release notes.

## v1.4.2 — 2026-09-21

Recovery release.

## v1.4.1 — 2026-09-20 (tagged, not published)

- Fix that shipped only in the recovery release.

## v1.4.0 — 2026-09-18

- Feature from the previous published release.

## v1.3.9 — 2026-09-01

- Older entry.
"""

PUBLISHED = {"v1.3.9", "v1.4.0"}


def test_recovery_release_notes_span_unpublished_tags_back_to_the_published_release():
    body, start_tag = notes.changelog_release_notes(CHANGELOG, "v1.4.2", PUBLISHED)

    assert start_tag == "v1.4.0", "the compare link must never start at the orphan v1.4.1"
    assert body.startswith("## v1.4.2 — 2026-09-21\n\nRecovery release.")
    assert "- Fix that shipped only in the recovery release.\n" in body
    assert body.endswith("- Fix that shipped only in the recovery release.\n")
    assert "## v1.4.0" not in body
    assert "Pending entry" not in body


def test_regular_release_notes_are_the_tag_section_alone():
    body, start_tag = notes.changelog_release_notes(CHANGELOG, "v1.4.0", PUBLISHED)

    assert start_tag == "v1.3.9"
    assert body == "## v1.4.0 — 2026-09-18\n\n- Feature from the previous published release.\n"


def test_without_an_older_published_release_the_notes_are_the_tag_section_alone():
    # The first release, or a changelog whose older sections were never published:
    # the body stops at the next heading and GitHub keeps its default compare range.
    assert notes.changelog_release_notes(CHANGELOG, "v1.3.9", PUBLISHED) == (
        "## v1.3.9 — 2026-09-01\n\n- Older entry.\n",
        None,
    )
    body, start_tag = notes.changelog_release_notes(CHANGELOG, "v1.4.1", {"v1.4.2"})
    assert start_tag is None, "a newer release never becomes the compare start"
    assert body == "## v1.4.1 — 2026-09-20 (tagged, not published)\n\n" + (
        "- Fix that shipped only in the recovery release.\n"
    )


def test_a_tag_without_a_changelog_section_gives_an_empty_body():
    assert notes.changelog_release_notes(CHANGELOG, "v9.9.9", PUBLISHED) == ("", None)


def test_the_repository_changelog_gives_the_current_release_a_body():
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    newest = notes._RELEASE_HEADING.search(changelog)
    assert newest is not None, "CHANGELOG.md has no `## vX.Y.Z — ` release heading"
    tag = newest.group(1)
    body, _ = notes.changelog_release_notes(changelog, tag, set())
    assert body.startswith(f"## {tag} — ")


def test_publish_creates_the_release_with_changelog_notes_from_the_last_published_tag():
    workflow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "publish.yml").read_text(encoding="utf-8")
    )
    run = next(
        step["run"]
        for step in workflow["jobs"]["github-release"]["steps"]
        if step.get("name") == "Create or reconcile the public GitHub Release"
    )

    assert "from scripts import release_notes" in run
    assert "release_notes.changelog_release_notes(" in run
    assert '"--exclude-drafts",' in run
    assert '"--exclude-pre-releases",' in run
    assert '("--notes-file", str(notes))' in run
    assert '("--notes-start-tag", start_tag)' in run
    assert '"--generate-notes",' in run
