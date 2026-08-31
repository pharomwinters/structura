"""The verb registry, and the type check that runs before a pipeline does.

Every verb is a function in a registry. Nothing spawns a subprocess; the whole
surface area is enumerable, which is what makes `help` complete and the
completer possible.

A verb declares what it consumes and what it produces, so a pipeline can be
checked before it runs. `find type:asset | sort date | table` connects;
`table | sort date` does not, and saying so at the prompt is worth more than
discovering it after the first stage has already done something.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .errors import TypeCheckError, did_you_mean
from .parser import Pipeline, Stage
from .rows import ANY, ROW_KINDS, SAME, Result

if TYPE_CHECKING:  # pragma: no cover
    from .engine import Context

Runner = Callable[[Stage, Result | None, "Context"], Result]


@dataclass(frozen=True)
class Verb:
    name: str
    summary: str
    produces: str
    run: Runner
    #: None marks a source: it starts a pipeline and consumes nothing.
    consumes: tuple[str, ...] | None = None
    #: Condition keys this verb understands. Empty means it takes none; a
    #: typo in a key is caught here rather than silently matching nothing.
    keys: tuple[str, ...] = ()
    flags: tuple[str, ...] = ()
    #: (minimum, maximum) positionals; None for no upper bound.
    positionals: tuple[int, int | None] = (0, 0)
    usage: str = ""
    group: str = "other"
    #: Set for verbs the design lists but a later phase delivers, so the
    #: prompt can say "not yet" rather than "unknown verb".
    planned_in: str | None = None
    #: Extra type-check, for verbs whose valid keys or field arguments depend
    #: on what is coming in. `where owner:x` is valid over tasks and not over
    #: documents, and the checker knows the incoming kind, so it can say so.
    check: Callable[[Stage, str | None, str], None] | None = None

    @property
    def is_source(self) -> bool:
        return self.consumes is None


VERBS: dict[str, Verb] = {}


def register(verb: Verb) -> Verb:
    VERBS[verb.name] = verb
    return verb


def verb(
    name: str,
    *,
    summary: str,
    produces: str,
    consumes: tuple[str, ...] | None = None,
    keys: tuple[str, ...] = (),
    flags: tuple[str, ...] = (),
    positionals: tuple[int, int | None] = (0, 0),
    usage: str = "",
    group: str = "other",
    check: Callable[[Stage, str | None, str], None] | None = None,
) -> Callable[[Runner], Runner]:
    def decorate(func: Runner) -> Runner:
        register(
            Verb(
                name=name,
                summary=summary,
                produces=produces,
                run=func,
                consumes=consumes,
                keys=keys,
                flags=flags,
                positionals=positionals,
                usage=usage,
                group=group,
                check=check,
            )
        )
        return func

    return decorate


def planned(name: str, *, summary: str, phase: str, group: str = "action") -> None:
    """Record a verb the design promises but this phase does not ship."""

    def unavailable(stage: Stage, _incoming: Result | None, _context: Context) -> Result:
        raise TypeCheckError(
            f"`{name}` is not available yet -- it arrives in {phase}",
            "",
            None,
        )

    register(
        Verb(
            name=name,
            summary=summary,
            produces="",
            run=unavailable,
            consumes=(ANY,),
            group=group,
            planned_in=phase,
        )
    )


def lookup(stage: Stage, source: str) -> Verb:
    found = VERBS.get(stage.verb)
    if found is None:
        raise TypeCheckError(
            f"unknown verb `{stage.verb}`{did_you_mean(stage.verb, sorted(VERBS))}",
            source,
            stage.offset,
        )
    if found.planned_in is not None:
        raise TypeCheckError(
            f"`{found.name}` is not available yet -- it arrives in {found.planned_in}",
            source,
            stage.offset,
        )
    return found


def check(pipeline: Pipeline) -> list[Verb]:
    """Type-check a whole pipeline, returning its verbs. Raises before any of
    them runs."""
    source = pipeline.source
    verbs: list[Verb] = []
    produced: str | None = None

    for index, stage in enumerate(pipeline.stages):
        found = lookup(stage, source)
        _check_arity(found, stage, source)
        _check_flags(found, stage, source)
        if found.check is None:
            _check_keys(found, stage, source)
        else:
            found.check(stage, produced, source)

        if index == 0:
            if not found.is_source:
                raise TypeCheckError(
                    f"`{found.name}` cannot start a pipeline -- it needs "
                    f"{_english(found.consumes)} coming in",
                    source,
                    stage.offset,
                )
        else:
            if found.is_source:
                raise TypeCheckError(
                    f"`{found.name}` starts a pipeline and cannot follow one -- "
                    f"it ignores whatever comes in",
                    source,
                    stage.offset,
                )
            if not _accepts(found, produced):
                raise TypeCheckError(
                    f"`{found.name}` takes {_english(found.consumes)}, but "
                    f"`{pipeline.stages[index - 1].verb}` produces {produced}",
                    source,
                    stage.offset,
                )

        produced = produced if found.produces == SAME else found.produces
        verbs.append(found)

    return verbs


def _accepts(found: Verb, produced: str | None) -> bool:
    if found.consumes is None or produced is None:
        return False
    if produced in found.consumes:
        return True
    # ANY covers row kinds only. A rendered view and a block of text are what
    # a pipeline ends with, so a verb that wants rows must not silently
    # accept them.
    return ANY in found.consumes and produced in ROW_KINDS


def _english(kinds: tuple[str, ...] | None) -> str:
    if not kinds:
        return "nothing"
    if ANY in kinds:
        return "any rows"
    return " or ".join(kinds)


def _check_arity(found: Verb, stage: Stage, source: str) -> None:
    low, high = found.positionals
    count = len(stage.positionals)
    if count < low:
        raise TypeCheckError(
            f"`{found.name}` needs {low} argument{'' if low == 1 else 's'}"
            + (f" -- usage: {found.usage}" if found.usage else ""),
            source,
            stage.offset,
        )
    if high is not None and count > high:
        extra = stage.positionals[high]
        raise TypeCheckError(
            f"`{found.name}` takes at most {high} argument{'' if high == 1 else 's'}"
            + (f" -- usage: {found.usage}" if found.usage else ""),
            source,
            extra.offset,
        )


def _check_keys(found: Verb, stage: Stage, source: str) -> None:
    for condition in stage.conditions:
        if condition.key not in found.keys:
            raise TypeCheckError(
                f"`{found.name}` has no key `{condition.key}`"
                + did_you_mean(condition.key, list(found.keys))
                + (f" -- it takes {', '.join(found.keys)}" if found.keys else ""),
                source,
                condition.offset,
            )


def _check_flags(found: Verb, stage: Stage, source: str) -> None:
    for name in stage.flags:
        if name not in found.flags:
            raise TypeCheckError(
                f"`{found.name}` has no flag `--{name}`" + did_you_mean(name, list(found.flags)),
                source,
                stage.offset,
            )


def groups() -> dict[str, list[Verb]]:
    out: dict[str, list[Verb]] = {}
    for found in VERBS.values():
        out.setdefault(found.group, []).append(found)
    for entries in out.values():
        entries.sort(key=lambda v: v.name)
    return out
