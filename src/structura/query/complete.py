"""Completion for the command line.

Phase 3 puts this behind Tab and ghost text; it lives here because completing
a pipeline means knowing the verb table and the type of the stage before, and
both of those are query concerns rather than UI ones. Written headless, it is
testable without a terminal.

Four contexts, decided by what is to the left of the cursor:

- at the start of a stage, the verbs that can go there -- sources first in a
  pipeline's first stage, and only verbs accepting the incoming kind after
- after a verb, that verb's condition keys and flags
- after `key:`, values drawn from the index
- after `sort`, `table`, `where` and friends, the fields the incoming rows
  actually have
"""

from __future__ import annotations

from dataclasses import dataclass

from .errors import QueryError
from .registry import VERBS, Verb
from .rows import ANY, COLUMNS, DOCUMENTS, SAME, TASKS


@dataclass(frozen=True)
class Completion:
    text: str
    detail: str = ""

    def __str__(self) -> str:
        return self.text


def _incoming_kind(text_before: str) -> str | None:
    """What the stage under the cursor will be handed, or None for a source."""
    stages = [part for part in text_before.split("|")]
    if len(stages) < 2:
        return None
    produced: str | None = None
    for chunk in stages[:-1]:
        words = chunk.split()
        if not words:
            continue
        found = VERBS.get(words[0])
        if found is None:
            return None
        produced = produced if found.produces == SAME else found.produces
    return produced


def _verb_candidates(incoming: str | None) -> list[Completion]:
    out = []
    for found in sorted(VERBS.values(), key=lambda v: v.name):
        if found.planned_in is not None:
            continue
        if incoming is None:
            if not found.is_source:
                continue
        else:
            if found.is_source or found.consumes is None:
                continue
            if ANY not in found.consumes and incoming not in found.consumes:
                continue
        out.append(Completion(found.name, found.summary))
    return out


def _value_candidates(verb_name: str, key: str, index) -> list[Completion]:
    """Values for a key, drawn from what the workspace actually contains."""
    if index is None:
        return []
    try:
        if key == "type":
            values = sorted({d.dtype for d in index.documents() if d.dtype})
        elif key == "area":
            values = sorted({d.area for d in index.documents() if d.area})
        elif key == "status":
            values = sorted({d.status for d in index.documents() if d.status})
        elif key == "tag":
            values = sorted(index.tags())
        elif key == "title":
            values = sorted({d.title for d in index.documents()})
        elif key in ("owner", "asset"):
            attr = "owner" if key == "owner" else "asset"
            values = sorted({getattr(t, attr) for t in index.tasks() if getattr(t, attr)})
        elif key == "source":
            values = sorted({t.source for t in index.tasks()})
        else:
            return []
    except Exception:  # pragma: no cover - completion must never break typing
        return []
    return [Completion(str(v)) for v in values]


def complete(text: str, index=None) -> list[Completion]:
    """Candidates for the token the cursor is sitting on at the end of `text`.

    Never raises. A completer that throws on half-typed input is worse than
    one that returns nothing.
    """
    try:
        return _complete(text, index)
    except (QueryError, IndexError, ValueError):  # pragma: no cover - defensive
        return []


def _prefix_filter(candidates: list[Completion], prefix: str) -> list[Completion]:
    if not prefix:
        return candidates
    lowered = prefix.casefold()
    exact = [c for c in candidates if c.text.casefold().startswith(lowered)]
    return exact or [c for c in candidates if lowered in c.text.casefold()]


def _complete(text: str, index) -> list[Completion]:
    stage_text = text.rsplit("|", 1)[-1]
    incoming = _incoming_kind(text)

    # Mid-token: everything after the last space is what we are completing.
    partial = "" if text.endswith(" ") else stage_text.split(" ")[-1]
    words = stage_text.split()
    at_verb = not words or (len(words) == 1 and not text.endswith(" ") and partial == words[0])

    if at_verb:
        return _prefix_filter(_verb_candidates(incoming), partial)

    found: Verb | None = VERBS.get(words[0])
    if found is None or found.planned_in is not None:
        return []

    # Completing a value after `key:`
    for operator in (":", "=", ">", "<"):
        if operator in partial:
            key, _, value_prefix = partial.partition(operator)
            return _prefix_filter(_value_candidates(found.name, key, index), value_prefix)

    fields = COLUMNS.get(incoming or (found.produces if found.produces != SAME else DOCUMENTS), ())

    candidates: list[Completion] = []
    if found.name == "tasks" and len(words) == 1:
        candidates += [Completion(state) for state in ("open", "done", "all")]
    if found.name == "sort" and len(words) >= 2:
        candidates += [Completion(order) for order in ("asc", "desc")]
    if found.check is not None and found.name != "where":
        candidates += [Completion(name, f"{incoming or TASKS} field") for name in fields]
    candidates += [Completion(f"{key}:", "key") for key in found.keys]
    if found.name == "where":
        candidates += [Completion(f"{name}:", "field") for name in fields]
    candidates += [Completion(f"--{flag}", "flag") for flag in found.flags]

    return _prefix_filter(candidates, partial)


def verb_names(include_planned: bool = False) -> list[str]:
    return sorted(
        name for name, found in VERBS.items() if include_planned or found.planned_in is None
    )
