"""The panes.

Each one is wiring: it owns a widget and a signal, and asks
`structura.app` or `structura.query` for anything worth testing. If logic
starts accumulating here, it belongs a layer down.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QKeyEvent, QTextCursor, QTextFormat
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QTableView,
    QTextEdit,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from structura.core.paths import relative_display
from structura.query import Result, complete
from structura.theme import Theme, load

from .highlight import MarkdownHighlighter
from .models import ResultModel


class PaneTitle(QLabel):
    """The one-line heading over a pane, so the layout explains itself."""

    def __init__(self, text: str) -> None:
        super().__init__(text.upper())
        self.setObjectName("PaneTitle")


def titled(title: str, widget: QWidget) -> QWidget:
    box = QWidget()
    layout = QVBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    label = PaneTitle(title)
    layout.addWidget(label)
    layout.addWidget(widget)
    box.title_label = label  # type: ignore[attr-defined]
    return box


# --- navigator --------------------------------------------------------


class Navigator(QTreeWidget):
    """Folders, saved views, tags and placeholders.

    A folder here is a directory, not the mutable membership kind: those
    arrive with `file` and `unfile` in phase 4, and calling both "folders"
    before then would teach the wrong noun.
    """

    document_chosen = Signal(Path)
    query_chosen = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("Navigator")
        self.setHeaderHidden(True)
        self.setIndentation(12)
        self.setUniformRowHeights(True)
        self.itemActivated.connect(self._activated)
        self.itemClicked.connect(self._activated)
        self._root = Path()

    def _activated(self, item: QTreeWidgetItem, _column: int = 0) -> None:
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(data, Path):
            self.document_chosen.emit(data)
        elif isinstance(data, str) and data:
            self.query_chosen.emit(data)

    def populate(self, root: Path, paths: list[Path], views, tags: dict[str, int]) -> None:
        expanded = {
            self.topLevelItem(i).text(0)
            for i in range(self.topLevelItemCount())
            if self.topLevelItem(i).isExpanded()
        } or {"Folders", "Saved views"}
        selected = self.currentItem().text(0) if self.currentItem() else None

        self.clear()
        self._root = root
        self._folders(root, paths)
        self._views(views)
        self._tags(tags)
        self._standing()

        for i in range(self.topLevelItemCount()):
            item = self.topLevelItem(i)
            item.setExpanded(item.text(0) in expanded)
            if selected and item.text(0) == selected:
                self.setCurrentItem(item)

    def _section(self, title: str) -> QTreeWidgetItem:
        item = QTreeWidgetItem([title])
        item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        self.addTopLevelItem(item)
        return item

    def _folders(self, root: Path, paths: list[Path]) -> None:
        section = self._section("Folders")
        folders: dict[str, QTreeWidgetItem] = {}
        for path in paths:
            relative = relative_display(path, root)
            parts = relative.split("/")
            parent = section
            for depth, part in enumerate(parts[:-1]):
                key = "/".join(parts[: depth + 1])
                if key not in folders:
                    folders[key] = QTreeWidgetItem(parent, [part])
                parent = folders[key]
            leaf = QTreeWidgetItem(parent, [path.stem])
            leaf.setData(0, Qt.ItemDataRole.UserRole, path)

    def _views(self, views) -> None:
        section = self._section("Saved views")
        for view in views:
            item = QTreeWidgetItem(section, [view.name])
            item.setData(0, Qt.ItemDataRole.UserRole, view.query)
            item.setToolTip(0, view.query)
        if not views:
            hint = QTreeWidgetItem(section, ["none saved"])
            hint.setFlags(Qt.ItemFlag.NoItemFlags)

    def _tags(self, tags: dict[str, int]) -> None:
        section = self._section("Tags")
        for tag, count in list(tags.items())[:40]:
            item = QTreeWidgetItem(section, [f"{tag}  ({count})"])
            item.setData(0, Qt.ItemDataRole.UserRole, f"find tag:{tag} | table")

    def _standing(self) -> None:
        """Queries worth a permanent place, because they are what the
        workspace is failing to answer."""
        section = self._section("Registers")
        for label, query in (
            ("Open tasks", "tasks open | sort age desc | table"),
            ("Placeholders", "placeholders | table"),
            ("Orphans", "orphans | sort title | table"),
            ("Assets", "find type:asset | tree"),
        ):
            item = QTreeWidgetItem(section, [label])
            item.setData(0, Qt.ItemDataRole.UserRole, query)


# --- view pane --------------------------------------------------------


class ViewPane(QTableView):
    """Whatever the last pipeline produced."""

    document_chosen = Signal(Path)

    def __init__(self, theme: Theme | None = None) -> None:
        super().__init__()
        self.setObjectName("ViewPane")
        self.model_ = ResultModel(theme)
        self.setModel(self.model_)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setShowGrid(False)
        self.setAlternatingRowColors(False)
        self.verticalHeader().setVisible(False)
        self.horizontalHeader().setStretchLastSection(True)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.doubleClicked.connect(self._open)
        self.activated.connect(self._open)

    def show_result(self, result: Result) -> None:
        self.model_.set_result(result)
        self.resizeColumnsToContents()
        header = self.horizontalHeader()
        for column in range(self.model_.columnCount()):
            header.resizeSection(column, min(header.sectionSize(column) + 16, 420))

    def _open(self, index) -> None:
        row = self.model_.row_at(index)
        if row is None:
            return
        # A row knows the document it stands for whatever kind it is: a task
        # row carries the note that raised it, a link row its source.
        path = row.get("path")
        if isinstance(path, str) and path:
            self.document_chosen.emit(Path(path))


# --- document pane ----------------------------------------------------


class Editor(QPlainTextEdit):
    """Source mode, and the only mode you type in.

    Preview is a toggle that arrives in phase 7 and is never an editing
    surface: for content whose schema is expressed in the text itself, a
    WYSIWYG layer over the data model is a machine for producing files that
    look right and index wrong.
    """

    save_requested = Signal()

    def __init__(self, theme: Theme | None = None, schema=None) -> None:
        super().__init__()
        self.setObjectName("Editor")
        self.theme = theme or load()
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.setTabStopDistance(32)
        self.highlighter = MarkdownHighlighter(self.document(), self.theme, schema)
        self.cursorPositionChanged.connect(self._highlight_current_line)
        self._highlight_current_line()

    def set_theme(self, theme: Theme) -> None:
        self.theme = theme
        self.highlighter.set_theme(theme)
        self._highlight_current_line()

    def _highlight_current_line(self) -> None:
        selection = QTextEdit.ExtraSelection()
        selection.format.setBackground(QColor(self.theme.editor.current_line))
        selection.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
        selection.cursor = self.textCursor()
        selection.cursor.clearSelection()
        self.setExtraSelections([selection])

    def set_document_text(self, text: str) -> None:
        """Replace the contents without the undo stack pretending it was typed."""
        cursor = self.textCursor()
        position = cursor.position()
        self.setPlainText(text)
        cursor = self.textCursor()
        cursor.setPosition(min(position, len(text)))
        self.setTextCursor(cursor)
        self.document().clearUndoRedoStacks()
        self.document().setModified(False)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - Qt's name
        if event.key() == Qt.Key.Key_S and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.save_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def goto_line(self, line: int) -> None:
        cursor = QTextCursor(self.document().findBlockByLineNumber(max(0, line - 1)))
        self.setTextCursor(cursor)
        self.centerCursor()


# --- command bar ------------------------------------------------------


class CommandBar(QLineEdit):
    """One line at the bottom, always present.

    Tab completion comes from `structura.query.complete`, which knows what a
    verb can follow and what fields the incoming rows have. None of that
    knowledge lives here.
    """

    submitted = Signal(str)

    def __init__(self, completions: Callable[[str], list[str]] | None = None) -> None:
        super().__init__()
        self.setObjectName("CommandBar")
        self.setPlaceholderText("tasks open | sort age desc | table     (Ctrl+L)")
        self.returnPressed.connect(self._submit)
        self._completions = completions or (lambda text: [c.text for c in complete(text)])
        self._history: list[str] = []
        self._position = 0

    def set_history(self, history: list[str]) -> None:
        self._history = list(history)
        self._position = len(self._history)

    @property
    def history(self) -> list[str]:
        return list(self._history)

    def _submit(self) -> None:
        text = self.text().strip()
        if not text:
            return
        if not self._history or self._history[-1] != text:
            self._history.append(text)
        self._position = len(self._history)
        self.submitted.emit(text)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - Qt's name
        key = event.key()
        if key == Qt.Key.Key_Up:
            self._walk(-1)
            event.accept()
            return
        if key == Qt.Key.Key_Down:
            self._walk(1)
            event.accept()
            return
        if key == Qt.Key.Key_Tab:
            self._complete()
            event.accept()
            return
        if key == Qt.Key.Key_Escape:
            self.clear()
            event.accept()
            return
        super().keyPressEvent(event)

    def _walk(self, step: int) -> None:
        if not self._history:
            return
        self._position = max(0, min(len(self._history), self._position + step))
        self.setText("" if self._position >= len(self._history) else self._history[self._position])

    def _complete(self) -> None:
        text = self.text()
        matches = self._completions(text)
        if not matches:
            return
        partial = "" if text.endswith(" ") else text.split(" ")[-1].split("|")[-1]
        head = text[: len(text) - len(partial)]
        if len(matches) == 1:
            self.setText(head + matches[0] + ("" if matches[0].endswith(":") else " "))
            return
        shared = _common_prefix(matches)
        if len(shared) > len(partial):
            self.setText(head + shared)


def _common_prefix(values: list[str]) -> str:
    if not values:
        return ""
    first, last = min(values), max(values)
    for index, char in enumerate(first):
        if index >= len(last) or last[index] != char:
            return first[:index]
    return first


# --- status line ------------------------------------------------------


class StatusBar(QLabel):
    """What the workspace is doing, in one line."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("StatusBar")
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.say("workspace ready")

    def say(self, message: str, state: str = "") -> None:
        self.setText(message)
        self.setProperty("state", state)
        self.style().unpolish(self)
        self.style().polish(self)


# --- application switcher ---------------------------------------------


class AppSwitcher(QWidget):
    """Notes, Calendar, Contacts.

    Calendar and Contacts are present and disabled rather than absent, for the
    same reason a promised verb is registered rather than unknown: a roadmap
    and a missing feature should not look alike.
    """

    switched = Signal(str)
    about_requested = Signal()

    def __init__(self, available: tuple[str, ...] = ("notes",)) -> None:
        super().__init__()
        self.setObjectName("AppSwitcher")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 6, 0, 6)
        layout.setSpacing(2)
        self.buttons: dict[str, QToolButton] = {}

        for key, label, phase in (
            ("notes", "Notes", ""),
            ("calendar", "Cal", "phase 5"),
            ("contacts", "Cont", "phase 6"),
        ):
            button = QToolButton()
            button.setText(label)
            button.setCheckable(True)
            button.setAutoExclusive(True)
            button.setFixedSize(QSize(52, 44))
            enabled = key in available
            button.setEnabled(enabled)
            button.setToolTip(label if enabled else f"{label} — arrives in {phase}")
            button.clicked.connect(lambda _checked=False, k=key: self.switched.emit(k))
            layout.addWidget(button)
            self.buttons[key] = button

        layout.addStretch(1)

        # GPLv3 §5(d): an interactive interface has to offer the legal notices
        # somewhere convenient and prominent. Pinned to the bottom of the one
        # piece of chrome that is always on screen, and also on F1.
        self.about = QToolButton()
        self.about.setText("?")
        self.about.setFixedSize(QSize(52, 32))
        self.about.setToolTip("About Structura — licence and notices (F1)")
        self.about.clicked.connect(self.about_requested.emit)
        layout.addWidget(self.about)

        self.buttons["notes"].setChecked(True)
