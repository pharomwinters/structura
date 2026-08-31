"""Structured validation results.

The legacy validator returned a list of human-readable strings, and the
acceptance gate for phase 0 is that Structura reports *exactly* that list for
the same content. So `Violation.message` holds the legacy string byte for
byte, and the structure -- code, path, line -- is added alongside it rather
than in place of it.

That ordering matters. Structure is what the UI needs to jump to a line and
what a future lint pane needs to group by rule; the message is what proves the
port did not quietly change a rule. Losing either one loses something.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Violation:
    code: str
    message: str
    path: Path | None = None
    line: int | None = None

    def __str__(self) -> str:
        return self.message


def messages(violations: list[Violation]) -> list[str]:
    """The legacy string list, for parity comparison."""
    return [v.message for v in violations]
