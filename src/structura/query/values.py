"""Coercing and comparing the values a condition can carry.

Three kinds matter and they must not be compared as strings: dates, because
`raised<2026-01-01` has to mean what it says; integers, because `age>90` is
not a lexicographic question; and everything else, which is text.

Relative dates exist because the useful queries are relative. `due<today` and
`from:today to:+7d` are what a person actually asks; writing out today's date
by hand is how a saved view goes stale.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from .errors import QueryError

RELATIVE_RE = re.compile(r"^([+-])(\d+)([dwmy])$")
ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_UNITS = {"d": 1, "w": 7, "m": 30, "y": 365}

WORDS = {"today": 0, "tomorrow": 1, "yesterday": -1}


def parse_date(text: str, *, today: date | None = None) -> date | None:
    """A date literal, a relative offset, or a word. None if it is neither."""
    anchor = today or date.today()
    if text in WORDS:
        return anchor + timedelta(days=WORDS[text])
    match = RELATIVE_RE.match(text)
    if match:
        sign, count, unit = match.groups()
        days = int(count) * _UNITS[unit]
        return anchor + timedelta(days=days if sign == "+" else -days)
    if ISO_DATE_RE.match(text):
        try:
            return date.fromisoformat(text)
        except ValueError:
            return None
    return None


def coerce(text: str, *, today: date | None = None) -> Any:
    """The most specific type a written value can be read as."""
    parsed = parse_date(text, today=today)
    if parsed is not None:
        return parsed
    if text.lstrip("-").isdigit():
        return int(text)
    if text.lower() in ("true", "false"):
        return text.lower() == "true"
    return text


def as_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, str) and ISO_DATE_RE.match(value):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


def compare(left: Any, op: str, right: Any) -> bool:
    """Apply one comparison, choosing the comparison the values deserve.

    Equality on text is case-insensitive, because a command line is typed and
    `area:WWT` meaning nothing would be a poor joke. Ordering is not, because
    ordering only ever applies to dates and numbers here.
    """
    if op in (":", "="):
        return _equal(left, right)
    if op == "!=":
        return not _equal(left, right)

    if isinstance(left, list | tuple | set | frozenset):
        # Ordering a set of values against one value has no meaning worth
        # guessing at.
        return False

    left_date, right_date = as_date(left), as_date(right)
    if left_date is not None and right_date is not None:
        left, right = left_date, right_date
    elif isinstance(right, int) and not isinstance(left, int):
        try:
            left = int(left)
        except (TypeError, ValueError):
            return False

    if left is None or right is None:
        # A missing value is not greater or less than anything. Treating it as
        # zero would quietly file every undated task under "overdue".
        return False

    try:
        if op == ">":
            return left > right
        if op == ">=":
            return left >= right
        if op == "<":
            return left < right
        if op == "<=":
            return left <= right
    except TypeError:
        return False
    raise QueryError(f"unknown operator `{op}`")


def _equal(left: Any, right: Any) -> bool:
    # A multi-valued field matches when any of its values does. `tag:pressure`
    # on a document carrying three tags is a membership question, and the
    # alternative -- a special case per multi-valued field in every caller --
    # is how a query language grows warts.
    if isinstance(left, list | tuple | set | frozenset):
        return any(_equal(item, right) for item in left)
    if left is None:
        return right is None
    left_date, right_date = as_date(left), as_date(right)
    if left_date is not None and right_date is not None:
        return left_date == right_date
    if isinstance(left, bool) or isinstance(right, bool):
        return bool(left) == bool(right)
    if isinstance(left, int) and isinstance(right, int):
        return left == right
    return str(left).casefold() == str(right).casefold()


def days_since(value: Any, *, today: date | None = None) -> int | None:
    """Age in days, or None when there is no date to count from."""
    parsed = as_date(value)
    if parsed is None:
        return None
    return ((today or date.today()) - parsed).days
