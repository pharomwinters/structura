"""Headless entry point.

The CLI is not a toy or a debugging aid: it is the second consumer of
`structura.app`, and having two is what keeps the boundary below the UI honest.
Phase 0 has no app layer yet, so it drives the markdown store directly.

    structura lint [workspace]     schema violations; exit 1 if any
    structura scan [workspace]     what the store sees, without validating
    structura uid  [workspace]     backfill UIDs onto files that have none
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from structura.core.schema import SchemaError, load_schema
from structura.stores.markdown import MarkdownStore


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
    open_tasks = [t for t in tasks if not t.done]
    typed: dict[str, int] = {}
    for doc in documents:
        typed[str(doc.dtype)] = typed.get(str(doc.dtype), 0) + 1
    missing_uid = sum(1 for d in documents if d.uid is None)

    print(f"  {len(documents)} documents · {len(tasks)} tasks ({len(open_tasks)} open)")
    print(f"  {missing_uid} without a uid")
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
            print(f"    {doc.path.relative_to(store.root)}")
        if len(without) > 20:
            print(f"    ... and {len(without) - 20} more")
        return 0
    for doc in without:
        store.assign_uid(doc.path)
    print(f"  stamped {len(without)} document(s)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="structura", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    for name, help_text in (
        ("lint", "report schema violations"),
        ("scan", "summarise what the store sees"),
        ("uid", "backfill document UIDs"),
    ):
        child = sub.add_parser(name, help=help_text)
        child.add_argument("workspace", nargs="?", default=".", type=Path)
        if name == "uid":
            child.add_argument("--apply", action="store_true", help="write the UIDs")
        if name == "lint":
            child.add_argument("-q", "--quiet", action="store_true")

    args = parser.parse_args(argv)
    workspace = args.workspace.resolve()

    try:
        if args.command == "lint":
            return cmd_lint(workspace, quiet=args.quiet)
        if args.command == "scan":
            return cmd_scan(workspace)
        if args.command == "uid":
            return cmd_uid(workspace, apply=args.apply)
    except SchemaError as exc:
        print(f"structura: schema error: {exc}", file=sys.stderr)
        return 2
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
