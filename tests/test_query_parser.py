"""Parsing tokens into a pipeline."""

import pytest

from structura.query.errors import ParseError
from structura.query.parser import parse


def test_stages_split_on_pipes():
    pipeline = parse("find type:asset | backlinks | table")
    assert [s.verb for s in pipeline.stages] == ["find", "backlinks", "table"]


def test_a_stage_keeps_its_parts_apart():
    stage = parse('grep "riser" area:wwt --all').stages[0]
    assert stage.verb == "grep"
    assert [v.text for v in stage.positionals] == ["riser"]
    assert [(c.key, c.op, c.value.text) for c in stage.conditions] == [("area", ":", "wwt")]
    assert stage.flag("all")


def test_an_empty_pipeline_is_an_error():
    with pytest.raises(ParseError, match="empty pipeline"):
        parse("   ")


def test_a_trailing_pipe_says_what_is_wrong():
    with pytest.raises(ParseError) as excinfo:
        parse("find |")
    assert "a `|` must have a verb on both sides" in excinfo.value.message


def test_a_doubled_pipe_is_an_error():
    with pytest.raises(ParseError, match="empty stage"):
        parse("find || table")


def test_a_stage_must_begin_with_a_verb():
    with pytest.raises(ParseError, match="must begin with a verb"):
        parse("type:asset")


def test_a_verb_cannot_be_quoted():
    with pytest.raises(ParseError, match="cannot be quoted"):
        parse('"find" type:asset')


def test_errors_render_a_caret_under_the_problem():
    try:
        parse('grep "unclosed')
    except ParseError as exc:
        rendered = exc.render()
    assert 'grep "unclosed' in rendered
    assert rendered.rstrip().endswith("^")
