"""Rendering rows as text.

The render verbs produce a `view`, and a view in a headless REPL is text. In
phase 3 the same rows go to a pane instead, which is why formatting lives here
rather than inside the verbs: the pipeline decides *what*, the formatter
decides *how*, and only the second one changes when a window arrives.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from typing import Any

from .rows import Result, Row

DASH = "—"
MAX_WIDTH = 60


def cell(value: Any) -> str:
    if value is None or value == "":
        return DASH
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _columns(result: Result, requested: Iterable[str] | None) -> list[str]:
    if requested:
        return list(requested)
    if result.columns:
        return list(result.columns)
    seen: dict[str, None] = {}
    for row in result.rows:
        for key in row.values:
            seen.setdefault(key, None)
    return list(seen)


def _truncate(text: str, width: int) -> str:
    return text if len(text) <= width else text[: width - 1] + "…"


def table(result: Result, columns: Iterable[str] | None = None, *, width: int = MAX_WIDTH) -> str:
    """A markdown table, so a result can be pasted into a note unchanged."""
    cols = _columns(result, columns)
    if not cols:
        return "No columns to show.\n"
    if not result.rows:
        return "No rows.\n"

    groups = _grouped(result)
    out: list[str] = []
    for heading, rows in groups:
        if heading is not None:
            out.append(f"## {heading}\n")
        body = [[_truncate(cell(row.get(col)), width) for col in cols] for row in rows]
        widths = [
            max(len(col), *(len(r[i]) for r in body)) if body else len(col)
            for i, col in enumerate(cols)
        ]
        out.append("| " + " | ".join(c.ljust(w) for c, w in zip(cols, widths, strict=True)) + " |")
        out.append("| " + " | ".join("-" * w for w in widths) + " |")
        out += [
            "| " + " | ".join(v.ljust(w) for v, w in zip(r, widths, strict=True)) + " |"
            for r in body
        ]
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def listing(result: Result, field: str | None = None) -> str:
    """One row per line. The default field is the first column."""
    if not result.rows:
        return "No rows.\n"
    key = field or _columns(result, None)[0]
    out: list[str] = []
    for heading, rows in _grouped(result):
        if heading is not None:
            out.append(f"## {heading}")
        out += [f"- {cell(row.get(key))}" for row in rows]
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def tree(result: Result, *, label: str = "title", parent: str = "parent") -> str:
    """A link-neighbourhood tree.

    A terminal draws a tree well and a force-directed graph badly, and what
    the graph is actually used for -- what a note reaches and what reaches it
    -- is a tree query anyway.
    """
    if not result.rows:
        return "No rows.\n"

    children: dict[str | None, list[Row]] = {}
    known = {row.get(label) for row in result.rows}
    for row in result.rows:
        owner = row.get(parent)
        children.setdefault(owner if owner in known else None, []).append(row)

    lines: list[str] = []
    seen: set[str] = set()

    def emit(owner: str | None, depth: int) -> None:
        for row in sorted(children.get(owner, []), key=lambda r: str(r.get(label) or "")):
            name = row.get(label)
            if name in seen:
                continue
            seen.add(name)
            lines.append(f"{'  ' * depth}- {cell(name)}")
            emit(name, depth + 1)

    emit(None, 0)

    # A parent chain that forms a cycle is reachable from no root, so its
    # members would vanish silently. Report them instead.
    unreachable = [row for row in result.rows if row.get(label) not in seen]
    if unreachable:
        lines.append("")
        lines.append("Unreachable (cycle in parent chain):")
        lines += [f"- {cell(row.get(label))}" for row in unreachable]

    return "\n".join(lines) + "\n"


def _grouped(result: Result) -> list[tuple[str | None, list[Row]]]:
    if not result.group_by:
        return [(None, result.rows)]
    buckets: dict[str, list[Row]] = {}
    for row in result.rows:
        buckets.setdefault(cell(row.get(result.group_by)), []).append(row)
    return sorted(buckets.items(), key=lambda item: item[0])
