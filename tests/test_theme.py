"""Nótt & Dagr as data, and the ANSI half of it.

The palettes ship as TOML and the specification lives in `docs/theme.md`. The
first test here reads both and asserts they agree, so the document stays the
source of truth rather than a description of something that drifted.
"""

from __future__ import annotations

import io
import re
from pathlib import Path

import pytest

from structura.theme import (
    DEFAULT,
    SYSTEM,
    VARIANTS,
    ThemeError,
    load,
    load_file,
    parse_theme,
    resolve,
)
from structura.theme.ansi import RESET, Palette, colour_enabled, truecolour_supported

SPEC = Path(__file__).resolve().parents[1] / "docs" / "theme.md"
HEX = re.compile(r"#[0-9A-Fa-f]{6}")


# --- the specification is the source ----------------------------------


def _spec_colours() -> set[str]:
    return {value.upper() for value in HEX.findall(SPEC.read_text(encoding="utf-8"))}


@pytest.mark.parametrize("variant", VARIANTS)
def test_every_shipped_colour_appears_in_the_specification(variant):
    """A palette that has drifted from the document it claims to implement is
    worse than no document."""
    theme = load(variant)
    spec = _spec_colours()

    shipped = set()
    for group in (theme.editor, theme.surface, theme.functional, theme.ansi):
        shipped |= {value.upper() for value in vars(group).values()}
    shipped.add(theme.accessibility.comment_aa.upper())

    missing = sorted(shipped - spec)
    assert missing == [], f"{variant} ships colours the spec does not list: {missing}"


def test_the_two_variants_share_one_role_architecture():
    """Switching preserves meaning rather than merely inverting lightness, and
    that is only true if both halves define the same roles."""
    nott, dagr = load("nott"), load("dagr")
    for group in ("editor", "surface", "functional", "ansi"):
        assert set(vars(getattr(nott, group))) == set(vars(getattr(dagr, group))), group


def test_the_ansi_half_follows_the_specs_blue_and_magenta_mapping():
    """`AnsiBlue` carries Purple and `AnsiMagenta` carries Pink, so a piped
    result and an editor pane agree about what a link looks like."""
    for variant in VARIANTS:
        theme = load(variant)
        assert theme.ansi.blue == theme.editor.purple
        assert theme.ansi.magenta == theme.editor.pink
        assert theme.ansi.cyan == theme.editor.cyan


def test_the_variants_are_actually_dark_and_light():
    assert load("nott").is_dark
    assert not load("dagr").is_dark


# --- loading ----------------------------------------------------------


def test_a_role_can_be_looked_up_by_name():
    theme = load()
    assert theme.colour("editor.pink") == theme.editor.pink
    assert theme.colour("pink") == theme.editor.pink
    assert theme.colour("surface.dark") == theme.surface.dark


def test_an_unknown_role_is_an_error_rather_than_a_default():
    with pytest.raises(ThemeError, match="no such theme role"):
        load().colour("editor.beige")


def test_an_unknown_variant_lists_the_known_ones():
    with pytest.raises(ThemeError, match="known: nott, dagr"):
        load("midnight")


def test_a_missing_colour_is_rejected_rather_than_half_loaded():
    """A half-loaded palette renders, so nobody notices, and one pane is
    quietly the wrong colour."""
    data = {
        "name": "Broken",
        "variant": "dark",
        "editor": {"background": "#000000"},
        "surface": {},
        "functional": {},
        "ansi": {},
        "accessibility": {},
    }
    with pytest.raises(ThemeError, match=r"\[editor\] is missing"):
        parse_theme(data)


def test_an_unknown_key_is_rejected():
    theme = load("nott")
    data = {
        "name": "X",
        "variant": "dark",
        "editor": {**vars(theme.editor), "beige": "#FFFFFF"},
        "surface": vars(theme.surface),
        "functional": vars(theme.functional),
        "ansi": vars(theme.ansi),
        "accessibility": vars(theme.accessibility),
    }
    with pytest.raises(ThemeError, match="unknown key"):
        parse_theme(data)


def test_a_variant_must_be_dark_or_light():
    with pytest.raises(ThemeError, match="must be `dark` or `light`"):
        parse_theme({"name": "X", "variant": "dusk"})


def test_a_workspace_can_carry_its_own_theme(tmp_path):
    theme = load("nott")
    source = Path(__file__).resolve().parents[1] / "src" / "structura" / "theme" / "nott.toml"
    target = tmp_path / "mine.toml"
    target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    assert load_file(target).editor.background == theme.editor.background


def test_invalid_toml_fails_loudly(tmp_path):
    path = tmp_path / "bad.toml"
    path.write_text("name = \n", encoding="utf-8")
    with pytest.raises(ThemeError, match="not valid TOML"):
        load_file(path)


# --- following the desktop --------------------------------------------


def test_system_follows_the_desktop_when_it_can_be_asked():
    assert resolve(SYSTEM, system_is_dark=True).variant == "dark"
    assert resolve(SYSTEM, system_is_dark=False).variant == "light"


def test_system_falls_back_to_the_default_rather_than_guessing():
    assert resolve(SYSTEM, system_is_dark=None).name == load(DEFAULT).name


def test_an_explicit_choice_ignores_the_desktop():
    assert resolve("dagr", system_is_dark=True).variant == "light"


# --- the ANSI half ----------------------------------------------------


class _Tty(io.StringIO):
    def __init__(self, tty: bool) -> None:
        super().__init__()
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


def test_colour_is_off_when_stdout_is_not_a_terminal():
    """`structura query ... > file.md` must write clean markdown. This is not
    a nicety: `export` output is compared byte for byte against the legacy
    renderer."""
    assert not colour_enabled(_Tty(False), {})


def test_colour_is_on_for_a_terminal():
    assert colour_enabled(_Tty(True), {})


def test_no_color_wins_over_everything():
    assert not colour_enabled(_Tty(True), {"NO_COLOR": "1"})
    assert not colour_enabled(_Tty(True), {"NO_COLOR": ""})


def test_colour_can_be_forced_for_a_pipe():
    assert colour_enabled(_Tty(False), {"STRUCTURA_COLOR": "always"})


def test_truecolour_is_used_when_advertised():
    assert truecolour_supported({"COLORTERM": "truecolor"})
    assert not truecolour_supported({"TERM": "xterm-256color"})


def test_truecolour_paints_the_palettes_exact_value():
    theme = load("nott")
    painted = Palette(theme, enabled=True, truecolour=True).link("x")
    assert painted == f"\033[38;2;110;184;214mx{RESET}"


def test_without_truecolour_the_indexed_slot_is_used():
    painted = Palette(load(), enabled=True, truecolour=False).link("x")
    assert painted == f"\033[36mx{RESET}"


def test_a_disabled_palette_returns_the_text_untouched():
    """Not a special case at the call site: the same code path produces
    coloured output on a terminal and clean markdown in a pipe."""
    palette = Palette.off()
    for role in ("verb", "error", "header", "number", "link", "muted", "success"):
        assert getattr(palette, role)("text") == "text"


def test_roles_exist_for_everything_the_repl_paints():
    palette = Palette(load(), enabled=True)
    for role in ("verb", "key", "header", "number", "link", "unresolved", "error", "success"):
        assert palette.sequence(role)


def test_an_unknown_role_is_an_attribute_error():
    with pytest.raises(AttributeError):
        Palette(load()).chartreuse("x")


def test_bold_is_used_sparingly_and_only_for_headers():
    palette = Palette(load(), enabled=True, truecolour=True)
    assert palette.sequence("header").startswith("\033[1m")
    assert not palette.sequence("link").startswith("\033[1m")
