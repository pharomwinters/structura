"""The command line's half of the theme.

`structura shell` prints to a terminal, so it uses the ANSI palette rather than
the hex one, with the spec's Blue→Purple and Magenta→Pink mapping. A piped
result and an editor pane then agree about what a link looks like.

Two rules that are cheaper to build in than to retrofit:

- **Colour only when stdout is a terminal.** `structura query ... > file.md`
  must write clean markdown, not a file full of escape sequences. This is not
  a nicety: the `export` verb writes a register that is compared byte for byte
  against the legacy renderer's output.
- **`NO_COLOR` wins.** Set in the environment, at any value, colour is off.

Truecolour is used when the terminal advertises it, because the palette's
whole point is being those exact colours; otherwise the nearest of the 16
indexed slots, which is what the ANSI half of the spec exists for.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import IO

from . import Theme, load

RESET = "\033[0m"

#: role -> (ANSI palette key, indexed slot, bold)
ROLES: dict[str, tuple[str, int, bool]] = {
    "verb": ("magenta", 35, False),
    "key": ("magenta", 35, False),
    "header": ("white", 37, True),
    "number": ("yellow", 33, False),
    "link": ("cyan", 36, False),
    "unresolved": ("bright_black", 90, False),
    "muted": ("bright_black", 90, False),
    "error": ("red", 31, False),
    "success": ("green", 32, False),
    "string": ("yellow", 33, False),
}


def truecolour_supported(env: dict[str, str] | None = None) -> bool:
    environ = os.environ if env is None else env
    return environ.get("COLORTERM", "").lower() in ("truecolor", "24bit")


def colour_enabled(stream: IO[str] | None = None, env: dict[str, str] | None = None) -> bool:
    """Whether to emit escape sequences at all."""
    environ = os.environ if env is None else env
    if "NO_COLOR" in environ:
        return False
    if environ.get("STRUCTURA_COLOR", "").lower() in ("always", "1", "true"):
        return True
    target = stream if stream is not None else sys.stdout
    try:
        return bool(target.isatty())
    except (AttributeError, ValueError):
        return False


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    text = value.lstrip("#")
    return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)


@dataclass(frozen=True)
class Palette:
    """Renders roles as escape sequences, or as nothing at all.

    A disabled palette is not a special case at the call site: `paint` simply
    returns the text unchanged, so the same code path produces coloured output
    on a terminal and clean markdown in a pipe.
    """

    theme: Theme
    enabled: bool = True
    truecolour: bool = True

    @classmethod
    def for_stream(
        cls,
        theme: Theme | None = None,
        stream: IO[str] | None = None,
        env: dict[str, str] | None = None,
    ) -> Palette:
        return cls(
            theme=theme or load(),
            enabled=colour_enabled(stream, env),
            truecolour=truecolour_supported(env),
        )

    @classmethod
    def off(cls, theme: Theme | None = None) -> Palette:
        return cls(theme=theme or load(), enabled=False)

    def sequence(self, role: str) -> str:
        if not self.enabled:
            return ""
        key, slot, bold = ROLES[role]
        prefix = "\033[1m" if bold else ""
        if not self.truecolour:
            return f"{prefix}\033[{slot}m"
        red, green, blue = _hex_to_rgb(getattr(self.theme.ansi, key))
        return f"{prefix}\033[38;2;{red};{green};{blue}m"

    def paint(self, text: str, role: str) -> str:
        if not self.enabled or not text:
            return text
        return f"{self.sequence(role)}{text}{RESET}"

    def __getattr__(self, role: str):
        """`palette.error("boom")` reads better than `palette.paint(...)`."""
        if role in ROLES:
            return lambda text: self.paint(text, role)
        raise AttributeError(role)
