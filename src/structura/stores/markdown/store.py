"""The markdown store: scanning, loading, and saving a note database."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from structura.core.document import Document
from structura.core.schema import Schema, default_schema
from structura.core.violations import Violation

from . import parse, serialize
from .validate import validate

STORE_NAME = parse.STORE_NAME


@dataclass
class Scan:
    """One directory walk, both answers.

    "Which files do I parse as notes?" and "which names may a wikilink
    legitimately resolve to?" are different questions with different skip
    rules, but they read the same directory tree. Answering them in separate
    walks doubled the traversal on every full sync for no reason.
    """

    #: Paths are resolved exactly once, here, and every consumer uses them as
    #: they are. `Path.resolve` walks the tree with `lstat` per component, and
    #: resolving the same file again for its stem and a third time in the sync
    #: loop was the largest single cost in a cold index of a large workspace --
    #: more than parsing the YAML.
    notes: list[Path] = field(default_factory=list)
    #: (name, providing path) -- a markdown file supplies both its filename and
    #: its stem; anything else supplies only its filename (legacy R31).
    link_targets: list[tuple[str, Path]] = field(default_factory=list)


class MarkdownStore:
    """Markdown files under `root`, parsed against `schema`."""

    name = STORE_NAME

    def __init__(self, root: Path, schema: Schema | None = None) -> None:
        # Resolved once, here. Every path the store hands out is rooted at it
        # and needs no resolving of its own -- `Path.resolve` costs a
        # `_getfinalpathname` syscall per call on Windows, and doing it per
        # file was the largest single cost in a cold index there.
        self.root = Path(root).resolve()
        self.schema = schema or default_schema()

    @property
    def _marker(self) -> str:
        return self.schema.markdown.task_marker

    def scan(self) -> Scan:
        """Walk the workspace once, collecting notes and link targets.

        Dot-directories (`.git`, `.structura`, `.venv`, `.pytest_cache`, ...)
        are skipped generically by a leading-`.` check on every path component
        (legacy R13) rather than by a fixed list. A fixed list let 15 phantom
        notes leak in from tool scratch directories the last time this was
        tried the other way.
        """
        skip = self.schema.markdown.skip
        link_skip = self.schema.markdown.link_target_skip
        result = Scan()

        for path in sorted(self.root.rglob("*")):
            if not path.is_file():
                continue
            parts = path.relative_to(self.root).parts
            dotted = any(part.startswith(".") for part in parts)
            is_markdown = path.suffix.lower() == ".md"

            wanted = is_markdown and not dotted and not any(part in skip for part in parts)
            linkable = not dotted and not any(part in link_skip for part in parts)
            if not (wanted or linkable):
                continue

            if wanted:
                result.notes.append(path)
            if linkable:
                result.link_targets.append((path.name, path))
                if is_markdown:
                    result.link_targets.append((path.stem, path))

        return result

    def paths(self) -> list[Path]:
        """Every markdown file that should be parsed as a note."""
        return self.scan().notes

    def contains(self, path: Path) -> bool:
        """Whether one path is a note this store parses.

        The same rules as `paths()`, decided per path. The incremental sync
        needs this: asking `paths()` whether it contains one file would walk
        the whole workspace on every keystroke-triggered save, which is what
        turned a 20 ms budget into 150 ms the first time it was measured.
        """
        path = Path(path)
        if path.suffix.lower() != ".md":
            return False
        try:
            parts = path.relative_to(self.root).parts
        except ValueError:
            return False
        skip = self.schema.markdown.skip
        if any(part.startswith(".") or part in skip for part in parts):
            return False
        return path.is_file()

    def read(self, path: Path) -> str:
        """A document's text, exactly as the bytes say.

        Deliberately not `read_text`, which applies universal newlines and
        silently turns a CRLF file into an LF one. Structura writes back only
        the bytes it changed, so a line ending it never saw is a line ending
        it would destroy on the next save -- on the platform where CRLF files
        are most likely, which is the one this ships on.
        """
        return Path(path).read_bytes().decode("utf-8")

    def parse(self, path: Path, text: str) -> Document:
        """Parse text already in hand, without touching the disk."""
        return parse.parse_document(Path(path), text, self._marker)

    def load(self, path: Path) -> Document:
        return self.parse(path, self.read(path))

    def documents(self) -> list[Document]:
        return [self.load(path) for path in self.paths()]

    def link_target_names(self) -> set[str]:
        """Every on-disk filename a wikilink may legitimately name.

        See `scan()` for the walk itself; this is the set of names it found.

        A wikilink can target a non-markdown file directly -- `[[poster.pdf]]`
        names the file with its extension, the way `[[Post Rinse 4]]` names a
        note without one. Both must resolve, or a file that genuinely exists is
        reported as an unwritten note (R21).

        The extension is therefore *mandatory* for a non-markdown file: only
        `path.name` is collected for it, never `path.stem` (R31). Adding the
        bare stem of an attachment let `[[PFMEA-HierarchyView]]` silently
        resolve against `PFMEA-HierarchyView.xlsx`, so a wikilink that meant to
        name an unwritten note vanished from the promotion queue instead of
        surfacing in it -- an invisible failure of the one thing the
        placeholder register exists for. Markdown files keep both forms,
        because a wikilink resolves a note by bare filename.

        Skips `link_target_skip` rather than `skip` (R36): generated index
        files are excluded from parsing but ARE resolvable link targets,
        because they exist on disk.
        """
        return {name for name, _ in self.scan().link_targets}

    def validate(self, documents: list[Document] | None = None) -> list[Violation]:
        return validate(self.documents() if documents is None else documents, self.schema)

    def save(self, path: Path, text: str, *, assign_uid: bool = True) -> str:
        """Write a document, minting its UID if it has none. Returns the text
        as written, which is what the caller should hash to recognise and skip
        the watcher event its own write is about to produce."""
        if assign_uid:
            text, _ = serialize.ensure_uid(text)
        Path(path).write_text(text, encoding="utf-8", newline="")
        return text

    def assign_uid(self, path: Path) -> str:
        """Stamp a UID onto a file that has none, and return it.

        Reading never writes, so a scan leaves files alone; this is the
        explicit call for backfilling an existing workspace.
        """
        path = Path(path)
        text = self.read(path)
        updated, uid = serialize.ensure_uid(text)
        if updated != text:
            path.write_text(updated, encoding="utf-8", newline="")
        return uid
