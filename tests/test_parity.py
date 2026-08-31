"""Lint parity against the legacy validator, on real content.

This is the phase 0 acceptance gate. Tests 1 and 3 in the design run against
real content rather than fixtures, on the grounds that a tool whose whole job
is the upkeep of structured notes should be gated on the notes it is for.

Both paths come from the environment so the suite stays green on a machine that
does not have the private workspace:

    STRUCTURA_LEGACY_VAULT=/path/to/vault \
    STRUCTURA_LEGACY_SCRIPTS=/path/to/vault/.foam/scripts \
    pytest tests/test_parity.py -v

An aggregate match is not sufficient. The violation lists must be identical,
in order, string for string.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from structura.core.schema import load_schema
from structura.core.violations import messages
from structura.stores.markdown import MarkdownStore

VAULT = os.environ.get("STRUCTURA_LEGACY_VAULT")
SCRIPTS = os.environ.get("STRUCTURA_LEGACY_SCRIPTS")

# Two gates, because the two halves of acceptance test 2 need different things.
# The seeded fixture needs only the legacy module; the real-content half needs
# the private workspace as well.
requires_legacy = pytest.mark.skipif(
    not SCRIPTS, reason="set STRUCTURA_LEGACY_SCRIPTS to run parity tests"
)
requires_vault = pytest.mark.skipif(
    not (VAULT and SCRIPTS),
    reason="set STRUCTURA_LEGACY_VAULT and STRUCTURA_LEGACY_SCRIPTS to run parity tests",
)


@pytest.fixture(scope="module")
def legacy():
    sys.path.insert(0, SCRIPTS)
    try:
        import vaultlib
    finally:
        sys.path.pop(0)
    return vaultlib


@pytest.fixture(scope="module")
def root() -> Path:
    return Path(VAULT).resolve()


@pytest.fixture(scope="module")
def legacy_notes(legacy, root):
    return legacy.load_vault(root)


@pytest.fixture(scope="module")
def documents(root):
    return MarkdownStore(root, load_schema(root)).documents()


@requires_vault
def test_the_same_files_are_scanned(legacy_notes, documents):
    assert sorted(n.path for n in legacy_notes) == sorted(d.path for d in documents)


@requires_vault
def test_the_workspace_is_not_empty(documents):
    """A parity suite that passes because both sides found nothing is not a
    passing parity suite."""
    assert len(documents) > 50


@requires_vault
def test_lint_output_is_identical(legacy, legacy_notes, documents):
    expected = legacy.validate(legacy_notes)
    actual = messages(MarkdownStore(Path(VAULT)).validate(documents))
    assert actual == expected


@requires_vault
def test_every_document_parses_the_same_title_and_type(legacy_notes, documents):
    legacy_by_path = {n.path: n for n in legacy_notes}
    for doc in documents:
        note = legacy_by_path[doc.path]
        assert (doc.title, doc.dtype) == (note.title, note.type), doc.path


@requires_vault
def test_every_task_parses_identically(legacy_notes, documents):
    legacy_by_path = {n.path: n for n in legacy_notes}
    for doc in documents:
        note = legacy_by_path[doc.path]
        assert len(doc.tasks) == len(note.items), doc.path
        for task, item in zip(doc.tasks, note.items, strict=True):
            assert (
                task.description,
                task.asset,
                task.owner,
                task.raised,
                task.due,
                task.ref,
                task.done,
                task.line_no,
            ) == (
                item.description,
                item.asset,
                item.owner,
                item.raised,
                item.due,
                item.ref,
                item.done,
                item.line_no,
            ), f"{doc.path}:{task.line_no}"


@requires_vault
def test_every_link_and_parent_matches(legacy_notes, documents):
    legacy_by_path = {n.path: n for n in legacy_notes}
    for doc in documents:
        note = legacy_by_path[doc.path]
        assert doc.link_targets == note.links, doc.path
        assert doc.parents == note.parents, doc.path


@requires_vault
def test_link_target_names_match(legacy, root):
    assert MarkdownStore(root).link_target_names() == legacy.list_vault_filenames(root)


@requires_vault
def test_alias_maps_match(legacy, legacy_notes, documents):
    from structura.stores.markdown import build_alias_map

    assert build_alias_map(documents) == legacy.build_alias_map(legacy_notes)


# --- The other half of acceptance test 2: every violation class, seeded ---
#
# The real workspace is kept clean, so parity against it exercises only the
# rules it happens to be breaking today. This fixture breaks all of them at
# once, so a rule that quietly stopped firing during the port is caught even
# when the vault is spotless.

SEEDED = {
    "unparseable.md": "---\ntype: [unclosed\n---\n\nbody\n",
    "missing-keys.md": "---\ntype: note\n---\n\nbody\n",
    "no-frontmatter.md": "Just prose, no frontmatter at all.\n",
    "asset-without-area.md": (
        "---\ntype: asset\ntitle: A\ndate: 2026-08-14\nstatus: operating\n---\n\nbody\n"
    ),
    "unknown-type.md": "---\ntype: sandwich\ntitle: S\ndate: 2026-08-14\n---\n\nbody\n",
    "bad-enum.md": (
        "---\ntype: asset\ntitle: B\ndate: 2026-08-14\narea: kitchen\n"
        "status: operating\n---\n\nbody\n"
    ),
    "bad-status.md": (
        "---\ntype: observation\ntitle: C\ndate: 2026-08-14\narea: wwt\n"
        "status: operating\n---\n\nbody\n"
    ),
    "link-in-frontmatter.md": (
        "---\ntype: meeting\ntitle: D\ndate: 2026-08-14\n"
        "attendees:\n  - '[[Houston Lamb]]'\n---\n\nbody\n"
    ),
    "bare-task.md": (
        "---\ntype: observation\ntitle: E\ndate: 2026-08-14\narea: wwt\n"
        "status: open\n---\n\n- [ ] #item Missing everything\n"
    ),
    "duplicate-key.md": (
        "---\ntype: observation\ntitle: F\ndate: 2026-08-14\narea: wwt\n"
        "status: open\n---\n\n- [ ] #item Install mixer [[Tank Mixer]] "
        "owner:[[Maintenance]] raised:2026-03-02 raised:2020-01-01\n"
    ),
    "reflowed-part-of.md": (
        "---\ntype: person\ntitle: G\ndate: 2026-08-14\n---\n\n"
        "Works at [[Schneider Electric]] Part of [[Maintenance]]\n"
    ),
    "near-miss.md": (
        "---\ntype: observation\ntitle: H\ndate: 2026-08-14\narea: wwt\n"
        "status: open\n---\n\n* [ ] #item Do a thing [[Post Rinse 4]] "
        "owner:[[Maintenance]] raised:2026-06-01\n"
    ),
    "clean.md": (
        "---\ntype: asset\ntitle: Post Rinse 4\ndate: 2026-08-14\narea: paint\n"
        "status: operating\n---\n\nPart of [[Paint Line]]\n"
    ),
    "documented-marker.md": (
        "---\ntype: note\ntitle: J\ndate: 2026-08-14\n---\n\n"
        "A line may mention `#item` in prose, and a fence may show one:\n\n"
        "```\n- [ ] #item example [[X]] owner:[[Y]] raised:2026-01-01\n```\n"
    ),
}


@pytest.fixture(scope="module")
def seeded(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("seeded")
    for name, text in SEEDED.items():
        (root / name).write_text(text, encoding="utf-8")
    return root


@requires_legacy
def test_seeded_fixture_lint_output_is_identical(legacy, seeded):
    expected = legacy.validate(legacy.load_vault(seeded))
    actual = messages(MarkdownStore(seeded).validate())
    assert actual == expected


@requires_legacy
def test_the_seeded_fixture_actually_trips_every_rule(seeded):
    """A parity test over a fixture that breaks nothing proves nothing."""
    codes = {v.code for v in MarkdownStore(seeded).validate()}
    assert codes == {
        "frontmatter-unparseable",
        "missing-required-key",
        "missing-type-required-key",
        "unknown-type",
        "enum-invalid",
        "status-invalid",
        "wikilink-in-frontmatter",
        "task-no-asset",
        "task-no-owner",
        "task-no-raised",
        "task-duplicate-key",
        "part-of-not-at-line-start",
        "task-near-miss",
    }
