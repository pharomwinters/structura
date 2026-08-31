"""The query API, on a known workspace."""

from structura.index import Index


def test_documents_by_type(index):
    assert [d.title for d in index.documents(dtype="asset")] == ["Paint Line", "Post Rinse 4"]


def test_documents_by_promoted_field(index):
    assert [d.title for d in index.documents(area="wwt")] == ["Standup"]
    assert [d.title for d in index.documents(status="operating")] == ["Post Rinse 4"]


def test_documents_by_tag(index):
    assert [d.title for d in index.documents(tag="pressure")] == ["Beta"]
    assert index.tags() == {"overnight": 1, "pressure": 1}


def test_an_alias_resolves_to_the_same_document_as_the_title(index):
    assert index.resolve("PR4").path == index.resolve("Post Rinse 4").path


def test_backlinks_follow_aliases(index):
    """The standup links `[[PR4]]`; the asset is titled `Post Rinse 4`. The
    index resolves through the alias table, so no caller has to know."""
    asset = index.resolve("Post Rinse 4")
    assert [d.title for d in index.backlinks(asset.id)] == ["Standup"]


def test_fields_hold_the_raw_frontmatter_and_tags_hold_the_interpretation(index):
    """`fields` is what the file says; `tags` is what it means. A comma-joined
    `tags:` string is one scalar in frontmatter and two tags in the tag index,
    and conflating them would make round-tripping the file impossible."""
    beta = index.resolve("Beta")
    assert index.fields(beta.id)["tags"] == ["pressure, overnight"]
    assert [d.title for d in index.documents(tag="overnight")] == ["Beta"]


def test_a_yaml_list_field_is_stored_one_value_per_row(indexer, workspace, write_note):
    write_note(workspace, "2-Notes/Listy.md", body="body\n")
    (workspace / "2-Notes" / "Listy.md").write_text(
        "---\ntype: note\ntitle: Listy\ndate: 2026-08-14\nsources:\n  - one\n  - two\n---\n\nbody\n"
    )
    indexer.sync()
    index = Index(indexer.db)
    assert index.fields(index.resolve("Listy").id)["sources"] == ["one", "two"]


def test_parents_and_children(index):
    line = index.resolve("Paint Line")
    assert [d.title for d in index.children(line.id)] == ["Post Rinse 4"]
    assert index.parents(index.resolve("Post Rinse 4").id) == ["Paint Line"]


def test_open_and_done_tasks(index):
    assert [t.description for t in index.tasks(done=False)] == ["Diagnose riser"]
    assert [t.description for t in index.tasks(done=True)] == ["Old work"]
    assert len(index.tasks()) == 2


def test_tasks_carry_their_source(index):
    task = index.tasks(done=False)[0]
    assert task.source == "Standup"
    assert task.owner == "Maintenance"
    assert task.raised == "2026-06-01"


def test_tasks_by_asset_resolve_the_raw_name(index):
    assert [t.description for t in index.tasks(asset="PR4")] == ["Diagnose riser"]


def test_placeholders_are_ranked_by_inbound_count(index):
    placeholders = index.placeholders()
    assert [(p.target, p.inbound) for p in placeholders] == [
        ("Maintenance", 2),
        ("Missing", 1),
    ]
    assert placeholders[1].sources == ("Alpha",)


def test_an_attachment_linked_by_filename_is_not_a_placeholder(indexer, workspace, write_note):
    """R21/R31: a non-markdown file is a legitimate link target when named with
    its extension, and not one when named without."""
    (workspace / "3-Resources").mkdir()
    (workspace / "3-Resources" / "poster.pdf").write_bytes(b"%PDF")
    write_note(workspace, "2-Notes/Refs.md", body="See [[poster.pdf]] and [[poster]].\n")
    indexer.sync()

    targets = {p.target for p in Index(indexer.db).placeholders()}
    assert "poster.pdf" not in targets
    assert "poster" in targets


def test_orphans_are_documents_nothing_links_to(index):
    assert "Alpha" in [d.title for d in index.orphans()]
    assert "Beta" not in [d.title for d in index.orphans()]


def test_full_text_search(index):
    assert [d.title for d in index.search("riser")] == ["Standup"]
    assert index.search("nonexistentword") == []


def test_search_matches_titles_as_well_as_bodies(index):
    assert "Alpha" in [d.title for d in index.search("Alpha")]
