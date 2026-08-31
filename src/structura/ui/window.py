"""The window.

Three panes and a command bar, assembled from parts that each know one thing.
The window itself knows the keymap, the navigation history, and what to do
when a save hits a conflict — and nothing else, because everything else has a
home a layer down where it can be tested without a screen.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QInputDialog,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from structura.app import ConflictError, DocumentBuffer
from structura.core.paths import relative_display
from structura.index import Indexer
from structura.index.watch import Watcher
from structura.query import Context, QueryError, Result, complete, run
from structura.query.views import load_views
from structura.theme import Theme, load

from .highlight import resolver_for
from .panes import AppSwitcher, CommandBar, Editor, Navigator, StatusBar, ViewPane, titled

HISTORY_LIMIT = 500
OPENING_VIEW = "tasks open | sort age desc | table"


class MainWindow(QMainWindow):
    """One workspace, open."""

    indexed = Signal()

    def __init__(self, context: Context, theme: Theme | None = None) -> None:
        super().__init__()
        self.context = context
        self.theme = theme or load()
        self.buffer: DocumentBuffer | None = None
        self._history: list[Path] = []
        self._position = -1
        self._navigating = False

        self.setWindowTitle(f"Structura — {context.workspace.name}")
        self.resize(1280, 820)
        self._build()
        self._actions()

        self.watcher = Watcher(
            Indexer(context.db, context.store), on_sync=lambda report: self.indexed.emit()
        )
        self.indexed.connect(self._on_external_change)

    # --- construction --------------------------------------------------

    def _build(self) -> None:
        self.switcher = AppSwitcher()
        self.navigator = Navigator()
        self.view = ViewPane(self.theme)
        self.editor = Editor(self.theme, self.context.schema)
        self.command = CommandBar(self._completions)
        self.status = StatusBar()

        self.view_box = titled("View", self.view)
        self.document_box = titled("Document", self.editor)

        right = QSplitter(Qt.Orientation.Vertical)
        right.addWidget(self.view_box)
        right.addWidget(self.document_box)
        right.setStretchFactor(0, 2)
        right.setStretchFactor(1, 3)
        self.right_splitter = right

        panes = QSplitter(Qt.Orientation.Horizontal)
        panes.addWidget(titled("Navigator", self.navigator))
        panes.addWidget(right)
        panes.setStretchFactor(0, 1)
        panes.setStretchFactor(1, 4)
        panes.setSizes([260, 1020])

        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(panes, 1)
        layout.addWidget(self.command)
        layout.addWidget(self.status)

        shell = QWidget()
        row = QVBoxLayout(shell)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)

        outer = QSplitter(Qt.Orientation.Horizontal)
        outer.addWidget(self.switcher)
        outer.addWidget(body)
        outer.setStretchFactor(1, 1)
        outer.setCollapsible(0, False)
        outer.setSizes([56, 1224])
        row.addWidget(outer)
        self.setCentralWidget(shell)

        self.navigator.document_chosen.connect(self.open_document)
        self.navigator.query_chosen.connect(self.run_pipeline)
        self.view.document_chosen.connect(self.open_document)
        self.command.submitted.connect(self.run_pipeline)
        self.editor.save_requested.connect(self.save_document)
        self.switcher.switched.connect(self._switch_app)

    def _actions(self) -> None:
        def act(shortcut: str, slot, name: str) -> None:
            action = QAction(name, self)
            action.setShortcut(QKeySequence(shortcut))
            action.triggered.connect(slot)
            self.addAction(action)

        act("Ctrl+L", self.focus_command, "Focus command line")
        act("Ctrl+S", self.save_document, "Save")
        act("Ctrl+O", self.quick_open, "Quick open")
        act("Ctrl+B", self.show_backlinks, "Backlinks")
        act("F5", self.reindex, "Reindex")
        act("Alt+Left", self.go_back, "Back")
        act("Alt+Right", self.go_forward, "Forward")
        act("Ctrl+1", lambda: self._switch_app("notes"), "Notes")
        act("Ctrl+2", lambda: self._switch_app("calendar"), "Calendar")
        act("Ctrl+3", lambda: self._switch_app("contacts"), "Contacts")

    # --- starting up ---------------------------------------------------

    def start(self) -> None:
        """Sync, fill the panes, and begin watching."""
        self.reindex(announce=False)
        self.run_pipeline(OPENING_VIEW, remember=False)
        self.watcher.start()
        self.command.setFocus()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt's name
        self.watcher.stop()
        super().closeEvent(event)

    # --- the command line ----------------------------------------------

    def _completions(self, text: str) -> list[str]:
        return [c.text for c in complete(text, self.context.index)]

    def run_pipeline(self, text: str, *, remember: bool = True) -> None:
        try:
            result = run(text, self.context)
        except QueryError as exc:
            self.status.say(exc.message, "error")
            return

        if result.kind == "text" and result.text is not None:
            self.status.say(result.text.strip().splitlines()[0] if result.text.strip() else "done")
            self.view.show_result(Result(kind="text", rows=[]))
            return

        self.view.show_result(result)
        self.view_box.title_label.setText(f"VIEW — {text}")
        if remember:
            self.command.setText("")
        self.status.say(f"{len(result.rows)} row(s) · {result.kind}")

    def focus_command(self) -> None:
        self.command.setFocus()
        self.command.selectAll()

    # --- documents -----------------------------------------------------

    def open_document(self, path: Path, *, remember: bool = True) -> None:
        path = Path(path)
        if not path.is_absolute():
            path = self.context.workspace / path
        if self.buffer is not None and self.buffer.is_dirty and not self._confirm_discard():
            return
        try:
            self.buffer = DocumentBuffer.open(self.context.store, path)
        except OSError as exc:
            self.status.say(f"cannot open {path.name}: {exc}", "error")
            return

        self.editor.highlighter.set_resolver(resolver_for(self.context.index))
        self.editor.set_document_text(self.buffer.text)
        self.document_box.title_label.setText(
            f"DOCUMENT — {relative_display(path, self.context.workspace)}"
        )
        if remember and not self._navigating:
            self._remember(path)
        self.status.say(f"opened {self.buffer.title}")

    def save_document(self) -> None:
        if self.buffer is None:
            return
        self.buffer.set_text(self.editor.toPlainText())
        try:
            self.buffer.save()
        except ConflictError as exc:
            self._resolve_conflict(exc)
            return
        self.editor.document().setModified(False)
        self.editor.set_document_text(self.buffer.text)
        self.reindex(announce=False, paths=[self.buffer.path])
        self.status.say(f"saved {self.buffer.title}", "ok")

    def _resolve_conflict(self, conflict: ConflictError) -> None:
        """Reload, overwrite, or save a copy — with the on-disk time shown.

        Never a silent choice. A single-writer workflow does not mean the
        program gets to decide which writer wins.
        """
        box = QMessageBox(self)
        box.setWindowTitle("Changed on disk")
        box.setText(str(conflict))
        box.setInformativeText("This document changed outside Structura while you were editing it.")
        reload_ = box.addButton("Reload", QMessageBox.ButtonRole.DestructiveRole)
        overwrite = box.addButton("Overwrite", QMessageBox.ButtonRole.AcceptRole)
        copy = box.addButton("Save a copy", QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(copy)
        box.exec()

        clicked = box.clickedButton()
        assert self.buffer is not None
        if clicked is reload_:
            self.buffer.reload()
            self.editor.set_document_text(self.buffer.text)
            self.status.say("reloaded from disk")
        elif clicked is overwrite:
            self.buffer.save(force=True)
            self.status.say("overwrote the version on disk", "ok")
        elif clicked is copy:
            target = self.buffer.save_a_copy()
            self.status.say(f"saved a copy as {target.name}", "ok")

    def _confirm_discard(self) -> bool:
        answer = QMessageBox.question(
            self,
            "Unsaved changes",
            f"{self.buffer.title if self.buffer else 'This document'} has unsaved changes.",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Save:
            self.save_document()
            return True
        return answer == QMessageBox.StandardButton.Discard

    def quick_open(self) -> None:
        titles = sorted(d.title for d in self.context.index.documents())
        title, chosen = QInputDialog.getItem(self, "Quick open", "Title:", titles, 0, True)
        if not chosen or not title:
            return
        found = self.context.index.resolve(title)
        if found is None:
            self.status.say(f"no document titled `{title}`", "error")
            return
        self.open_document(found.path)

    def show_backlinks(self) -> None:
        if self.buffer is None:
            self.status.say("no document open", "error")
            return
        self.run_pipeline(f'find title:"{self.buffer.title}" | backlinks | table', remember=False)

    # --- navigation history ---------------------------------------------

    def _remember(self, path: Path) -> None:
        del self._history[self._position + 1 :]
        self._history.append(path)
        del self._history[:-HISTORY_LIMIT]
        self._position = len(self._history) - 1

    def go_back(self) -> None:
        self._step(-1)

    def go_forward(self) -> None:
        self._step(1)

    def _step(self, delta: int) -> None:
        target = self._position + delta
        if not 0 <= target < len(self._history):
            return
        self._position = target
        self._navigating = True
        try:
            self.open_document(self._history[target], remember=False)
        finally:
            self._navigating = False

    # --- the index -------------------------------------------------------

    def reindex(self, *, announce: bool = True, paths: list[Path] | None = None) -> None:
        indexer = Indexer(self.context.db, self.context.store)
        report = indexer.sync_paths(paths) if paths else indexer.sync()
        self._refresh_navigator()
        if announce:
            self.status.say(str(report), "ok" if not report.errors else "error")

    def _refresh_navigator(self) -> None:
        try:
            views = load_views(self.context)
        except QueryError:
            views = []
        self.navigator.populate(
            self.context.workspace,
            self.context.store.paths(),
            views,
            self.context.index.tags(),
        )

    def _on_external_change(self) -> None:
        """A file changed outside Structura.

        The navigator and the current view are refreshed; the open buffer is
        deliberately left alone, because taking someone's editor out from
        under them is worse than a stale pane. The conflict prompt handles it
        at save time, which is the moment it actually matters.
        """
        QTimer.singleShot(0, self._refresh_navigator)
        if self.buffer is not None and self.buffer.disk_changed():
            self.status.say(f"{self.buffer.path.name} changed on disk", "busy")

    # --- applications -----------------------------------------------------

    def _switch_app(self, key: str) -> None:
        if key == "notes":
            self.switcher.buttons["notes"].setChecked(True)
            return
        phase = {"calendar": "phase 5", "contacts": "phase 6"}[key]
        self.switcher.buttons["notes"].setChecked(True)
        self.status.say(f"{key} arrives in {phase}", "busy")
