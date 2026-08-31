"""Write markdown back, changing only the bytes that changed.

This is the module the no-reformatting promise lives or dies in, and it is
written the way it is for one reason: **frontmatter is never re-dumped through
the YAML serializer.** Round-tripping a mapping through `yaml.safe_dump` would
reorder keys, requote strings, rewrap long values, and normalise the block
style -- producing a file that means the same thing and does not look the same,
on every save, for every note the user merely opened.

So edits are surgical. A field's value is replaced in its own line. A new field
is inserted as one new line. Everything else in the file is the bytes that were
read.

Line endings are part of that promise and are handled per line rather than per
file, so a CRLF document stays CRLF, an LF document stays LF, and a document
that is inconsistent with itself is left inconsistent rather than tidied.
"""

from __future__ import annotations

import re

from structura.core.uid import new_uid

from .parse import FRONTMATTER_RE

# A top-level frontmatter key: no leading whitespace, so a nested mapping key
# or a list item is never mistaken for one.
_KEY_RE = re.compile(r"^(?P<key>[A-Za-z0-9_-]+):(?P<sep>[ \t]*)(?P<value>.*)$")


def newline_style(text: str) -> str:
    """The line ending the file already uses. A file that arrived with CRLF is
    written back with CRLF -- rewriting line endings is exactly the kind of
    whole-file churn this module exists to prevent."""
    return "\r\n" if "\r\n" in text else "\n"


def _split(text: str) -> tuple[str, str, str] | None:
    """(prefix, frontmatter_block, body) or None when there is no frontmatter.

    `prefix` is everything up to and including the opening delimiter line, so
    reassembly is pure concatenation and nothing between the pieces is
    re-derived.
    """
    match = FRONTMATTER_RE.match(text)
    if not match:
        return None
    block_start = match.start(1)
    block_end = match.end(1)
    return text[:block_start], text[block_start:block_end], text[block_end:]


def get_field_raw(text: str, key: str) -> str | None:
    """The unparsed text of a top-level frontmatter value, or None."""
    parts = _split(text)
    if parts is None:
        return None
    for line in parts[1].splitlines():
        match = _KEY_RE.match(line)
        if match and match.group("key") == key:
            return match.group("value")
    return None


def set_field(text: str, key: str, value: str) -> str:
    """Set a top-level frontmatter field, touching only its line.

    A file with no frontmatter is given one. A key that exists is replaced in
    place, keeping its position and the spacing after the colon. A key that
    does not exist is appended as the last line of the block, because appending
    is the only insertion point that cannot reorder what is already there.
    """
    nl = newline_style(text)
    parts = _split(text)

    if parts is None:
        return f"---{nl}{key}: {value}{nl}---{nl}{text}"

    prefix, block, body = parts
    lines = block.split("\n")
    for index, line in enumerate(lines):
        stripped = line.rstrip("\r")
        match = _KEY_RE.match(stripped)
        if match and match.group("key") == key:
            sep = match.group("sep") or " "
            carriage = "\r" if line.endswith("\r") else ""
            lines[index] = f"{key}:{sep}{value}{carriage}"
            return prefix + "\n".join(lines) + body

    # Appending needs the ending of the line it is appended *after*, and that
    # line's ending was consumed by the frontmatter regex -- so it is not on
    # `lines[-1]` to be copied. The body still starts with it, which is exactly
    # the right place to read it from: it keeps a CRLF file CRLF and a mixed
    # file mixed, rather than deciding for the whole document from one sample.
    #
    # Getting this wrong corrupted the *previous* line rather than the new one,
    # which is the kind of bug that hides until a platform makes CRLF normal.
    carriage = "\r" if body.startswith("\r\n") else ""
    if lines:
        lines[-1] = lines[-1] + carriage
    lines.append(f"{key}: {value}")
    return prefix + "\n".join(lines) + body


def has_uid(text: str) -> bool:
    from structura.core.uid import is_uid

    raw = get_field_raw(text, "uid")
    return raw is not None and is_uid(raw.strip().strip("\"'"))


def ensure_uid(text: str, uid: str | None = None) -> tuple[str, str]:
    """Return (text, uid), minting and writing a `uid:` field if there is none.

    Called on first save rather than on first read. Stamping a UID during a
    scan would mean opening a workspace rewrites every file in it, which is
    both a surprising amount of git noise and a violation of the rule that
    reading never writes.
    """
    existing = get_field_raw(text, "uid")
    if existing is not None:
        cleaned = existing.strip().strip("\"'")
        from structura.core.uid import is_uid

        if is_uid(cleaned):
            return text, cleaned

    minted = uid or new_uid()
    return set_field(text, "uid", minted), minted
