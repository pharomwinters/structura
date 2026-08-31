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

Phase 0. No window yet — see the phase table in the design doc. What works:

- The document model, with an immutable ULID on every document.
- The schema, loaded from `structura.toml` and validated on load.
- The markdown store: parse, validate, and write back only the bytes that
  changed.
- `structura lint`, `scan`, and `uid`.

## Try it

```sh
uv venv && . .venv/bin/activate
uv pip install -e ".[dev]"

structura lint /path/to/workspace     # schema violations; exit 1 if any
structura scan /path/to/workspace     # what the store sees
structura uid  /path/to/workspace     # which documents still need a UID
```

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

## Licence

MIT.
