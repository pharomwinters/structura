"""The document model: one record, whatever store it came from.

A document is a bag of named fields plus a body. What varies between stores is
only how those fields are spelled on disk -- YAML frontmatter, iCalendar
properties, vCard properties. Everything above `structura.stores` sees this
shape and nothing else, which is what lets a query span notes, events, and
contacts without knowing which is which.

`raw_text` is kept deliberately. Structura writes back only the bytes it
changed, and the only way to honour that is to still have the original bytes
when a save happens.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any


@dataclass
class Task:
    """An actionable line raised inside a document.

    The legacy vault spelled these `#item`; the design calls them tasks, and
    `source`/`source_path`/`line_no` are what let one be edited from a task
    view and written back to the line it came from.
    """

    description: str
    asset: str | None
    owner: str | None
    raised: date | None
    due: date | None
    ref: str | None
    done: bool
    source: str
    source_path: Path
    line_no: int


@dataclass
class Link:
    target: str
    line_no: int
    is_embed: bool = False


@dataclass
class Document:
    """One record in one store."""

    uid: str | None
    path: Path
    store: str
    dtype: str | None
    title: str
    fields: dict[str, Any] = field(default_factory=dict)
    body: str = ""
    raw_text: str = ""
    links: list[Link] = field(default_factory=list)
    tasks: list[Task] = field(default_factory=list)
    parents: list[str] = field(default_factory=list)
    frontmatter_error: str | None = None

    # The document text with fenced code blocks blanked out, line numbering
    # preserved -- exactly the text tasks were parsed from, so a line number
    # taken from it agrees with `Task.line_no`. The validator walks this to
    # find lines that MEANT to be tasks and failed to parse (legacy R39);
    # without it the validator can only inspect tasks that already parsed, and
    # a silently-dropped task is invisible to the one tool meant to see it.
    live_text: str = ""

    @property
    def link_targets(self) -> list[str]:
        return [link.target for link in self.links]
