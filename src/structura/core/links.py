"""Wikilink text handling, shared by the index and the renderers.

A wikilink can carry two suffixes: `[[Note#Section]]` points into a heading,
and `[[Note|display text]]` shows something other than the target. Neither is
part of the note the link resolves to, and every consumer that forgets this
reports a real note as unwritten.
"""

from __future__ import annotations


def strip_section(link: str) -> str:
    """The resolvable note target: everything before a `#section` or
    `|display` suffix, whichever comes first."""
    return link.split("#", 1)[0].split("|", 1)[0].strip()


def link_section(link: str) -> str | None:
    """The `#section` a link points into, or None.

    Read from the part before any `|display` suffix, so a pipe character in
    the display text cannot be mistaken for the end of the section.
    """
    head = link.split("|", 1)[0]
    if "#" not in head:
        return None
    section = head.split("#", 1)[1].strip()
    return section or None
