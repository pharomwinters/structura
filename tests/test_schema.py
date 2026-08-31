"""The schema file is data, and Structura checks it before trusting it."""

import pytest

from structura.core.schema import (
    SCHEMA_FILENAME,
    SchemaError,
    default_schema,
    load_schema,
    parse_schema,
)

MINIMAL = {"schema": {"required": ["type"], "types": ["note"]}}


def test_a_missing_schema_file_is_not_an_error(tmp_path):
    """An unconfigured workspace gets the built-in defaults rather than a
    workspace where nothing is checked."""
    assert load_schema(tmp_path) == default_schema()


def test_a_workspace_schema_overrides_the_default(tmp_path):
    (tmp_path / SCHEMA_FILENAME).write_text(
        '[schema]\nrequired = ["title"]\ntypes = ["recipe"]\n\n'
        '[schema.enums]\ncuisine = ["thai", "welsh"]\n'
    )
    schema = load_schema(tmp_path)
    assert schema.types == {"recipe"}
    assert schema.enums["cuisine"] == {"thai", "welsh"}


def test_invalid_toml_fails_loudly(tmp_path):
    (tmp_path / SCHEMA_FILENAME).write_text("[schema\nrequired = ")
    with pytest.raises(SchemaError, match="not valid TOML"):
        load_schema(tmp_path)


def test_an_unknown_top_level_key_is_rejected():
    with pytest.raises(SchemaError, match="unknown key"):
        parse_schema({"schema": {}, "sandwich": {}})


def test_an_unknown_schema_key_is_rejected():
    with pytest.raises(SchemaError, match="unknown key"):
        parse_schema({"schema": {"requried": ["type"]}})


def test_a_non_list_enum_is_rejected():
    with pytest.raises(SchemaError, match="list of strings"):
        parse_schema({"schema": {"types": ["note"], "enums": {"area": "paint"}}})


def test_a_status_rule_for_an_unknown_type_is_rejected():
    """A rule that can never fire is worse than no rule: the author believes a
    check is running and it is not."""
    with pytest.raises(SchemaError, match="could never fire"):
        parse_schema({"schema": {"types": ["note"], "status": {"asset": ["operating"]}}})


def test_a_required_for_naming_an_unknown_type_is_rejected():
    with pytest.raises(SchemaError, match="could never fire"):
        parse_schema({"schema": {"types": ["note"], "required_for": {"asset": ["area"]}}})


def test_a_task_marker_that_would_corrupt_the_regex_is_rejected():
    with pytest.raises(SchemaError, match="bare word"):
        parse_schema({**MINIMAL, "markdown": {"task_marker": "item)("}})


def test_markdown_defaults_apply_when_the_section_is_absent():
    schema = parse_schema(MINIMAL)
    assert schema.markdown.task_marker == "item"
    assert "0-Index" in schema.markdown.skip


def test_link_target_skip_keeps_generated_output_resolvable():
    """R36: generated index files are excluded from parsing but ARE resolvable
    link targets, because they exist on disk."""
    schema = default_schema()
    assert "0-Index" in schema.markdown.skip
    assert "0-Index" not in schema.markdown.link_target_skip
