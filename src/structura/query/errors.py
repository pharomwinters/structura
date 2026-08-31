"""Query errors that point at the character that caused them.

A command line is read and retyped far more often than a source file, so an
error that says *where* is worth more than one that says what. Every error
here carries an offset into the input and renders a caret under it.
"""

from __future__ import annotations

from difflib import get_close_matches


class QueryError(Exception):
    """Anything wrong with a pipeline. Carries a position when it has one."""

    def __init__(self, message: str, source: str = "", offset: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.source = source
        self.offset = offset

    def render(self) -> str:
        """The message, and the input with a caret under the offending token."""
        if not self.source or self.offset is None:
            return self.message
        return f"{self.message}\n  {self.source}\n  {' ' * self.offset}^"

    def __str__(self) -> str:
        return self.render()


class ParseError(QueryError):
    """The text is not a pipeline."""


class TypeCheckError(QueryError):
    """The pipeline is well-formed but does not connect.

    Raised before anything runs. A stage that cannot accept what the one
    before it produces is a mistake worth catching at the prompt rather than
    halfway through an action.
    """


def did_you_mean(word: str, candidates: list[str], *, cutoff: float = 0.6) -> str:
    """` -- did you mean \\`x\\`?` when something is close, else empty."""
    matches = get_close_matches(word, candidates, n=1, cutoff=cutoff)
    return f" -- did you mean `{matches[0]}`?" if matches else ""
