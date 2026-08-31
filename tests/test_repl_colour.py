"""The command line's half of the theme, where it meets the REPL.

The rule these exist to hold: **colour is the last thing that happens, and
only on the way to a terminal.** `export` writes what the formatter produced
and that output is compared byte for byte against the legacy renderer, so an
escape sequence anywhere upstream of the formatter would fail export parity.
"""

from __future__ import annotations

import io

from structura.query import run
from structura.repl import Repl, colourise
from structura.theme import load
from structura.theme.ansi import Palette

ESC = "\033["


def _coloured(context) -> Repl:
    return Repl(context, use_readline=False, palette=Palette(load(), enabled=True))


def _plain(context) -> Repl:
    return Repl(context, use_readline=False, palette=Palette.off())


def test_a_table_is_coloured_on_a_terminal(context):
    output, _ = _coloured(context).execute("find type:asset | table title")
    assert ESC in output
    assert "Post Rinse 4" in output


def test_the_same_table_is_clean_in_a_pipe(context):
    output, _ = _plain(context).execute("find type:asset | table title")
    assert ESC not in output
    assert "Post Rinse 4" in output


def test_an_error_paints_the_message_and_the_caret_but_not_the_echo(context):
    """Painting the echoed line too would make the user's own text look like
    part of the complaint."""
    output, _ = _coloured(context).execute("find | where onwer:x")
    lines = output.splitlines()
    assert lines[0].startswith(ESC)
    assert not lines[1].startswith(ESC)
    assert lines[2].lstrip().startswith(ESC)


def test_an_error_is_still_readable_without_colour(context):
    output, _ = _plain(context).execute("where type:asset")
    assert ESC not in output
    assert "cannot start a pipeline" in output
    assert output.rstrip().endswith("^")


def test_export_output_is_never_coloured(context, workspace):
    """The verb writes the formatter's own bytes, and export parity is a gate."""
    _coloured(context).execute("find type:asset | table title | export out/Assets.md")
    written = (workspace / "out" / "Assets.md").read_text(encoding="utf-8")
    assert ESC not in written


def test_the_formatter_itself_emits_no_escapes(context):
    """Colour is applied to rendered text, not inside the renderer."""
    result = run("find type:asset | table title", context)
    assert ESC not in (result.text or "")


def test_group_headings_take_the_header_role(context):
    output, _ = _coloured(context).execute("tasks | group owner | table")
    heading = next(line for line in output.splitlines() if "Maintenance" in line and "##" in line)
    assert heading.startswith(ESC)


def test_a_table_rule_is_muted(context):
    """The rule is structure rather than content, so it takes the muted role."""
    output, _ = _coloured(context).execute("find type:asset | table title")
    rule = next(line for line in output.splitlines() if "---" in line and "|" in line)
    assert rule.startswith(ESC)
    assert load().ansi.bright_black.lstrip("#").upper() == "757C90"


def test_colourise_leaves_an_empty_result_alone():
    assert colourise("", Palette(load(), enabled=True)) == ""


def test_colourise_preserves_the_trailing_newline():
    palette = Palette(load(), enabled=True)
    assert colourise("| a |\n", palette).endswith("\n")
    assert not colourise("| a |", palette).endswith("\n")


def test_the_banner_is_muted_and_the_count_is_a_number(context, capsys):
    stream = io.StringIO(".quit\n")
    _coloured(context).run(stream)
    out = capsys.readouterr().out
    assert ESC in out.splitlines()[0]


def test_a_repl_defaults_to_asking_the_stream(context):
    """Constructed with no palette, it decides for itself -- and under pytest
    stdout is captured, so it decides not to colour."""
    output, _ = Repl(context, use_readline=False).execute("find type:asset | table title")
    assert ESC not in output
