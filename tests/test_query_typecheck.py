"""The half of the phase 2 gate that matters most: bad pipelines fail before
anything runs.

A stage does not emit text, it emits typed rows, and each verb declares what
it consumes and produces. That is the whole reason for the type system, and
these are the tests that say it works. Every case here must raise at compile
time -- no index is touched, no file is read, nothing has happened yet.
"""

import pytest

from structura.query import TypeCheckError, compile_pipeline


def fails(text: str) -> TypeCheckError:
    with pytest.raises(TypeCheckError) as excinfo:
        compile_pipeline(text)
    return excinfo.value


# --- pipelines that connect -------------------------------------------


@pytest.mark.parametrize(
    "pipeline",
    [
        "find type:asset area:wwt | backlinks | where type:observation | sort date desc | table",
        "tasks open age>120 | table age,description,asset,owner",
        'grep "riser pressure" | list title',
        "placeholders | head 10 | table",
        "find type:asset | links | where resolved:false | count",
        "orphans | sort title | list",
        "find type:asset | tree",
        "tasks | group owner | table",
        "find | distinct area | list area",
        "lint",
        "help tasks",
        "reindex --rebuild",
        "find type:asset | export registers/Assets.md",
    ],
)
def test_a_good_pipeline_type_checks(pipeline):
    assert compile_pipeline(pipeline)


# --- pipelines that do not ---------------------------------------------


def test_an_unknown_verb_is_caught():
    error = fails("finde type:asset")
    assert "unknown verb `finde`" in error.message
    assert "did you mean `find`" in error.message


def test_a_plumbing_verb_cannot_start_a_pipeline():
    error = fails("where type:asset")
    assert "cannot start a pipeline" in error.message


def test_a_source_cannot_follow_a_stage():
    error = fails("find | tasks")
    assert "starts a pipeline and cannot follow one" in error.message


def test_a_kind_mismatch_names_both_sides():
    error = fails("tasks | backlinks")
    assert "`backlinks` takes documents" in error.message
    assert "`tasks` produces tasks" in error.message


def test_nothing_can_follow_a_render_verb():
    error = fails("find | table | sort title")
    assert "`sort` takes any rows, but `table` produces view" in error.message


def test_nothing_can_follow_a_text_verb():
    error = fails("lint | table")
    assert "produces text" in error.message


def test_a_tree_only_takes_documents():
    assert "takes documents" in fails("tasks | tree").message


def test_an_unknown_key_on_a_source_is_caught():
    error = fails("find colour:red")
    assert "`find` has no key `colour`" in error.message
    assert "it takes type, area" in error.message


def test_a_near_miss_key_is_suggested():
    assert "did you mean `status`" in fails("find staus:open").message


def test_a_field_that_the_incoming_rows_do_not_have_is_caught():
    """`where owner:x` is valid over tasks and meaningless over documents,
    and the checker knows which is coming in."""
    error = fails("find type:asset | where owner:Maintenance")
    assert "`documents` rows have no field `owner`" in error.message


def test_the_same_field_is_fine_when_the_rows_do_have_it():
    assert compile_pipeline("tasks | where owner:Maintenance")


def test_a_sort_field_is_checked_against_the_incoming_rows():
    assert "rows have no field `owner`" in fails("find | sort owner").message


def test_a_table_column_is_checked_against_the_incoming_rows():
    error = fails("tasks | table age,onwer")
    assert "no field `onwer`" in error.message
    assert "did you mean `owner`" in error.message


def test_too_few_arguments_names_the_usage():
    error = fails("grep")
    assert "`grep` needs 1 argument" in error.message
    assert 'usage: grep "riser pressure"' in error.message


def test_too_many_arguments_points_at_the_extra_one():
    error = fails("head 10 20")
    assert "at most 1 argument" in error.message
    assert error.offset == len("head 10 ")


def test_an_unknown_flag_is_caught():
    error = fails("reindex --rebiuld")
    assert "has no flag `--rebiuld`" in error.message
    assert "did you mean `rebuild`" in error.message


def test_a_promised_verb_says_which_phase_rather_than_unknown():
    """A roadmap and a typo should not look alike."""
    error = fails("find | set status:open")
    assert "`set` is not available yet" in error.message
    assert "phase 4" in error.message


def test_a_future_store_verb_says_so_too():
    assert "phase 5-6" in fails("events from:today").message


def test_errors_point_at_the_offending_stage():
    error = fails("find type:asset | tasks")
    assert error.offset == len("find type:asset | ")
    assert error.render().rstrip().endswith("^")


def test_type_checking_touches_nothing(tmp_path):
    """Compilation must not need a workspace at all. If it ever does, the
    "fails at parse time" promise has quietly become "fails early-ish"."""
    assert compile_pipeline("tasks open | sort age desc | table")
