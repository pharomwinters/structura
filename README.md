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

Phases 0 and 1 are done. No window yet — see the phase table in the design
doc. What works:

- The document model, with an immutable ULID on every document.
- The schema, loaded from `structura.toml` and validated on load.
- The markdown store: parse, validate, and write back only the bytes that
  changed.
- The index: SQLite, incremental sync, link resolution, full-text search, and
  a filesystem watcher.
- The export renderers, byte-identical to the legacy generated registers.

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
```

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
