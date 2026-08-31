"""Incremental sync: stat, then hash, then reparse — and only when needed."""

import os
import time

from structura.index import Index
from structura.index.sync import sha256_bytes


def test_a_first_sync_adds_everything(indexer):
    report = indexer.sync()
    assert report.added == 5
    assert report.updated == report.removed == 0
    assert Index(indexer.db).document_count() == 5


def test_a_second_sync_changes_nothing(indexer):
    indexer.sync()
    report = indexer.sync()
    assert (report.added, report.updated, report.removed) == (0, 0, 0)
    assert report.unchanged == 5


def test_a_content_change_is_picked_up(indexer, workspace):
    indexer.sync()
    (workspace / "2-Notes" / "Beta.md").write_text(
        "---\ntype: note\ntitle: Beta\ndate: 2026-08-14\n---\n\nNow links [[Alpha]].\n"
    )
    report = indexer.sync()
    assert (report.added, report.updated, report.removed) == (0, 1, 0)

    index = Index(indexer.db)
    alpha = index.resolve("Alpha")
    assert [d.title for d in index.backlinks(alpha.id)] == ["Beta"]


def test_a_touch_does_not_reparse(indexer, workspace):
    """Same bytes, new mtime. The hash check is what stops a `touch` -- or a
    formatter that rewrites a file identically -- from costing a reparse."""
    indexer.sync()
    path = workspace / "2-Notes" / "Beta.md"
    future = time.time_ns() + 1_000_000_000
    os.utime(path, ns=(future, future))

    report = indexer.sync()
    assert (report.added, report.updated, report.removed) == (0, 0, 0)
    assert report.unchanged == 5


def test_a_touch_is_recorded_so_the_next_pass_is_a_cheap_skip(indexer, workspace):
    indexer.sync()
    path = workspace / "2-Notes" / "Beta.md"
    future = time.time_ns() + 1_000_000_000
    os.utime(path, ns=(future, future))
    indexer.sync()

    row = (
        indexer.db.reader()
        .execute("SELECT mtime_ns FROM documents WHERE path = ?", (str(path.resolve()),))
        .fetchone()
    )
    assert row["mtime_ns"] == future


def test_a_deleted_file_is_removed(indexer, workspace):
    indexer.sync()
    (workspace / "2-Notes" / "Beta.md").unlink()
    report = indexer.sync()
    assert report.removed == 1
    assert Index(indexer.db).resolve("Beta") is None


def test_deleting_a_document_cascades_to_its_rows(indexer, workspace):
    indexer.sync()
    (workspace / "4-Meetings" / "Standup.md").unlink()
    indexer.sync()

    conn = indexer.db.reader()
    for table in ("fields", "tags", "links", "tasks", "parents", "aliases"):
        orphaned = conn.execute(
            f"SELECT COUNT(*) AS n FROM {table} "  # noqa: S608 - literal table name
            "WHERE doc_id NOT IN (SELECT id FROM documents)"
        ).fetchone()["n"]
        assert orphaned == 0, table
    assert (
        conn.execute(
            "SELECT COUNT(*) AS n FROM fts WHERE doc_id NOT IN (SELECT id FROM documents)"
        ).fetchone()["n"]
        == 0
    )


def test_a_new_file_resolves_links_that_already_pointed_at_it(indexer, workspace, write_note):
    """Resolution runs after the batch, not per document, so writing a note
    turns every link that was waiting for it into a real edge."""
    indexer.sync()
    index = Index(indexer.db)
    # `owner:[[Maintenance]]` is a wikilink like any other, and it appears on
    # both task lines, so it outranks the single link to [[Missing]].
    assert [(p.target, p.inbound) for p in index.placeholders()] == [
        ("Maintenance", 2),
        ("Missing", 1),
    ]

    write_note(workspace, "2-Notes/Missing.md")
    indexer.sync()
    assert [p.target for p in index.placeholders()] == ["Maintenance"]

    missing = index.resolve("Missing")
    assert [d.title for d in index.backlinks(missing.id)] == ["Alpha"]


def test_sync_paths_only_touches_what_it_is_given(indexer, workspace):
    indexer.sync()
    path = workspace / "2-Notes" / "Beta.md"
    path.write_text("---\ntype: note\ntitle: Beta\ndate: 2026-08-14\n---\n\nchanged\n")

    report = indexer.sync_paths([path])
    assert (report.added, report.updated, report.removed) == (0, 1, 0)


def test_sync_paths_removes_a_vanished_file(indexer, workspace):
    indexer.sync()
    path = workspace / "2-Notes" / "Beta.md"
    path.unlink()
    report = indexer.sync_paths([path])
    assert report.removed == 1


def test_sync_paths_ignores_a_path_outside_the_store(indexer, workspace):
    """A watcher fires on every file in the tree and most of them are not
    ours. An unknown path must not be read as a deletion."""
    indexer.sync()
    report = indexer.sync_paths([workspace / ".structura" / "index.db"])
    assert (report.added, report.updated, report.removed) == (0, 0, 0)


def test_our_own_write_is_recognised_and_skipped(indexer, workspace, store):
    """Structura records the hash it wrote, so the watcher event its own save
    provokes does not bounce back through the parser."""
    indexer.sync()
    path = workspace / "2-Notes" / "Beta.md"
    text = "---\ntype: note\ntitle: Beta\ndate: 2026-08-14\n---\n\nsaved by us\n"

    written = store.save(path, text, assign_uid=False)
    indexer.sync_paths([path])  # the real write: index it once
    indexer.expect(path, sha256_bytes(written.encode()))

    os.utime(path, ns=(time.time_ns() + 10**9,) * 2)
    report = indexer.sync_paths([path])
    assert report.updated == 0


def test_an_unreadable_file_is_reported_not_raised(indexer, workspace):
    indexer.sync()
    path = workspace / "2-Notes" / "Beta.md"
    path.write_bytes(b"---\ntype: note\n---\n\n\xff\xfe not utf-8\n")

    report = indexer.sync()
    assert report.errors and report.errors[0][0] == path.resolve()
    assert Index(indexer.db).document_count() == 5


def test_a_failed_sync_leaves_the_index_untouched(indexer, workspace, monkeypatch, write_note):
    """The whole pass is one transaction, so a crash halfway cannot leave the
    index describing a workspace that never existed."""
    indexer.sync()
    before = Index(indexer.db).document_count()

    write_note(workspace, "2-Notes/Gamma.md")
    monkeypatch.setattr(
        indexer, "_resolve", lambda conn: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    try:
        indexer.sync()
    except RuntimeError:
        pass

    assert Index(indexer.db).document_count() == before


def test_uids_are_indexed_when_present(indexer, workspace, store):
    path = workspace / "2-Notes" / "Beta.md"
    uid = store.assign_uid(path)
    indexer.sync()
    assert Index(indexer.db).resolve("Beta").uid == uid


def test_a_document_without_a_uid_still_indexes(indexer):
    """Reading never writes, so a workspace is queryable before it is stamped."""
    indexer.sync()
    assert all(d.uid is None for d in Index(indexer.db).documents())
