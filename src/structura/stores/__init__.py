"""Store adapters: one interface, one implementation per on-disk format.

Files are the truth, in the native format for their domain -- markdown for
notes, iCalendar for calendar, vCard for contacts. A store is the only thing
that knows which. Everything above it sees `Document`.

Phase 0 ships the markdown store. The protocol exists now, with one
implementation, because the shape of the second and third adapters is what
decides whether the first one was written at the right altitude.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from structura.core.document import Document


@runtime_checkable
class Store(Protocol):
    """What every store must do. Deliberately small."""

    name: str
    root: Path

    def paths(self) -> list[Path]:
        """Every file in this store that should be parsed, in stable order."""

    def load(self, path: Path) -> Document:
        """Parse one file. Must not raise for malformed content -- a document
        carrying its own error keeps one bad file from hiding the rest."""

    def documents(self) -> list[Document]:
        """Every document in the store."""
