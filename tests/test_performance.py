"""The performance budget, measured rather than argued about.

The design states numbers so they can be checked. These are the phase 1 ones,
against the reference workspace size the budget names.

Marked slow because the fixture is 5,000 files. Deselect with `-m "not slow"`;
do not delete, because a budget nobody measures is a wish.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from structura.index import Database, Indexer
from structura.stores.markdown import MarkdownStore

DOCUMENTS = 5000
COLD_BUDGET_S = 2.0
INCREMENTAL_BUDGET_S = 0.020

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def big_workspace(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("big")
    for i in range(DOCUMENTS):
        group = root / f"g{i % 50}"
        group.mkdir(exist_ok=True)
        (group / f"Note {i}.md").write_text(
            f"---\ntype: note\ntitle: Note {i}\ndate: 2026-08-14\narea: paint\n---\n\n"
            f"Body about pumps and valves. See [[Note {(i + 1) % DOCUMENTS}]].\n"
            f"- [ ] #item Do {i} [[Note {i}]] owner:[[Maintenance]] raised:2026-06-01\n",
            encoding="utf-8",
        )
    return root


def test_cold_reindex_is_within_budget(big_workspace):
    db = Database.in_memory(big_workspace)
    try:
        report = Indexer(db, MarkdownStore(big_workspace)).sync()
        assert report.added == DOCUMENTS
        assert report.elapsed_s < COLD_BUDGET_S, (
            f"cold reindex of {DOCUMENTS} documents took {report.elapsed_s:.2f}s, "
            f"budget is {COLD_BUDGET_S}s"
        )
    finally:
        db.close()


def test_incremental_reindex_of_one_document_is_within_budget(big_workspace):
    """The one that governs whether editing feels immediate.

    It was 183 ms the first time it was measured, for two reasons worth
    remembering: link resolution re-ran over the whole workspace on every
    save, and the membership check walked the entire directory tree to decide
    whether one file belonged to the store.
    """
    db = Database.in_memory(big_workspace)
    try:
        store = MarkdownStore(big_workspace)
        indexer = Indexer(db, store)
        indexer.sync()

        path = big_workspace / "g0" / "Note 0.md"
        timings = []
        for n in range(5):
            path.write_text(path.read_text() + f"\nedit {n}\n", encoding="utf-8")
            report = indexer.sync_paths([path])
            assert report.updated == 1
            timings.append(report.elapsed_s)

        median = sorted(timings)[len(timings) // 2]
        assert median < INCREMENTAL_BUDGET_S, (
            f"incremental reindex took {median * 1000:.0f} ms, "
            f"budget is {INCREMENTAL_BUDGET_S * 1000:.0f} ms"
        )
    finally:
        db.close()


def test_an_unchanged_workspace_costs_a_stat_per_file(big_workspace):
    """A second sync must not reparse anything. This is the check that a
    formatter run, or a `touch`, cannot turn into a full reindex."""
    db = Database.in_memory(big_workspace)
    try:
        indexer = Indexer(db, MarkdownStore(big_workspace))
        indexer.sync()
        report = indexer.sync()
        assert (report.added, report.updated, report.removed) == (0, 0, 0)
        assert report.unchanged == DOCUMENTS
    finally:
        db.close()


def test_a_query_over_the_big_workspace_is_immediate(big_workspace):
    from structura.index import Index

    db = Database.in_memory(big_workspace)
    try:
        Indexer(db, MarkdownStore(big_workspace)).sync()
        index = Index(db)

        started = time.perf_counter()
        results = index.search("valves")
        elapsed = time.perf_counter() - started

        assert len(results) == DOCUMENTS
        assert elapsed < 0.5, f"full-text search took {elapsed * 1000:.0f} ms"
    finally:
        db.close()
