# Structura

A single-user document database with a personal information manager built on it.
Open source, local-first, offline, and deliberately not a mail client.

The design in [`docs/design.md`](docs/design.md) explains the whole thing, and
[`docs/theme.md`](docs/theme.md) specifies Nótt & Dagr, the paired dark/light
colour scheme it uses. The
short version: documents are bags of fields, a form says how you edit one, a
view is a selection plus columns evaluated live, and an agent is code that runs
over a set of documents. Notes, calendar, contacts, and tasks are all built out
of those four ideas rather than beside them.

**Files are the truth**, in the native format for their domain — markdown for
notes, iCalendar for calendar, vCard for contacts. The index is a cache with no
authority; deleting it must lose nothing.

## Status

Phases 0-3 are done. There is a window.

What works:

- The document model, with an immutable ULID on every document.
- The schema, loaded from `structura.toml` and validated on load.
- The markdown store: parse, validate, and write back only the bytes that
  changed.
- The index: SQLite, incremental sync, link resolution, full-text search, and
  a filesystem watcher.
- The export renderers, byte-identical to the legacy generated registers.
- The command line: a typed pipeline over the index, checked before it runs,
  with saved views and a headless REPL.
- The window: three panes, a navigator, a source editor that saves without
  reformatting, and the Nótt & Dagr palette.

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
structura gui     /path/to/workspace   # the window
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

## The window

The window is an optional extra, so the CLI, the index and the query pipeline
install and run on a machine with no Qt:

```sh
uv pip install -e ".[gui,dev]"
structura gui /path/to/workspace --theme nott   # or dagr, or system
```

Without the `gui` extra the UI tests are skipped rather than erroring, and
everything else runs. On a bare Linux box PySide6 also needs
`libegl1 libgl1 libxkbcommon0 libdbus-1-3 libfontconfig1`.

Three panes and a command bar. The navigator lists folders, saved views, tags
and standing registers; the view pane shows whatever the last pipeline
produced, whatever kind of rows those are; the document pane is source mode,
and the only mode you type in.

| Key | | Key | |
| --- | --- | --- | --- |
| `Ctrl+L` | focus the command line | `Ctrl+S` | save |
| `Ctrl+O` | quick open by title | `Ctrl+B` | backlinks of this document |
| `F5` | reindex | `Alt+←` `→` | navigation history |
| `Ctrl+1/2/3` | Notes / Calendar / Contacts | | |

Calendar and Contacts are present and disabled, and say which phase they
arrive in — a roadmap and a missing feature should not look alike.

**Saving never reformats.** Opening every document and saving it unedited
leaves the working tree empty; that is an acceptance test, over CRLF, LF and
mixed line endings, files with no trailing newline, tabs, trailing spaces and
unicode. If a document changed on disk while you were editing it, saving asks
— reload, overwrite, or save a copy — with the on-disk time shown.

## Colours

[Nótt & Dagr](docs/theme.md), loaded as data — one TOML per variant, so a
third is a file rather than a code change. Nótt is the default; `--theme dagr`
or `--theme system` for the others.

The command line uses the ANSI half of the same palette, and only when stdout
is a terminal: `structura query ... > file.md` writes clean markdown, and
`NO_COLOR` turns colour off regardless.

## Licence

**GPL-3.0-or-later.** The full text is in [`LICENSE`](LICENSE).

Structura bundles Qt, used under the **LGPL-3.0-only** — the option that
obliges us to keep Qt replaceable, which is why builds ship as a directory or
a native installer and never as a one-file freeze. What ships, under what
terms, and how to swap Qt out is in
[`THIRD-PARTY-NOTICES.md`](THIRD-PARTY-NOTICES.md), and the running program
will tell you itself:

```sh
structura licenses
```

This program comes with ABSOLUTELY NO WARRANTY.
