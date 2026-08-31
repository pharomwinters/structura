"""Writing back changes only the bytes that changed.

Acceptance test 3 in the design is that opening every document and saving it
without editing leaves the working tree empty. That test belongs to phase 3,
when there is an editor to open things with, but the module it depends on is
this one, so its promise is tested here from the start.
"""

from structura.core.uid import is_uid
from structura.stores.markdown import serialize

NOTE = (
    "---\n"
    "type: observation\n"
    'title: "Riser pressure drop"\n'
    "date: 2026-08-14\n"
    "area: wwt\n"
    "tags:\n"
    "  - pressure\n"
    "  - overnight\n"
    "---\n"
    "\n"
    "Riser pressure dropped during the overnight cycle.\n"
)


def test_setting_a_field_touches_only_that_line():
    updated = serialize.set_field(NOTE, "area", "paint")
    before = NOTE.splitlines()
    after = updated.splitlines()
    assert len(before) == len(after)
    differing = [i for i, (a, b) in enumerate(zip(before, after, strict=True)) if a != b]
    assert differing == [4]
    assert after[4] == "area: paint"


def test_quoting_and_key_order_are_left_alone():
    """The whole reason frontmatter is never re-dumped through the YAML
    serializer: a round trip would requote, reorder, and rewrap."""
    updated = serialize.set_field(NOTE, "date", "2026-09-01")
    assert 'title: "Riser pressure drop"' in updated
    assert updated.index("type:") < updated.index("title:") < updated.index("date:")
    assert "  - pressure\n  - overnight\n" in updated


def test_a_nested_key_is_not_mistaken_for_a_top_level_one():
    text = "---\nmeta:\n  area: wwt\narea: paint\n---\n\nbody\n"
    updated = serialize.set_field(text, "area", "monorail")
    assert "  area: wwt" in updated
    assert "area: monorail" in updated


def test_a_new_field_is_appended_as_one_line():
    updated = serialize.set_field(NOTE, "status", "contained")
    assert updated.splitlines()[-4:] == [
        "status: contained",
        "---",
        "",
        "Riser pressure dropped during the overnight cycle.",
    ]
    assert updated.startswith("---\ntype: observation\n")


def test_a_file_with_no_frontmatter_gains_one_without_losing_its_body():
    updated = serialize.set_field("Just prose.\n", "type", "note")
    assert updated == "---\ntype: note\n---\nJust prose.\n"


def test_crlf_survives():
    """Rewriting line endings is exactly the whole-file churn this prevents."""
    crlf = NOTE.replace("\n", "\r\n")
    updated = serialize.set_field(crlf, "area", "paint")
    assert updated.replace("\r\n", "").count("\n") == 0, "a bare LF crept in"
    assert updated.count("\r\n") == crlf.count("\r\n")
    assert "area: paint\r\n" in updated


def test_ensure_uid_mints_one_and_leaves_the_rest_alone():
    updated, uid = serialize.ensure_uid(NOTE)
    assert is_uid(uid)
    assert f"uid: {uid}" in updated
    assert updated.splitlines()[:5] == NOTE.splitlines()[:5]
    assert updated.endswith("Riser pressure dropped during the overnight cycle.\n")


def test_ensure_uid_is_idempotent():
    once, uid = serialize.ensure_uid(NOTE)
    twice, again = serialize.ensure_uid(once)
    assert twice == once
    assert again == uid


def test_a_malformed_uid_is_replaced_rather_than_trusted():
    text = "---\ntype: note\nuid: not-a-ulid\n---\n\nbody\n"
    updated, uid = serialize.ensure_uid(text)
    assert is_uid(uid)
    assert "not-a-ulid" not in updated


def test_a_quoted_uid_is_recognised():
    text = '---\ntype: note\nuid: "01ARZ3NDEKTSV4RRFFQ69G5FAV"\n---\n\nbody\n'
    updated, uid = serialize.ensure_uid(text)
    assert uid == "01ARZ3NDEKTSV4RRFFQ69G5FAV"
    assert updated == text
