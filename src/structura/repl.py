"""The headless REPL.

Phase 2 ends here: no window, but the workspace is queryable from a prompt,
which is already more than existed before. Phase 3 moves this same engine
behind a command bar at the bottom of a three-pane window; nothing in
`structura.query` needs to change when it does, which is the point of having
built it headless.

History persists to `.structura/history`, so the prompt remembers across
sessions the way a shell does.
"""

from __future__ import annotations

import sys
from pathlib import Path

from structura.index import Indexer
from structura.query import Context, QueryError, complete
from structura.query.format import table
from structura.query.rows import TEXT, VIEW

BANNER = "structura — type `help` for verbs, `.quit` to leave"
PROMPT = "> "
HISTORY_LIMIT = 2000


def history_path(workspace: Path) -> Path:
    return workspace / ".structura" / "history"


def render(result) -> str:
    """What to print for a result.

    A pipeline that ends without a render verb still has to show something,
    and a table is the right default: it is what the result already is.
    """
    if result.kind in (TEXT, VIEW) and result.text is not None:
        return result.text
    return table(result)


class Repl:
    def __init__(self, context: Context, *, use_readline: bool = True) -> None:
        self.context = context
        self.readline = None
        if use_readline:
            try:
                import readline

                self.readline = readline
            except ImportError:  # pragma: no cover - Windows without pyreadline
                self.readline = None

    # --- one line -----------------------------------------------------

    def execute(self, line: str) -> tuple[str, bool]:
        """Run one line. Returns (output, keep_going)."""
        from structura.query import run

        stripped = line.strip()
        if not stripped:
            return "", True
        if stripped in (".quit", ".exit", ".q"):
            return "", False
        if stripped == ".sync":
            return f"{Indexer(self.context.db, self.context.store).sync()}\n", True
        if stripped in (".help", "?"):
            return f"{BANNER}\n  .sync  reindex now\n  .quit  leave\n", True

        try:
            return render(run(stripped, self.context)), True
        except QueryError as exc:
            return f"{exc.render()}\n", True

    # --- the loop -----------------------------------------------------

    def _setup_readline(self) -> None:
        if self.readline is None:
            return
        path = history_path(self.context.workspace)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            try:
                self.readline.read_history_file(str(path))
            except OSError:  # pragma: no cover - unreadable history is not fatal
                pass
        self.readline.set_history_length(HISTORY_LIMIT)

        def completer(text: str, state: int):  # pragma: no cover - driven by readline
            buffer = self.readline.get_line_buffer()[: self.readline.get_endidx()]
            matches = [c.text for c in complete(buffer, self.context.index)]
            return matches[state] if state < len(matches) else None

        self.readline.set_completer(completer)
        self.readline.set_completer_delims(" \t|")
        self.readline.parse_and_bind("tab: complete")

    def _save_history(self) -> None:
        if self.readline is None:
            return
        try:
            self.readline.write_history_file(str(history_path(self.context.workspace)))
        except OSError:  # pragma: no cover
            pass

    def run(self, stream=None) -> int:
        self._setup_readline()
        print(BANNER)
        print(f"  {self.context.index.document_count()} documents indexed\n")

        while True:
            try:
                line = input(PROMPT) if stream is None else stream.readline()
            except EOFError:
                break
            except KeyboardInterrupt:
                print()
                continue
            if stream is not None and line == "":
                break

            output, keep_going = self.execute(line)
            if output:
                sys.stdout.write(output if output.endswith("\n") else output + "\n")
            if not keep_going:
                break

        self._save_history()
        return 0
