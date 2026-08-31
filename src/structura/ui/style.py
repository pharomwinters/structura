"""Qt styling, generated from a theme.

Qt's default look needs deliberate styling not to feel like 2009, and the
alternative to a stylesheet is a platform theme that would ignore Nótt and
Dagr entirely. So the whole window is styled from the palette, and the mapping
from surface to pane is the one the design states rather than whatever the
toolkit would have picked.

Functional colours appear here and nowhere near the document pane: they are
chrome -- borders, focus rings, state -- and on a page of prose they would
outshout the content.
"""

from __future__ import annotations

from structura.theme import Theme

#: Surface for each part of the window, per the design's Appearance section.
SURFACES = {
    "chrome": "surface.dark",
    "navigator": "surface.light",
    "view": "editor.background",
    "document": "editor.background",
    "floating": "surface.floating",
    "command": "surface.lighter",
    "status": "surface.dark",
    "separator": "editor.current_line",
}

MONO_STACK = '"Cascadia Mono", "JetBrains Mono", "Consolas", "DejaVu Sans Mono", monospace'
UI_STACK = '"Segoe UI", "Inter", "Noto Sans", sans-serif'


def stylesheet(theme: Theme) -> str:
    """The whole application's Qt stylesheet for one theme."""
    e, s, f = theme.editor, theme.surface, theme.functional
    return f"""
QWidget {{
    background: {e.background};
    color: {e.foreground};
    font-family: {UI_STACK};
    font-size: 13px;
}}

QMainWindow, QMainWindow::separator {{ background: {s.dark}; }}
QMainWindow::separator {{ width: 1px; height: 1px; background: {e.current_line}; }}

QSplitter::handle {{ background: {e.current_line}; }}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:vertical {{ height: 1px; }}

#AppSwitcher {{ background: {s.darker}; border: none; }}
#AppSwitcher QToolButton {{
    background: transparent;
    color: {e.comment};
    border: none;
    border-left: 2px solid transparent;
    padding: 10px 6px;
    font-size: 11px;
}}
#AppSwitcher QToolButton:hover {{ color: {e.foreground}; background: {s.dark}; }}
#AppSwitcher QToolButton:checked {{
    color: {e.foreground};
    background: {s.light};
    border-left: 2px solid {f.purple};
}}
#AppSwitcher QToolButton:disabled {{ color: {e.comment}; }}

#Navigator {{ background: {s.light}; border: none; }}
#Navigator::item {{ padding: 3px 4px; border: none; }}
#Navigator::item:hover {{ background: {s.floating}; }}
#Navigator::item:selected {{ background: {e.selection}; color: {e.foreground}; }}
#Navigator QHeaderView::section {{
    background: {s.light};
    color: {e.comment};
    border: none;
    border-bottom: 1px solid {e.current_line};
    padding: 4px 6px;
}}

#ViewPane {{
    background: {e.background};
    alternate-background-color: {e.background};
    gridline-color: {e.current_line};
    border: none;
    selection-background-color: {e.selection};
    selection-color: {e.foreground};
}}
#ViewPane::item {{ padding: 2px 6px; }}
#ViewPane QHeaderView::section {{
    background: {s.light};
    color: {e.comment};
    border: none;
    border-bottom: 1px solid {e.current_line};
    padding: 4px 6px;
    font-weight: 600;
}}

#Editor {{
    background: {e.background};
    color: {e.foreground};
    border: none;
    font-family: {MONO_STACK};
    font-size: 13px;
    selection-background-color: {e.selection};
    selection-color: {e.foreground};
}}

#CommandBar {{
    background: {s.lighter};
    color: {e.foreground};
    border: none;
    border-top: 1px solid {e.current_line};
    padding: 6px 8px;
    font-family: {MONO_STACK};
}}
#CommandBar:focus {{ border-top: 1px solid {f.purple}; }}

#StatusBar {{
    background: {s.dark};
    color: {e.comment};
    border-top: 1px solid {e.current_line};
    padding: 3px 8px;
    font-size: 12px;
}}
#StatusBar[state="error"] {{ color: {f.red}; }}
#StatusBar[state="busy"] {{ color: {f.orange}; }}
#StatusBar[state="ok"] {{ color: {f.green}; }}

#PaneTitle {{
    background: {s.light};
    color: {e.comment};
    border-bottom: 1px solid {e.current_line};
    padding: 4px 8px;
    font-size: 11px;
    font-weight: 600;
}}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; }}
QScrollBar::handle {{ background: {e.selection}; border-radius: 5px; min-height: 24px; }}
QScrollBar::handle:hover {{ background: {e.comment}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QToolTip {{
    background: {s.floating};
    color: {e.foreground};
    border: 1px solid {e.current_line};
    padding: 4px 6px;
}}

QMessageBox {{ background: {s.floating}; }}
QPushButton {{
    background: {s.lighter};
    color: {e.foreground};
    border: 1px solid {e.current_line};
    padding: 5px 12px;
}}
QPushButton:hover {{ border-color: {f.cyan}; }}
QPushButton:focus {{ border-color: {f.purple}; }}
QPushButton:default {{ border-color: {f.cyan}; }}

QLineEdit {{
    background: {s.floating};
    color: {e.foreground};
    border: 1px solid {e.current_line};
    padding: 5px 8px;
    selection-background-color: {e.selection};
}}
QLineEdit:focus {{ border-color: {f.purple}; }}

QListView {{ background: {s.floating}; border: 1px solid {e.current_line}; }}
QListView::item {{ padding: 4px 8px; }}
QListView::item:selected {{ background: {e.selection}; color: {e.foreground}; }}
"""
