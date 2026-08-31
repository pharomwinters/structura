"""Parsing behaviour the ported suite does not already pin down."""

from pathlib import Path

from structura.stores.markdown import build_alias_map, parse_document
from structura.stores.markdown.parse import body_line_offset, extract_links

FRONT = "---\ntype: note\ntitle: T\ndate: 2026-08-14\n---\n\n"


def _doc(text: str, name: str = "T.md"):
    return parse_document(Path(name), text)


def test_embeds_are_links_and_are_flagged_as_embeds():
    doc = _doc(FRONT + "![[Open Items]] and [[Post Rinse 4]]\n")
    assert [(link.target, link.is_embed) for link in doc.links] == [
        ("Open Items", True),
        ("Post Rinse 4", False),
    ]


def test_body_line_offset_counts_the_frontmatter_block():
    """The body group starts immediately after the closing delimiter, so the
    offset is the five lines of `---`, three keys, and `---`."""
    assert body_line_offset(FRONT + "x\n") == 5
    assert body_line_offset("no frontmatter\n") == 0


def test_link_line_numbers_are_file_relative_so_they_agree_with_task_lines():
    doc = _doc(
        FRONT + "first\n\nsee [[X]]\n- [ ] #item Do it [[X]] owner:[[Y]] raised:2026-01-01\n"
    )
    # Three links: the prose one, and both the asset and the owner on the task
    # line -- `owner:[[Y]]` is a wikilink like any other.
    assert [(link.target, link.line_no) for link in doc.links] == [
        ("X", 9),
        ("X", 10),
        ("Y", 10),
    ]
    assert doc.tasks[0].line_no == 10


def test_a_fenced_example_is_neither_a_task_nor_a_link():
    doc = _doc(FRONT + "```\n- [ ] #item example [[Fenced]] owner:[[Y]] raised:2026-01-01\n```\n")
    assert doc.tasks == []
    assert doc.link_targets == []


def test_uid_is_read_from_frontmatter_when_present():
    doc = _doc("---\ntype: note\ntitle: T\nuid: 01ARZ3NDEKTSV4RRFFQ69G5FAV\n---\n\nbody\n")
    assert doc.uid == "01ARZ3NDEKTSV4RRFFQ69G5FAV"


def test_a_malformed_uid_is_treated_as_absent_rather_than_trusted():
    doc = _doc("---\ntype: note\ntitle: T\nuid: 42\n---\n\nbody\n")
    assert doc.uid is None


def test_title_falls_back_to_the_filename():
    assert _doc("---\ntype: note\n---\n\nbody\n", "Post Rinse 4.md").title == "Post Rinse 4"


def test_alias_map_resolves_every_spelling_to_the_canonical_title():
    docs = [
        _doc("---\ntype: asset\ntitle: Post Rinse 4\nalias: PR4, Rinse 4\n---\n\nbody\n"),
        _doc("---\ntype: note\ntitle: Other\n---\n\nbody\n"),
    ]
    amap = build_alias_map(docs)
    assert amap["PR4"] == "Post Rinse 4"
    assert amap["Rinse 4"] == "Post Rinse 4"
    assert amap["Post Rinse 4"] == "Post Rinse 4"
    assert amap["Other"] == "Other"


def test_extract_links_handles_an_empty_body():
    assert extract_links("") == []
