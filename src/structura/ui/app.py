"""Starting the window.

The only place that constructs a `QApplication`, so everything else in
`structura.ui` is importable and testable without one.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication

from structura.query import Context
from structura.theme import DEFAULT, Theme, resolve

from .style import stylesheet
from .window import MainWindow

APP_NAME = "Structura"


def system_is_dark(app: QApplication) -> bool:
    """Whether the desktop is running a dark theme.

    Qt 6.5+ answers directly; older builds are asked the old way, by looking
    at whether the window text is lighter than the window itself.
    """
    hints = app.styleHints()
    scheme = getattr(hints, "colorScheme", None)
    if scheme is not None:
        try:
            return scheme() == Qt.ColorScheme.Dark
        except (AttributeError, TypeError):  # pragma: no cover - older Qt
            pass
    palette = app.palette()
    text = palette.color(QPalette.ColorRole.WindowText).lightness()
    window = palette.color(QPalette.ColorRole.Window).lightness()
    return text > window


def apply_theme(app: QApplication, theme: Theme) -> None:
    app.setStyleSheet(stylesheet(theme))


def build(workspace: Path, preference: str = DEFAULT, app: QApplication | None = None):
    """A window over a workspace, themed and ready to `start()`.

    Separate from `run` so a test can build one, drive it, and never enter an
    event loop.
    """
    owner = app or QApplication.instance()
    theme = resolve(preference, system_is_dark=system_is_dark(owner) if owner else None)
    if owner is not None:
        apply_theme(owner, theme)
    context = Context.open(workspace)
    return MainWindow(context, theme)


def run(workspace: Path, preference: str = DEFAULT) -> int:
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)

    window = build(workspace, preference, app)
    try:
        window.start()
        window.show()
        return app.exec()
    finally:
        window.context.close()
