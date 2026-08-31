"""The verb table.

Every verb is a function here. Nothing spawns a subprocess, nothing escapes to
a system shell, and the whole surface is enumerable -- which is what makes
`help` complete, the completer possible, and the tests exhaustive.

Verbs that mutate files (`set`, `tag`, `new`, `rename`, `move`, `delete`) are
registered as planned rather than missing. They need the save path with the
conflict prompt, which is phase 4's deliverable; until then the prompt says
"arrives in phase 4" instead of "unknown verb", which is the difference
between a roadmap and a typo.
"""

from __future__ import annotations

from structura.core.paths import relative_display

from . import format as fmt
from .errors import QueryError, TypeCheckError, did_you_mean
from .parser import Stage
from .registry import VERBS, groups, planned, verb
from .rows import (
    ANY,
    COLUMNS,
    DOCUMENTS,
    LINKS,
    PLACEHOLDERS,
    SAME,
    TASKS,
    TEXT,
    VIEW,
    Result,
    Row,
    text_result,
)
from .values import coerce, compare, days_since

# --- row builders -----------------------------------------------------


def _document_row(doc, context, tags: tuple[str, ...] = ()) -> Row:
    return Row(
        {
            "title": doc.title,
            "type": doc.dtype,
            "area": doc.area,
            "status": doc.status,
            "date": doc.date,
            "age": days_since(doc.date, today=context.today),
            "tag": tags,
            "tags": tags,
            "uid": doc.uid,
            "path": relative_display(doc.path, context.workspace),
            "parent": None,
        },
        ref=doc,
    )


def _documents(rows, context) -> Result:
    rows = list(rows)
    by_document = context.index.tags_by_document() if rows else {}
    return Result(
        kind=DOCUMENTS,
        rows=[_document_row(d, context, by_document.get(d.id, ())) for d in rows],
        columns=("title", "type", "area", "status", "date"),
    )


def _task_row(task, context) -> Row:
    return Row(
        {
            "description": task.description,
            "asset": task.asset,
            "owner": task.owner,
            "raised": task.raised,
            "due": task.due,
            "age": days_since(task.raised, today=context.today),
            "done": task.done,
            "source": task.source,
            "ref": task.ref,
            "line": task.line_no,
            "path": str(task.path),
        },
        ref=task,
    )


def _tasks(rows, context) -> Result:
    return Result(
        kind=TASKS,
        rows=[_task_row(t, context) for t in rows],
        columns=("age", "description", "asset", "owner", "raised", "source"),
    )


# --- shared filtering -------------------------------------------------


def _apply_conditions(result: Result, stage: Stage, context, *, skip: set[str] = frozenset()):
    """Filter rows by every condition on a stage except the ones already
    pushed down into the index query."""
    keep = []
    for row in result.rows:
        for condition in stage.conditions:
            if condition.key in skip:
                continue
            wanted = coerce(condition.value.text, today=context.today)
            if not compare(row.get(condition.key), condition.op, wanted):
                break
        else:
            keep.append(row)
    return result.replace(keep)


def _field_check(field_positionals: tuple[int, ...] = (), *, keys: bool = False):
    """A type check that validates field names against the incoming kind.

    `where owner:x` is valid over tasks and meaningless over documents, and
    the checker knows which is coming in, so it can say so at the prompt.
    """

    def check(stage: Stage, incoming: str | None, source: str) -> None:
        columns = COLUMNS.get(incoming or "", ())
        if not columns:
            return
        if keys:
            for condition in stage.conditions:
                if condition.key not in columns:
                    raise TypeCheckError(
                        f"`{incoming}` rows have no field `{condition.key}`"
                        + did_you_mean(condition.key, list(columns))
                        + f" -- they have {', '.join(columns)}",
                        source,
                        condition.offset,
                    )
        for position in field_positionals:
            if position < len(stage.positionals):
                value = stage.positionals[position]
                for name in value.text.split(","):
                    name = name.strip()
                    if name and name not in columns:
                        raise TypeCheckError(
                            f"`{incoming}` rows have no field `{name}`"
                            + did_you_mean(name, list(columns))
                            + f" -- they have {', '.join(columns)}",
                            source,
                            value.offset,
                        )

    return check


# --- sources ----------------------------------------------------------

_FIND_INDEXED = {
    "type": "dtype",
    "area": "area",
    "status": "status",
    "tag": "tag",
    "title": "title",
}


@verb(
    "find",
    summary="documents by type, area, status, tag, title or date",
    produces=DOCUMENTS,
    keys=("type", "area", "status", "tag", "tags", "title", "uid", "date", "age", "path"),
    usage="find type:asset area:wwt",
    group="source",
)
def _find(stage: Stage, _incoming, context) -> Result:
    # Every condition is applied over the rows, including the ones the index
    # has a column for.
    #
    # Pushing equality into SQL was the obvious optimisation and it was wrong:
    # SQLite compares text case-sensitively, the pipeline compares it
    # case-insensitively, so `find area:PAINT` returned nothing while
    # `find | where area:PAINT` returned everything. Two paths that answer the
    # same question differently is exactly the class of bug this project keeps
    # finding, and an optimisation is not worth one.
    #
    # It can come back in a later phase behind a test that runs both paths
    # over the same workspace and asserts they agree.
    return _apply_conditions(_documents(context.index.documents(), context), stage, context)


@verb(
    "grep",
    summary="full-text search over titles and bodies",
    produces=DOCUMENTS,
    positionals=(1, 1),
    usage='grep "riser pressure"',
    group="source",
)
def _grep(stage: Stage, _incoming, context) -> Result:
    return _documents(context.index.search(stage.text(0)), context)


@verb(
    "tasks",
    summary="tasks raised in the workspace; `open` or `done` narrows them",
    produces=TASKS,
    keys=("owner", "asset", "source", "age", "due", "raised", "ref", "description"),
    positionals=(0, 1),
    usage="tasks open age>120",
    group="source",
)
def _tasks_verb(stage: Stage, _incoming, context) -> Result:
    state = stage.text(0)
    if state is not None and state not in ("open", "done", "all"):
        raise QueryError(f"`tasks` takes `open`, `done` or `all`, not `{state}`")
    done = {"open": False, "done": True}.get(state)
    result = _tasks(context.index.tasks(done=done), context)
    return _apply_conditions(result, stage, context)


@verb(
    "placeholders",
    summary="unwritten link targets, ranked by inbound count",
    produces=PLACEHOLDERS,
    keys=("target", "inbound"),
    group="source",
)
def _placeholders(stage: Stage, _incoming, context) -> Result:
    rows = [
        Row(
            {
                "target": p.target,
                "inbound": p.inbound,
                "sources": ", ".join(p.sources),
            },
            ref=p,
        )
        for p in context.index.placeholders()
    ]
    result = Result(kind=PLACEHOLDERS, rows=rows, columns=("inbound", "target", "sources"))
    return _apply_conditions(result, stage, context)


@verb(
    "orphans",
    summary="documents nothing links to",
    produces=DOCUMENTS,
    keys=("type", "area", "status", "tag", "tags", "title"),
    group="source",
)
def _orphans(stage: Stage, _incoming, context) -> Result:
    return _apply_conditions(_documents(context.index.orphans(), context), stage, context)


# --- traversal --------------------------------------------------------


@verb(
    "links",
    summary="outbound links, including the ones that resolve to nothing",
    produces=LINKS,
    consumes=(DOCUMENTS,),
    group="traversal",
)
def _links(_stage: Stage, incoming: Result, context) -> Result:
    index = context.index
    rows: list[Row] = []
    for row in incoming.rows:
        doc = row.ref
        for target, line in index.links_from(doc.id):
            resolved = index.resolve(target)
            rows.append(
                Row(
                    {
                        "source": doc.title,
                        "target": target,
                        "resolved": resolved is not None,
                        "embed": False,
                        "line": line,
                        "path": str(doc.path),
                    },
                    ref=resolved,
                )
            )
    return Result(kind=LINKS, rows=rows, columns=("source", "target", "resolved", "line"))


@verb(
    "backlinks",
    summary="documents that link to these ones",
    produces=DOCUMENTS,
    consumes=(DOCUMENTS,),
    group="traversal",
)
def _backlinks(_stage: Stage, incoming: Result, context) -> Result:
    return _documents(context.index.backlinks_many([row.ref.id for row in incoming.rows]), context)


@verb(
    "children",
    summary="documents that name these as a parent",
    produces=DOCUMENTS,
    consumes=(DOCUMENTS,),
    group="traversal",
)
def _children(_stage: Stage, incoming: Result, context) -> Result:
    return _documents(context.index.children_many([row.ref.id for row in incoming.rows]), context)


@verb(
    "parents",
    summary="the documents these name as a parent",
    produces=DOCUMENTS,
    consumes=(DOCUMENTS,),
    group="traversal",
)
def _parents(_stage: Stage, incoming: Result, context) -> Result:
    return _documents(context.index.parents_many([row.ref.id for row in incoming.rows]), context)


# --- plumbing ---------------------------------------------------------


@verb(
    "where",
    summary="keep rows matching every condition",
    produces=SAME,
    consumes=(ANY,),
    usage="where type:observation",
    group="plumbing",
    check=_field_check(keys=True),
)
def _where(stage: Stage, incoming: Result, context) -> Result:
    if not stage.conditions:
        raise QueryError("`where` needs at least one condition, e.g. `where status:open`")
    return _apply_conditions(incoming, stage, context)


@verb(
    "sort",
    summary="order rows by a field; `desc` reverses",
    produces=SAME,
    consumes=(ANY,),
    positionals=(1, 2),
    usage="sort age desc",
    group="plumbing",
    check=_field_check((0,)),
)
def _sort(stage: Stage, incoming: Result, _context) -> Result:
    key = stage.text(0)
    direction = (stage.text(1) or "asc").lower()
    if direction not in ("asc", "desc"):
        raise QueryError(f"`sort` takes `asc` or `desc`, not `{direction}`")

    present = [row.get(key) for row in incoming.rows if row.get(key) is not None]
    # One comparison for the whole column. A column holding both numbers and
    # text would otherwise raise partway through the sort, on data rather than
    # on a mistake anyone made.
    numeric = bool(present) and all(
        isinstance(v, int | float) and not isinstance(v, bool) for v in present
    )

    def sort_key(row: Row):
        value = row.get(key)
        if value is None:
            return (1, 0 if numeric else "")
        return (0, value if numeric else str(value).casefold())

    rows = sorted(incoming.rows, key=sort_key, reverse=direction == "desc")
    if direction == "desc":
        # None sorts last in both directions: a task with no date is not the
        # oldest one, it is the one with no date.
        rows = [r for r in rows if r.get(key) is not None] + [r for r in rows if r.get(key) is None]
    return incoming.replace(rows)


@verb(
    "head",
    summary="the first n rows",
    produces=SAME,
    consumes=(ANY,),
    positionals=(1, 1),
    usage="head 10",
    group="plumbing",
)
def _head(stage: Stage, incoming: Result, _context) -> Result:
    raw = stage.text(0)
    if not raw.isdigit():
        raise QueryError(f"`head` takes a count, not `{raw}`")
    return incoming.replace(incoming.rows[: int(raw)])


@verb(
    "distinct",
    summary="drop rows repeating a field value",
    produces=SAME,
    consumes=(ANY,),
    positionals=(1, 1),
    usage="distinct owner",
    group="plumbing",
    check=_field_check((0,)),
)
def _distinct(stage: Stage, incoming: Result, _context) -> Result:
    key = stage.text(0)
    seen: set = set()
    rows = []
    for row in incoming.rows:
        value = row.get(key)
        if value not in seen:
            seen.add(value)
            rows.append(row)
    return incoming.replace(rows)


@verb(
    "group",
    summary="group rows under a field for rendering",
    produces=SAME,
    consumes=(ANY,),
    keys=("by",),
    positionals=(0, 1),
    usage="group owner",
    group="plumbing",
    check=_field_check((0,), keys=False),
)
def _group(stage: Stage, incoming: Result, _context) -> Result:
    key = stage.text(0) or next((c.value.text for c in stage.conditions if c.key == "by"), None)
    if not key:
        raise QueryError("`group` needs a field, e.g. `group owner` or `group by:owner`")
    result = incoming.replace(incoming.rows)
    result.group_by = key
    return result


@verb(
    "count",
    summary="how many rows",
    produces=TEXT,
    consumes=(ANY,),
    group="plumbing",
)
def _count(_stage: Stage, incoming: Result, _context) -> Result:
    return text_result(f"{len(incoming.rows)}\n")


# --- render -----------------------------------------------------------


@verb(
    "table",
    summary="render as a markdown table; name columns to choose them",
    produces=VIEW,
    consumes=(ANY,),
    positionals=(0, 1),
    usage="table age,description,owner",
    group="render",
    check=_field_check((0,)),
)
def _table(stage: Stage, incoming: Result, _context) -> Result:
    raw = stage.text(0)
    columns = [c.strip() for c in raw.split(",") if c.strip()] if raw else None
    return Result(
        kind=VIEW,
        rows=incoming.rows,
        text=fmt.table(incoming, columns),
        columns=tuple(columns or incoming.columns),
        group_by=incoming.group_by,
    )


@verb(
    "list",
    summary="render one row per line",
    produces=VIEW,
    consumes=(ANY,),
    positionals=(0, 1),
    usage="list title",
    group="render",
    check=_field_check((0,)),
)
def _list(stage: Stage, incoming: Result, _context) -> Result:
    return Result(
        kind=VIEW,
        rows=incoming.rows,
        text=fmt.listing(incoming, stage.text(0)),
        group_by=incoming.group_by,
    )


@verb(
    "tree",
    summary="render as a parent tree",
    produces=VIEW,
    consumes=(DOCUMENTS,),
    group="render",
)
def _tree(_stage: Stage, incoming: Result, context) -> Result:
    index = context.index
    rows = []
    for row in incoming.rows:
        parents = index.parents(row.ref.id)
        rows.append(Row({**row.values, "parent": parents[0] if parents else None}, ref=row.ref))
    populated = incoming.replace(rows)
    return Result(kind=VIEW, rows=rows, text=fmt.tree(populated))


# --- meta -------------------------------------------------------------


@verb(
    "export",
    summary="write the result to a markdown file inside the workspace",
    produces=TEXT,
    # Rows, or an already-rendered view: `find | table | export x.md` writes
    # the table you just looked at, which is the point of the verb.
    consumes=(ANY, VIEW),
    positionals=(1, 1),
    usage="export 0-Index/Open.md",
    group="meta",
)
def _export(stage: Stage, incoming: Result, context) -> Result:
    target = (context.workspace / stage.text(0)).resolve()
    if not target.is_relative_to(context.workspace):
        raise QueryError(
            f"`export` writes inside the workspace only, and `{stage.text(0)}` escapes it"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    body = incoming.text if incoming.kind == VIEW else fmt.table(incoming)
    target.write_text(body, encoding="utf-8", newline="\n")
    return text_result(
        f"wrote {relative_display(target, context.workspace)} ({len(incoming.rows)} rows)\n"
    )


@verb(
    "lint",
    summary="schema violations across the workspace",
    produces=TEXT,
    group="meta",
)
def _lint(_stage: Stage, _incoming, context) -> Result:
    problems = context.store.validate()
    if not problems:
        return text_result("schema clean\n")
    lines = [f"{len(problems)} schema violation(s):"]
    lines += [f"  {p.message}" for p in problems]
    return text_result("\n".join(lines) + "\n")


@verb(
    "reindex",
    summary="bring the index into step with the files",
    produces=TEXT,
    flags=("rebuild",),
    group="meta",
)
def _reindex(stage: Stage, _incoming, context) -> Result:
    from structura.index import Indexer

    if stage.flag("rebuild"):
        context.db.drop()
        context.db.ensure()
    return text_result(f"{Indexer(context.db, context.store).sync()}\n")


@verb(
    "help",
    summary="what the verbs are, and what one of them does",
    produces=TEXT,
    positionals=(0, 1),
    usage="help tasks",
    group="meta",
)
def _help(stage: Stage, _incoming, context) -> Result:
    name = stage.text(0)
    if name:
        found = VERBS.get(name)
        if found is None:
            raise QueryError(f"unknown verb `{name}`{did_you_mean(name, sorted(VERBS))}")
        lines = [f"{found.name} -- {found.summary}"]
        if found.planned_in:
            lines.append(f"  not available yet; arrives in {found.planned_in}")
            return text_result("\n".join(lines) + "\n")
        takes = "nothing (it starts a pipeline)" if found.is_source else " or ".join(found.consumes)
        lines.append(f"  takes    {takes}")
        lines.append(f"  produces {found.produces if found.produces != SAME else 'the same rows'}")
        if found.keys:
            lines.append(f"  keys     {', '.join(found.keys)}")
        if found.flags:
            lines.append(f"  flags    {', '.join('--' + f for f in found.flags)}")
        if found.usage:
            lines.append(f"  usage    {found.usage}")
        return text_result("\n".join(lines) + "\n")

    order = ["source", "traversal", "plumbing", "render", "meta", "action", "other"]
    lines: list[str] = []
    for name in order:
        entries = groups().get(name)
        if not entries:
            continue
        lines.append(f"{name}:")
        for found in entries:
            marker = f"  (in {found.planned_in})" if found.planned_in else ""
            lines.append(f"  {found.name:<14} {found.summary}{marker}")
        lines.append("")
    return text_result("\n".join(lines).rstrip() + "\n")


# --- promised, not yet delivered --------------------------------------

for _name, _summary in (
    ("open", "load a document into the editor"),
    ("new", "create a document from a template"),
    ("set", "set a frontmatter field"),
    ("tag", "add a tag"),
    ("untag", "remove a tag"),
    ("rename", "rename a document"),
    ("move", "move a document between folders"),
    ("delete", "delete a document, reporting what linked to it first"),
    ("wrap", "reflow prose and align tables"),
    ("file", "add documents to a folder"),
    ("unfile", "remove documents from a folder"),
):
    planned(_name, summary=_summary, phase="phase 4")

for _name, _summary in (
    ("events", "calendar events in a date range"),
    ("contacts", "the address book"),
    ("calendar", "render as a calendar grid"),
    ("cards", "render as contact cards"),
):
    planned(_name, summary=_summary, phase="phase 5-6", group="source")

planned(
    "git",
    summary="status, diff, commit -- explicit and controlled",
    phase="phase 7",
    group="meta",
)
