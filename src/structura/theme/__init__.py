"""Nótt & Dagr, loaded as data.

The colour scheme is a specification (`docs/theme.md`), not a set of constants
in a widget file. That is the same rule the schema follows and it buys the same
thing: a third variant is a file, not a code change, and a palette change is a
reviewable diff.

**This package must not import Qt.** The command line uses the ANSI half and
the window uses the hex half, and only one of those has a toolkit. Keeping the
palette below the UI is what lets both read the same file.

Roles, not colours, are what the rest of the application asks for. Nothing
outside this package should mention `#E35F5B`; it asks for `theme.editor.red`
or, better, for the semantic role that means -- so that switching variants
preserves meaning rather than merely inverting lightness.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, fields
from functools import lru_cache
from importlib import resources
from pathlib import Path

DEFAULT = "nott"
VARIANTS = ("nott", "dagr")
SYSTEM = "system"


class ThemeError(Exception):
    """The theme file is wrong. Raised at load time, never swallowed."""


@dataclass(frozen=True)
class Editor:
    """The syntax palette. Roles are the spec's, verbatim."""

    background: str
    current_line: str
    selection: str
    foreground: str
    comment: str
    red: str
    orange: str
    yellow: str
    green: str
    cyan: str
    purple: str
    pink: str


@dataclass(frozen=True)
class Surface:
    """Application chrome, beyond the editor.

    Elevation is surface-based rather than shadowed, which is why these exist
    as named layers instead of as opacities over one colour.
    """

    floating: str
    lighter: str
    light: str
    dark: str
    darker: str


@dataclass(frozen=True)
class Functional:
    """State and interaction colours.

    **Never used on a document surface.** They carry more saturation than the
    editor accents would tolerate on a page of prose, and on a document they
    would outshout the content. Chrome only: borders, focus rings, status.
    """

    red: str
    orange: str
    green: str
    cyan: str
    purple: str


@dataclass(frozen=True)
class Ansi:
    """The terminal palette.

    `blue` carries the palette's Purple and `magenta` its Pink, following the
    spec, so a piped result and an editor pane agree about what a link looks
    like.
    """

    black: str
    red: str
    green: str
    yellow: str
    blue: str
    magenta: str
    cyan: str
    white: str
    bright_black: str
    bright_red: str
    bright_green: str
    bright_yellow: str
    bright_blue: str
    bright_magenta: str
    bright_cyan: str
    bright_white: str


@dataclass(frozen=True)
class Accessibility:
    comment_aa: str
    shadow: str


@dataclass(frozen=True)
class Theme:
    name: str
    variant: str
    editor: Editor
    surface: Surface
    functional: Functional
    ansi: Ansi
    accessibility: Accessibility

    @property
    def is_dark(self) -> bool:
        return self.variant == "dark"

    def colour(self, role: str) -> str:
        """A colour by dotted role, e.g. `editor.pink` or `surface.dark`."""
        group, _, name = role.partition(".")
        if not name:
            group, name = "editor", group
        try:
            return getattr(getattr(self, group), name)
        except AttributeError as exc:
            raise ThemeError(f"no such theme role: `{role}`") from exc


_GROUPS = {
    "editor": Editor,
    "surface": Surface,
    "functional": Functional,
    "ansi": Ansi,
    "accessibility": Accessibility,
}


def _group(data: dict, name: str, kind: type):
    raw = data.get(name)
    if not isinstance(raw, dict):
        raise ThemeError(f"[{name}] must be a table")
    expected = {f.name for f in fields(kind)}
    missing = sorted(expected - set(raw))
    unknown = sorted(set(raw) - expected)
    if missing:
        raise ThemeError(f"[{name}] is missing: {', '.join(missing)}")
    if unknown:
        raise ThemeError(f"[{name}] has unknown key(s): {', '.join(unknown)}")
    return kind(**raw)


def parse_theme(data: dict) -> Theme:
    """Build a Theme from parsed TOML, rejecting anything malformed.

    A half-loaded palette is worse than none: it renders, so nobody notices,
    and one pane is quietly the wrong colour.
    """
    for key in ("name", "variant"):
        if not isinstance(data.get(key), str):
            raise ThemeError(f"a theme needs a string `{key}`")
    if data["variant"] not in ("dark", "light"):
        raise ThemeError("`variant` must be `dark` or `light`")

    unknown = sorted(set(data) - {"name", "variant", *_GROUPS})
    if unknown:
        raise ThemeError(f"unknown table(s): {', '.join(unknown)}")

    return Theme(
        name=data["name"],
        variant=data["variant"],
        **{name: _group(data, name, kind) for name, kind in _GROUPS.items()},
    )


@lru_cache(maxsize=8)
def load(name: str = DEFAULT) -> Theme:
    """A shipped variant, by name."""
    key = (name or DEFAULT).strip().casefold()
    if key not in VARIANTS:
        raise ThemeError(f"unknown theme `{name}` -- known: {', '.join(VARIANTS)}")
    text = resources.files("structura.theme").joinpath(f"{key}.toml").read_text(encoding="utf-8")
    return parse_theme(tomllib.loads(text))


def load_file(path: Path) -> Theme:
    """A theme from an arbitrary file, so a workspace can carry its own."""
    try:
        data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ThemeError(f"{path}: not valid TOML -- {exc}") from exc
    return parse_theme(data)


def resolve(preference: str = DEFAULT, *, system_is_dark: bool | None = None) -> Theme:
    """The theme to use, given a setting of `nott`, `dagr` or `system`.

    `system` with nothing to ask falls back to Nótt rather than guessing, since
    the dark half is the default and a wrong guess is more jarring than a
    default.
    """
    if (preference or DEFAULT).strip().casefold() == SYSTEM:
        if system_is_dark is None:
            return load(DEFAULT)
        return load("nott" if system_is_dark else "dagr")
    return load(preference)


__all__ = [
    "DEFAULT",
    "SYSTEM",
    "VARIANTS",
    "Accessibility",
    "Ansi",
    "Editor",
    "Functional",
    "Surface",
    "Theme",
    "ThemeError",
    "load",
    "load_file",
    "parse_theme",
    "resolve",
]
