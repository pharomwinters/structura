"""Headless entry point.

The CLI is not a toy or a debugging aid: it is the second consumer of the
layers below the UI, and having two is what keeps that boundary honest. By the
end of phase 2 it grows the query pipeline; for now it is enough to index a
workspace, watch it, lint it, and export the registers.

    structura lint     [workspace]     schema violations; exit 1 if any
    structura scan     [workspace]     what the store sees, without validating
    structura uid      [workspace]     backfill document UIDs
    structura reindex  [workspace]     bring the index into step
    structura watch    [workspace]     reindex on every change until interrupted
    structura export   [workspace]     write the generated registers
    structura query    <pipeline>      run one pipeline and print the result
    structura shell    [workspace]     the interactive prompt
    structura gui      [workspace]     the window
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import threading
from datetime import date
from pathlib import Path

from structura.core.paths import relative_display
from structura.core.schema import SchemaError, load_schema
from structura.index import Database, Index, Indexer
from structura.index.watch import Watcher
from structura.query import Context, QueryError
from structura.stores.markdown import MarkdownStore
from structura.theme import SYSTEM, VARIANTS
from structura.views import render

REGISTERS = {
    "Open Items.md": render.render_open_items,
    "Assets.md": render.render_assets,
    "Contacts.md": render.render_contacts,
}


def _store(workspace: Path) -> MarkdownStore:
    return MarkdownStore(workspace, load_schema(workspace))


def cmd_lint(workspace: Path, *, quiet: bool = False) -> int:
    store = _store(workspace)
    documents = store.documents()
    problems = store.validate(documents)

    if not quiet:
        print(f"  {len(documents)} documents scanned")
    if problems:
        print(f"\n  {len(problems)} schema violation(s):", file=sys.stderr)
        for problem in problems:
            print(f"    warn  {problem.message}", file=sys.stderr)
        return 1
    if not quiet:
        print("  schema clean")
    return 0


def cmd_scan(workspace: Path) -> int:
    store = _store(workspace)
    documents = store.documents()
    tasks = [t for d in documents for t in d.tasks]
    typed: dict[str, int] = {}
    for doc in documents:
        typed[str(doc.dtype)] = typed.get(str(doc.dtype), 0) + 1

    print(
        f"  {len(documents)} documents · {len(tasks)} tasks "
        f"({sum(1 for t in tasks if not t.done)} open)"
    )
    print(f"  {sum(1 for d in documents if d.uid is None)} without a uid")
    for dtype, count in sorted(typed.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"    {count:>5}  {dtype}")
    return 0


def cmd_uid(workspace: Path, *, apply: bool = False) -> int:
    store = _store(workspace)
    without = [doc for doc in store.documents() if doc.uid is None]
    if not without:
        print("  every document already has a uid")
        return 0
    if not apply:
        print(f"  {len(without)} document(s) have no uid. Re-run with --apply to stamp them:")
        for doc in without[:20]:
            print(f"    {relative_display(doc.path, store.root)}")
        if len(without) > 20:
            print(f"    ... and {len(without) - 20} more")
        return 0
    for doc in without:
        store.assign_uid(doc.path)
    print(f"  stamped {len(without)} document(s)")
    return 0


def cmd_reindex(workspace: Path, *, rebuild: bool = False) -> int:
    store = _store(workspace)
    # One Database object, opened once. Building a second one from the first
    # one's path leaked the first one's writer connection, which is invisible
    # on Linux and stops `--rebuild` dead on Windows: an open handle cannot be
    # unlinked there.
    db = Database.open(workspace)
    try:
        if rebuild:
            db.drop()
            db.ensure()
        report = Indexer(db, store).sync()
        print(f"  {report}")
        for path, message in report.errors:
            print(f"    warn  {path}: {message}", file=sys.stderr)
        print(f"  {Index(db).document_count()} documents indexed")
        return 1 if report.errors else 0
    finally:
        db.close()


def cmd_watch(workspace: Path) -> int:
    store = _store(workspace)
    db = Database.open(workspace)
    try:
        indexer = Indexer(db, store)
        print(f"  initial sync: {indexer.sync()}")

        stopping = threading.Event()

        def report(result) -> None:
            if result.changed:
                print(f"  {result}")

        def interrupt(*_args: object) -> None:
            stopping.set()

        signal.signal(signal.SIGINT, interrupt)
        with Watcher(indexer, on_sync=report):
            print(f"  watching {store.root} — Ctrl-C to stop")
            stopping.wait()
        print("\n  stopped")
    finally:
        db.close()
    return 0


def cmd_export(workspace: Path, *, out: Path | None = None, today: date | None = None) -> int:
    store = _store(workspace)
    documents = store.documents()
    when = today or date.today()
    target = out or (workspace / "0-Index")
    target.mkdir(parents=True, exist_ok=True)

    for filename, renderer in REGISTERS.items():
        (target / filename).write_text(renderer(documents, when), encoding="utf-8", newline="\n")
        print(f"  wrote  {target.name}/{filename}")

    # Placeholders needs the on-disk filename set too (legacy R21), so it is
    # not driven through the uniform (documents, today) signature above.
    (target / "Placeholders.md").write_text(
        render.render_placeholders(documents, when, frozenset(store.link_target_names())),
        encoding="utf-8",
        newline="\n",
    )
    print(f"  wrote  {target.name}/Placeholders.md")
    return 0


def cmd_query(workspace: Path, pipeline: str, *, sync: bool = True) -> int:
    from structura.query import run
    from structura.repl import render

    with Context.open(workspace) as context:
        if sync:
            context.sync()
        try:
            sys.stdout.write(render(run(pipeline, context)))
        except QueryError as exc:
            print(f"structura: {exc.render()}", file=sys.stderr)
            return 1
    return 0


def cmd_shell(workspace: Path) -> int:
    from structura.repl import Repl

    with Context.open(workspace) as context:
        context.sync()
        return Repl(context).run()


def cmd_gui(workspace: Path, theme: str) -> int:
    # Imported here, not at module scope: the CLI must keep working on a
    # machine with no Qt installed, and say so usefully rather than failing to
    # import at all.
    try:
        from structura.ui import run as run_window
    except ImportError as exc:  # pragma: no cover - depends on the install
        print(
            f"structura: the window needs PySide6, which is not installed ({exc}).\n"
            f"           install it with: pip install 'structura[gui]'",
            file=sys.stderr,
        )
        return 3
    return run_window(workspace, theme)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="structura", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    for name, help_text in (
        ("lint", "report schema violations"),
        ("scan", "summarise what the store sees"),
        ("uid", "backfill document UIDs"),
        ("reindex", "bring the index into step with the files"),
        ("watch", "reindex on every change until interrupted"),
        ("export", "write the generated registers"),
        ("shell", "the interactive prompt"),
        ("gui", "the window"),
    ):
        child = sub.add_parser(name, help=help_text)
        child.add_argument("workspace", nargs="?", default=".", type=Path)
        if name == "gui":
            child.add_argument(
                "--theme",
                default=SYSTEM,
                choices=[*VARIANTS, SYSTEM],
                help="nott (dark), dagr (light), or follow the desktop",
            )
        if name == "uid":
            child.add_argument("--apply", action="store_true", help="write the UIDs")
        if name == "lint":
            child.add_argument("-q", "--quiet", action="store_true")
        if name == "reindex":
            child.add_argument(
                "--rebuild",
                action="store_true",
                help="delete the index first — always a safe answer, it is a cache",
            )
        if name == "export":
            child.add_argument("--out", type=Path, help="output directory (default 0-Index/)")
            child.add_argument(
                "--today", type=date.fromisoformat, help="date to render as (YYYY-MM-DD)"
            )

    query = sub.add_parser("query", help="run one pipeline and print the result")
    query.add_argument("pipeline", help='e.g. "tasks open | sort age desc | table"')
    query.add_argument("-w", "--workspace", default=".", type=Path)
    query.add_argument("--no-sync", action="store_true", help="query the index as it stands")

    args = parser.parse_args(argv)
    workspace = args.workspace.resolve()

    try:
        if args.command == "lint":
            return cmd_lint(workspace, quiet=args.quiet)
        if args.command == "scan":
            return cmd_scan(workspace)
        if args.command == "uid":
            return cmd_uid(workspace, apply=args.apply)
        if args.command == "reindex":
            return cmd_reindex(workspace, rebuild=args.rebuild)
        if args.command == "watch":
            return cmd_watch(workspace)
        if args.command == "export":
            return cmd_export(workspace, out=args.out, today=args.today)
        if args.command == "query":
            return cmd_query(workspace, args.pipeline, sync=not args.no_sync)
        if args.command == "shell":
            return cmd_shell(workspace)
        if args.command == "gui":
            return cmd_gui(workspace, args.theme)
    except SchemaError as exc:
        print(f"structura: schema error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
    except BrokenPipeError:
        # `structura uid | head -5` closes the pipe under us. Exiting with a
        # traceback there makes a normal shell idiom look like a crash.
        # Redirect stdout to devnull so the interpreter's own flush at exit
        # does not raise a second time on the way out.
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
