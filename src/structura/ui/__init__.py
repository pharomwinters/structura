"""The window.

**The only package that imports Qt.** Everything below it — the stores, the
index, the query pipeline, the document buffer, the theme — is importable and
testable without a toolkit, which is what having a second consumer (the CLI)
keeps honest.

Importing this package imports PySide6, so callers that may not have it
installed should import it inside a function and say something useful when it
is missing.
"""

from .app import apply_theme, build, run
from .highlight import MarkdownHighlighter, resolver_for
from .models import ResultModel
from .style import stylesheet
from .window import MainWindow

__all__ = [
    "MainWindow",
    "MarkdownHighlighter",
    "ResultModel",
    "apply_theme",
    "build",
    "resolver_for",
    "run",
    "stylesheet",
]
