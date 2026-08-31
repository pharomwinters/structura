"""The shipped schema must equal the legacy constants, field for field.

Moving the rules out of code and into data is only safe if the data says the
same thing the code did. The expected values below are transcribed from the
legacy validator's module scope; a diff here is a diff in what the workspace is
checked against, and should never be an accident.

`tests/test_parity.py` proves the same thing dynamically against the real
module when it is available. This file proves it without needing the private
content, so CI catches a drifted schema on its own.
"""

from structura.core.schema import default_schema

LEGACY_REQUIRED_KEYS = ("type", "title", "date")

LEGACY_VALID_TYPES = {
    "asset",
    "person",
    "org",
    "document",
    "project",
    "meeting",
    "observation",
    "note",
    "resource",
    "index",
}

LEGACY_ENUMS = {
    "area": {"paint", "wwt", "monorail", "power-free", "plant"},
    "document_type": {
        "work-instruction",
        "sop",
        "form",
        "record",
        "spec",
        "drawing",
        "poster",
    },
    "document_format": {
        "docx",
        "xlsx",
        "pptx",
        "pdf",
        "tex",
        "typ",
        "jpg",
        "png",
        "msg",
        "json",
        "html",
    },
    "resource_type": {
        "link",
        "pdf",
        "vendor-doc",
        "datasheet",
        "standard",
        "reference",
    },
    "category": {"Friends", "Family", "Co-Worker", "Employee", "Vendor"},
    "org_type": {"internal", "vendor", "customer"},
}

LEGACY_STATUS_ENUMS = {
    "asset": {"operating", "degraded", "down", "removed"},
    "observation": {"open", "contained", "resolved"},
    "project": {"planning", "active", "on-hold", "complete", "cancelled"},
}

LEGACY_TYPE_REQUIRED_KEYS = {"asset": ("area",)}

LEGACY_SKIP_DIRS = {"0-Index", "6-Archive", "docs", "node_modules"}
LEGACY_LINK_TARGET_SKIP_DIRS = LEGACY_SKIP_DIRS - {"0-Index"}


def test_required_keys_match():
    assert default_schema().required == LEGACY_REQUIRED_KEYS


def test_types_match():
    assert default_schema().types == LEGACY_VALID_TYPES


def test_enums_match_key_for_key():
    shipped = default_schema().enums
    assert set(shipped) == set(LEGACY_ENUMS)
    for key, expected in LEGACY_ENUMS.items():
        assert shipped[key] == expected, key


def test_status_enums_match_key_for_key():
    shipped = default_schema().status
    assert set(shipped) == set(LEGACY_STATUS_ENUMS)
    for key, expected in LEGACY_STATUS_ENUMS.items():
        assert shipped[key] == expected, key


def test_type_required_keys_match():
    assert default_schema().required_for == LEGACY_TYPE_REQUIRED_KEYS


def test_skip_directories_match():
    markdown = default_schema().markdown
    assert markdown.skip == LEGACY_SKIP_DIRS
    assert markdown.link_target_skip == LEGACY_LINK_TARGET_SKIP_DIRS


def test_the_default_task_marker_is_the_legacy_one():
    """Existing content says `#item`. The default must keep parsing it."""
    assert default_schema().markdown.task_marker == "item"
