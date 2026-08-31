"""Parse a markdown workspace into documents and tasks.

Ported from the legacy `vaultlib` with its rules intact. Every regex and every
guard here represents a bug found the hard way against real content, and the
ruling numbers in the comments (R9, R10, R13, R21, R31, R36, R39) are the
record of that. Rewriting this module from the grammar alone would be
volunteering to find them all again.

Two things changed in the port and nothing else did:

- The task marker is configurable, because the design calls these tasks and a
  workspace should be able to say `#task` without a migration. It defaults to
  the legacy `item`, so existing content parses unchanged.
- Wikilinks became `Link` objects carrying a file-relative line number, so the
  index can point at one. The set of links found is identical.

Relationships live in the body, never in frontmatter -- markdown tooling does
not resolve wikilinks inside YAML, so a link there is invisible to everything
that reads the vault. The validator enforces that; this module simply does not
look for links anywhere but the body.
"""

from __future__ import annotations

import re
from datetime import date
from functools import lru_cache
from pathlib import Path

import yaml

from structura.core.document import Document, Link, Task
from structura.core.uid import is_uid

STORE_NAME = "markdown"

FRONTMATTER_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n?(.*)\Z", re.DOTALL)
WIKILINK_RE = re.compile(r"(!?)\[\[([^\]]+)\]\]")
META_PAIR_RE = re.compile(r"\b(owner|raised|due|ref):(\[\[[^\]]+\]\]|\S+)")
# Metadata is the TRAILING run of one-or-more key:value pairs at the end of
# the line. A colon anywhere before that run -- e.g. "ref:" or "owner:" used
# as ordinary English words in the free-text description -- is therefore never
# mistaken for a key (R9). The run may start either at the very beginning of
# the remainder (no description at all, e.g. a task with no asset) or after
# whitespace -- never mid-word -- so a leading key is not missed when there is
# nothing before it (R9 regression, round 2).
META_RUN_RE = re.compile(
    r"(?<!\S)(?:owner|raised|due|ref):(?:\[\[[^\]]+\]\]|\S+)"
    r"(?:\s+(?:owner|raised|due|ref):(?:\[\[[^\]]+\]\]|\S+))*\s*$"
)
# One asset may have more than one parent -- e.g. a shared component fed by two
# machines -- so every "Part of" line in the body is collected, not just the
# first (findall, not search). `Part of` states membership for any document,
# not only an asset's place in the equipment tree: a person note uses it for
# the departments, crews and committees they belong to alongside their
# employer.
PARENT_RE = re.compile(r"^Part of\s+\[\[([^\]]+)\]\]", re.MULTILINE)
FENCE_RE = re.compile(r"^\s*(```|~~~)")
# An inline code span: one or more backticks, anything, the same run again.
# Used to hide a task marker written as prose from the near-miss scan (R39).
INLINE_CODE_RE = re.compile(r"(`+)(?:(?!\1).)*\1", re.DOTALL)


class Grammar:
    """The task-line grammar for one marker word.

    Compiled once per marker and cached, because the near-miss scan in the
    validator runs `task_re` against every line of every document.
    """

    __slots__ = ("marker", "task_re", "description")

    def __init__(self, marker: str) -> None:
        self.marker = marker
        self.task_re = re.compile(
            rf"^\s*-\s\[(?P<state>[ xX])\]\s+#{re.escape(marker)}\s+(?P<rest>.+?)\s*$"
        )
        # Spelled out for the near-miss violation message, and kept next to
        # the regex so the two cannot drift apart.
        self.description = (
            f"- [ ] #{marker} <description> [[Asset]] owner:[[Person or Org]] raised:YYYY-MM-DD"
        )


@lru_cache(maxsize=8)
def grammar(marker: str = "item") -> Grammar:
    return Grammar(marker)


def split_frontmatter(text: str) -> tuple[dict, str]:
    """Return (fields, body). Missing or invalid frontmatter yields ({}, text)."""
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    try:
        props = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError:
        return {}, match.group(2)
    if not isinstance(props, dict):
        return {}, match.group(2)
    return props, match.group(2)


def frontmatter_error(text: str) -> str | None:
    """The YAML error message if frontmatter is present but fails to parse.

    `split_frontmatter` swallows YAMLError and returns ({}, body) so callers
    always get a body to work with; that makes malformed frontmatter
    indistinguishable from absent frontmatter. This recovers the signal
    `split_frontmatter` intentionally discards, so the validator can report a
    parse failure distinctly (R10) instead of burying it under four misleading
    missing-key violations.
    """
    match = FRONTMATTER_RE.match(text)
    if not match:
        return None
    try:
        yaml.safe_load(match.group(1))
    except yaml.YAMLError as exc:
        return str(exc)
    return None


def body_line_offset(text: str) -> int:
    """Lines consumed by the frontmatter block, so body line numbers can be
    reported relative to the file the author is looking at."""
    match = FRONTMATTER_RE.match(text)
    return text[: match.start(2)].count("\n") if match else 0


def strip_code_fences(text: str) -> str:
    """Blank out fenced code blocks, preserving line numbering.

    Documentation notes show example task lines and wikilinks inside fences.
    Without this, a README's own grammar example is indexed as real open work.
    """
    out: list[str] = []
    in_fence = False
    for line in text.splitlines():
        if FENCE_RE.match(line):
            in_fence = not in_fence
            out.append("")
            continue
        out.append("" if in_fence else line)
    return "\n".join(out)


def strip_inline_code(text: str) -> str:
    """Remove inline code spans (`` `like this` ``), keeping everything else.

    The near-miss scan flags any line that mentions the task marker and does
    not parse as one. Notes that legitimately discuss the marker in running
    prose write it backticked, and flagging those would be a false positive on
    the workspace's own documentation (R39).
    """
    return INLINE_CODE_RE.sub("", text)


def duplicate_meta_keys(line: str, marker: str = "item") -> list[str]:
    """Metadata keys appearing more than once in one task line's trailing run.

    `parse_task_line` builds its metadata with a dict comprehension, so
    `raised:2026-03-02 raised:2020-01-01` keeps only the LAST value -- the task
    silently ages from the wrong date and the register shows a number nobody
    wrote. Only the trailing run is inspected, never the description, so a task
    whose text contains the English words "owner:" or "ref:" is not accused of
    repeating a key (R9).
    """
    match = grammar(marker).task_re.match(line)
    if not match:
        return []
    rest = match.group("rest")
    run_match = META_RUN_RE.search(rest)
    if not run_match:
        return []
    keys = [k for k, _ in META_PAIR_RE.findall(rest[run_match.start() :])]
    return sorted({k for k in keys if keys.count(k) > 1})


def dropped_part_of(line: str) -> bool:
    """True when a line states a `Part of` membership that PARENT_RE will not
    collect, so the membership is silently lost.

    PARENT_RE anchors to the start of a line, so a `Part of [[Org]]` sharing
    its line with anything before it is not a parent at all -- invisible to
    every tool here and to the contact and asset indexes.

    The way that happens in practice is formatting, not typing. A formatter
    running with `proseWrap: always` and format-on-save reflows a paragraph
    onto one line, so

        Works at [[Schneider Electric]]
        Part of [[Maintenance]]

    written as two adjacent lines is saved as one and the membership disappears
    with nothing anywhere saying so. A blank line between them makes them
    separate paragraphs and the formatter leaves both alone.

    Counting rather than matching also catches a second `Part of` on a line
    that already starts with one: PARENT_RE would collect the first and drop
    the rest just as quietly.
    """
    stripped = strip_inline_code(line)
    return stripped.count("Part of [[") != len(PARENT_RE.findall(stripped))


def extract_links(body: str, line_offset: int = 0) -> list[Link]:
    """Every wikilink in the body, in order, with file-relative line numbers.

    Embeds (`![[x]]`) are included and flagged; the leading `!` is not part of
    the target.
    """
    links: list[Link] = []
    consumed = 0
    for line_no, line in enumerate(body.splitlines(), start=line_offset + 1):
        for match in WIKILINK_RE.finditer(line):
            links.append(
                Link(
                    target=match.group(2).strip(),
                    line_no=line_no,
                    is_embed=bool(match.group(1)),
                )
            )
        consumed += 1
    return links


def _parse_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def _unwrap(value: str) -> str:
    return value[2:-2].strip() if value.startswith("[[") and value.endswith("]]") else value


def parse_task_line(line: str, marker: str = "item") -> dict | None:
    """Parse one task line, or return None if the line is not a task.

    Grammar: `- [ ] #item <description> [[Asset]] owner:[[Who]] raised:YYYY-MM-DD`

    The asset is the LAST wikilink before the metadata run -- the trailing,
    unbroken sequence of key:value pairs at the end of the line -- so the
    description may contain wikilinks, and even the words owner/raised/due/ref
    followed by a colon, of its own.
    """
    match = grammar(marker).task_re.match(line)
    if not match:
        return None

    rest = match.group("rest")
    run_match = META_RUN_RE.search(rest)
    head = rest[: run_match.start()] if run_match else rest
    meta_str = rest[run_match.start() :] if run_match else ""

    links = list(WIKILINK_RE.finditer(head))
    if links:
        asset = links[-1].group(2).strip()
        description = head[: links[-1].start()].strip()
    else:
        asset = None
        description = head.strip()

    meta = {k: _unwrap(v) for k, v in META_PAIR_RE.findall(meta_str)}

    return {
        "description": description,
        "asset": asset,
        "owner": meta.get("owner"),
        "raised": _parse_date(meta["raised"]) if "raised" in meta else None,
        "due": _parse_date(meta["due"]) if "due" in meta else None,
        "ref": meta.get("ref"),
        "done": match.group("state").lower() == "x",
    }


def parse_document(path: Path, text: str, marker: str = "item") -> Document:
    """One markdown file, parsed. Never raises: a malformed file becomes a
    document carrying the reason, so one bad note cannot hide the rest."""
    fields, body = split_frontmatter(text)
    title = str(fields.get("title") or path.stem)
    live_body = strip_code_fences(body)
    live_text = strip_code_fences(text)
    raw_uid = fields.get("uid")

    doc = Document(
        uid=str(raw_uid) if is_uid(raw_uid) else None,
        path=path,
        store=STORE_NAME,
        dtype=fields.get("type"),
        title=title,
        fields=fields,
        body=body,
        raw_text=text,
        links=extract_links(live_body, body_line_offset(text)),
        frontmatter_error=frontmatter_error(text),
        live_text=live_text,
    )

    doc.parents = [m.strip() for m in PARENT_RE.findall(live_body)]

    for offset, line in enumerate(live_text.splitlines(), start=1):
        parsed = parse_task_line(line, marker)
        if parsed is not None:
            doc.tasks.append(Task(**parsed, source=title, source_path=path, line_no=offset))

    return doc


def build_alias_map(documents: list[Document]) -> dict[str, str]:
    """Map every alias and title to its canonical title, so `[[PR4]]` and
    `[[Post Rinse 4]]` resolve to the same entity."""
    amap: dict[str, str] = {}
    for doc in documents:
        amap[doc.title] = doc.title
        alias = doc.fields.get("alias")
        if isinstance(alias, str):
            alias = [a.strip() for a in alias.split(",")]
        for name in alias or []:
            amap[str(name).strip()] = doc.title
    return amap
