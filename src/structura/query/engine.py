"""Running a pipeline.

Three steps, always in this order: parse, type-check the whole thing, then
run. Nothing executes until every stage is known to connect, which is the
point of the types.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from structura.core.schema import Schema, load_schema
from structura.index import Database, Index, Indexer
from structura.stores.markdown import MarkdownStore

# Importing the verb table for its registrations is the whole point: without
# it the registry is empty and `compile_pipeline` would call every verb
# unknown. It is a module-level import rather than a lazy one so that
# importing the engine alone cannot leave the type checker half-armed.
from . import verbs as _verbs  # noqa: F401
from .parser import Pipeline, parse
from .registry import check
from .rows import Result
from .views import expand_view_command


@dataclass
class Context:
    """What a verb is allowed to reach.

    Deliberately small: a workspace, its store, its index, and today. A verb
    that wants anything else is a verb that has grown past being a verb.
    """

    workspace: Path
    store: MarkdownStore
    db: Database
    today: date = field(default_factory=date.today)

    @property
    def index(self) -> Index:
        return Index(self.db)

    @property
    def schema(self) -> Schema:
        return self.store.schema

    @property
    def views_dir(self) -> Path:
        return self.workspace / "design" / "views"

    @classmethod
    def open(cls, workspace: Path, *, today: date | None = None) -> Context:
        workspace = Path(workspace).resolve()
        schema = load_schema(workspace)
        return cls(
            workspace=workspace,
            store=MarkdownStore(workspace, schema),
            db=Database.open(workspace),
            today=today or date.today(),
        )

    def sync(self) -> None:
        Indexer(self.db, self.store).sync()

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> Context:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


def compile_pipeline(text: str) -> Pipeline:
    """Parse and type-check without running. What the prompt does as you
    type, and what the pipeline tests assert on."""
    pipeline = parse(text)
    check(pipeline)
    return pipeline


def run(text: str, context: Context) -> Result:
    """Parse, check, and evaluate a command line."""

    handled = expand_view_command(text, context)
    if handled is not None:
        return handled

    pipeline = parse(text)
    found = check(pipeline)

    result: Result | None = None
    for verb, stage in zip(found, pipeline.stages, strict=True):
        result = verb.run(stage, result, context)
    assert result is not None
    return result
