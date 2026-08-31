# Structura

A single-user document database with a personal information manager built on it.
Open source, local-first, offline, and deliberately not a mail client.

The design in [`docs/design.md`](docs/design.md) explains the whole thing. The
short version: documents are bags of fields, a form says how you edit one, a
view is a selection plus columns evaluated live, and an agent is code that runs
over a set of documents. Notes, calendar, contacts, and tasks are all built out
of those four ideas rather than beside them.

**Files are the truth**, in the native format for their domain — markdown for
notes, iCalendar for calendar, vCard for contacts. The index is a cache with no
authority; deleting it must lose nothing.

## Status

Phases 0, 1 and 2 are done. No window yet — see the phase table in the design
doc. What works:

- The document model, with an immutable ULID on every document.
- The schema, loaded from `structura.toml` and validated on load.
- The markdown store: parse, validate, and write back only the bytes that
  changed.
- The index: SQLite, incremental sync, link resolution, full-text search, and
  a filesystem watcher.
- The export renderers, byte-identical to the legacy generated registers.
- The command line: a typed pipeline over the index, checked before it runs,
  with saved views and a headless REPL.

## Try it

```sh
uv venv && . .venv/bin/activate
uv pip install -e ".[dev]"

structura lint    /path/to/workspace   # schema violations; exit 1 if any
structura scan    /path/to/workspace   # what the store sees
structura uid     /path/to/workspace   # which documents still need a UID
structura reindex /path/to/workspace   # bring the index into step
structura watch   /path/to/workspace   # reindex on every change
structura export  /path/to/workspace   # write the generated registers
structura shell   /path/to/workspace   # the interactive prompt
structura query -w /path/to/workspace "tasks open | sort age desc | table"
```

### The command line

A prompt whose vocabulary is the knowledge base, not the filesystem. A stage
does not emit text, it emits typed rows, so a pipeline is checked before it
runs:

```
find type:asset area:wwt | backlinks | where type:observation | sort date desc | table
tasks open age>120 | table age,description,asset,owner
placeholders | head 10 | table
find type:asset | tree
```

A mistake fails at the prompt with a caret under it, rather than halfway
through an action:

```
> find | where onwer:Maintenance
`documents` rows have no field `onwer` -- did you mean `owner`? ...
  find | where onwer:Maintenance
               ^
```

A **view is a saved pipeline**, not a stored copy of anything, so it is never
out of date. Views live as one TOML file each under `design/views/`:

```
view save "Open by age" tasks open | sort age desc | table age,description,owner,source
view list
view "Open by age"
```

`help` lists every verb, including the ones a later phase delivers — a roadmap
and a typo should not look alike.

The index lives at `<workspace>/.structura/index.db` and is a cache with no
authority. `structura reindex --rebuild` deletes it first, which is always a
safe answer to any index problem — if it ever stops being safe, that is the
bug.

## Tests

```sh
pytest
```

The suite includes the legacy validator's own tests, ported with their
assertions unchanged — the phase 0 gate is that the rules did not shift while
the code moved.

**Lint parity against real content** is the acceptance test that matters, and
it needs a workspace to run against:

```sh
STRUCTURA_LEGACY_VAULT=/path/to/vault \
STRUCTURA_LEGACY_SCRIPTS=/path/to/vault/.foam/scripts \
pytest tests/test_parity.py -v
```

Without those variables the parity tests skip, so CI stays green on a machine
that does not have the private content.

The performance budget is measured against a 5,000-document workspace and is
marked `slow`:

```sh
pytest -m slow          # just the budget
pytest -m "not slow"    # everything else
```

## Licence

MIT.
