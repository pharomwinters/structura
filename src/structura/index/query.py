"""Reading the index.

Phase 2 puts the typed pipeline on top of this. Phase 1 gives it the answers
it will need, and gives acceptance test 4 something to check: every method
here must return exactly what the same question computed directly from the
parsed documents returns.

Every result is a plain Python value -- paths, titles, counts, dictionaries --
not a cursor. The caller never holds a connection open, and the read
connection is short-lived, which is what keeps a long-running UI from blocking
a write.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .db import Database


@dataclass(frozen=True)
class DocumentRow:
    id: int
    path: Path
    uid: str | None
    dtype: str | None
    title: str
    date: str | None
    area: str | None
    status: str | None

    @classmethod
    def of(cls, row: sqlite3.Row) -> DocumentRow:
        return cls(
            id=row["id"],
            path=Path(row["path"]),
            uid=row["uid"],
            dtype=row["dtype"],
            title=row["title"],
            date=row["date"],
            area=row["area"],
            status=row["status"],
        )


@dataclass(frozen=True)
class TaskRow:
    path: Path
    source: str
    line_no: int
    description: str
    asset: str | None
    owner: str | None
    raised: str | None
    due: str | None
    ref: str | None
    done: bool


@dataclass(frozen=True)
class Placeholder:
    target: str
    inbound: int
    sources: tuple[str, ...]


_DOC_COLUMNS = "d.id, d.path, d.uid, d.dtype, d.title, d.date, d.area, d.status"


class Index:
    """Queries over one index. Cheap to construct; holds no open cursor."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def _rows(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        conn = self.db.reader()
        try:
            return conn.execute(sql, params).fetchall()
        finally:
            if conn is not self.db._writer:
                conn.close()

    # --- documents ----------------------------------------------------

    def documents(
        self,
        *,
        dtype: str | None = None,
        area: str | None = None,
        status: str | None = None,
        tag: str | None = None,
        title: str | None = None,
    ) -> list[DocumentRow]:
        # DISTINCT because the tag join can in principle multiply rows. Tags
        # are deduplicated on the way in, so this is belt and braces rather
        # than the fix -- but a cache should not be able to invent duplicates
        # of a document under any circumstances.
        sql = f"SELECT DISTINCT {_DOC_COLUMNS} FROM documents d"
        where: list[str] = []
        params: list[object] = []
        if tag is not None:
            sql += " JOIN tags t ON t.doc_id = d.id"
            where.append("t.tag = ?")
            params.append(tag)
        for column, value in (
            ("dtype", dtype),
            ("area", area),
            ("status", status),
            ("title", title),
        ):
            if value is not None:
                where.append(f"d.{column} = ?")
                params.append(value)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY d.path"
        return [DocumentRow.of(row) for row in self._rows(sql, tuple(params))]

    def document_count(self) -> int:
        return self._rows("SELECT COUNT(*) AS n FROM documents")[0]["n"]

    def resolve(self, name: str) -> DocumentRow | None:
        """The document a title or alias names, or None.

        Ties -- two documents claiming one name -- break by greatest path, the
        same way `build_alias_map` breaks them, so the index and the exported
        registers never disagree about which note a link means.
        """
        rows = self._rows(
            f"SELECT {_DOC_COLUMNS} FROM documents d "
            "JOIN aliases a ON a.doc_id = d.id WHERE a.alias = ? "
            "ORDER BY d.path DESC LIMIT 1",
            (name,),
        )
        return DocumentRow.of(rows[0]) if rows else None

    def fields(self, doc_id: int) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for row in self._rows(
            "SELECT key, value FROM fields WHERE doc_id = ? ORDER BY key, ord", (doc_id,)
        ):
            out.setdefault(row["key"], []).append(row["value"])
        return out

    def tags(self) -> dict[str, int]:
        return {
            row["tag"]: row["n"]
            for row in self._rows(
                "SELECT tag, COUNT(*) AS n FROM tags GROUP BY tag ORDER BY n DESC, tag"
            )
        }

    # --- links --------------------------------------------------------

    def links_from(self, doc_id: int) -> list[tuple[str, int]]:
        return [
            (row["target_norm"], row["line_no"])
            for row in self._rows(
                "SELECT target_norm, line_no FROM links WHERE doc_id = ? "
                "ORDER BY line_no, target_norm",
                (doc_id,),
            )
        ]

    def backlinks(self, doc_id: int) -> list[DocumentRow]:
        return [
            DocumentRow.of(row)
            for row in self._rows(
                f"SELECT DISTINCT {_DOC_COLUMNS} FROM links l "
                "JOIN documents d ON d.id = l.doc_id "
                "WHERE l.target_id = ? ORDER BY d.path",
                (doc_id,),
            )
        ]

    def orphans(self) -> list[DocumentRow]:
        """Documents nothing links to."""
        return [
            DocumentRow.of(row)
            for row in self._rows(
                f"SELECT {_DOC_COLUMNS} FROM documents d "
                "WHERE NOT EXISTS (SELECT 1 FROM links l WHERE l.target_id = d.id) "
                "ORDER BY d.path"
            )
        ]

    def placeholders(self) -> list[Placeholder]:
        """Unwritten link targets, ranked by inbound count.

        A target is a placeholder when it resolves to no document AND names no
        file on disk -- an attachment linked by its full filename is not an
        unwritten note (legacy R21/R31).
        """
        rows = self._rows(
            "SELECT l.target_norm AS target, COUNT(*) AS n, "
            "       GROUP_CONCAT(DISTINCT d.title) AS sources "
            "FROM links l JOIN documents d ON d.id = l.doc_id "
            "WHERE l.target_id IS NULL AND l.target_norm != '' "
            "  AND NOT EXISTS (SELECT 1 FROM link_targets f WHERE f.name = l.target_norm) "
            "GROUP BY l.target_norm "
            "ORDER BY n DESC, l.target_norm"
        )
        return [
            Placeholder(
                target=row["target"],
                inbound=row["n"],
                sources=tuple(sorted((row["sources"] or "").split(","))),
            )
            for row in rows
        ]

    # --- tasks --------------------------------------------------------

    def tasks(
        self,
        *,
        done: bool | None = None,
        owner: str | None = None,
        asset: str | None = None,
    ) -> list[TaskRow]:
        sql = (
            "SELECT d.path, d.title AS source, t.* FROM tasks t JOIN documents d ON d.id = t.doc_id"
        )
        where: list[str] = []
        params: list[object] = []
        if done is not None:
            where.append("t.done = ?")
            params.append(int(done))
        if owner is not None:
            where.append("t.owner = ?")
            params.append(owner)
        if asset is not None:
            where.append("t.asset_norm = ?")
            params.append(asset)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY d.path, t.line_no"
        return [
            TaskRow(
                path=Path(row["path"]),
                source=row["source"],
                line_no=row["line_no"],
                description=row["description"],
                asset=row["asset_raw"],
                owner=row["owner"],
                raised=row["raised"],
                due=row["due"],
                ref=row["ref"],
                done=bool(row["done"]),
            )
            for row in self._rows(sql, tuple(params))
        ]

    # --- structure ----------------------------------------------------

    def children(self, doc_id: int) -> list[DocumentRow]:
        return [
            DocumentRow.of(row)
            for row in self._rows(
                f"SELECT DISTINCT {_DOC_COLUMNS} FROM parents p "
                "JOIN documents d ON d.id = p.doc_id "
                "WHERE p.target_id = ? ORDER BY d.title",
                (doc_id,),
            )
        ]

    def parents(self, doc_id: int) -> list[str]:
        return [
            row["target_norm"]
            for row in self._rows(
                "SELECT target_norm FROM parents WHERE doc_id = ? ORDER BY ord", (doc_id,)
            )
        ]

    # --- search -------------------------------------------------------

    def search(self, text: str) -> list[DocumentRow]:
        """Full-text search over titles and bodies, best match first."""
        rows = self._rows(
            f"SELECT {_DOC_COLUMNS} FROM fts "
            "JOIN documents d ON d.id = fts.doc_id "
            "WHERE fts MATCH ? ORDER BY rank, d.path",
            (text,),
        )
        return [DocumentRow.of(row) for row in rows]
