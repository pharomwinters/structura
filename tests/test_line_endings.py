"""Line endings, which the target platform makes load-bearing.

`Path.read_text` applies universal newlines and silently turns a CRLF file
into an LF one. Structura writes back only the bytes it changed, so a line
ending it never saw is one it would destroy on the next save — on Windows,
where CRLF files are most likely, and which is the platform this ships on.

The bug was invisible on Linux and appeared within minutes of running the
suite on the target machine. These tests are what stop it coming back.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from structura.index import Database, Index, Indexer
from structura.stores.markdown import MarkdownStore, serialize

LF_NOTE = "---\ntype: note\ntitle: Endings\ndate: 2026-08-14\n---\n\nbody\n"


def crlf(text: str) -> str:
    """CRLF built at runtime, so this file carries no line-ending escapes of
    its own for an editor or a formatter to normalise."""
    return text.replace("\n", "\r\n")


def _write(path: Path, text: str) -> bytes:
    path.write_bytes(text.encode("utf-8"))
    return path.read_bytes()


def test_reading_preserves_crlf(tmp_path):
    path = tmp_path / "Crlf.md"
    _write(path, crlf(LF_NOTE))

    doc = MarkdownStore(tmp_path).load(path)
    assert doc.raw_text == crlf(LF_NOTE)
    assert (doc.title, doc.dtype) == ("Endings", "note")


def test_a_crlf_document_round_trips_byte_for_byte(tmp_path):
    """Acceptance test 3 for the line-ending case: open, save without editing,
    and the file is unchanged."""
    path = tmp_path / "Crlf.md"
    original = _write(path, crlf(LF_NOTE))

    store = MarkdownStore(tmp_path)
    store.save(path, store.load(path).raw_text, assign_uid=False)
    assert path.read_bytes() == original


def test_an_lf_document_round_trips_byte_for_byte(tmp_path):
    path = tmp_path / "Lf.md"
    original = _write(path, LF_NOTE)

    store = MarkdownStore(tmp_path)
    store.save(path, store.load(path).raw_text, assign_uid=False)
    assert path.read_bytes() == original


def test_stamping_a_uid_on_a_crlf_document_keeps_crlf(tmp_path):
    path = tmp_path / "Crlf.md"
    _write(path, crlf(LF_NOTE))
    MarkdownStore(tmp_path).assign_uid(path)

    data = path.read_bytes()
    assert data.count(b"\n") == data.count(b"\r\n"), "a bare LF crept in"


def test_stamping_a_uid_on_an_lf_document_keeps_lf(tmp_path):
    path = tmp_path / "Lf.md"
    _write(path, LF_NOTE)
    MarkdownStore(tmp_path).assign_uid(path)
    assert b"\r" not in path.read_bytes()


def test_editing_a_field_in_a_crlf_document_keeps_crlf(tmp_path):
    text = crlf(LF_NOTE)
    updated = serialize.set_field(text, "area", "paint")
    assert updated.count("\n") == updated.count("\r\n")
    assert "area: paint\r\n" in updated


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_the_index_agrees_with_the_file_whatever_its_line_endings(tmp_path, newline):
    body = "See [[Other]].\n- [ ] #item Do it [[X]] owner:[[Y]] raised:2026-06-01\n"
    path = tmp_path / "Doc.md"
    _write(path, (LF_NOTE.replace("body\n", body)).replace("\n", newline))

    db = Database.in_memory(tmp_path)
    try:
        store = MarkdownStore(tmp_path)
        Indexer(db, store).sync()
        index = Index(db)

        doc = index.resolve("Endings")
        assert doc is not None
        assert [target for target, _ in index.links_from(doc.id)] == ["Other", "X", "Y"]
        tasks = index.tasks()
        assert len(tasks) == 1
        assert tasks[0].description == "Do it"
    finally:
        db.close()


def test_a_mixed_ending_document_is_left_exactly_as_found(tmp_path):
    """Nothing normalises a file Structura did not ask to change, including a
    file that is inconsistent with itself."""
    path = tmp_path / "Mixed.md"
    original = _write(path, "---\ntype: note\r\ntitle: Mixed\ndate: 2026-08-14\r\n---\n\nbody\r\n")

    store = MarkdownStore(tmp_path)
    store.save(path, store.load(path).raw_text, assign_uid=False)
    assert path.read_bytes() == original
