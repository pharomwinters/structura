"""What flows between stages.

**This is the part that is not a shell.** A stage does not emit text; it emits
a typed set of rows, and each verb declares what it consumes and produces. A
pipeline is therefore checkable before it runs, and a bad one fails at the
prompt rather than halfway through an action.

A `Row` is a labelled mapping plus the object it came from. The mapping is
what `where`, `sort` and `table` work on, so plumbing verbs are generic over
every kind. The `ref` is what traversal verbs need -- `backlinks` has to get
from a row back to the document it stands for.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Result kinds. Strings rather than an enum so a store added later can
# introduce a kind without editing this file.
DOCUMENTS = "documents"
TASKS = "tasks"
LINKS = "links"
PLACEHOLDERS = "placeholders"
TEXT = "text"
VIEW = "view"

#: Accepted by a verb that works on any row kind, and returned by one that
#: passes its input kind through unchanged.
ANY = "any"
SAME = "same"

#: The kinds that are rows. `text` and `view` are outputs, not rows: they are
#: what a pipeline ends with. ANY means any of these and deliberately not
#: those, so `lint | table` and `find | table | sort title` fail at the prompt
#: rather than quietly rendering a rendering.
ROW_KINDS = frozenset({DOCUMENTS, TASKS, LINKS, PLACEHOLDERS})


@dataclass(frozen=True)
class Row:
    values: dict[str, Any]
    ref: Any = None

    def get(self, key: str, default: Any = None) -> Any:
        return self.values.get(key, default)


@dataclass
class Result:
    kind: str
    rows: list[Row] = field(default_factory=list)
    #: Rendered output, set by `table`, `list`, `tree` and the meta verbs.
    text: str | None = None
    #: Column order a render verb should prefer, when a stage has opinions.
    columns: tuple[str, ...] = ()
    #: Field to group rows under, set by `group`.
    group_by: str | None = None

    def __len__(self) -> int:
        return len(self.rows)

    def replace(self, rows: list[Row]) -> Result:
        """The same result shape with different rows. Used by plumbing verbs
        so a filter cannot silently drop a column preference or a grouping."""
        return Result(
            kind=self.kind,
            rows=rows,
            text=self.text,
            columns=self.columns,
            group_by=self.group_by,
        )


def text_result(text: str) -> Result:
    return Result(kind=TEXT, text=text)


#: The columns each kind carries. The type checker validates field names in
#: `where`, `sort`, `group`, `distinct` and `table` against these, so a typo
#: fails at the prompt instead of quietly matching nothing.
COLUMNS: dict[str, tuple[str, ...]] = {
    # `tag` and `tags` are the same value under two names: `tag:pressure`
    # reads correctly as a filter and `table tags` reads correctly as a
    # column. Carrying both is cheaper than a special case in the filter.
    DOCUMENTS: (
        "title",
        "type",
        "area",
        "status",
        "date",
        "age",
        "tag",
        "tags",
        "uid",
        "path",
        "parent",
    ),
    TASKS: (
        "description",
        "asset",
        "owner",
        "raised",
        "due",
        "age",
        "done",
        "source",
        "ref",
        "line",
        "path",
    ),
    LINKS: ("source", "target", "resolved", "embed", "line", "path"),
    PLACEHOLDERS: ("target", "inbound", "sources"),
}
