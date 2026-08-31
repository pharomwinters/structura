"""Who owns what, and under which terms.

Structura is GPL-3.0-or-later. Two obligations follow, and both are easier to
satisfy now than at release:

- **GPLv3 §5(d).** An interactive program must display Appropriate Legal
  Notices — the copyright, the absence of warranty, the licence, and how to
  read it. That is what `about()` is for, and why the window carries a `?`
  button on the one piece of chrome that is always on screen.
- **Corresponding Source.** Anything conveyed as a binary has to come with, or
  point at, the source of everything bundled in it. Qt is the one that matters,
  because it is large and not ours.

The component list below is data rather than prose so that a test can check it
against what is actually installed. A notices file that has drifted from the
build is worse than none: it reads as a promise and is a mistake.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as installed_version

PROJECT = "Structura"
COPYRIGHT = "Copyright (C) 2026 Adam Bick"
LICENCE = "GPL-3.0-or-later"
SOURCE_URL = "https://github.com/pharomwinters/structura"

WARRANTY = (
    "This program comes with ABSOLUTELY NO WARRANTY. It is free software, and "
    "you are welcome to redistribute it under the terms of the GNU General "
    "Public License, version 3 or later."
)


@dataclass(frozen=True)
class Component:
    """A third-party thing that ships inside a build."""

    #: Distribution name, as `importlib.metadata` knows it.
    distribution: str
    #: What it is called in the world, if that differs.
    name: str
    purpose: str
    #: The SPDX expression the distribution offers.
    offered: str
    #: The one of those Structura actually takes it under.
    taken_under: str
    source: str
    note: str = ""


COMPONENTS: tuple[Component, ...] = (
    Component(
        distribution="PySide6-Essentials",
        name="Qt for Python (PySide6) and Qt",
        purpose="the window",
        offered="LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only",
        taken_under="LGPL-3.0-only",
        source="https://download.qt.io/official_releases/QtForPython/",
        note=(
            "Taken under the LGPL rather than the GPL on purpose. Both are "
            "compatible with Structura's own licence, but the LGPL is the one "
            "that obliges us to keep Qt replaceable, and that is a property "
            "worth being obliged to keep."
        ),
    ),
    Component(
        distribution="shiboken6",
        name="Shiboken",
        purpose="the binding layer PySide6 is built on",
        offered="LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only",
        taken_under="LGPL-3.0-only",
        source="https://download.qt.io/official_releases/QtForPython/",
    ),
    Component(
        distribution="PyYAML",
        name="PyYAML",
        purpose="frontmatter parsing",
        offered="MIT",
        taken_under="MIT",
        source="https://github.com/yaml/pyyaml",
    ),
    Component(
        distribution="watchdog",
        name="watchdog",
        purpose="the filesystem watcher",
        offered="Apache-2.0",
        taken_under="Apache-2.0",
        source="https://github.com/gorakhargosh/watchdog",
    ),
)

RELINKING = """\
Replacing Qt
------------

Structura uses Qt under the LGPL, which gives you the right to run it against
your own build of Qt. Builds are distributed as a directory or a native
installer -- never as a single fused executable -- precisely so that this is
possible without rebuilding anything:

  1. Find the Qt shared libraries in the installed application directory
     (`PySide6/` on Windows and Linux, `Contents/Resources/` inside the .app
     on macOS).
  2. Replace them with your own binary-compatible build.
  3. Run the application.

On macOS an application that has been signed and notarised will refuse to
start once a bundled library is replaced, because the signature no longer
matches. This is a property of the platform rather than of the licence. Re-sign
the bundle locally to run it:

    codesign --force --deep --sign - /Applications/Structura.app

Alternatively, rebuild from source: Structura's own source and its complete
build configuration are public, so substituting a different PySide6 in the
build environment and rebuilding produces a working application.
"""


def component_versions() -> dict[str, str]:
    """The installed version of each declared component, where present.

    A component that is not installed is not an error: the window is an
    optional extra, so a CLI-only install has no Qt to report.
    """
    found: dict[str, str] = {}
    for component in COMPONENTS:
        try:
            found[component.distribution] = installed_version(component.distribution)
        except PackageNotFoundError:
            continue
    return found


def about() -> str:
    """The Appropriate Legal Notices, short enough for a dialog."""
    return (
        f"{PROJECT}\n"
        f"{COPYRIGHT}\n\n"
        f"{WARRANTY}\n\n"
        f"Source: {SOURCE_URL}\n"
        f"Licence: see LICENSE in the source distribution, or "
        f"https://www.gnu.org/licenses/gpl-3.0.html"
    )


def notices() -> str:
    """The full third-party notice, as `structura licenses` prints it."""
    versions = component_versions()
    lines = [
        f"{PROJECT} — {LICENCE}",
        COPYRIGHT,
        "",
        WARRANTY,
        "",
        f"Source: {SOURCE_URL}",
        "",
        "Bundled components",
        "------------------",
        "",
    ]

    for component in COMPONENTS:
        version = versions.get(component.distribution)
        heading = component.name + (f" {version}" if version else " (not installed)")
        lines.append(heading)
        lines.append(f"  used for   {component.purpose}")
        lines.append(f"  offered as {component.offered}")
        if component.taken_under != component.offered:
            lines.append(f"  used under {component.taken_under}")
        lines.append(f"  source     {component.source}")
        if component.note:
            lines.append(f"  note       {component.note}")
        lines.append("")

    lines.append(RELINKING)
    return "\n".join(lines)
