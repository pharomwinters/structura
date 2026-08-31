"""The markdown store: scanning, loading, and saving a note database."""

from __future__ import annotations

from pathlib import Path

from structura.core.document import Document
from structura.core.schema import Schema, default_schema
from structura.core.violations import Violation

from . import parse, serialize
from .validate import validate

STORE_NAME = parse.STORE_NAME


class MarkdownStore:
    """Markdown files under `root`, parsed against `schema`."""

    name = STORE_NAME

    def __init__(self, root: Path, schema: Schema | None = None) -> None:
        self.root = Path(root)
        self.schema = schema or default_schema()

    @property
    def _marker(self) -> str:
        return self.schema.markdown.task_marker

    def paths(self) -> list[Path]:
        """Every markdown file that should be parsed as a note.

        Dot-directories (`.git`, `.structura`, `.venv`, `.pytest_cache`, ...)
        are skipped generically by a leading-`.` check on every path component
        (legacy R13) rather than by a fixed list. A fixed list let 15 phantom
        notes leak in from tool scratch directories the last time this was
        tried the other way.
        """
        skip = self.schema.markdown.skip
        found = []
        for path in sorted(self.root.rglob("*.md")):
            parts = path.relative_to(self.root).parts
            if any(part.startswith(".") or part in skip for part in parts):
                continue
            found.append(path)
        return found

    def load(self, path: Path) -> Document:
        return parse.parse_document(
            Path(path), Path(path).read_text(encoding="utf-8"), self._marker
        )

    def documents(self) -> list[Document]:
        return [self.load(path) for path in self.paths()]

    def link_target_names(self) -> set[str]:
        """Every on-disk filename a wikilink may legitimately name.

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
        skip = self.schema.markdown.link_target_skip
        names: set[str] = set()
        for path in self.root.rglob("*"):
            if not path.is_file():
                continue
            parts = path.relative_to(self.root).parts
            if any(part.startswith(".") or part in skip for part in parts):
                continue
            names.add(path.name)
            if path.suffix.lower() == ".md":
                names.add(path.stem)
        return names

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
        text = path.read_text(encoding="utf-8")
        updated, uid = serialize.ensure_uid(text)
        if updated != text:
            path.write_text(updated, encoding="utf-8", newline="")
        return uid
