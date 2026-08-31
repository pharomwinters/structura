"""Lexing a command line."""

import pytest

from structura.query.errors import ParseError
from structura.query.lexer import Kind, tokenize


def kinds(text):
    return [t.kind for t in tokenize(text)]


def texts(text):
    return [t.value.text if t.value else "|" for t in tokenize(text)]


def test_a_bare_verb():
    tokens = tokenize("find")
    assert kinds("find") == [Kind.VALUE]
    assert tokens[0].value.text == "find"


def test_conditions_split_on_the_operator():
    token = tokenize("find type:asset")[1]
    assert (token.kind, token.key, token.op, token.value.text) == (
        Kind.CONDITION,
        "type",
        ":",
        "asset",
    )


@pytest.mark.parametrize("op", [":", "=", "!=", ">", ">=", "<", "<="])
def test_every_operator(op):
    token = tokenize(f"tasks age{op}90")[1]
    assert (token.key, token.op, token.value.text) == ("age", op, "90")


def test_a_quoted_string_is_one_value():
    assert texts('grep "riser pressure"') == ["grep", "riser pressure"]


def test_a_quoted_value_is_never_split_on_an_operator():
    """`grep "a:b"` searches for `a:b`; it does not filter on a key named a."""
    tokens = tokenize('grep "a:b"')
    assert tokens[1].kind is Kind.VALUE
    assert tokens[1].value.text == "a:b"


def test_a_quote_can_be_escaped():
    assert texts(r'grep "say \"hello\""') == ["grep", 'say "hello"']


def test_a_wikilink_value():
    token = tokenize("tasks owner:[[Houston Lamb]]")[1]
    assert token.value.wikilink is True
    assert token.value.text == "Houston Lamb"


def test_a_key_must_look_like_an_identifier():
    """`10:30` is a time, not a condition on a key named `10`."""
    tokens = tokenize("grep 10:30")
    assert tokens[1].kind is Kind.VALUE
    assert tokens[1].value.text == "10:30"


def test_flags_with_and_without_a_value():
    bare, valued = tokenize("reindex --rebuild --out=x")[1:]
    assert (bare.flag, bare.value) == ("rebuild", None)
    assert (valued.flag, valued.value.text) == ("out", "x")


def test_pipes_separate_stages():
    assert kinds("find | table").count(Kind.PIPE) == 1


def test_a_pipe_needs_no_surrounding_spaces():
    assert texts("find|table") == ["find", "|", "table"]


def test_offsets_point_at_the_token():
    tokens = tokenize("find type:asset")
    assert [t.offset for t in tokens] == [0, 5]


def test_an_unterminated_string_says_where():
    with pytest.raises(ParseError) as excinfo:
        tokenize('grep "unclosed')
    assert excinfo.value.offset == 5
    assert "unterminated" in excinfo.value.message


def test_an_unterminated_wikilink_says_where():
    with pytest.raises(ParseError, match="unterminated wikilink"):
        tokenize("tasks owner:[[Nope")


def test_a_flag_needs_a_name():
    with pytest.raises(ParseError, match="expected a flag name"):
        tokenize("reindex --")
