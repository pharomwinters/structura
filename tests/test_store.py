"""Scanning a workspace: what gets parsed, what gets skipped, what resolves."""

from pathlib import Path

from structura.core.uid import is_uid
from structura.stores.markdown import MarkdownStore

FRONT = "---\ntype: note\ntitle: {title}\ndate: 2026-08-14\n---\n\n"


def _write(root: Path, rel: str, body: str = "body\n", title: str | None = None) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(FRONT.format(title=title or path.stem) + body, encoding="utf-8")
    return path


def test_scans_markdown_and_skips_generated_and_archived(tmp_path):
    _write(tmp_path, "2-Notes/Live.md")
    _write(tmp_path, "0-Index/Open Items.md")
    _write(tmp_path, "6-Archive/Old.md")
    _write(tmp_path, "docs/Guide.md")

    names = {p.name for p in MarkdownStore(tmp_path).paths()}
    assert names == {"Live.md"}


def test_skips_dot_directories_generically(tmp_path):
    """R13: a fixed skip list let 15 phantom notes leak in from tool scratch
    directories, so every path component is checked for a leading dot."""
    _write(tmp_path, "2-Notes/Live.md")
    _write(tmp_path, ".structura/cache/Stale.md")
    _write(tmp_path, ".superpowers/Doc.md")
    _write(tmp_path, ".pytest_cache/Junk.md")

    assert {p.name for p in MarkdownStore(tmp_path).paths()} == {"Live.md"}


def test_link_targets_include_generated_output_but_not_archive(tmp_path):
    """R36: `0-Index/` is excluded from parsing and included as a link target."""
    _write(tmp_path, "0-Index/Open Items.md")
    _write(tmp_path, "6-Archive/Old.md")
    _write(tmp_path, "2-Notes/Live.md")

    names = MarkdownStore(tmp_path).link_target_names()
    assert "Open Items" in names
    assert "Old" not in names
    assert "Live" in names


def test_an_attachment_resolves_only_with_its_extension(tmp_path):
    """R31: adding the bare stem let a wikilink meaning an unwritten note
    silently resolve against a spreadsheet, so it vanished from the promotion
    queue instead of surfacing in it."""
    _write(tmp_path, "2-Notes/Live.md")
    (tmp_path / "3-Resources").mkdir()
    (tmp_path / "3-Resources" / "PFMEA-HierarchyView.xlsx").write_bytes(b"")

    names = MarkdownStore(tmp_path).link_target_names()
    assert "PFMEA-HierarchyView.xlsx" in names
    assert "PFMEA-HierarchyView" not in names


def test_reading_never_writes(tmp_path):
    """Opening a workspace must not stamp a UID onto every file in it: that is
    a surprising amount of git noise and a violation of read-only reads."""
    path = _write(tmp_path, "2-Notes/Live.md")
    before = path.read_bytes()
    docs = MarkdownStore(tmp_path).documents()
    assert docs[0].uid is None
    assert path.read_bytes() == before


def test_assign_uid_backfills_one_file(tmp_path):
    path = _write(tmp_path, "2-Notes/Live.md")
    store = MarkdownStore(tmp_path)
    uid = store.assign_uid(path)
    assert is_uid(uid)
    assert store.load(path).uid == uid
    assert store.assign_uid(path) == uid


def test_save_mints_a_uid(tmp_path):
    store = MarkdownStore(tmp_path)
    path = tmp_path / "New.md"
    written = store.save(path, FRONT.format(title="New") + "body\n")
    assert store.load(path).uid is not None
    assert path.read_text() == written


def test_one_unparseable_document_does_not_hide_the_rest(tmp_path):
    _write(tmp_path, "2-Notes/Good.md")
    (tmp_path / "2-Notes" / "Bad.md").write_text("---\ntype: [unclosed\n---\n\nbody\n")

    store = MarkdownStore(tmp_path)
    docs = store.documents()
    assert len(docs) == 2

    bad = next(d for d in docs if d.path.name == "Bad.md")
    assert bad.frontmatter_error is not None
    problems = store.validate(docs)
    assert len(problems) == 1
    assert problems[0].code == "frontmatter-unparseable"
    assert problems[0].path == bad.path


def test_violations_carry_a_line_number_for_the_editor_to_jump_to(tmp_path):
    _write(
        tmp_path,
        "2-Notes/Obs.md",
        body="- [ ] #item Do a thing raised:2026-01-01\n",
    )
    problems = MarkdownStore(tmp_path).validate()
    assert {p.code for p in problems} == {"task-no-asset", "task-no-owner"}
    assert all(p.line == 7 for p in problems)


def test_links_carry_file_relative_line_numbers(tmp_path):
    path = _write(tmp_path, "2-Notes/Live.md", body="See [[Post Rinse 4]].\n")
    doc = MarkdownStore(tmp_path).load(path)
    assert [(link.target, link.line_no) for link in doc.links] == [("Post Rinse 4", 7)]


def test_a_wikilink_in_frontmatter_is_not_collected_as_a_link(tmp_path):
    """Links live in bodies. Frontmatter links are a violation, not an edge."""
    path = tmp_path / "M.md"
    path.write_text(
        "---\ntype: meeting\ntitle: M\ndate: 2026-08-14\n"
        "attendees:\n  - '[[Houston Lamb]]'\n---\n\nSpoke to [[Houston Lamb]].\n"
    )
    store = MarkdownStore(tmp_path)
    doc = store.load(path)
    assert doc.link_targets == ["Houston Lamb"]
    assert doc.links[0].line_no == 9
    assert [p.code for p in store.validate([doc])] == ["wikilink-in-frontmatter"]
