"""The watcher: external edits reach the index without a keystroke."""

from __future__ import annotations

import time

from structura.index import Index
from structura.index.watch import Watcher


def _wait_for(predicate, timeout: float = 5.0, interval: float = 0.02) -> bool:
    """Poll rather than sleep a fixed time, so the test is neither flaky on a
    loaded machine nor slow on a fast one."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def test_enqueue_and_drain_without_an_observer(indexer, workspace, write_note):
    """The queue and the sync are testable without touching the filesystem
    watcher, which is the part that varies by platform."""
    indexer.sync()
    watcher = Watcher(indexer)

    write_note(workspace, "2-Notes/Gamma.md")
    watcher.enqueue(workspace / "2-Notes" / "Gamma.md")

    report = watcher.drain()
    assert report is not None and report.added == 1
    assert Index(indexer.db).resolve("Gamma") is not None


def test_drain_with_nothing_pending_is_a_no_op(indexer):
    indexer.sync()
    assert Watcher(indexer).drain() is None


def test_non_markdown_events_are_ignored(indexer, workspace):
    """A watcher fires on every file in the tree. Only notes are ours."""
    indexer.sync()
    watcher = Watcher(indexer)
    watcher.enqueue(workspace / ".structura" / "index.db")
    watcher.enqueue(workspace / "notes.txt")
    assert watcher.take_pending() == set()


def test_repeated_events_for_one_file_collapse(indexer, workspace):
    """Editors write a temp file, rename it, and touch the mtime. Syncing per
    raw event would reparse the same document three times per save."""
    indexer.sync()
    watcher = Watcher(indexer)
    path = workspace / "2-Notes" / "Beta.md"
    for _ in range(5):
        watcher.enqueue(path)
    assert watcher.take_pending() == {path.resolve()}


def test_an_external_edit_reaches_the_index(indexer, workspace):
    """End to end, through the real filesystem watcher."""
    indexer.sync()
    index = Index(indexer.db)

    with Watcher(indexer, debounce_s=0.05, max_wait_s=0.2):
        (workspace / "2-Notes" / "External.md").write_text(
            "---\ntype: note\ntitle: External\ndate: 2026-08-14\n---\n\nwritten elsewhere\n",
            encoding="utf-8",
        )
        assert _wait_for(lambda: index.resolve("External") is not None), (
            "the watcher did not pick up a new file"
        )


def test_an_external_delete_reaches_the_index(indexer, workspace):
    indexer.sync()
    index = Index(indexer.db)

    with Watcher(indexer, debounce_s=0.05, max_wait_s=0.2):
        (workspace / "2-Notes" / "Beta.md").unlink()
        assert _wait_for(lambda: index.resolve("Beta") is None), (
            "the watcher did not pick up a deletion"
        )


def test_the_watcher_reports_what_it_did(indexer, workspace):
    seen: list[object] = []
    indexer.sync()

    with Watcher(indexer, on_sync=seen.append, debounce_s=0.05, max_wait_s=0.2):
        (workspace / "2-Notes" / "Delta.md").write_text(
            "---\ntype: note\ntitle: Delta\ndate: 2026-08-14\n---\n\nbody\n",
            encoding="utf-8",
        )
        assert _wait_for(lambda: bool(seen))

    assert seen[0].added == 1


def test_stopping_a_watcher_that_never_started_is_safe(indexer):
    Watcher(indexer).stop()


def test_a_watcher_can_be_started_twice_without_doubling_up(indexer, workspace):
    watcher = Watcher(indexer, debounce_s=0.05)
    try:
        watcher.start()
        watcher.start()
    finally:
        watcher.stop()
