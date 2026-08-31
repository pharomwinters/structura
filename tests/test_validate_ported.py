"""Ported verbatim from the legacy validator's own test suite.

These tests are the phase 0 gate. Only the API calls were rewritten -- every
fixture, every assertion, and every docstring is the original, because the
point of the port is to prove the rules did not change while the code moved.
`validate()` now returns `Violation` objects, so the adapter below renders the
legacy string list the assertions were written against.

This file is excluded from the formatter and the linter on purpose: it should
stay diffable against the original, and reflowing it would destroy the one
property that makes it worth having.

The one substantive addition is a case the legacy suite could not have had:
the ported near-miss scan must honour a non-default task marker.
"""

from pathlib import Path

from structura.core.schema import default_schema, parse_schema
from structura.core.violations import messages
from structura.stores import markdown
from structura.stores.markdown import parse as md_parse


class _Adapter:
    """Renders the legacy call shapes onto the new API.

    `STATUS_ENUMS` and `ITEM_GRAMMAR` were module constants in the legacy
    validator and are now derived from the shipped schema and the compiled
    grammar. Pointing the original assertions at those sources is itself the
    check that moving the rules into data did not change them.
    """

    STATUS_ENUMS = {k: set(v) for k, v in default_schema().status.items()}
    ITEM_GRAMMAR = md_parse.grammar("item").description

    @staticmethod
    def parse_note(path, text):
        return markdown.parse_document(Path(path), text)

    @staticmethod
    def validate(documents):
        return messages(markdown.validate(documents))


vaultlib = _Adapter()


def _note(tmp_path, name, text):
    return vaultlib.parse_note(tmp_path / f"{name}.md", text)


def test_validate_accepts_a_conforming_note(tmp_path):
    note = _note(
        tmp_path,
        "Post Rinse 4",
        "---\ntype: asset\ntitle: Post Rinse 4\ndate: 2026-08-22\narea: paint\nstatus: operating\n---\n\nbody\n",
    )
    assert vaultlib.validate([note]) == []


def test_validate_flags_unknown_type(tmp_path):
    note = _note(tmp_path, "X", "---\ntype: sandwich\ntitle: X\ndate: 2026-08-22\n---\n\nbody\n")
    problems = vaultlib.validate([note])
    assert any("sandwich" in p for p in problems)


def test_validate_flags_missing_required_keys(tmp_path):
    note = _note(tmp_path, "X", "---\ntype: note\n---\n\nbody\n")
    problems = vaultlib.validate([note])
    assert any("date" in p for p in problems)


def test_validate_flags_bad_enum_value(tmp_path):
    note = _note(
        tmp_path,
        "X",
        "---\ntype: asset\ntitle: X\ndate: 2026-08-22\narea: kitchen\nstatus: operating\n---\n\nbody\n",
    )
    problems = vaultlib.validate([note])
    assert any("kitchen" in p for p in problems)


def test_validate_flags_wikilink_in_frontmatter(tmp_path):
    """The trap that motivated this whole schema: a link here is invisible to Foam."""
    note = _note(
        tmp_path,
        "X",
        "---\ntype: meeting\ntitle: X\ndate: 2026-08-22\nattendees:\n  - '[[Houston Lamb]]'\n---\n\nbody\n",
    )
    problems = vaultlib.validate([note])
    assert any("frontmatter" in p.lower() for p in problems)


def test_validate_flags_item_missing_owner_or_asset(tmp_path):
    note = _note(
        tmp_path,
        "X",
        "---\ntype: observation\ntitle: X\ndate: 2026-08-22\narea: paint\nstatus: open\n---\n\n"
        "- [ ] #item Missing everything raised:2026-01-01\n",
    )
    problems = vaultlib.validate([note])
    assert any("asset" in p for p in problems)
    assert any("owner" in p for p in problems)


def test_validate_reports_unparseable_frontmatter_distinctly(tmp_path):
    """Ruling R10: this is not hypothetical -- two real notes in this vault
    have `attendees:\\n  - [[A]], [[B]]`, a YAML block-collection error. Without
    this check every key in the note appears missing, sending the user
    hunting for the wrong fault entirely. Reported here as a distinct
    parse-failure message instead."""
    note = _note(
        tmp_path,
        "X",
        "---\ntype: meeting\ntitle: X\ndate: 2026-08-22\nattendees:\n  - [[A]], [[B]]\n---\n\nbody\n",
    )
    problems = vaultlib.validate([note])
    assert any("yaml" in p.lower() and "frontmatter" in p.lower() for p in problems)


def test_validate_suppresses_missing_key_noise_when_frontmatter_unparseable(tmp_path):
    """When frontmatter fails to parse, EVERY key appears missing. One accurate
    parse-failure error beats four misleading missing-key ones, so the
    missing-key messages must not also fire for this note."""
    note = _note(
        tmp_path,
        "X",
        "---\ntype: meeting\ntitle: X\ndate: 2026-08-22\nattendees:\n  - [[A]], [[B]]\n---\n\nbody\n",
    )
    problems = vaultlib.validate([note])
    assert not any("missing required frontmatter key" in p for p in problems)


def test_validate_still_flags_missing_keys_when_frontmatter_genuinely_absent(tmp_path):
    """A note with no frontmatter at all (frontmatter_error is None, properties
    is {}) must still report the missing required keys normally -- the
    suppression above is specific to a parse failure, not to an empty
    properties dict in general."""
    note = _note(tmp_path, "X", "# Just a heading, no frontmatter\n\nbody\n")
    problems = vaultlib.validate([note])
    assert any("missing required frontmatter key `type`" in p for p in problems)
    assert any("missing required frontmatter key `title`" in p for p in problems)
    assert any("missing required frontmatter key `date`" in p for p in problems)


def test_validate_reports_list_type_as_unknown_instead_of_crashing(tmp_path):
    """R19: `type:` as a YAML list is valid YAML (frontmatter_error stays None,
    so the R10 suppression never engages), but `list not in VALID_TYPES` used
    to raise TypeError because a list is unhashable. It must be reported as
    an unknown type instead of aborting validation for the whole vault."""
    note = _note(
        tmp_path,
        "X",
        "---\ntype:\n  - asset\ntitle: X\ndate: 2026-08-22\n---\n\nbody\n",
    )
    problems = vaultlib.validate([note])
    assert any("unknown type" in p for p in problems)


def test_validate_reports_dict_type_as_unknown_instead_of_crashing(tmp_path):
    """Same crash, different unhashable culprit: a mapping for `type:`."""
    note = _note(
        tmp_path,
        "X",
        "---\ntype:\n  kind: asset\ntitle: X\ndate: 2026-08-22\n---\n\nbody\n",
    )
    problems = vaultlib.validate([note])
    assert any("unknown type" in p for p in problems)


def test_validate_does_not_lose_other_notes_when_one_has_an_unhashable_type(tmp_path):
    """Before the fix, one bad note aborted validate() for the entire batch --
    validate([good, bad]) raised and returned nothing. A good note's findings
    (or clean pass) must survive alongside the bad note's finding."""
    good = _note(
        tmp_path,
        "Good",
        "---\ntype: asset\ntitle: Good\ndate: 2026-08-22\narea: kitchen\nstatus: operating\n---\n\nbody\n",
    )
    bad = _note(
        tmp_path,
        "Bad",
        "---\ntype:\n  - asset\ntitle: Bad\ndate: 2026-08-22\n---\n\nbody\n",
    )
    problems = vaultlib.validate([good, bad])
    assert any("Good.md" in p and "kitchen" in p for p in problems)
    assert any("Bad.md" in p and "unknown type" in p for p in problems)


def test_validate_plain_unknown_string_type_still_reports_as_before(tmp_path):
    """R19 regression guard: str()-wrapping note.type before the membership
    check must not change behavior for the ordinary case of an unrecognised
    string type."""
    note = _note(tmp_path, "X", "---\ntype: sandwich\ntitle: X\ndate: 2026-08-22\n---\n\nbody\n")
    problems = vaultlib.validate([note])
    assert any("unknown type `sandwich`" in p for p in problems)


# --- Task 9: R35 (`area` is required for asset notes specifically) ---------


def test_validate_requires_area_on_asset_notes(tmp_path):
    """R35: render_open_items() groups an item by its ASSET's `area`, falling
    back to the source note's area when the asset supplies none. An asset note
    with no `area` therefore silently misfiles every item referencing it, with
    nothing in the rendered register to show for it. The schema must make that
    state unrepresentable rather than leaving it to be noticed by eye."""
    note = _note(
        tmp_path,
        "Filter Press",
        "---\ntype: asset\ntitle: Filter Press\ndate: 2026-08-22\nstatus: degraded\n---\n\nbody\n",
    )
    problems = vaultlib.validate([note])
    assert any("missing required frontmatter key `area`" in p for p in problems)
    assert any("Filter Press.md" in p and "asset" in p for p in problems)


def test_validate_accepts_an_asset_note_that_has_area(tmp_path):
    """Regression guard for the rule above: the 14 real asset notes all carry
    `area`, so adding the requirement must not turn any of them red."""
    note = _note(
        tmp_path,
        "Filter Press",
        "---\ntype: asset\ntitle: Filter Press\ndate: 2026-08-22\narea: wwt\nstatus: degraded\n---\n\nbody\n",
    )
    assert vaultlib.validate([note]) == []


def test_validate_does_not_require_area_on_non_asset_types(tmp_path):
    """R35 is deliberately narrow. A meeting, document, or concept note may
    legitimately span areas or belong to none, and only assets drive the
    open-items grouping — so requiring `area` everywhere would flag notes that
    are not wrong."""
    for type_name in ("note", "meeting", "document", "person", "org", "project", "resource"):
        note = _note(
            tmp_path,
            "X",
            f"---\ntype: {type_name}\ntitle: X\ndate: 2026-08-22\n---\n\nbody\n",
        )
        problems = vaultlib.validate([note])
        assert not any("`area`" in p for p in problems), type_name


def test_validate_does_not_report_missing_area_when_asset_frontmatter_unparseable(tmp_path):
    """The R10 suppression must cover the type-specific check too: an asset
    note whose frontmatter fails to parse reports one YAML error, not a YAML
    error plus a derived `area` complaint that is an artifact of properties
    being empty."""
    note = _note(
        tmp_path,
        "Filter Press",
        "---\ntype: asset\ntitle: Filter Press\ndate: 2026-08-22\nlinks:\n  - [[A]], [[B]]\n---\n\nbody\n",
    )
    problems = vaultlib.validate([note])
    assert any("failed to parse as YAML" in p for p in problems)
    assert not any("`area`" in p for p in problems)


# --- Final fix wave: per-type `status` enums (R40) ---
#
# Replacing the STATUS_ENUMS check with `if False:` passed all 75 tests before
# these: three spec-mandated enums were entirely unguarded.


def test_validate_flags_status_not_valid_for_asset(tmp_path):
    note = _note(
        tmp_path,
        "X",
        "---\ntype: asset\ntitle: X\ndate: 2026-08-22\narea: paint\nstatus: contained\n---\n\nbody\n",
    )
    problems = vaultlib.validate([note])
    assert any("`status` value `contained` is not valid for type `asset`" in p for p in problems)


def test_validate_flags_status_not_valid_for_observation(tmp_path):
    note = _note(
        tmp_path,
        "X",
        "---\ntype: observation\ntitle: X\ndate: 2026-08-22\narea: paint\nstatus: degraded\n---\n\nbody\n",
    )
    problems = vaultlib.validate([note])
    assert any("`status` value `degraded` is not valid for type `observation`" in p for p in problems)


def test_validate_flags_status_not_valid_for_project(tmp_path):
    note = _note(
        tmp_path,
        "X",
        "---\ntype: project\ntitle: X\ndate: 2026-08-22\nstatus: operating\n---\n\nbody\n",
    )
    problems = vaultlib.validate([note])
    assert any("`status` value `operating` is not valid for type `project`" in p for p in problems)


def test_validate_accepts_every_spec_status_for_its_own_type(tmp_path):
    for note_type, values in vaultlib.STATUS_ENUMS.items():
        for value in values:
            area = "" if note_type == "project" else "area: paint\n"
            note = _note(
                tmp_path,
                "X",
                f"---\ntype: {note_type}\ntitle: X\ndate: 2026-08-22\n{area}status: {value}\n---\n\nbody\n",
            )
            assert vaultlib.validate([note]) == [], f"{note_type}/{value} should be accepted"


def test_validate_leaves_status_unchecked_on_types_with_no_status_enum(tmp_path):
    """A `meeting` has no status enum in the spec, so any value passes — the
    per-type check must not leak the asset set onto other types."""
    note = _note(
        tmp_path,
        "X",
        "---\ntype: meeting\ntitle: X\ndate: 2026-08-22\nstatus: whatever\n---\n\nbody\n",
    )
    assert vaultlib.validate([note]) == []


# --- Final fix wave: near-miss `#item` lines (R39) ---
#
# ITEM_RE is strict and validate() could only inspect items that already
# parsed, so a line that missed the grammar by one character produced no item,
# no warning and no violation. For a register whose value is making unexecuted
# work visible, a silently-dropped item is the worst failure it can have.

_FM = "---\ntype: observation\ntitle: T\ndate: 2026-06-09\narea: paint\n---\n\n"
_TAIL = "Do a thing [[Post Rinse 4]] owner:[[Maintenance]] raised:2026-06-01\n"

NEAR_MISSES = [
    ("asterisk bullet", "* [ ] #item " + _TAIL),
    ("two spaces after the dash", "-  [ ] #item " + _TAIL),
    ("empty checkbox brackets", "- [] #item " + _TAIL),
    ("no space between ] and #item", "- [ ]#item " + _TAIL),
]


def test_validate_flags_every_near_miss_item_line(tmp_path):
    for description, line in NEAR_MISSES:
        note = _note(tmp_path, "T", _FM + line)
        assert note.tasks == [], f"{description}: should not have parsed as an item"
        problems = vaultlib.validate([note])
        assert len(problems) == 1, f"{description}: expected exactly one violation, got {problems}"
        assert "does not parse as an item" in problems[0], description
        assert problems[0].startswith("T.md:8:"), f"{description}: wrong line number in {problems[0]}"
        assert vaultlib.ITEM_GRAMMAR in problems[0], description


def test_validate_does_not_flag_backticked_item_in_prose(tmp_path):
    """The two lines in the live vault that legitimately carry a backticked
    `#item` in running prose: 1-Projects/Paint Line.md and
    3-Resources/3.2-Documents/Paint and WWT Observation Record.md."""
    paint_line = _note(
        tmp_path,
        "Paint Line",
        _FM
        + "> **authoritative for status and age** — those `#item` lines are what "
        "`.foam/scripts/reindex.py` collects and ages into\n",
    )
    record = _note(
        tmp_path,
        "Paint and WWT Observation Record",
        _FM
        + "Two live views. The first is generated from every `#item` line in the vault and "
        "aged automatically; the second is the\n",
    )
    assert vaultlib.validate([paint_line]) == []
    assert vaultlib.validate([record]) == []


def test_validate_does_not_flag_the_fenced_grammar_example(tmp_path):
    """README.md documents the grammar inside a fence; strip_code_fences
    blanks it, so it is neither an item nor a near miss."""
    note = _note(
        tmp_path,
        "README",
        _FM + "```markdown\n- [ ] #item <description> [[Asset]] owner:[[Who]] raised:YYYY-MM-DD\n```\n",
    )
    assert note.tasks == []
    assert vaultlib.validate([note]) == []


def test_validate_does_not_flag_a_well_formed_item(tmp_path):
    note = _note(tmp_path, "T", _FM + "- [ ] #item " + _TAIL + "- [x] #item " + _TAIL)
    assert len(note.tasks) == 2
    assert vaultlib.validate([note]) == []


# --- Final fix wave: duplicated metadata keys on one item line (R41) ---


def test_validate_flags_a_duplicated_metadata_key(tmp_path):
    note = _note(
        tmp_path,
        "T",
        _FM
        + "- [ ] #item Install mixer [[Tank Mixer]] owner:[[Maintenance]] "
        "raised:2026-03-02 raised:2020-01-01\n",
    )
    # The bug it guards: the last value silently wins, so the item ages from
    # a date nobody wrote.
    assert note.tasks[0].raised.isoformat() == "2020-01-01"
    problems = vaultlib.validate([note])
    assert len(problems) == 1
    assert problems[0].startswith("T.md:8:")
    assert "repeats `raised:`" in problems[0]


def test_validate_flags_a_duplicated_owner_key(tmp_path):
    note = _note(
        tmp_path,
        "T",
        _FM
        + "- [ ] #item Install mixer [[Tank Mixer]] owner:[[Maintenance]] "
        "owner:[[Houston Lamb]] raised:2026-03-02\n",
    )
    problems = vaultlib.validate([note])
    assert any("repeats `owner:`" in p for p in problems)


def test_validate_does_not_flag_a_key_word_repeated_in_the_description(tmp_path):
    """R9: the metadata run is the TRAILING run only, so `ref:` used as
    English in the description is not a repeated key."""
    note = _note(
        tmp_path,
        "T",
        _FM
        + "- [ ] #item Check ref: and ref: in the drawing [[Tank Mixer]] "
        "owner:[[Maintenance]] raised:2026-03-02\n",
    )
    assert vaultlib.validate([note]) == []


# --- Task 2: `document_format` enum widened for the 2026-08-22 GitLab import ---


def test_document_format_accepts_media_types(tmp_path):
    """Task 10 creates stubs for photo sets, saved emails and the PFMEA tool."""
    for fmt in ("jpg", "png", "msg", "json", "html"):
        note = _note(
            tmp_path,
            "X",
            "---\ntype: document\ntitle: X\ndate: 2026-08-22\n"
            f"document_type: record\ndocument_format: {fmt}\n---\n\nbody\n",
        )
        assert vaultlib.validate([note]) == [], f"{fmt} should be a valid document_format"


def test_document_format_still_rejects_junk(tmp_path):
    note = _note(
        tmp_path,
        "X",
        "---\ntype: document\ntitle: X\ndate: 2026-08-22\n"
        "document_type: record\ndocument_format: exe\n---\n\nbody\n",
    )
    problems = vaultlib.validate([note])
    assert any("document_format" in p for p in problems)


# --- Added in the port: the task marker is configurable now ---


def test_near_miss_scan_follows_a_non_default_task_marker(tmp_path):
    """The legacy scan hard-coded `#item`. A workspace that renames the marker
    must get the same protection under the new name, and must not be flagged
    for the old one."""
    schema = parse_schema(
        {
            "schema": {"required": ["type", "title", "date"], "types": ["observation"]},
            "markdown": {"task_marker": "task"},
        }
    )
    text = (
        "---\ntype: observation\ntitle: T\ndate: 2026-06-09\n---\n\n"
        "* [ ] #task Do a thing [[X]] owner:[[Y]] raised:2026-06-01\n"
    )
    doc = markdown.parse_document(tmp_path / "T.md", text, "task")
    problems = messages(markdown.validate([doc], schema))
    assert len(problems) == 1
    assert "#task" in problems[0]
    assert "#item" not in problems[0]


def test_default_marker_ignores_a_line_using_a_different_marker(tmp_path):
    doc = markdown.parse_document(
        tmp_path / "T.md",
        "---\ntype: note\ntitle: T\ndate: 2026-06-09\n---\n\n- [ ] #todo something\n",
    )
    assert messages(markdown.validate([doc], default_schema())) == []
