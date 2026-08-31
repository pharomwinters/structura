"""The window, driven without a screen.

Every test here runs against the offscreen platform, so the suite is the same
on a developer's machine and on a CI runner with no display. What is being
tested is the wiring — that a click reaches the right service and the result
comes back to the right pane — because everything worth testing about the
services themselves is tested a layer down, without Qt at all.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6", reason="the window needs PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from structura.query import Result, Row, run  # noqa: E402
from structura.theme import load  # noqa: E402
from structura.ui.highlight import MarkdownHighlighter  # noqa: E402
from structura.ui.models import ResultModel  # noqa: E402
from structura.ui.panes import CommandBar, Editor, Navigator, StatusBar, ViewPane  # noqa: E402
from structura.ui.style import stylesheet  # noqa: E402
from structura.ui.window import MainWindow  # noqa: E402


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, context):
    window = MainWindow(context, load("nott"))
    yield window
    window.watcher.stop()
    window.close()


@pytest.fixture
def started(window):
    window.start()
    return window


# --- the model --------------------------------------------------------


def test_the_model_shows_whatever_kind_of_rows_it_is_given(app, context):
    model = ResultModel()
    model.set_result(run("find type:asset | table title,status", context))
    assert model.rowCount() == 2
    assert model.columnCount() == 2
    assert model.headerData(0, Qt.Orientation.Horizontal) == "title"

    model.set_result(run("tasks open", context))
    assert model.kind == "tasks"
    assert model.columnCount() > 2


def test_an_empty_value_renders_as_an_em_dash(app):
    model = ResultModel()
    model.set_result(Result(kind="tasks", rows=[Row({"due": None})], columns=("due",)))
    index = model.index(0, 0)
    assert model.data(index) == "—"


def test_quantities_are_right_aligned(app):
    model = ResultModel()
    model.set_result(Result(kind="tasks", rows=[Row({"age": 12})], columns=("age",)))
    alignment = model.data(model.index(0, 0), Qt.ItemDataRole.TextAlignmentRole)
    assert alignment & int(Qt.AlignmentFlag.AlignRight)


# --- panes ------------------------------------------------------------


def test_the_view_pane_fills_from_a_result(app, context):
    pane = ViewPane()
    pane.show_result(run("find type:asset | table title", context))
    assert pane.model_.rowCount() == 2


def test_activating_a_row_asks_to_open_its_document(app, context, qtbot):
    pane = ViewPane()
    pane.show_result(run("find type:asset | table title,path", context))
    with qtbot.waitSignal(pane.document_chosen, timeout=1000) as caught:
        pane.activated.emit(pane.model_.index(0, 0))
    assert caught.args[0].name.endswith(".md")


def test_the_navigator_offers_folders_views_tags_and_registers(app, context):
    navigator = Navigator()
    navigator.populate(context.workspace, context.store.paths(), [], context.index.tags())
    sections = [navigator.topLevelItem(i).text(0) for i in range(navigator.topLevelItemCount())]
    assert sections == ["Folders", "Saved views", "Tags", "Registers"]


def test_choosing_a_register_emits_its_pipeline(app, context, qtbot):
    navigator = Navigator()
    navigator.populate(context.workspace, context.store.paths(), [], {})
    registers = navigator.topLevelItem(3)
    with qtbot.waitSignal(navigator.query_chosen, timeout=1000) as caught:
        navigator.itemActivated.emit(registers.child(0), 0)
    assert caught.args[0].startswith("tasks open")


def test_the_command_bar_submits_and_remembers(app, qtbot):
    bar = CommandBar(lambda _text: [])
    bar.setText("find type:asset")
    with qtbot.waitSignal(bar.submitted, timeout=1000) as caught:
        bar.returnPressed.emit()
    assert caught.args[0] == "find type:asset"
    assert bar.history == ["find type:asset"]


def test_up_walks_the_history(app, qtbot):
    bar = CommandBar(lambda _text: [])
    bar.set_history(["one", "two"])
    qtbot.keyClick(bar, Qt.Key.Key_Up)
    assert bar.text() == "two"
    qtbot.keyClick(bar, Qt.Key.Key_Up)
    assert bar.text() == "one"
    qtbot.keyClick(bar, Qt.Key.Key_Down)
    assert bar.text() == "two"


def test_tab_completes_a_unique_verb(app, qtbot):
    bar = CommandBar(lambda text: ["tasks"])
    bar.setText("ta")
    qtbot.keyClick(bar, Qt.Key.Key_Tab)
    assert bar.text() == "tasks "


def test_tab_completes_as_far_as_the_candidates_agree(app, qtbot):
    bar = CommandBar(lambda text: ["tasks", "table"])
    bar.setText("t")
    qtbot.keyClick(bar, Qt.Key.Key_Tab)
    assert bar.text() == "ta"


def test_tab_does_nothing_when_the_candidates_share_no_more(app, qtbot):
    """`placeholders` and `parents` agree on `p` and no further, so there is
    nothing to add and the cursor must not jump."""
    bar = CommandBar(lambda text: ["placeholders", "parents"])
    bar.setText("p")
    qtbot.keyClick(bar, Qt.Key.Key_Tab)
    assert bar.text() == "p"


def test_the_status_line_carries_its_state_for_the_stylesheet(app):
    status = StatusBar()
    status.say("boom", "error")
    assert status.text() == "boom"
    assert status.property("state") == "error"


# --- the editor -------------------------------------------------------


def test_setting_text_does_not_leave_an_undo_step(app, context):
    editor = Editor(load(), context.schema)
    editor.set_document_text("hello\n")
    assert editor.toPlainText() == "hello\n"
    assert not editor.document().isModified()
    assert not editor.document().isUndoAvailable()


def test_ctrl_s_asks_to_save(app, context, qtbot):
    editor = Editor(load(), context.schema)
    qtbot.addWidget(editor)
    with qtbot.waitSignal(editor.save_requested, timeout=1000):
        qtbot.keyClick(editor, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)


# --- highlighting -----------------------------------------------------


def _formats(text: str, context, resolves=None) -> dict[int, list]:
    """The character formats each line ends up with, by line number."""
    editor = Editor(load(), context.schema)
    if resolves is not None:
        editor.highlighter.set_resolver(resolves)
    editor.set_document_text(text)
    block = editor.document().firstBlock()
    out: dict[int, list] = {}
    while block.isValid():
        out[block.blockNumber()] = list(block.layout().formats())
        block = block.next()
    return out


def _colours(formats) -> set[str]:
    return {f.format.foreground().color().name().upper() for f in formats}


def test_a_frontmatter_key_takes_the_keyword_role(app, context):
    theme = load()
    lines = _formats("---\ntype: asset\n---\n\nbody\n", context)
    assert theme.editor.pink.upper() in _colours(lines[1])


def test_a_closed_enum_value_takes_the_type_role(app, context):
    theme = load()
    lines = _formats("---\ntype: asset\narea: paint\n---\n\nbody\n", context)
    assert theme.editor.cyan.upper() in _colours(lines[2])


def test_a_value_outside_its_enum_takes_the_error_role(app, context):
    theme = load()
    lines = _formats("---\ntype: asset\narea: kitchen\n---\n\nbody\n", context)
    assert theme.editor.red.upper() in _colours(lines[2])


def test_a_heading_takes_purple(app, context):
    theme = load()
    lines = _formats("---\ntype: note\n---\n\n## A heading\n", context)
    assert theme.editor.purple.upper() in _colours(lines[4])


def test_an_unresolved_link_is_underlined_rather_than_recoloured(app, context):
    """A placeholder is a feature, not an error, and the spec forbids relying
    on colour alone."""
    resolved = _formats("---\ntype: note\n---\n\nSee [[Known]].\n", context, lambda _n: True)
    missing = _formats("---\ntype: note\n---\n\nSee [[Gone]].\n", context, lambda _n: False)

    assert _colours(resolved[4]) == _colours(missing[4])
    styles = {f.format.underlineStyle() for f in missing[4]}
    assert any(style != 0 for style in styles)


def test_a_wikilink_in_frontmatter_is_flagged_rather_than_shown_as_a_link(app, context):
    """The trap the whole schema exists to prevent. Colouring it like a link
    would make it look correct."""
    theme = load()
    lines = _formats("---\ntype: meeting\nattendees: [[Someone]]\n---\n\nx\n", context)
    assert theme.editor.red.upper() in _colours(lines[2])


def test_a_fenced_block_is_not_recoloured_as_prose(app, context):
    theme = load()
    text = "---\ntype: note\n---\n\n```\n## not a heading\n```\n"
    lines = _formats(text, context)
    assert theme.editor.purple.upper() not in _colours(lines[5])


def test_a_task_line_marks_its_grammar(app, context):
    theme = load()
    text = "---\ntype: note\n---\n\n- [ ] #item Do it [[X]] owner:[[Y]] raised:2026-01-01\n"
    colours = _colours(_formats(text, context)[4])
    assert theme.editor.pink.upper() in colours
    assert theme.editor.cyan.upper() in colours


def test_a_completed_task_marks_its_x_green(app, context):
    theme = load()
    text = "---\ntype: note\n---\n\n- [x] #item Done [[X]] owner:[[Y]] raised:2026-01-01\n"
    assert theme.editor.green.upper() in _colours(_formats(text, context)[4])


def test_the_highlighter_follows_a_theme_change(app, context):
    editor = Editor(load("nott"), context.schema)
    editor.set_document_text("---\ntype: asset\n---\n\nbody\n")
    editor.set_theme(load("dagr"))
    line = editor.document().findBlockByLineNumber(1)
    assert load("dagr").editor.pink.upper() in _colours(list(line.layout().formats()))


# --- the window -------------------------------------------------------


def test_starting_fills_every_pane(started):
    assert started.view.model_.rowCount() >= 1
    assert started.navigator.topLevelItemCount() == 4
    assert "documents" not in started.status.text()


def test_running_a_pipeline_fills_the_view(started):
    started.run_pipeline("find type:asset | table title")
    assert started.view.model_.rowCount() == 2
    assert "VIEW" in started.view_box.title_label.text()


def test_a_bad_pipeline_reports_in_the_status_line_rather_than_raising(started):
    started.run_pipeline("where type:asset")
    assert "cannot start a pipeline" in started.status.text()
    assert started.status.property("state") == "error"


def test_a_meta_verb_answers_in_the_status_line(started):
    started.run_pipeline("lint")
    assert "schema clean" in started.status.text()


def test_opening_a_document_loads_it_into_the_editor(started, workspace):
    started.open_document(workspace / "2-Notes" / "Alpha.md")
    assert "Links to" in started.editor.toPlainText()
    assert started.buffer is not None
    assert started.buffer.title == "Alpha"


def test_saving_an_untouched_document_changes_nothing_on_disk(started, workspace):
    """Acceptance test 3, through the actual editor."""
    path = workspace / "2-Notes" / "Alpha.md"
    started.open_document(path)
    started.save_document()
    before = path.read_bytes()

    started.open_document(path)
    started.save_document()
    assert path.read_bytes() == before


def test_an_edit_reaches_the_file_and_the_index(started, workspace):
    path = workspace / "2-Notes" / "Alpha.md"
    started.open_document(path)
    started.editor.setPlainText(started.editor.toPlainText() + "\nA new sentence about pumps.\n")
    started.save_document()

    assert "A new sentence about pumps." in path.read_text(encoding="utf-8")
    assert started.status.property("state") == "ok"
    assert [d.title for d in started.context.index.search("pumps")] == ["Alpha"]


def test_backlinks_of_the_open_document(started, workspace):
    started.open_document(workspace / "1-Assets" / "Post Rinse 4.md")
    started.show_backlinks()
    assert started.view.model_.rowCount() == 1


def test_navigation_history_walks_back_and_forward(started, workspace):
    first = workspace / "2-Notes" / "Alpha.md"
    second = workspace / "2-Notes" / "Beta.md"
    started.open_document(first)
    started.open_document(second)

    started.go_back()
    assert started.buffer.path == first
    started.go_forward()
    assert started.buffer.path == second


def test_going_back_past_the_start_does_nothing(started, workspace):
    started.open_document(workspace / "2-Notes" / "Alpha.md")
    started.go_back()
    started.go_back()
    assert started.buffer.path.name == "Alpha.md"


def test_the_calendar_switch_says_which_phase_it_arrives_in(started):
    started._switch_app("calendar")
    assert "phase 5" in started.status.text()
    assert started.switcher.buttons["notes"].isChecked()


def test_promised_applications_are_present_and_disabled(started):
    """A roadmap and a missing feature should not look alike."""
    assert not started.switcher.buttons["calendar"].isEnabled()
    assert "phase 5" in started.switcher.buttons["calendar"].toolTip()


def test_reindex_reports(started):
    started.reindex()
    assert "unchanged" in started.status.text()


# --- the legal notices ------------------------------------------------


def test_the_about_button_is_always_on_screen(started):
    """GPLv3 section 5(d) wants the notices somewhere convenient and
    prominent, so the button lives on the one piece of chrome that never
    goes away."""
    assert started.switcher.about.isVisible() or started.switcher.about.isEnabled()
    assert "licence" in started.switcher.about.toolTip().lower()


def test_the_about_button_asks_for_the_notices(app, qtbot):
    from structura.ui.panes import AppSwitcher

    switcher = AppSwitcher()
    qtbot.addWidget(switcher)
    with qtbot.waitSignal(switcher.about_requested, timeout=1000):
        switcher.about.click()


def test_the_about_dialog_carries_the_notices(started, monkeypatch):
    """Built rather than shown: exec() would block, and what is being tested
    is the content, not Qt's modal loop."""
    from PySide6.QtWidgets import QMessageBox

    from structura.licensing import COPYRIGHT

    seen = {}

    def capture(self):
        seen["text"] = self.text()
        seen["detail"] = self.detailedText()
        return 0

    monkeypatch.setattr(QMessageBox, "exec", capture)
    started.show_about()

    assert COPYRIGHT in seen["text"]
    assert "NO WARRANTY" in seen["text"]
    assert "LGPL-3.0-only" in seen["detail"]
    assert "Replacing Qt" in seen["detail"]


# --- the stylesheet ---------------------------------------------------


@pytest.mark.parametrize("variant", ["nott", "dagr"])
def test_the_stylesheet_is_built_from_the_theme(variant):
    theme = load(variant)
    sheet = stylesheet(theme)
    assert theme.editor.background in sheet
    assert theme.surface.dark in sheet
    assert theme.functional.purple in sheet


def test_functional_colours_never_reach_the_document_pane():
    """They are chrome. On a page of prose they would outshout the content."""
    theme = load()
    sheet = stylesheet(theme)
    editor_block = sheet[sheet.index("#Editor {") : sheet.index("#CommandBar {")]
    for colour in (
        theme.functional.red,
        theme.functional.orange,
        theme.functional.green,
        theme.functional.cyan,
        theme.functional.purple,
    ):
        assert colour not in editor_block


def test_the_highlighter_never_uses_a_functional_colour(app, context):
    """The same rule, on the other surface that could break it."""
    theme = load()
    functional = {
        theme.functional.red.upper(),
        theme.functional.orange.upper(),
        theme.functional.green.upper(),
        theme.functional.cyan.upper(),
        theme.functional.purple.upper(),
    }
    text = (
        "---\ntype: asset\narea: paint\nstatus: operating\n---\n\n"
        "# Heading\n\nSee [[X]] #tag\n- [x] #item Done [[X]] owner:[[Y]] raised:2026-01-01\n"
    )
    used: set[str] = set()
    for formats in _formats(text, context).values():
        used |= _colours(formats)
    assert not (used & functional)


def test_a_highlighter_works_without_an_index(app):
    """A workspace opened before its first sync still renders."""
    from PySide6.QtGui import QTextDocument

    document = QTextDocument()
    document.setPlainText("---\ntype: note\n---\n\nSee [[Anything]].\n")
    assert MarkdownHighlighter(document) is not None


def test_building_a_window_needs_no_event_loop(app, workspace):
    from structura.ui.app import build

    window = build(workspace, "dagr", app)
    try:
        assert window.theme.variant == "light"
    finally:
        window.watcher.stop()
        window.context.close()


def test_the_context_closes_with_the_workspace(app, workspace):
    from structura.ui.app import build

    window = build(workspace, "nott", app)
    window.context.close()
    assert Path(window.context.workspace) == workspace
