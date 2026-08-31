"""Saved views: a pipeline plus a column list, evaluated on open."""

import pytest

from structura.query import QueryError, load_views, run
from structura.query.views import slugify


def test_saving_writes_a_reviewable_file(context, workspace):
    run('view save "Open by age" tasks open | sort age desc | table', context)
    path = workspace / "design" / "views" / "open-by-age.toml"
    assert path.exists()
    assert 'name = "Open by age"' in path.read_text()
    assert "tasks open | sort age desc | table" in path.read_text()


def test_a_saved_view_survives_the_pipes_in_its_own_query(context):
    """`view save` cannot go through the pipeline parser, because its argument
    *is* a pipeline and the parser would split it on the pipes."""
    run('view save "Three stages" find | sort title | table', context)
    assert load_views(context)[0].query == "find | sort title | table"


def test_running_a_view_evaluates_it_now(context):
    run('view save "Assets" find type:asset | list title', context)
    text = run('view run "Assets"', context).text
    assert "- Post Rinse 4" in text


def test_a_view_is_never_a_stored_copy(context, workspace, write_note):
    """The whole reason for saving a pipeline rather than its output."""
    run('view save "Assets" find type:asset | list title', context)
    assert "Bag Filter" not in run('view "Assets"', context).text

    write_note(workspace, "1-Assets/Bag Filter.md", dtype="asset", area="paint")
    context.sync()
    assert "Bag Filter" in run('view "Assets"', context).text


def test_a_view_runs_by_name_without_the_run_word(context):
    run('view save "Assets" find type:asset | list title', context)
    assert "Post Rinse 4" in run('view "Assets"', context).text


def test_listing_views(context):
    run('view save "One" find | count', context)
    run('view save "Two" tasks | count', context)
    text = run("view list", context).text
    assert "One" in text and "Two" in text


def test_listing_with_no_views_says_how_to_make_one(context):
    assert "Save one with" in run("view list", context).text


def test_bare_view_lists_them(context):
    assert "No saved views" in run("view", context).text


def test_showing_a_view(context):
    run('view save "One" find | count', context)
    assert "find | count" in run('view show "One"', context).text


def test_deleting_a_view(context, workspace):
    run('view save "One" find | count', context)
    run('view delete "One"', context)
    assert load_views(context) == []


def test_an_unknown_view_lists_the_known_ones(context):
    run('view save "Kept" find | count', context)
    with pytest.raises(QueryError) as excinfo:
        run('view run "Missing"', context)
    assert "no view named `Missing`" in str(excinfo.value)
    assert "Kept" in str(excinfo.value)


def test_a_view_that_does_not_type_check_is_refused_at_save_time(context):
    """A saved view that cannot run is worse than no view: it fails later,
    somewhere else, for someone who did not write it."""
    with pytest.raises(QueryError, match="cannot start a pipeline"):
        run('view save "Broken" where type:asset', context)
    assert load_views(context) == []


def test_saving_needs_a_pipeline(context):
    with pytest.raises(QueryError, match="needs a pipeline"):
        run('view save "Empty"', context)


def test_an_unquoted_name_is_one_word(context):
    run("view save Quick find | count", context)
    assert load_views(context)[0].name == "Quick"


def test_a_malformed_view_file_is_reported_not_ignored(context, workspace):
    directory = workspace / "design" / "views"
    directory.mkdir(parents=True)
    (directory / "bad.toml").write_text("name = 'No query'\n")
    with pytest.raises(QueryError, match="needs a `name` and a `query`"):
        load_views(context)


def test_view_rejects_an_action_it_does_not_have(context):
    with pytest.raises(QueryError, match="takes list, save, show, run or delete"):
        run("view frobnicate", context)


@pytest.mark.parametrize(
    "name,slug",
    [("Open by age", "open-by-age"), ("WWT / open", "wwt-open"), ("!!!", "view")],
)
def test_slugs_are_filenames(name, slug):
    assert slugify(name) == slug
