"""Paths as they are shown, rather than as the platform spells them.

Every path that reaches a person or a file goes through here, and comes out
with forward slashes on every platform. That is not cosmetic:

- Export parity is a gate. A register rendered on Windows and one rendered on
  Linux must be the same bytes, and `2-Notes\Alpha.md` versus
  `2-Notes/Alpha.md` is a difference in the output.
- A saved view is tracked in git and shared between machines. A `path` column
  that changes shape depending on who ran it is a diff nobody made.
- Wikilinks and markdown links are forward-slashed already, so a path column
  that is not looks like a different kind of thing than it is.

The index still stores the platform's own absolute paths; this is only for
display and for anything written into a document.
"""

from __future__ import annotations

import os
from pathlib import Path


def display(path: Path | str) -> str:
    """A path as it should be shown: forward slashes, no drive gymnastics."""
    return str(path).replace(os.sep, "/") if os.sep != "/" else str(path)


def relative_display(path: Path | str, root: Path | str) -> str:
    """`path` relative to `root`, forward-slashed, falling back to the whole
    path when it lies outside.

    A string prefix test rather than `Path.relative_to`: the latter parses
    both paths, and doing it per row was the largest single cost in a query
    over a large workspace.
    """
    prefix = f"{root}{os.sep}"
    text = str(path)
    return display(text[len(prefix) :] if text.startswith(prefix) else text)
