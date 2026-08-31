"""Shared workspace fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from structura.index import Database, Index, Indexer
from structura.stores.markdown import MarkdownStore

FRONT = "---\ntype: {dtype}\ntitle: {title}\ndate: 2026-08-14\n{extra}---\n\n"


def _write_note(
    root: Path,
    rel: str,
    *,
    dtype: str = "note",
    title: str | None = None,
    body: str = "body\n",
    **extra: str,
) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = "".join(f"{key}: {value}\n" for key, value in extra.items())
    path.write_text(
        FRONT.format(dtype=dtype, title=title or path.stem, extra=lines) + body,
        encoding="utf-8",
    )
    return path


@pytest.fixture
def write_note():
    """The note-writing helper, as a fixture so test modules need no package."""
    return _write_note


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    _write_note(tmp_path, "2-Notes/Alpha.md", body="Links to [[Beta]] and [[Missing]].\n")
    _write_note(tmp_path, "2-Notes/Beta.md", tags="pressure, overnight")
    _write_note(
        tmp_path,
        "1-Assets/Post Rinse 4.md",
        dtype="asset",
        area="paint",
        status="operating",
        alias="PR4",
        body="Part of [[Paint Line]]\n",
    )
    _write_note(tmp_path, "1-Assets/Paint Line.md", dtype="asset", area="paint")
    _write_note(
        tmp_path,
        "4-Meetings/Standup.md",
        dtype="observation",
        area="wwt",
        status="open",
        body=(
            "Saw a thing on [[PR4]].\n"
            "- [ ] #item Diagnose riser [[PR4]] owner:[[Maintenance]] raised:2026-06-01\n"
            "- [x] #item Old work [[Paint Line]] owner:[[Maintenance]] raised:2026-01-01\n"
        ),
    )
    return tmp_path


@pytest.fixture
def store(workspace: Path) -> MarkdownStore:
    return MarkdownStore(workspace)


@pytest.fixture
def db(workspace: Path):
    database = Database.open(workspace)
    yield database
    database.close()


@pytest.fixture
def indexer(db, store) -> Indexer:
    return Indexer(db, store)


@pytest.fixture
def index(indexer) -> Index:
    indexer.sync()
    return Index(indexer.db)
