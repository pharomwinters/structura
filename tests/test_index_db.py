"""The index file: created, rebuilt, and disposable."""

from pathlib import Path

import pytest

from structura.index import Database, Index, Indexer, index_path
from structura.index.schema import SCHEMA_VERSION
from structura.stores.markdown import MarkdownStore


def test_the_index_lives_inside_the_workspace(workspace):
    db = Database.open(workspace)
    try:
        assert db.path == workspace / ".structura" / "index.db"
        assert db.path.exists()
    finally:
        db.close()


def test_a_stale_schema_version_rebuilds_rather_than_migrates(workspace, indexer):
    """A cache does not need migrations. Dropping and rebuilding is simpler,
    and keeping it cheap is what proves the index has no authority."""
    indexer.sync()
    indexer.db.writer.execute("UPDATE meta SET value = ? WHERE key = 'schema_version'", ("0",))
    indexer.db.close()

    reopened = Database.open(workspace)
    try:
        row = (
            reopened.reader()
            .execute("SELECT value FROM meta WHERE key = 'schema_version'")
            .fetchone()
        )
        assert int(row[0]) == SCHEMA_VERSION
        assert Index(reopened).document_count() == 0
    finally:
        reopened.close()


def test_a_corrupt_index_is_replaced_rather_than_raising(workspace):
    path = index_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"this is not a database")

    db = Database.open(workspace)
    try:
        assert Index(db).document_count() == 0
    finally:
        db.close()


def test_deleting_the_index_loses_nothing_but_time(workspace, store):
    db = Database.open(workspace)
    Indexer(db, store).sync()
    before = Index(db).documents()
    db.drop()

    rebuilt = Database.open(workspace)
    try:
        Indexer(rebuilt, store).sync()
        after = Index(rebuilt).documents()
    finally:
        rebuilt.close()

    assert [d.path for d in after] == [d.path for d in before]
    assert [d.title for d in after] == [d.title for d in before]


def test_drop_removes_the_wal_sidecars(workspace, store):
    db = Database.open(workspace)
    Indexer(db, store).sync()
    db.drop()
    for suffix in ("", "-wal", "-shm"):
        assert not Path(str(index_path(workspace)) + suffix).exists()


def test_an_in_memory_index_never_touches_disk(workspace):
    db = Database.in_memory(workspace)
    try:
        Indexer(db, MarkdownStore(workspace)).sync()
        assert Index(db).document_count() == 5
    finally:
        db.close()
    assert not index_path(workspace).exists()


@pytest.mark.parametrize("pragma,expected", [("journal_mode", "wal"), ("foreign_keys", 1)])
def test_connection_pragmas(workspace, pragma, expected):
    db = Database.open(workspace)
    try:
        value = db.writer.execute(f"PRAGMA {pragma}").fetchone()[0]
        assert str(value).lower() == str(expected).lower()
    finally:
        db.close()
