"""Completion over the command line.

Phase 3 puts this behind Tab. It is tested headless because knowing what can
come next is a query concern, not a terminal one.
"""

from structura.query import complete


def names(text, index=None):
    return [c.text for c in complete(text, index)]


def test_an_empty_line_offers_only_sources():
    """`where` cannot start a pipeline, so it must not be offered as one."""
    offered = names("")
    assert "find" in offered and "tasks" in offered
    assert "where" not in offered and "table" not in offered


def test_a_partial_verb_narrows_and_still_respects_position():
    """`table` also starts with `ta`, and is not offered here because nothing
    can render rows that no stage has produced yet."""
    assert names("ta") == ["tasks"]
    assert "table" in names("find | ta")


def test_after_a_pipe_only_verbs_that_accept_what_is_coming():
    offered = names("find type:asset | ")
    assert "backlinks" in offered and "where" in offered
    assert "find" not in offered, "a source cannot follow a stage"


def test_a_verb_that_cannot_accept_the_incoming_kind_is_not_offered():
    assert "tree" not in names("tasks | ")
    assert "tree" in names("find | ")


def test_verbs_that_have_not_arrived_are_never_offered():
    assert "set" not in names("find | ")
    assert "events" not in names("")


def test_a_verbs_own_keys_are_offered():
    offered = names("find ")
    assert "type:" in offered and "area:" in offered


def test_where_offers_the_fields_the_incoming_rows_have():
    assert "owner:" in names("tasks | where ")
    assert "owner:" not in names("find | where ")


def test_sort_offers_fields_then_directions():
    assert "age" in names("tasks | sort ")
    assert "desc" in names("tasks | sort age ")


def test_tasks_offers_its_states():
    assert set(names("tasks ")) >= {"open", "done", "all"}


def test_flags_are_offered():
    assert "--rebuild" in names("reindex ")


def test_values_come_from_the_index(index):
    assert "asset" in names("find type:", index)
    assert "paint" in names("find area:", index)


def test_values_narrow_on_what_is_typed(index):
    assert names("find type:as", index) == ["asset"]


def test_completion_without_an_index_offers_no_values():
    assert names("find type:") == []


def test_completion_never_raises_on_half_typed_input():
    for text in ('grep "unclosed', "find |", "|", "find type:", "--", "find [[", "  "):
        assert isinstance(complete(text), list)


def test_an_unknown_verb_offers_nothing_rather_than_guessing():
    assert names("frobnicate ") == []
