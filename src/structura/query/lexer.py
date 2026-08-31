"""Turning a command line into tokens.

The grammar is deliberately the same `key:value` shape as a task line. The
workspace already has one metadata grammar and the application should not
teach a second.

    verb [positional] [key:value ...] [--flag] [| verb ...]

A value is a bare token, a `"quoted string"`, or a `[[wikilink]]`. Ordered
fields also take a comparison: `age>90`, `raised<2026-01-01`, `due<today`.

One rule keeps the whole thing unambiguous: **a key must look like an
identifier.** `10:30` is therefore a value and not a condition on a key named
`10`, and a quoted string is never split on an operator it happens to contain.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from .errors import ParseError

OPERATORS = (">=", "<=", "!=", ":", "=", ">", "<")
KEY_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*")
_QUOTES = "\"'"


class Kind(Enum):
    PIPE = "pipe"
    VALUE = "value"
    CONDITION = "condition"
    FLAG = "flag"


@dataclass(frozen=True)
class Value:
    """A literal, and how it was written.

    `quoted` and `wikilink` survive lexing because they change meaning: a
    quoted value is never re-split, and a wikilink is a link target rather
    than a word that happens to have brackets.
    """

    text: str
    offset: int
    quoted: bool = False
    wikilink: bool = False


@dataclass(frozen=True)
class Token:
    kind: Kind
    offset: int
    value: Value | None = None
    key: str | None = None
    op: str | None = None
    flag: str | None = None


def _read_value(text: str, i: int) -> tuple[Value, int]:
    """Read one value starting at `i`. Returns the value and the next index."""
    start = i

    if text[i] in _QUOTES:
        quote = text[i]
        i += 1
        chars: list[str] = []
        while i < len(text) and text[i] != quote:
            # A backslash escapes the quote character, so a search for a
            # literal quote is expressible.
            if text[i] == "\\" and i + 1 < len(text) and text[i + 1] == quote:
                chars.append(quote)
                i += 2
                continue
            chars.append(text[i])
            i += 1
        if i >= len(text):
            raise ParseError("unterminated quoted string", text, start)
        return Value("".join(chars), start, quoted=True), i + 1

    if text.startswith("[[", i):
        end = text.find("]]", i)
        if end == -1:
            raise ParseError("unterminated wikilink -- expected `]]`", text, start)
        return Value(text[i + 2 : end].strip(), start, wikilink=True), end + 2

    while i < len(text) and not text[i].isspace() and text[i] != "|":
        i += 1
    if i == start:
        raise ParseError("expected a value", text, start)
    return Value(text[start:i], start), i


def _match_operator(text: str, i: int) -> str | None:
    for op in OPERATORS:
        if text.startswith(op, i):
            return op
    return None


def tokenize(text: str) -> list[Token]:
    """Lex a command line. Raises `ParseError` with a position."""
    tokens: list[Token] = []
    i = 0

    while i < len(text):
        if text[i].isspace():
            i += 1
            continue

        start = i

        if text[i] == "|":
            tokens.append(Token(Kind.PIPE, start))
            i += 1
            continue

        if text.startswith("--", i):
            i += 2
            match = KEY_RE.match(text, i)
            if not match:
                raise ParseError("expected a flag name after `--`", text, start)
            name = match.group()
            i = match.end()
            if i < len(text) and text[i] == "=":
                value, i = _read_value(text, i + 1)
                tokens.append(Token(Kind.FLAG, start, value=value, flag=name))
            else:
                tokens.append(Token(Kind.FLAG, start, flag=name))
            continue

        # A condition, but only when the text really begins with an
        # identifier followed by an operator. Anything else is a value.
        key_match = KEY_RE.match(text, i)
        if key_match and text[i] not in _QUOTES:
            op = _match_operator(text, key_match.end())
            if op is not None:
                value, i = _read_value(text, key_match.end() + len(op))
                tokens.append(
                    Token(Kind.CONDITION, start, value=value, key=key_match.group(), op=op)
                )
                continue

        value, i = _read_value(text, start)
        tokens.append(Token(Kind.VALUE, start, value=value))

    return tokens
