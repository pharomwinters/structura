"""Acceptance test 3: round-trip fidelity, plus the conflict rules.

*"Open each note in source mode and save each without editing → the working
tree stays empty."* That is the test that keeps the no-reformatting promise
honest, and it is the phase 3 gate.

It runs headless, against the buffer the editor pane wraps, because the part
worth testing is not the widget.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from structura.app import ConflictError, DocumentBuffer
from structura.stores.markdown import MarkdownStore

AWKWARD = {
    "plain.md": "---\ntype: note\ntitle: Plain\ndate: 2026-08-14\n---\n\nbody\n",
    "quoted.md": '---\ntype: note\ntitle: "Quoted: with a colon"\ndate: 2026-08-14\n---\n\nx\n',
    "listy.md": (
        "---\ntype: meeting\ntitle: Listy\ndate: 2026-08-14\n"
        "attendees:\n  - one\n  - two\n---\n\nx\n"
    ),
    "no-frontmatter.md": "Just prose, no frontmatter at all.\n",
    "no-trailing-newline.md": "---\ntype: note\ntitle: NoNewline\n---\n\nbody",
    "blank-lines.md": "---\ntype: note\ntitle: Blanks\n---\n\n\n\nbody\n\n\n",
    "tabs.md": "---\ntype: note\ntitle: Tabs\n---\n\n\tindented with a tab\n",
    "unicode.md": "---\ntype: note\ntitle: Únïcodé — Nótt\n---\n\nnaïve café — ok\n",
    "wide.md": (
        "---\ntype: note\ntitle: Wide\n---\n\n"
        + "A very long unwrapped paragraph that a formatter would love to reflow. " * 6
        + "\n"
    ),
    "trailing-space.md": "---\ntype: note\ntitle: Trailing\n---\n\nline with a space \n",
    "fenced.md": (
        "---\ntype: note\ntitle: Fenced\n---\n\n"
        "```\n- [ ] #item example [[X]] owner:[[Y]] raised:2026-01-01\n```\n"
    ),
    "crlf.md": "---\r\ntype: note\r\ntitle: Crlf\r\n---\r\n\r\nbody\r\n",
    "with-uid.md": ("---\ntype: note\ntitle: HasUid\nuid: 01ARZ3NDEKTSV4RRFFQ69G5FAV\n---\n\nx\n"),
}


@pytest.fixture
def awkward(tmp_path: Path) -> Path:
    for name, text in AWKWARD.items():
        (tmp_path / name).write_bytes(text.encode("utf-8"))
    return tmp_path


# --- acceptance test 3 ------------------------------------------------


def test_opening_and_saving_without_editing_changes_nothing(awkward):
    """The whole promise, over every shape of file that tempts a rewrite."""
    store = MarkdownStore(awkward)
    before = {p: p.read_bytes() for p in sorted(awkward.iterdir())}

    for path in before:
        buffer = DocumentBuffer.open(store, path)
        buffer.save(assign_uid=False)

    after = {p: p.read_bytes() for p in sorted(awkward.iterdir())}
    changed = [p.name for p in before if before[p] != after[p]]
    assert changed == [], f"saving without editing rewrote: {changed}"


def test_an_untouched_save_does_not_even_write(awkward):
    """Stronger than "the bytes match": there is no code path that could have
    rewritten them, so a save cannot bump an mtime and set the watcher off."""
    store = MarkdownStore(awkward)
    path = awkward / "plain.md"
    before = os.stat(path).st_mtime_ns

    time.sleep(0.01)
    DocumentBuffer.open(store, path).save(assign_uid=False)
    assert os.stat(path).st_mtime_ns == before


def test_a_uid_is_the_only_thing_a_first_save_adds(awkward):
    store = MarkdownStore(awkward)
    path = awkward / "plain.md"
    original = path.read_text(encoding="utf-8")

    DocumentBuffer.open(store, path).save()
    updated = path.read_text(encoding="utf-8")

    added = [line for line in updated.splitlines() if line not in original.splitlines()]
    assert len(added) == 1 and added[0].startswith("uid: ")


def test_a_document_that_already_has_a_uid_is_untouched_by_a_save(awkward):
    store = MarkdownStore(awkward)
    path = awkward / "with-uid.md"
    original = path.read_bytes()
    DocumentBuffer.open(store, path).save()
    assert path.read_bytes() == original


# --- editing ----------------------------------------------------------


def test_a_buffer_knows_when_it_is_dirty(awkward):
    store = MarkdownStore(awkward)
    buffer = DocumentBuffer.open(store, awkward / "plain.md")
    assert not buffer.is_dirty

    buffer.set_text(buffer.text + "more\n")
    assert buffer.is_dirty


def test_an_edit_writes_and_the_buffer_settles(awkward):
    store = MarkdownStore(awkward)
    path = awkward / "plain.md"
    buffer = DocumentBuffer.open(store, path)

    buffer.set_text(buffer.text + "another line\n")
    buffer.save(assign_uid=False)

    assert not buffer.is_dirty
    assert "another line" in path.read_text(encoding="utf-8")


def test_the_parse_follows_the_buffer(awkward):
    store = MarkdownStore(awkward)
    buffer = DocumentBuffer.open(store, awkward / "plain.md")
    assert buffer.parsed.title == "Plain"

    buffer.set_text(buffer.text.replace("title: Plain", "title: Renamed"))
    assert buffer.reparse().title == "Renamed"


# --- an unsaved buffer ------------------------------------------------


def test_an_unsaved_buffer_writes_on_first_save(tmp_path):
    """Startup opens today's journal this way, so launching the application on
    a day you did no work does not seed an empty daily note."""
    store = MarkdownStore(tmp_path)
    path = tmp_path / "5-Journal" / "2026-08-31.md"
    buffer = DocumentBuffer.unsaved(store, path, "---\ntype: note\ntitle: Today\n---\n\n")

    assert buffer.is_new
    assert not path.exists()

    buffer.save()
    assert path.exists()
    assert not buffer.is_new


# --- conflicts --------------------------------------------------------


def test_saving_over_an_outside_change_raises_rather_than_clobbering(awkward):
    store = MarkdownStore(awkward)
    path = awkward / "plain.md"
    buffer = DocumentBuffer.open(store, path)
    buffer.set_text(buffer.text + "mine\n")

    path.write_text("---\ntype: note\ntitle: Plain\n---\n\ntheirs\n", encoding="utf-8")

    with pytest.raises(ConflictError) as excinfo:
        buffer.save()
    assert "plain.md changed on disk" in str(excinfo.value)
    assert "theirs" in path.read_text(encoding="utf-8"), "the other edit was clobbered"


def test_a_conflict_carries_the_time_a_prompt_has_to_show(awkward):
    store = MarkdownStore(awkward)
    path = awkward / "plain.md"
    buffer = DocumentBuffer.open(store, path)
    path.write_text("changed\n", encoding="utf-8")

    with pytest.raises(ConflictError) as excinfo:
        buffer.save()
    assert excinfo.value.path == path
    assert excinfo.value.disk_modified is not None


def test_force_overwrites_when_the_person_says_so(awkward):
    store = MarkdownStore(awkward)
    path = awkward / "plain.md"
    buffer = DocumentBuffer.open(store, path)
    buffer.set_text("---\ntype: note\ntitle: Plain\n---\n\nmine\n")
    path.write_text("theirs\n", encoding="utf-8")

    buffer.save(force=True, assign_uid=False)
    assert "mine" in path.read_text(encoding="utf-8")


def test_reload_takes_the_disk_and_drops_the_edits(awkward):
    store = MarkdownStore(awkward)
    path = awkward / "plain.md"
    buffer = DocumentBuffer.open(store, path)
    buffer.set_text("mine\n")
    path.write_text("---\ntype: note\ntitle: Plain\n---\n\ntheirs\n", encoding="utf-8")

    buffer.reload()
    assert "theirs" in buffer.text
    assert not buffer.is_dirty
    buffer.save(assign_uid=False)


def test_save_a_copy_loses_nothing(awkward):
    store = MarkdownStore(awkward)
    path = awkward / "plain.md"
    buffer = DocumentBuffer.open(store, path)
    buffer.set_text("mine\n")
    path.write_text("theirs\n", encoding="utf-8")

    copy = buffer.save_a_copy()
    assert copy.name == "plain.conflict.md"
    assert copy.read_text(encoding="utf-8") == "mine\n"
    assert path.read_text(encoding="utf-8") == "theirs\n"


def test_save_a_copy_does_not_overwrite_an_earlier_copy(awkward):
    store = MarkdownStore(awkward)
    buffer = DocumentBuffer.open(store, awkward / "plain.md")
    buffer.set_text("one\n")
    first = buffer.save_a_copy()
    buffer.set_text("two\n")
    second = buffer.save_a_copy()

    assert first != second
    assert first.read_text(encoding="utf-8") == "one\n"


def test_a_rewrite_with_identical_content_is_not_a_conflict(awkward):
    """A formatter that rewrote a file identically, or a `touch`, must not
    interrupt anyone."""
    store = MarkdownStore(awkward)
    path = awkward / "plain.md"
    buffer = DocumentBuffer.open(store, path)
    buffer.set_text(buffer.text + "mine\n")

    path.write_bytes(path.read_bytes())
    buffer.save(assign_uid=False)
    assert "mine" in path.read_text(encoding="utf-8")
