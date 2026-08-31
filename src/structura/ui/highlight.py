"""Syntax highlighting for the document pane.

The theme spec's roles are written for code; this surface is markdown whose
schema lives in the text itself. The mapping is by **meaning**, as the spec's
consistency rule requires, and it is the one stated in the design:

    frontmatter / task metadata key  -> Pink    (the schema's vocabulary is
                                                 its keyword set)
    closed-enum value                -> Cyan    (a value from a named set is
                                                 a type)
    date value                       -> Orange  (the constant role)
    free text, code span, fence      -> Yellow  (the string role)
    a value outside its enum         -> Red     (the error role)
    wikilink that resolves           -> Cyan
    wikilink that resolves to nothing-> Cyan, dotted underline
    heading                          -> Purple bold
    tag                              -> Purple
    task marker, checkbox, `Part of` -> Pink
    a completed task's `x`           -> Green
    everything else                  -> Foreground

Purple carries tags here. The spec gives that role to instance reserved words
-- `self`, `this`, `Self` -- which cannot occur in prose, so the slot is vacant
rather than contested. Inside a fenced code block nothing is re-coloured, so a
Rust snippet in a note still means what the spec says it means.

A placeholder is marked with an underline rather than a colour of its own,
because an unwritten link is a feature and not an error, and because the spec
forbids relying on colour alone.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat

from structura.core.links import strip_section
from structura.core.schema import Schema, default_schema
from structura.theme import Theme, load

# Block states, so a line knows what it is inside.
NORMAL = 0
FRONTMATTER = 1
FENCE = 2

DELIMITER_RE = re.compile(r"^---\s*$")
FENCE_RE = re.compile(r"^\s*(```|~~~)")
KEY_RE = re.compile(r"^(?P<key>[A-Za-z0-9_-]+)(?P<colon>:)(?P<rest>.*)$")
LIST_ITEM_RE = re.compile(r"^(\s*-\s+)(.*)$")
HEADING_RE = re.compile(r"^(#{1,6})\s+.*$")
WIKILINK_RE = re.compile(r"(!?)\[\[([^\]]+)\]\]")
TAG_RE = re.compile(r"(?<![\w/])#([A-Za-z][\w/-]*)")
CODE_SPAN_RE = re.compile(r"`[^`]+`")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
PART_OF_RE = re.compile(r"^Part of\b")
TABLE_PIPE_RE = re.compile(r"\|")
QUOTE_RE = re.compile(r"^\s*>")
META_KEY_RE = re.compile(r"\b(owner|raised|due|ref)(:)")


def _format(
    colour: str, *, bold: bool = False, italic: bool = False, underline: str = ""
) -> QTextCharFormat:
    fmt = QTextCharFormat()
    fmt.setForeground(QColor(colour))
    if bold:
        fmt.setFontWeight(QFont.Weight.Bold)
    if italic:
        fmt.setFontItalic(True)
    if underline == "dotted":
        fmt.setUnderlineStyle(QTextCharFormat.UnderlineStyle.DotLine)
        fmt.setUnderlineColor(QColor(colour))
    elif underline == "wave":
        fmt.setUnderlineStyle(QTextCharFormat.UnderlineStyle.WaveUnderline)
        fmt.setUnderlineColor(QColor(colour))
    return fmt


class MarkdownHighlighter(QSyntaxHighlighter):
    """Highlights one document against a theme and a schema.

    `resolves` answers "is this link target written?" -- normally backed by the
    index. It is a callable rather than the index itself so the highlighter can
    be tested, and so a workspace with no index yet still renders.
    """

    def __init__(
        self,
        document,
        theme: Theme | None = None,
        schema: Schema | None = None,
        resolves: Callable[[str], bool] | None = None,
    ) -> None:
        super().__init__(document)
        self.theme = theme or load()
        self.schema = schema or default_schema()
        self.resolves = resolves or (lambda _name: True)
        self._build()

    def set_theme(self, theme: Theme) -> None:
        self.theme = theme
        self._build()
        self.rehighlight()

    def set_resolver(self, resolves: Callable[[str], bool]) -> None:
        self.resolves = resolves
        self.rehighlight()

    def _build(self) -> None:
        e = self.theme.editor
        self.f_comment = _format(e.comment, italic=True)
        self.f_key = _format(e.pink)
        self.f_enum = _format(e.cyan)
        self.f_date = _format(e.orange)
        self.f_text = _format(e.yellow)
        self.f_bad = _format(e.red, underline="wave")
        self.f_link = _format(e.cyan)
        self.f_placeholder = _format(e.cyan, underline="dotted")
        self.f_heading = _format(e.purple, bold=True)
        self.f_tag = _format(e.purple)
        self.f_marker = _format(e.pink)
        self.f_done = _format(e.green)
        self.f_body = _format(e.foreground)
        self.f_code = _format(e.yellow)

    # --- the enum question --------------------------------------------

    def _value_format(self, key: str, value: str) -> QTextCharFormat:
        """A frontmatter value's role, decided by what the schema says it is."""
        stripped = value.strip().strip("\"'")
        if not stripped:
            return self.f_body
        allowed = self.schema.enums.get(key)
        if key == "type":
            allowed = self.schema.types
        if allowed is not None:
            return self.f_enum if stripped in allowed else self.f_bad
        if key == "status":
            # Only checkable once the type is known, which a single line does
            # not know. Left as a plain value here; `lint` is the backstop.
            return self.f_enum
        if DATE_RE.match(stripped):
            return self.f_date
        return self.f_text

    # --- the entry point ----------------------------------------------

    def highlightBlock(self, text: str) -> None:  # noqa: N802 - Qt's name
        previous = self.previousBlockState()
        if previous == -1:
            previous = NORMAL

        if previous == FENCE:
            self.setFormat(0, len(text), self.f_code)
            self.setCurrentBlockState(NORMAL if FENCE_RE.match(text) else FENCE)
            return

        if FENCE_RE.match(text):
            self.setFormat(0, len(text), self.f_comment)
            self.setCurrentBlockState(FENCE)
            return

        if previous == FRONTMATTER:
            if DELIMITER_RE.match(text):
                self.setFormat(0, len(text), self.f_comment)
                self.setCurrentBlockState(NORMAL)
                return
            self._frontmatter_line(text)
            self.setCurrentBlockState(FRONTMATTER)
            return

        # The opening delimiter is frontmatter only on the very first block.
        if DELIMITER_RE.match(text) and self.currentBlock().blockNumber() == 0:
            self.setFormat(0, len(text), self.f_comment)
            self.setCurrentBlockState(FRONTMATTER)
            return

        self.setCurrentBlockState(NORMAL)
        self._body_line(text)

    # --- frontmatter ---------------------------------------------------

    def _frontmatter_line(self, text: str) -> None:
        self.setFormat(0, len(text), self.f_body)

        item = LIST_ITEM_RE.match(text)
        if item:
            self.setFormat(0, len(item.group(1)), self.f_comment)
            self.setFormat(item.start(2), len(item.group(2)), self.f_text)
            self._mark_links(text)
            return

        match = KEY_RE.match(text)
        if not match:
            return
        key = match.group("key")
        self.setFormat(0, len(key) + 1, self.f_key)
        rest = match.group("rest")
        if rest.strip():
            offset = match.start("rest") + (len(rest) - len(rest.lstrip()))
            self.setFormat(offset, len(rest.strip()), self._value_format(key, rest))

        # A wikilink here is the trap the whole schema exists to prevent, and
        # `lint` reports it. Marking it as a link would make it look correct.
        for link in WIKILINK_RE.finditer(text):
            self.setFormat(link.start(), len(link.group()), self.f_bad)

    # --- body ----------------------------------------------------------

    def _body_line(self, text: str) -> None:
        self.setFormat(0, len(text), self.f_body)

        if HEADING_RE.match(text):
            self.setFormat(0, len(text), self.f_heading)
        elif QUOTE_RE.match(text):
            self.setFormat(0, len(text), self.f_comment)
        elif PART_OF_RE.match(text):
            self.setFormat(0, len("Part of"), self.f_marker)

        self._task_line(text)

        for pipe in TABLE_PIPE_RE.finditer(text):
            self.setFormat(pipe.start(), 1, self.f_comment)
        for span in CODE_SPAN_RE.finditer(text):
            self.setFormat(span.start(), len(span.group()), self.f_code)

        self._mark_links(text)

        marker = self.schema.markdown.task_marker
        for tag in TAG_RE.finditer(text):
            if tag.group(1) == marker:
                continue
            self.setFormat(tag.start(), len(tag.group()), self.f_tag)

    def _task_line(self, text: str) -> None:
        marker = self.schema.markdown.task_marker
        pattern = re.compile(rf"^(\s*-\s)(\[)([ xX])(\])(\s+)(#{re.escape(marker)})")
        match = pattern.match(text)
        if not match:
            return
        self.setFormat(match.start(1), len(match.group(1)), self.f_marker)
        self.setFormat(match.start(2), 1, self.f_marker)
        state = match.group(3)
        self.setFormat(match.start(3), 1, self.f_done if state.lower() == "x" else self.f_marker)
        self.setFormat(match.start(4), 1, self.f_marker)
        self.setFormat(match.start(6), len(match.group(6)), self.f_marker)

        for meta in META_KEY_RE.finditer(text, match.end()):
            self.setFormat(meta.start(), len(meta.group()), self.f_key)

    def _mark_links(self, text: str) -> None:
        for link in WIKILINK_RE.finditer(text):
            target = strip_section(link.group(2))
            resolved = self.resolves(target) if target else True
            self.setFormat(
                link.start(),
                len(link.group()),
                self.f_link if resolved else self.f_placeholder,
            )


def resolver_for(index) -> Callable[[str], bool]:
    """A cached `resolves` backed by the index.

    Cached because the highlighter asks per link per repaint, and a query per
    keystroke per link is how an editor comes to feel slow.
    """
    seen: dict[str, bool] = {}

    def resolves(name: str) -> bool:
        if name not in seen:
            try:
                seen[name] = index.resolve(name) is not None
            except Exception:  # pragma: no cover - highlighting must never raise
                seen[name] = True
        return seen[name]

    return resolves


_ = Qt  # imported for the enum namespace used by callers of this module
