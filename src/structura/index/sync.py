"""Bringing the index into step with the files.

The algorithm, from the design: stat the file, compare `(mtime, size)`, hash
only on mismatch, and reparse only on hash change. A changed document deletes
its rows and reinserts -- no diffing, because reparsing one document is
already cheap and diff logic would be a source of drift for no measurable
gain.

Deletion is by `path` with `ON DELETE CASCADE` doing the rest, which is the
whole reason the index is keyed on path rather than on content.
"""

from __future__ import annotations

import hashlib
import os
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from structura.core.document import Document
from structura.core.links import link_section, strip_section
from structura.stores.markdown import MarkdownStore

from .db import Database
from .schema import PROMOTED_FIELDS


@dataclass
class SyncReport:
    added: int = 0
    updated: int = 0
    unchanged: int = 0
    removed: int = 0
    elapsed_s: float = 0.0
    errors: list[tuple[Path, str]] = field(default_factory=list)

    @property
    def changed(self) -> int:
        return self.added + self.updated + self.removed

    def __str__(self) -> str:
        return (
            f"{self.added} added · {self.updated} updated · {self.removed} removed "
            f"· {self.unchanged} unchanged · {self.elapsed_s * 1000:.0f} ms"
        )


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _scalars(value: Any) -> list[str]:
    """Frontmatter value flattened to the strings the index stores.

    A list becomes one row per element so `tags` and `alias` are queryable
    without parsing on read. Anything else is stored as its text, because a
    free-form key with a nested value is still worth finding by document even
    if it is not worth querying by value.
    """
    if value is None or value == "":
        return []
    if isinstance(value, bool):
        return ["true" if value else "false"]
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            out.extend(_scalars(item))
        return out
    if isinstance(value, date | datetime):
        return [value.isoformat()]
    return [str(value)]


def _dedupe(values: Iterable[str]) -> list[str]:
    """Unique, in first-seen order."""
    seen: dict[str, None] = {}
    for value in values:
        seen.setdefault(value, None)
    return list(seen)


def extract_tags(fields: dict[str, Any]) -> list[str]:
    """Tags from the `tags` frontmatter key, comma-separated or as a list.

    Deduplicated, because "this document has tag X" is a fact rather than a
    count: a note that writes `tags: pressure, pressure` has one tag, and
    storing two rows would return the document twice from a tag query.

    Body hashtags are deliberately not collected: the task marker is a body
    hashtag, and sweeping those into the tag index would make every task line
    a tag on its document.
    """
    raw = fields.get("tags")
    if isinstance(raw, str):
        values = [part.strip() for part in raw.split(",")]
    else:
        values = _scalars(raw)
    return _dedupe(tag.lstrip("#") for tag in values if tag and tag.strip())


def extract_aliases(doc: Document) -> list[str]:
    raw = doc.fields.get("alias")
    if isinstance(raw, str):
        values = [part.strip() for part in raw.split(",")]
    else:
        values = _scalars(raw)
    return _dedupe(value for value in values if value)


class Indexer:
    """Keeps one index in step with one store."""

    def __init__(self, db: Database, store: MarkdownStore) -> None:
        self.db = db
        self.store = store
        # Hashes of writes Structura made itself. The watcher event its own
        # save produces is recognised here and skipped, rather than bouncing
        # back through the parser.
        self._expected: dict[Path, str] = {}
        # Filled during a pass so an incremental resolve knows its blast
        # radius: the documents that changed, and every name whose meaning
        # those changes could have altered.
        self._touched_ids: set[int] = set()
        self._touched_names: set[str] = set()

    def expect(self, path: Path, sha: str) -> None:
        self._expected[Path(path).resolve()] = sha

    # --- syncing ------------------------------------------------------

    def sync(self) -> SyncReport:
        """Bring the whole index into step, including removals."""
        started = time.perf_counter()
        report = SyncReport()
        conn = self.db.writer

        scan = self.store.scan()
        on_disk = {path.resolve(): path for path in scan.notes}
        known = {
            Path(row["path"]): (row["id"], row["mtime_ns"], row["size"], row["sha256"])
            for row in conn.execute("SELECT id, path, mtime_ns, size, sha256 FROM documents")
        }

        conn.execute("BEGIN")
        try:
            for resolved, path in on_disk.items():
                self._sync_one(conn, resolved, path, known.get(resolved), report)

            gone = set(known) - set(on_disk)
            for path in gone:
                conn.execute("DELETE FROM documents WHERE path = ?", (str(path),))
                report.removed += 1

            self._refresh_link_targets(conn, scan)
            if report.changed:
                self._resolve(conn)
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise

        report.elapsed_s = time.perf_counter() - started
        return report

    def sync_paths(self, paths: Iterable[Path]) -> SyncReport:
        """Bring specific paths into step. What the watcher calls.

        A path that no longer exists is removed; a path outside the store is
        ignored rather than treated as a deletion, because a watcher fires on
        every file in the tree and most of them are not ours.
        """
        started = time.perf_counter()
        report = SyncReport()
        conn = self.db.writer
        self._touched_ids = set()
        self._touched_names = set()

        conn.execute("BEGIN")
        try:
            for raw in paths:
                resolved = Path(raw).resolve()
                row = conn.execute(
                    "SELECT id, mtime_ns, size, sha256 FROM documents WHERE path = ?",
                    (str(resolved),),
                ).fetchone()
                known = (row["id"], row["mtime_ns"], row["size"], row["sha256"]) if row else None

                if not self.store.contains(resolved):
                    if known is not None:
                        self._record_names(conn, known[0])
                        conn.execute("DELETE FROM documents WHERE path = ?", (str(resolved),))
                        report.removed += 1
                    continue

                self._sync_one(conn, resolved, resolved, known, report)
                self._touch_link_target(conn, resolved)

            if report.changed:
                self._resolve(conn, self._touched_ids, self._touched_names)
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise

        report.elapsed_s = time.perf_counter() - started
        return report

    def _sync_one(
        self,
        conn,
        resolved: Path,
        path: Path,
        known: tuple[int, int, int, str] | None,
        report: SyncReport,
    ) -> None:
        try:
            stat = os.stat(resolved)
        except OSError as exc:
            report.errors.append((resolved, str(exc)))
            return

        if known is not None and known[1] == stat.st_mtime_ns and known[2] == stat.st_size:
            report.unchanged += 1
            return

        try:
            data = resolved.read_bytes()
        except OSError as exc:
            report.errors.append((resolved, str(exc)))
            return

        sha = sha256_bytes(data)
        expected = self._expected.pop(resolved, None)

        if known is not None and known[3] == sha:
            # Same content, new timestamp -- a touch, or our own write coming
            # back through the watcher. Record the stat so the next pass is a
            # cheap skip, and do not reparse.
            conn.execute(
                "UPDATE documents SET mtime_ns = ?, size = ? WHERE id = ?",
                (stat.st_mtime_ns, stat.st_size, known[0]),
            )
            report.unchanged += 1
            return

        if expected is not None and expected == sha and known is not None:
            # Our own save. The row was written from the same bytes already.
            conn.execute(
                "UPDATE documents SET mtime_ns = ?, size = ?, sha256 = ? WHERE id = ?",
                (stat.st_mtime_ns, stat.st_size, sha, known[0]),
            )
            report.unchanged += 1
            return

        try:
            doc = self.store.load(resolved)
        except (OSError, UnicodeDecodeError) as exc:
            report.errors.append((resolved, str(exc)))
            return

        if known is not None:
            self._record_names(conn, known[0])
            conn.execute("DELETE FROM documents WHERE id = ?", (known[0],))
            report.updated += 1
        else:
            report.added += 1

        self._insert(conn, doc, resolved, stat.st_mtime_ns, stat.st_size, sha)

    # --- writing ------------------------------------------------------

    def _record_names(self, conn, doc_id: int) -> None:
        """Remember the names a document was answering to before it is deleted.

        Removing a note un-resolves every link that pointed at it, so those
        links have to be revisited even though their own files did not change.
        """
        self._touched_names.update(
            row["alias"]
            for row in conn.execute("SELECT alias FROM aliases WHERE doc_id = ?", (doc_id,))
        )

    def _insert(self, conn, doc: Document, path: Path, mtime_ns: int, size: int, sha: str) -> None:
        promoted = {key: (_scalars(doc.fields.get(key)) or [None])[0] for key in PROMOTED_FIELDS}
        cursor = conn.execute(
            "INSERT INTO documents "
            "(path, uid, store, dtype, title, date, area, status, mtime_ns, size, sha256, "
            " indexed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(path),
                doc.uid,
                doc.store,
                str(doc.dtype) if doc.dtype is not None else None,
                doc.title,
                promoted["date"],
                promoted["area"],
                promoted["status"],
                mtime_ns,
                size,
                sha,
                datetime.now(UTC).isoformat(timespec="seconds"),
            ),
        )
        doc_id = cursor.lastrowid

        conn.executemany(
            "INSERT INTO fields (doc_id, key, value, ord) VALUES (?, ?, ?, ?)",
            [
                (doc_id, key, value, ord_)
                for key, raw in doc.fields.items()
                for ord_, value in enumerate(_scalars(raw))
            ],
        )
        conn.executemany(
            "INSERT INTO tags (doc_id, tag) VALUES (?, ?)",
            [(doc_id, tag) for tag in extract_tags(doc.fields)],
        )
        conn.executemany(
            "INSERT INTO aliases (alias, doc_id) VALUES (?, ?)",
            # An alias equal to the title is one name, not two.
            [(name, doc_id) for name in _dedupe([doc.title, *extract_aliases(doc)])],
        )
        conn.executemany(
            "INSERT INTO links (doc_id, target_raw, target_norm, section, is_embed, line_no) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                (
                    doc_id,
                    link.target,
                    strip_section(link.target),
                    link_section(link.target),
                    int(link.is_embed),
                    link.line_no,
                )
                for link in doc.links
            ],
        )
        conn.executemany(
            "INSERT INTO parents (doc_id, target_norm, ord) VALUES (?, ?, ?)",
            [(doc_id, strip_section(name), i) for i, name in enumerate(doc.parents)],
        )
        conn.executemany(
            "INSERT INTO tasks "
            "(doc_id, line_no, description, asset_raw, asset_norm, owner, raised, due, ref, done) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    doc_id,
                    task.line_no,
                    task.description,
                    task.asset,
                    strip_section(task.asset) if task.asset else None,
                    task.owner,
                    task.raised.isoformat() if task.raised else None,
                    task.due.isoformat() if task.due else None,
                    task.ref,
                    int(task.done),
                )
                for task in doc.tasks
            ],
        )
        conn.execute(
            "INSERT INTO fts (title, body, doc_id) VALUES (?, ?, ?)",
            (doc.title, doc.body, doc_id),
        )

        self._touched_ids.add(doc_id)
        self._touched_names.update(_dedupe([doc.title, *extract_aliases(doc)]))

    def _refresh_link_targets(self, conn, scan) -> None:
        """Rebuild the set of on-disk names a wikilink may name.

        Fed by the same walk that found the notes, so a full sync traverses the
        workspace once. The incremental path updates only the file it touched,
        so a per-keystroke save does not walk it at all.
        """
        conn.execute("DELETE FROM link_targets")
        conn.executemany(
            "INSERT OR IGNORE INTO link_targets (name, path) VALUES (?, ?)",
            [(name, str(path.resolve())) for name, path in scan.link_targets],
        )

    def _touch_link_target(self, conn, path: Path) -> None:
        """Update the names one file provides, after that file changed."""
        conn.execute("DELETE FROM link_targets WHERE path = ?", (str(path),))
        if not path.exists():
            return
        try:
            parts = path.relative_to(self.store.root).parts
        except ValueError:
            return
        if any(
            part.startswith(".") or part in self.store.schema.markdown.link_target_skip
            for part in parts
        ):
            return
        names = [path.name] + ([path.stem] if path.suffix.lower() == ".md" else [])
        conn.executemany(
            "INSERT OR IGNORE INTO link_targets (name, path) VALUES (?, ?)",
            [(name, str(path)) for name in names],
        )

    def _resolve(
        self,
        conn,
        doc_ids: set[int] | None = None,
        names: set[str] | None = None,
    ) -> None:
        """Point every link and parent at the document it names.

        Run after the whole batch rather than per document, because writing a
        new note resolves links that already pointed at it.

        When two documents claim the same title or alias -- a schema violation
        the linter reports -- the tie is broken by taking the greatest path.
        That is not an arbitrary choice: `build_alias_map` walks documents in
        path order and lets the last one win, and the renderers resolve
        through that map. An index that picked the other one would answer
        "which note is [[X]]?" differently from the exported register built
        from the same workspace, and export parity would drift with nothing
        saying why. Ordering by path rather than by row id also survives
        incremental sync, where insertion order stops tracking path order.

        Scope is what keeps a single-file save cheap. Given the documents that
        changed and the names whose meaning they could have altered, only the
        links in those documents and the links pointing at those names are
        revisited -- which is the exact set that can have changed. Passing
        neither re-resolves everything, which is what a full sync wants.
        """
        conn.execute("DELETE FROM fts WHERE doc_id NOT IN (SELECT id FROM documents)")

        # One indexed lookup table instead of a correlated ORDER BY per link.
        # SQLite lets a bare column in a MAX() aggregate come from the row that
        # supplied the maximum, which is exactly the greatest-path rule above.
        conn.execute("DROP TABLE IF EXISTS temp.alias_best")
        conn.execute(
            "CREATE TEMP TABLE alias_best AS "
            "SELECT a.alias AS alias, a.doc_id AS doc_id, MAX(d.path) AS path "
            "FROM aliases a JOIN documents d ON d.id = a.doc_id "
            "GROUP BY a.alias"
        )
        conn.execute("CREATE INDEX temp.alias_best_alias ON alias_best(alias)")

        scoped = doc_ids is not None or names is not None
        id_list = sorted(doc_ids or ())
        name_list = sorted(names or ())

        for table in ("links", "parents"):
            if scoped:
                where = (
                    f" WHERE {table}.doc_id IN ({','.join('?' * len(id_list))}) "
                    f"    OR {table}.target_norm IN ({','.join('?' * len(name_list))})"
                )
                params = (*id_list, *name_list)
            else:
                where = ""
                params = ()

            # Clear first, then set what matches, so a link whose target was
            # deleted goes back to being a placeholder.
            conn.execute(
                f"UPDATE {table} SET target_id = NULL{where}",  # noqa: S608 - literal names
                params,
            )
            conn.execute(
                f"UPDATE {table} SET target_id = ab.doc_id "  # noqa: S608 - literal names
                f"FROM alias_best ab WHERE ab.alias = {table}.target_norm"
                + (where.replace(" WHERE ", " AND ", 1) if where else ""),
                params,
            )

        conn.execute("DROP TABLE temp.alias_best")
