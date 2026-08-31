"""The pipeline AST, and turning tokens into it."""

from __future__ import annotations

from dataclasses import dataclass, field

from .errors import ParseError
from .lexer import Kind, Token, Value, tokenize


@dataclass(frozen=True)
class Condition:
    key: str
    op: str
    value: Value
    offset: int


@dataclass(frozen=True)
class Stage:
    verb: str
    offset: int
    positionals: tuple[Value, ...] = ()
    conditions: tuple[Condition, ...] = ()
    flags: dict[str, Value | None] = field(default_factory=dict)

    def flag(self, name: str) -> bool:
        return name in self.flags

    def text(self, index: int = 0, default: str | None = None) -> str | None:
        """The nth positional as plain text."""
        if index < len(self.positionals):
            return self.positionals[index].text
        return default


@dataclass(frozen=True)
class Pipeline:
    stages: tuple[Stage, ...]
    source: str

    def __len__(self) -> int:
        return len(self.stages)


def parse(text: str) -> Pipeline:
    """Parse a command line into a pipeline. Raises `ParseError`."""
    tokens = tokenize(text)
    if not tokens:
        raise ParseError("empty pipeline", text, 0)

    groups: list[list[Token]] = [[]]
    for token in tokens:
        if token.kind is Kind.PIPE:
            groups.append([])
        else:
            groups[-1].append(token)

    stages: list[Stage] = []
    offset = 0
    for group in groups:
        if not group:
            # An empty stage is almost always a trailing pipe or a doubled
            # one, and saying which is more use than "syntax error".
            where = text.find("|", offset)
            raise ParseError(
                "empty stage -- a `|` must have a verb on both sides",
                text,
                where if where != -1 else len(text),
            )
        offset = group[0].offset
        stages.append(_stage(group, text))

    return Pipeline(tuple(stages), text)


def _stage(group: list[Token], source: str) -> Stage:
    head = group[0]
    if head.kind is not Kind.VALUE:
        raise ParseError("a stage must begin with a verb", source, head.offset)
    if head.value.quoted or head.value.wikilink:
        raise ParseError("a verb cannot be quoted or a wikilink", source, head.offset)

    positionals: list[Value] = []
    conditions: list[Condition] = []
    flags: dict[str, Value | None] = {}

    for token in group[1:]:
        if token.kind is Kind.VALUE:
            positionals.append(token.value)
        elif token.kind is Kind.CONDITION:
            conditions.append(Condition(token.key, token.op, token.value, token.offset))
        elif token.kind is Kind.FLAG:
            flags[token.flag] = token.value

    return Stage(
        verb=head.value.text,
        offset=head.offset,
        positionals=tuple(positionals),
        conditions=tuple(conditions),
        flags=flags,
    )
