"""Connection management for the index.

Access model from the design: WAL, one writer connection owned by the indexer,
a read-only connection per reader. The event loop never blocks on the database.

A schema version mismatch is not migrated. The file is deleted and rebuilt,
which is both simpler than migration and a standing proof that the index is a
cache: if dropping it ever became expensive, that would be the bug.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .schema import DDL, SCHEMA_VERSION

INDEX_DIRNAME = ".structura"
INDEX_FILENAME = "index.db"


def index_path(workspace: Path) -> Path:
    return Path(workspace) / INDEX_DIRNAME / INDEX_FILENAME


class Database:
    """The index file, and the connections onto it."""

    def __init__(self, path: Path, *, workspace: Path | None = None) -> None:
        self.path = Path(path)
        self.workspace = Path(workspace) if workspace else self.path.parent.parent
        self._writer: sqlite3.Connection | None = None

    # --- construction -------------------------------------------------

    @classmethod
    def open(cls, workspace: Path) -> Database:
        """Open (creating if needed) the index for a workspace."""
        db = cls(index_path(workspace), workspace=workspace)
        db.ensure()
        return db

    @classmethod
    def in_memory(cls, workspace: Path | None = None) -> Database:
        """An index that never touches disk. Used by tests and by any caller
        that wants a throwaway view of a workspace."""
        db = cls(Path(":memory:"), workspace=workspace or Path("."))
        db.ensure()
        return db

    # --- lifecycle ----------------------------------------------------

    def ensure(self) -> None:
        """Create or rebuild the index so its schema matches this build."""
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self.path.exists() and self._stored_version() != SCHEMA_VERSION:
                self.drop()
        conn = self.writer
        conn.executescript(DDL)
        conn.execute(
            "INSERT INTO meta(key, value) VALUES ('schema_version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (str(SCHEMA_VERSION),),
        )
        conn.commit()

    def _stored_version(self) -> int | None:
        try:
            conn = sqlite3.connect(self.path)
            try:
                row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
            finally:
                conn.close()
        except sqlite3.DatabaseError:
            # Not a database, or a corrupt one. Either way: rebuild.
            return None
        return int(row[0]) if row else None

    def drop(self) -> None:
        """Delete the index file and its WAL sidecars. Losing nothing is the
        point; this is the supported answer to any index bug."""
        self.close()
        if str(self.path) == ":memory:":
            return
        for suffix in ("", "-wal", "-shm"):
            candidate = Path(str(self.path) + suffix)
            if candidate.exists():
                candidate.unlink()

    def close(self) -> None:
        if self._writer is not None:
            self._writer.close()
            self._writer = None

    def __enter__(self) -> Database:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # --- connections --------------------------------------------------

    def _configure(self, conn: sqlite3.Connection) -> sqlite3.Connection:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        if str(self.path) != ":memory:":
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")
        return conn

    @property
    def writer(self) -> sqlite3.Connection:
        """The single write connection. Owned by whoever is syncing."""
        if self._writer is None:
            self._writer = self._configure(
                sqlite3.connect(self.path, isolation_level=None, check_same_thread=False)
            )
        return self._writer

    def reader(self) -> sqlite3.Connection:
        """A fresh read connection.

        An in-memory database has exactly one connection, so readers share the
        writer there -- a second `:memory:` connection would open a different,
        empty database.
        """
        if str(self.path) == ":memory:":
            return self.writer
        uri = f"file:{self.path}?mode=ro"
        return self._configure(sqlite3.connect(uri, uri=True, check_same_thread=False))
