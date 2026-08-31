"""Saved views: a pipeline plus a column list, evaluated on open.

This is the idea worth keeping from the system Structura is modelled on. A
view was a selection formula and a column list, never a stored copy of
anything, so it could not be out of date. A generated register is a stored
copy and drifts the moment content changes.

Views live as one TOML file per view under `design/views/`, so a view is a
tracked, reviewable diff rather than a row in a database nobody can read.

`view save` is the one command that cannot go through the pipeline parser,
because its argument *is* a pipeline and the parser would split it on the
pipes. It is therefore handled as a prefix before parsing, which is stated
here rather than discovered.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .errors import QueryError
from .rows import Result, text_result

SLUG_RE = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class View:
    name: str
    query: str
    path: Path | None = None

    @property
    def slug(self) -> str:
        return slugify(self.name)


def slugify(name: str) -> str:
    return SLUG_RE.sub("-", name.strip().casefold()).strip("-") or "view"


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def views_dir(context) -> Path:
    return context.workspace / "design" / "views"


def load_views(context) -> list[View]:
    directory = views_dir(context)
    if not directory.is_dir():
        return []
    found: list[View] = []
    for path in sorted(directory.glob("*.toml")):
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as exc:
            raise QueryError(f"{path.name}: not valid TOML -- {exc}") from exc
        name, query = data.get("name"), data.get("query")
        if not isinstance(name, str) or not isinstance(query, str):
            raise QueryError(f"{path.name}: a view needs a `name` and a `query`")
        found.append(View(name=name, query=query, path=path))
    return found


def find_view(context, name: str) -> View | None:
    wanted = slugify(name)
    for view in load_views(context):
        if view.slug == wanted or view.name == name:
            return view
    return None


def save_view(context, name: str, query: str) -> View:
    from .engine import compile_pipeline

    # Type-check before writing. A saved view that cannot run is worse than
    # no view: it fails later, somewhere else, for someone who did not write
    # it.
    compile_pipeline(query)

    directory = views_dir(context)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{slugify(name)}.toml"
    path.write_text(
        f'name = "{_escape(name)}"\nquery = "{_escape(query)}"\n',
        encoding="utf-8",
        newline="\n",
    )
    return View(name=name, query=query, path=path)


def _split_name(rest: str) -> tuple[str, str]:
    """Split `"Open by age" tasks open | sort age desc` into name and query."""
    rest = rest.strip()
    if not rest:
        raise QueryError('`view save` needs a name, e.g. view save "Open by age" tasks open')
    if rest[0] in "\"'":
        quote = rest[0]
        end = rest.find(quote, 1)
        if end == -1:
            raise QueryError("unterminated view name")
        return rest[1:end], rest[end + 1 :].strip()
    name, _, query = rest.partition(" ")
    return name, query.strip()


def expand_view_command(text: str, context) -> Result | None:
    """Handle a `view ...` command. Returns None when the text is not one."""
    stripped = text.strip()
    if stripped != "view" and not stripped.startswith("view "):
        return None

    rest = stripped[4:].strip()
    action, _, remainder = rest.partition(" ")

    if not action or action == "list":
        found = load_views(context)
        if not found:
            return text_result('No saved views. Save one with `view save "Name" <pipeline>`.\n')
        width = max(len(v.name) for v in found)
        lines = [f"{v.name.ljust(width)}  {v.query}" for v in found]
        return text_result("\n".join(lines) + "\n")

    if action == "save":
        name, query = _split_name(remainder)
        if not query:
            raise QueryError(f'`view save "{name}"` needs a pipeline to save')
        view = save_view(context, name, query)
        return text_result(f"saved view `{view.name}` to {view.path.name}\n")

    if action in ("show", "delete", "run"):
        target = remainder.strip().strip("\"'")
        if not target:
            raise QueryError(f"`view {action}` needs a view name")
        view = find_view(context, target)
        if view is None:
            known = ", ".join(v.name for v in load_views(context)) or "none saved"
            raise QueryError(f"no view named `{target}` -- known views: {known}")
        if action == "show":
            return text_result(f"{view.name}\n  {view.query}\n")
        if action == "delete":
            view.path.unlink()
            return text_result(f"deleted view `{view.name}`\n")
        return _run_view(view, context)

    # `view "Open by age"` runs it, because that is what you mean.
    view = find_view(context, rest.strip().strip("\"'"))
    if view is None:
        raise QueryError(
            f"`view` takes list, save, show, run or delete -- `{action}` is none of those, "
            f"and no view is named that either"
        )
    return _run_view(view, context)


def _run_view(view: View, context) -> Result:
    from .engine import run

    return run(view.query, context)
