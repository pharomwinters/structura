"""The licence notices, checked against what is actually installed.

A notices file that has drifted from the build is worse than none: it reads as
a promise and is a mistake. So these tests compare the declared component list
against `importlib.metadata`, and the prose files against the declared list.
"""

from __future__ import annotations

import re
from importlib.metadata import metadata
from pathlib import Path

import pytest

from structura.cli import main
from structura.licensing import (
    COMPONENTS,
    COPYRIGHT,
    LICENCE,
    PROJECT,
    SOURCE_URL,
    about,
    component_versions,
    notices,
)

ROOT = Path(__file__).resolve().parents[1]
LICENSE = ROOT / "LICENSE"
LGPL = ROOT / "LICENSES" / "LGPL-3.0.txt"
NOTICES = ROOT / "THIRD-PARTY-NOTICES.md"


# --- the licence texts are present and are what they claim ------------


def test_the_project_licence_is_the_gpl_v3_text():
    text = LICENSE.read_text(encoding="utf-8")
    assert "GNU GENERAL PUBLIC LICENSE" in text
    assert "Version 3, 29 June 2007" in text
    # The operative sections, so a truncated or placeholder file fails.
    assert "Corresponding Source" in text
    assert "TERMS AND CONDITIONS" in text


def test_the_lesser_licence_text_ships_too():
    """LGPLv3 is a set of permissions on top of GPLv3, so Qt's terms need
    both files present, not just one."""
    text = LGPL.read_text(encoding="utf-8")
    assert "GNU LESSER GENERAL PUBLIC LICENSE" in text
    assert "Version 3, 29 June 2007" in text


def test_the_package_metadata_says_what_the_file_says():
    assert metadata("structura")["License-Expression"] == LICENCE


# --- the declared components match the installed ones -----------------


@pytest.mark.parametrize("component", COMPONENTS, ids=lambda c: c.distribution)
def test_each_declared_component_is_installed_and_agrees(component):
    """The version is read at runtime rather than written down, but the
    *licence* is written down -- so it has to be checked."""
    declared = metadata(component.distribution)
    offered = declared.get("License-Expression") or declared.get("License") or ""
    assert offered.splitlines()[0].strip() == component.offered, (
        f"{component.distribution} now offers {offered!r}, "
        f"but the notices still say {component.offered!r}"
    )


def test_nothing_is_bundled_that_is_not_declared():
    """A new runtime dependency has to be added to the notices, and this is
    what says so out loud rather than at release."""
    requires = metadata("structura").get_all("Requires-Dist") or []
    runtime = {
        re.split(r"[<>=!;\s\[]", line.strip())[0].lower()
        for line in requires
        if "extra ==" not in line
    }
    declared = {c.distribution.lower() for c in COMPONENTS}
    assert runtime - declared == set(), (
        f"undeclared runtime dependencies: {sorted(runtime - declared)}"
    )


def test_qt_is_taken_under_the_lgpl_deliberately():
    """The choice that obliges us to keep Qt replaceable. If this ever flips
    to the GPL, the relinking promise in the notices stops being required and
    the distribution shape stops being load-bearing -- so it should be a
    decision, not a drift."""
    qt = next(c for c in COMPONENTS if c.distribution == "PySide6-Essentials")
    assert qt.taken_under == "LGPL-3.0-only"
    assert "GPL-3.0-only" in qt.offered


# --- the rendered notice ----------------------------------------------


def test_the_notice_names_every_component_and_where_to_get_it():
    text = notices()
    for component in COMPONENTS:
        assert component.name in text
        assert component.source in text


def test_the_notice_carries_the_versions_actually_installed():
    text = notices()
    for distribution, version in component_versions().items():
        assert version in text, f"{distribution} {version} missing from the notice"


def test_the_notice_explains_how_to_replace_qt():
    """The LGPL right is worth nothing if nobody is told how to exercise it."""
    text = notices()
    assert "Replacing Qt" in text
    assert "binary-compatible" in text
    assert "codesign" in text, "the macOS signature tension has to be stated"


def test_the_short_notice_has_what_gplv3_section_5d_asks_for():
    text = about()
    assert COPYRIGHT in text
    assert "NO WARRANTY" in text
    assert "General Public License" in text
    assert "gnu.org/licenses" in text or "LICENSE" in text
    assert SOURCE_URL in text


def test_the_short_notice_stays_short_enough_for_a_dialog():
    assert len(about().splitlines()) <= 12


# --- the prose file agrees with the code ------------------------------


def test_the_notices_file_names_every_component():
    text = NOTICES.read_text(encoding="utf-8")
    for component in COMPONENTS:
        assert component.name in text, f"{component.name} missing from THIRD-PARTY-NOTICES.md"


def test_the_notices_file_states_the_licence_qt_is_taken_under():
    text = NOTICES.read_text(encoding="utf-8")
    assert "LGPL-3.0-only" in text
    assert "reverse-engineer" in text, "the LGPL debugging permission has to be stated"


def _prose(text: str) -> str:
    """The file with emphasis and line wrapping removed, so a test asserts on
    what it says rather than on where the paragraph happened to break."""
    return re.sub(r"\s+", " ", text.replace("*", ""))


def test_the_notices_file_rules_out_a_one_file_freeze():
    """The whole reason this document exists in this shape."""
    text = _prose(NOTICES.read_text(encoding="utf-8"))
    assert "never as a single fused executable" in text
    assert "swap the file" in text


def test_the_notices_file_records_that_only_essentials_ship():
    text = NOTICES.read_text(encoding="utf-8")
    assert "Essentials" in text
    assert "Qt Charts" in text, "the GPL-only addons are the thing to stay away from"


# --- the command line -------------------------------------------------


def test_structura_licenses_prints_the_notice(capsys):
    assert main(["licenses"]) == 0
    out = capsys.readouterr().out
    assert PROJECT in out
    assert "LGPL-3.0-only" in out


def test_structura_licenses_needs_no_workspace(tmp_path, monkeypatch):
    """It has to work from anywhere: someone checking what a binary bundles is
    not standing in a workspace."""
    monkeypatch.chdir(tmp_path)
    assert main(["licenses"]) == 0
