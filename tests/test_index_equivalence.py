"""Acceptance test 4: the index answers what the documents say.

For a generated workspace, every query answer from SQLite must equal the
answer computed directly from the parsed documents. The index is a cache with
no authority, and this is the test that says so in a way that fails when it
stops being true.

The reference implementations below are deliberately naive -- plain loops over
`Document` objects, no SQL, no cleverness. If a reference and a query ever
agree because they share a bug, it is because someone made them share code, so
they share none.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from structura.core.document import Document
from structura.core.links import strip_section
from structura.index import Database, Index, Indexer
from structura.stores.markdown import MarkdownStore, build_alias_map

DTYPES = ["note", "asset", "person", "org", "observation", "meeting"]
AREAS = ["paint", "wwt", "monorail"]
STATUSES = ["open", "contained", "resolved"]
OWNERS = ["Maintenance", "Engineering"]

# Kept ASCII and single-cased so the reference tokeniser and SQLite's
# `unicode61` cannot disagree about what a word is.
WORDS = ["riser", "pressure", "pump", "valve", "overnight", "cycle"]
NAMES = ["Alpha", "Bravo", "Charlie", "Delta", "Echo"]
TOKEN_RE = re.compile(r"[a-z0-9]+")


note_strategy = st.fixed_dictionaries(
    {
        "title": st.sampled_from(NAMES),
        "dtype": st.sampled_from(DTYPES),
        "area": st.one_of(st.none(), st.sampled_from(AREAS)),
        "status": st.one_of(st.none(), st.sampled_from(STATUSES)),
        "alias": st.one_of(st.none(), st.sampled_from(["A1", "B2", "C3"])),
        "tags": st.lists(st.sampled_from(["pressure", "wwt", "safety"]), max_size=3),
        "links": st.lists(st.sampled_from([*NAMES, "Unwritten", "Ghost"]), max_size=4),
        "body_words": st.lists(st.sampled_from(WORDS), max_size=6),
        "tasks": st.lists(
            st.tuples(
                st.sampled_from(WORDS),
                st.sampled_from([*NAMES, None]),
                st.sampled_from([*OWNERS, None]),
                st.booleans(),
            ),
            max_size=3,
        ),
    }
)

workspace_strategy = st.lists(note_strategy, min_size=1, max_size=6, unique_by=lambda n: n["title"])


def build_workspace(root: Path, specs: list[dict]) -> None:
    for spec in specs:
        lines = [
            "---",
            f"type: {spec['dtype']}",
            f"title: {spec['title']}",
            "date: 2026-08-14",
        ]
        if spec["area"]:
            lines.append(f"area: {spec['area']}")
        if spec["status"]:
            lines.append(f"status: {spec['status']}")
        if spec["alias"]:
            lines.append(f"alias: {spec['alias']}")
        if spec["tags"]:
            lines.append(f"tags: {', '.join(spec['tags'])}")
        lines += ["---", ""]
        lines += [" ".join(spec["body_words"]) or "body"]
        lines += [f"See [[{target}]]." for target in spec["links"]]
        for description, asset, owner, done in spec["tasks"]:
            mark = "x" if done else " "
            line = f"- [{mark}] #item {description}"
            if asset:
                line += f" [[{asset}]]"
            if owner:
                line += f" owner:[[{owner}]]"
            line += " raised:2026-06-01"
            lines.append(line)
        (root / f"{spec['title']}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


# --- reference implementations, computed straight from the documents ---


def ref_documents(docs: list[Document], **filters) -> list[Path]:
    out = []
    for doc in docs:
        if filters.get("dtype") is not None and doc.dtype != filters["dtype"]:
            continue
        for key in ("area", "status"):
            if filters.get(key) is not None and str(doc.fields.get(key, "")) != filters[key]:
                break
        else:
            tag = filters.get("tag")
            if tag is not None:
                raw = doc.fields.get("tags")
                tags = (
                    [t.strip() for t in raw.split(",")]
                    if isinstance(raw, str)
                    else [str(t) for t in (raw or [])]
                )
                if tag not in tags:
                    continue
            out.append(doc.path)
    return sorted(out)


def ref_resolve(docs: list[Document], name: str) -> Path | None:
    amap = build_alias_map(docs)
    canonical = amap.get(name)
    if canonical is None:
        return None
    return next((d.path for d in docs if d.title == canonical), None)


def ref_backlinks(docs: list[Document], target: Document) -> list[Path]:
    amap = build_alias_map(docs)
    out = set()
    for doc in docs:
        for link in doc.link_targets:
            if amap.get(strip_section(link)) == target.title:
                out.add(doc.path)
    return sorted(out)


def ref_placeholders(docs: list[Document], on_disk: set[str]) -> list[tuple[str, int]]:
    amap = build_alias_map(docs)
    existing = set(amap) | on_disk
    counts: Counter[str] = Counter()
    for doc in docs:
        for link in doc.link_targets:
            target = strip_section(link)
            if target and target not in existing:
                counts[target] += 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))


def ref_tokens(doc: Document) -> set[str]:
    return set(TOKEN_RE.findall(f"{doc.title} {doc.body}".lower()))


# --- the property -----------------------------------------------------


@settings(
    max_examples=40,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(specs=workspace_strategy)
def test_every_query_answer_matches_the_documents(tmp_path_factory, specs):
    root = tmp_path_factory.mktemp("equiv")
    build_workspace(root, specs)

    store = MarkdownStore(root)
    docs = store.documents()
    db = Database.in_memory(root)
    try:
        Indexer(db, store).sync()
        index = Index(db)

        assert [d.path for d in index.documents()] == ref_documents(docs)
        assert index.document_count() == len(docs)

        for dtype in DTYPES:
            assert [d.path for d in index.documents(dtype=dtype)] == ref_documents(
                docs, dtype=dtype
            ), dtype
        for area in AREAS:
            assert [d.path for d in index.documents(area=area)] == ref_documents(docs, area=area), (
                area
            )
        for status in STATUSES:
            assert [d.path for d in index.documents(status=status)] == ref_documents(
                docs, status=status
            ), status
        for tag in ("pressure", "wwt", "safety"):
            assert [d.path for d in index.documents(tag=tag)] == ref_documents(docs, tag=tag), tag

        for name in [*NAMES, "A1", "B2", "C3", "Unwritten"]:
            row = index.resolve(name)
            assert (row.path if row else None) == ref_resolve(docs, name), name

        for doc in docs:
            row = index.resolve(doc.title)
            assert [d.path for d in index.backlinks(row.id)] == ref_backlinks(docs, doc), doc.title
            assert index.parents(row.id) == [strip_section(p) for p in doc.parents]

        assert [(p.target, p.inbound) for p in index.placeholders()] == ref_placeholders(
            docs, store.link_target_names()
        )

        indexed_tasks = [(t.path, t.line_no, t.description, t.done) for t in index.tasks()]
        expected_tasks = sorted(
            (doc.path, task.line_no, task.description, task.done)
            for doc in docs
            for task in doc.tasks
        )
        assert indexed_tasks == expected_tasks

        for done in (True, False):
            assert [(t.path, t.line_no) for t in index.tasks(done=done)] == sorted(
                (doc.path, task.line_no) for doc in docs for task in doc.tasks if task.done is done
            ), done

        for owner in OWNERS:
            assert [(t.path, t.line_no) for t in index.tasks(owner=owner)] == sorted(
                (doc.path, task.line_no)
                for doc in docs
                for task in doc.tasks
                if task.owner == owner
            ), owner

        assert [d.path for d in index.orphans()] == sorted(
            doc.path for doc in docs if not ref_backlinks(docs, doc)
        )

        for word in WORDS:
            assert {d.path for d in index.search(word)} == {
                doc.path for doc in docs if word in ref_tokens(doc)
            }, word
    finally:
        db.close()


def test_a_duplicate_title_resolves_deterministically(tmp_path, write_note):
    """Two documents claiming one title is a schema violation the linter
    reports. The index still has to pick one the same way every time rather
    than depend on row order."""
    write_note(tmp_path, "a/Dup.md", title="Dup")
    write_note(tmp_path, "b/Dup.md", title="Dup")

    store = MarkdownStore(tmp_path)
    db = Database.in_memory(tmp_path)
    try:
        Indexer(db, store).sync()
        index = Index(db)
        first = index.resolve("Dup")
        assert first is not None
        for _ in range(5):
            assert index.resolve("Dup").path == first.path
    finally:
        db.close()
