#!/usr/bin/env python3
"""GitHub Release notes for a tag, taken from CHANGELOG.md.

The tag-triggered publish workflow passes this body to `gh release create`, which
appends GitHub's generated compare link. A recovery release follows a tag that
never published (v1.14.2 after the stopped v1.14.1), so its notes carry every
changelog section back to the previous *published* release, and the compare link
starts there too, never at the unpublished tag.

Stdlib-only — no project imports.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Collection

_RELEASE_HEADING = re.compile(r"^## (v\S+)\s+—", re.MULTILINE)


def changelog_release_notes(
    changelog: str, tag: str, published_tags: Collection[str]
) -> tuple[str, str | None]:
    """Return ``(body, notes_start_tag)`` for the GitHub Release of ``tag``.

    ``notes_start_tag`` is the newest release below ``tag`` in the changelog that
    has a published GitHub Release (``published_tags``). ``body`` runs from the
    ``## <tag> —`` heading down to, not including, that release's heading, so the
    sections of tagged-but-unpublished releases in between are carried along. With
    no published older release, the body is the ``tag`` section alone and there is
    no start tag. A changelog without a ``tag`` section gives an empty body.
    """
    headings = list(_RELEASE_HEADING.finditer(changelog))
    names = [heading.group(1) for heading in headings]
    if tag not in names:
        return "", None
    start = names.index(tag)
    older = range(start + 1, len(names))
    stop = next((i for i in older if names[i] in published_tags), None)
    end_index = stop if stop is not None else start + 1
    end = headings[end_index].start() if end_index < len(headings) else len(changelog)
    body = changelog[headings[start].start() : end].strip() + "\n"
    return body, names[stop] if stop is not None else None
