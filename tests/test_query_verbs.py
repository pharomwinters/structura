"""One test per verb, over the fixture workspace.

The other half of the phase 2 gate. The fixture is five documents: two notes,
two assets in a `Part of` relationship, and an observation carrying one open
task and one done one.
"""

import pytest

from structura.query import QueryError
from structura.query.rows import DOCUMENTS, LINKS, TASKS, TEXT, VIEW

# --- sources ----------------------------------------------------------


def test_find_returns_every_document(q):
    assert len(q("find")) == 5


def test_find_by_type(rows):
    assert rows("find type:asset", "title") == ["Paint Line", "Post Rinse 4"]


def test_find_by_several_keys_at_once(rows):
    assert rows("find type:asset area:paint status:operating", "title") == ["Post Rinse 4"]


def test_find_by_tag(rows):
    assert rows("find tag:pressure", "title") == ["Beta"]


def test_find_with_a_comparison_on_a_date(rows):
    assert rows("find date<2026-09-01", "title") != []
    assert rows("find date<2020-01-01") == []


def test_find_matches_case_insensitively(rows):
    """A command line is typed. `area:PAINT` meaning nothing would be a joke."""
    assert rows("find area:PAINT", "title") == rows("find area:paint", "title")


def test_grep_searches_bodies(rows):
    assert rows('grep "riser"', "title") == ["Standup"]


def test_grep_finds_nothing_gracefully(q):
    assert len(q('grep "nonexistentword"')) == 0


def test_tasks_defaults_to_all_of_them(q):
    assert len(q("tasks")) == 2


@pytest.mark.parametrize("state,expected", [("open", ["Diagnose riser"]), ("done", ["Old work"])])
def test_tasks_open_and_done(rows, state, expected):
    assert rows(f"tasks {state}", "description") == expected


def test_tasks_rejects_a_state_it_does_not_have(q):
    with pytest.raises(QueryError, match="takes `open`, `done` or `all`"):
        q("tasks pending")


def test_tasks_by_owner(rows):
    assert len(rows("tasks owner:Maintenance")) == 2
    assert rows("tasks owner:Nobody") == []


def test_tasks_by_age(rows, context):
    """Age is computed from `raised` against the context's today, so a saved
    view does not go stale the way a written-out date would."""
    assert rows("tasks open age>60", "description") == ["Diagnose riser"]
    assert rows("tasks open age>10000") == []


def test_placeholders_rank_by_inbound_count(rows):
    assert rows("placeholders", "target") == ["Maintenance", "Missing"]
    assert rows("placeholders", "inbound") == [2, 1]


def test_placeholders_can_be_filtered(rows):
    assert rows("placeholders inbound>1", "target") == ["Maintenance"]


def test_orphans_are_documents_nothing_links_to(rows):
    assert "Alpha" in rows("orphans", "title")
    assert "Beta" not in rows("orphans", "title")


# --- traversal --------------------------------------------------------


def test_links_include_the_unresolved_ones(q):
    result = q("find title:Alpha | links")
    assert result.kind == LINKS
    assert {(r.get("target"), r.get("resolved")) for r in result.rows} == {
        ("Beta", True),
        ("Missing", False),
    }


def test_backlinks_resolve_through_aliases(rows):
    """The standup links `[[PR4]]`; the asset is titled `Post Rinse 4`."""
    assert rows("find title:'Post Rinse 4' | backlinks", "title") == ["Standup"]


def test_backlinks_deduplicate_across_several_inputs(q, workspace, context, write_note):
    """One document linking two of the inputs is one backlink, not two."""
    write_note(
        workspace,
        "2-Notes/Both.md",
        body="Mentions [[Paint Line]] and [[Post Rinse 4]].\n",
    )
    context.sync()
    titles = [r.get("title") for r in q("find type:asset | backlinks").rows]
    assert titles.count("Both") == 1


def test_children(rows):
    assert rows("find title:'Paint Line' | children", "title") == ["Post Rinse 4"]


def test_parents(rows):
    assert rows("find title:'Post Rinse 4' | parents", "title") == ["Paint Line"]


# --- plumbing ---------------------------------------------------------


def test_where_filters_what_came_in(rows):
    assert rows("find | where type:asset", "title") == ["Paint Line", "Post Rinse 4"]


def test_where_needs_a_condition(q):
    with pytest.raises(QueryError, match="needs at least one condition"):
        q("find | where")


def test_sort_ascending_and_descending(rows):
    ascending = rows("find | sort title", "title")
    assert ascending == sorted(ascending, key=str.casefold)
    assert rows("find | sort title desc", "title") == list(reversed(ascending))


def test_sort_rejects_a_direction_it_does_not_have(q):
    with pytest.raises(QueryError, match="takes `asc` or `desc`"):
        q("find | sort title sideways")


def test_sort_puts_missing_values_last_in_both_directions(rows):
    """A task with no due date is not the most urgent one; it is the one with
    no due date."""
    assert rows("tasks | sort due", "due")[-1] is None
    assert rows("tasks | sort due desc", "due")[-1] is None


def test_sort_orders_numbers_numerically(rows):
    ages = [a for a in rows("tasks | sort age desc", "age") if a is not None]
    assert ages == sorted(ages, reverse=True)


def test_head_limits(q):
    assert len(q("find | head 2")) == 2


def test_head_needs_a_number(q):
    with pytest.raises(QueryError, match="takes a count"):
        q("find | head lots")


def test_distinct_drops_repeats(rows):
    kinds = rows("find | distinct type", "type")
    assert len(kinds) == len(set(kinds))
    assert set(kinds) == set(rows("find", "type"))


def test_count_produces_text(q):
    result = q("find | count")
    assert result.kind == TEXT
    assert result.text.strip() == "5"


def test_group_sets_the_grouping_for_rendering(q):
    result = q("tasks | group owner")
    assert result.kind == TASKS
    assert result.group_by == "owner"


def test_group_accepts_the_by_key_too(q):
    assert q("tasks | group by:owner").group_by == "owner"


def test_group_needs_a_field(q):
    with pytest.raises(QueryError, match="needs a field"):
        q("tasks | group")


# --- render -----------------------------------------------------------


def test_table_renders_markdown(q):
    result = q("find type:asset | table title,status")
    assert result.kind == VIEW
    assert "| title" in result.text
    assert "| Post Rinse 4" in result.text


def test_table_without_columns_uses_the_sources_preference(q):
    text = q("tasks | table").text
    assert text.index("age") < text.index("description")


def test_table_renders_group_headings(q):
    assert "## Maintenance" in q("tasks | group owner | table").text


def test_table_says_so_when_there_are_no_rows(q):
    assert q("find type:person | table").text == "No rows.\n"


def test_list_renders_one_row_per_line(q):
    assert q("find type:asset | list title").text.splitlines() == [
        "- Paint Line",
        "- Post Rinse 4",
    ]


def test_tree_nests_by_parent(q):
    assert q("find type:asset | tree").text.splitlines() == [
        "- Paint Line",
        "  - Post Rinse 4",
    ]


def test_tree_reports_a_cycle_rather_than_dropping_it(q, workspace, context, write_note):
    write_note(workspace, "1-Assets/A.md", dtype="asset", area="paint", body="Part of [[B]]\n")
    write_note(workspace, "1-Assets/B.md", dtype="asset", area="paint", body="Part of [[A]]\n")
    context.sync()
    text = q("find type:asset | tree").text
    assert "Unreachable (cycle in parent chain)" in text
    assert "- A" in text and "- B" in text


# --- meta -------------------------------------------------------------


def test_export_writes_inside_the_workspace(q, workspace):
    result = q("find type:asset | table title | export registers/Assets.md")
    written = workspace / "registers" / "Assets.md"
    assert written.exists()
    assert "| Post Rinse 4" in written.read_text()
    assert "wrote registers/Assets.md" in result.text


def test_export_refuses_to_escape_the_workspace(q):
    with pytest.raises(QueryError, match="escapes it"):
        q("find | table | export ../outside.md")


def test_export_renders_rows_that_were_never_rendered(q, workspace):
    q("find type:asset | export registers/Raw.md")
    assert "| title" in (workspace / "registers" / "Raw.md").read_text()


def test_lint_reports_the_validator(q, workspace, context, write_note):
    assert q("lint").text.strip() == "schema clean"
    write_note(workspace, "2-Notes/Bad.md", dtype="sandwich")
    context.sync()
    assert "unknown type `sandwich`" in q("lint").text


def test_reindex_reports_what_it_did(q):
    assert "unchanged" in q("reindex").text


def test_reindex_rebuild_starts_from_nothing(q):
    assert "5 added" in q("reindex --rebuild").text


def test_help_lists_every_group(q):
    text = q("help").text
    for group in ("source:", "traversal:", "plumbing:", "render:", "meta:"):
        assert group in text


def test_help_marks_the_verbs_that_have_not_arrived(q):
    assert "(in phase 4)" in q("help").text


def test_help_on_one_verb_describes_its_types(q):
    text = q("help backlinks").text
    assert "takes    documents" in text
    assert "produces documents" in text


def test_help_on_an_unknown_verb_suggests(q):
    with pytest.raises(QueryError, match="did you mean `tasks`"):
        q("help taks")


# --- the whole thing --------------------------------------------------


def test_the_design_documents_own_examples_run(q):
    """Every pipeline printed in the design doc, executed."""
    for pipeline in (
        "find type:asset area:paint | backlinks | where type:observation | sort date desc | table",
        "tasks open age>60 | table age,description,asset,owner",
        "placeholders | head 10 | table",
    ):
        assert q(pipeline) is not None


def test_a_pipeline_ending_without_a_render_verb_still_has_rows(q):
    result = q("find type:asset")
    assert result.kind == DOCUMENTS
    assert result.text is None
