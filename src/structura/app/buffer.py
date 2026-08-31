"""An open document: its text, whether it has changed, and how it is saved.

Headless on purpose. The editor pane is a `QPlainTextEdit` wrapped around one
of these, and everything worth testing about opening and saving a document --
including acceptance test 3, that a save without an edit changes nothing --
is testable without a window.

Two promises live here.

**Only the bytes that changed.** A buffer that has not been edited saves the
bytes it read, unchanged. Not "logically equivalent", not "re-serialised" --
the same bytes. Every reformatting temptation is somebody else's job, behind
an explicit verb.

**No silent clobbering.** If the file changed on disk while the buffer was
dirty, saving raises rather than overwriting, and carries what the UI needs to
offer reload / overwrite / save-a-copy with the on-disk time shown.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from structura.core.document import Document
from structura.index.sync import sha256_bytes
from structura.stores.markdown import MarkdownStore, serialize


class ConflictError(Exception):
    """The file changed underneath a dirty buffer.

    Carries what a prompt needs to say: which file, and when it changed. A
    conflict is a question for the person, not a decision for the program.
    """

    def __init__(self, path: Path, disk_modified: datetime) -> None:
        stamp = disk_modified.astimezone().strftime("%Y-%m-%d %H:%M:%S")
        super().__init__(f"{path.name} changed on disk at {stamp}")
        self.path = path
        self.disk_modified = disk_modified


def _modified(path: Path) -> datetime:
    return datetime.fromtimestamp(os.stat(path).st_mtime, tz=UTC)


@dataclass
class DocumentBuffer:
    """One document, open."""

    path: Path
    store: MarkdownStore
    #: The bytes as read, and as they will be written back untouched.
    original: str = ""
    text: str = ""
    #: Hash of what is on disk as far as this buffer knows.
    disk_sha: str = ""
    parsed: Document | None = None
    _new: bool = field(default=False, repr=False)

    # --- opening ------------------------------------------------------

    @classmethod
    def open(cls, store: MarkdownStore, path: Path) -> DocumentBuffer:
        path = Path(path)
        text = store.read(path)
        return cls(
            path=path,
            store=store,
            original=text,
            text=text,
            disk_sha=sha256_bytes(text.encode("utf-8")),
            parsed=store.parse(path, text),
        )

    @classmethod
    def unsaved(cls, store: MarkdownStore, path: Path, text: str) -> DocumentBuffer:
        """A buffer for a document that does not exist yet.

        Startup opens today's journal this way: rendered from a template but
        not written, so launching the application on a day you did no work
        does not seed the workspace with an empty daily note.
        """
        return cls(
            path=Path(path),
            store=store,
            original="",
            text=text,
            disk_sha="",
            parsed=store.parse(Path(path), text),
            _new=True,
        )

    # --- state --------------------------------------------------------

    @property
    def is_new(self) -> bool:
        return self._new

    @property
    def is_dirty(self) -> bool:
        return self.text != self.original

    @property
    def title(self) -> str:
        return self.parsed.title if self.parsed else self.path.stem

    def set_text(self, text: str) -> None:
        self.text = text

    def reparse(self) -> Document:
        self.parsed = self.store.parse(self.path, self.text)
        return self.parsed

    # --- the disk -----------------------------------------------------

    def disk_changed(self) -> bool:
        """Whether the file differs from what this buffer last saw.

        Compares content, not timestamps: a formatter that rewrote a file
        identically, or a `touch`, is not a conflict worth interrupting anyone
        for.
        """
        if self._new:
            return self.path.exists()
        try:
            current = sha256_bytes(self.path.read_bytes())
        except FileNotFoundError:
            return True
        return current != self.disk_sha

    def disk_modified(self) -> datetime:
        return _modified(self.path)

    def reload(self) -> None:
        """Take what is on disk and discard the buffer's edits."""
        text = self.store.read(self.path)
        self.original = self.text = text
        self.disk_sha = sha256_bytes(text.encode("utf-8"))
        self._new = False
        self.reparse()

    # --- saving -------------------------------------------------------

    def save(self, *, force: bool = False, assign_uid: bool = True) -> str:
        """Write the buffer. Returns the text as written.

        A clean buffer still writes when it is new or has no UID; otherwise it
        writes nothing at all, which is the strongest form of the
        no-reformatting promise -- there is no code path that could rewrite it.
        """
        if self.disk_changed() and not force:
            raise ConflictError(self.path, self.disk_modified() if self.path.exists() else _now())

        text = self.text
        if assign_uid:
            text, _ = serialize.ensure_uid(text)

        if not self._new and text == self.original and not self.disk_changed():
            # Nothing to write. Saving an untouched document must not so much
            # as open the file for writing.
            return text

        self.path.parent.mkdir(parents=True, exist_ok=True)
        written = self.store.save(self.path, text, assign_uid=False)
        self.original = self.text = written
        self.disk_sha = sha256_bytes(written.encode("utf-8"))
        self._new = False
        self.reparse()
        return written

    def save_a_copy(self, suffix: str = "conflict") -> Path:
        """Write the buffer beside the original, leaving both.

        The third option in the conflict prompt, and the only one that loses
        nothing.
        """
        target = self.path.with_name(f"{self.path.stem}.{suffix}{self.path.suffix}")
        index = 2
        while target.exists():
            target = self.path.with_name(f"{self.path.stem}.{suffix}{index}{self.path.suffix}")
            index += 1
        self.store.save(target, self.text, assign_uid=False)
        return target


def _now() -> datetime:
    return datetime.now(tz=UTC)
