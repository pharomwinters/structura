"""The domain command line.

A prompt whose vocabulary is the knowledge base, not the filesystem. The nouns
are documents, tasks, links and placeholders; the verbs are `find`, `tasks`,
`backlinks`, `export` and the rest. Its pipe carries typed result sets rather
than raw text, so a pipeline is checked before it runs.

Nothing here spawns a subprocess. The whole surface is a registry, which is
what makes it behave identically everywhere, testable without a terminal, and
enumerable.
"""

from .complete import Completion, complete, verb_names
from .engine import Context, compile_pipeline, run
from .errors import ParseError, QueryError, TypeCheckError
from .parser import Pipeline, Stage, parse
from .registry import VERBS, Verb
from .rows import DOCUMENTS, LINKS, PLACEHOLDERS, TASKS, TEXT, VIEW, Result, Row
from .views import View, load_views, save_view

__all__ = [
    "DOCUMENTS",
    "LINKS",
    "PLACEHOLDERS",
    "TASKS",
    "TEXT",
    "VERBS",
    "VIEW",
    "Completion",
    "Context",
    "ParseError",
    "Pipeline",
    "QueryError",
    "Result",
    "Row",
    "Stage",
    "TypeCheckError",
    "Verb",
    "View",
    "compile_pipeline",
    "complete",
    "load_views",
    "parse",
    "run",
    "save_view",
    "verb_names",
]
