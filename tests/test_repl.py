"""The headless REPL.

Phase 2 ends with no window but a queryable workspace, and this is the thing
that makes that true.
"""

import io

from structura.repl import Repl, history_path


def test_a_pipeline_prints_its_result(context):
    output, keep_going = Repl(context, use_readline=False).execute("find type:asset | list title")
    assert "- Post Rinse 4" in output
    assert keep_going


def test_a_pipeline_without_a_render_verb_still_prints(context):
    """The result already is a table; showing nothing would be a poor joke."""
    output, _ = Repl(context, use_readline=False).execute("find type:asset")
    assert "| title" in output


def test_an_error_is_printed_with_its_caret_rather_than_raised(context):
    output, keep_going = Repl(context, use_readline=False).execute("where type:asset")
    assert "cannot start a pipeline" in output
    assert output.rstrip().endswith("^")
    assert keep_going, "a mistake must not end the session"


def test_a_blank_line_does_nothing(context):
    assert Repl(context, use_readline=False).execute("   ") == ("", True)


def test_quit_stops(context):
    for word in (".quit", ".exit", ".q"):
        assert Repl(context, use_readline=False).execute(word) == ("", False)


def test_dot_sync_reindexes(context):
    output, _ = Repl(context, use_readline=False).execute(".sync")
    assert "unchanged" in output


def test_dot_help_explains_the_dot_commands(context):
    output, _ = Repl(context, use_readline=False).execute(".help")
    assert ".sync" in output and ".quit" in output


def test_the_loop_reads_until_the_stream_ends(context, capsys):
    stream = io.StringIO("find type:asset | count\n.quit\n")
    assert Repl(context, use_readline=False).run(stream) == 0
    out = capsys.readouterr().out
    assert "2 documents indexed" not in out  # five documents, not two
    assert "\n2\n" in out


def test_the_loop_survives_a_bad_line_and_carries_on(context, capsys):
    stream = io.StringIO("nonsense\nfind | count\n")
    Repl(context, use_readline=False).run(stream)
    out = capsys.readouterr().out
    assert "unknown verb `nonsense`" in out
    assert "\n5\n" in out


def test_history_lives_in_the_workspace(context):
    assert history_path(context.workspace) == context.workspace / ".structura" / "history"
