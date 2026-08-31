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
from structura.theme.ansi import Palette

BANNER = "structura — type `help` for verbs, `.quit` to leave"
PROMPT = "> "
HISTORY_LIMIT = 2000

#: Table rules and the em dash standing for an empty cell: structure rather
#: than content, so they take the muted role.
_MUTED_LINE = ("| ---", "|---")


def history_path(workspace: Path) -> Path:
    return workspace / ".structura" / "history"


def render(result, palette: Palette | None = None) -> str:
    """What to print for a result.

    A pipeline that ends without a render verb still has to show something,
    and a table is the right default: it is what the result already is.
    """
    text = result.text if result.kind in (TEXT, VIEW) and result.text is not None else table(result)
    return colourise(text, palette) if palette is not None else text


def colourise(text: str, palette: Palette) -> str:
    """Paint rendered output with the ANSI half of the theme.

    Deliberately applied to the rendered text rather than inside the
    formatter: `export` writes what the formatter produced, and a register
    full of escape sequences would fail export parity. Colour is the last
    thing that happens, and only on the way to a terminal.
    """
    if not palette.enabled or not text:
        return text

    lines = text.splitlines()
    painted: list[str] = []
    header_pending = True
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith("## "):
            painted.append(palette.header(line))
        elif stripped.startswith(_MUTED_LINE):
            painted.append(palette.muted(line))
            header_pending = False
        elif line.startswith("|") and header_pending:
            painted.append(palette.header(line))
        elif line.startswith("|"):
            painted.append(line)
        else:
            painted.append(line)
    return "\n".join(painted) + ("\n" if text.endswith("\n") else "")


class Repl:
    def __init__(
        self,
        context: Context,
        *,
        use_readline: bool = True,
        palette: Palette | None = None,
    ) -> None:
        self.context = context
        self.palette = palette if palette is not None else Palette.for_stream()
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
            report = Indexer(self.context.db, self.context.store).sync()
            return f"{self.palette.success(str(report))}\n", True
        if stripped in (".help", "?"):
            return f"{BANNER}\n  .sync  reindex now\n  .quit  leave\n", True

        try:
            return render(run(stripped, self.context), self.palette), True
        except QueryError as exc:
            return f"{self._paint_error(exc)}\n", True

    def _paint_error(self, exc: QueryError) -> str:
        """The message in red, the echoed input plain, the caret in red.

        Painting the echoed line too would make the user's own text look like
        part of the complaint.
        """
        if not self.palette.enabled:
            return exc.render()
        lines = exc.render().splitlines()
        if len(lines) < 3:
            return self.palette.error(exc.message)
        return "\n".join([self.palette.error(lines[0]), lines[1], self.palette.error(lines[2])])

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
        print(self.palette.muted(BANNER))
        count = self.context.index.document_count()
        print(f"  {self.palette.number(str(count))} documents indexed\n")

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
