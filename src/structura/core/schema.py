"""The workspace schema, loaded from data rather than compiled into code.

Decision: the schema is a TOML file in the workspace, not module-level dicts.
The legacy validator kept its rules as constants, which is right for one vault
with one schema and wrong the moment a second exists -- a personal workspace
wanting different enums would need a code change to a tool shared with a work
workspace.

Three properties this file has to keep, because each is load-bearing:

- The file is tracked and reviewable, so a schema change is a diff.
- A missing schema file is not an error; the shipped default applies.
- The shipped default is equivalent to the legacy constants, and a test
  asserts it field for field.

Structura validates the schema itself on load. An unknown key, a non-list
enum, or a `required_for` naming a type that is not in `types` fails loudly at
startup rather than producing a workspace where nothing is checked.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

SCHEMA_FILENAME = "structura.toml"

_ALLOWED_TOP = {"schema", "markdown"}
_ALLOWED_SCHEMA = {"required", "types", "enums", "status", "required_for"}
_ALLOWED_MARKDOWN = {"task_marker", "skip", "link_target_skip"}


class SchemaError(Exception):
    """The schema file itself is wrong. Raised at load time, never swallowed."""


@dataclass(frozen=True)
class MarkdownSettings:
    task_marker: str = "item"
    skip: frozenset[str] = frozenset({"0-Index", "6-Archive", "docs", "node_modules"})
    link_target_skip: frozenset[str] = frozenset({"6-Archive", "docs", "node_modules"})


@dataclass(frozen=True)
class Schema:
    required: tuple[str, ...]
    types: frozenset[str]
    enums: dict[str, frozenset[str]]
    status: dict[str, frozenset[str]]
    required_for: dict[str, tuple[str, ...]]
    markdown: MarkdownSettings = field(default_factory=MarkdownSettings)

    def status_for(self, dtype: str) -> frozenset[str] | None:
        return self.status.get(dtype)

    def required_keys_for(self, dtype: str) -> tuple[str, ...]:
        return self.required_for.get(dtype, ())


def _require_str_list(value: object, where: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise SchemaError(f"{where} must be a list of strings, got {type(value).__name__}")
    return tuple(value)


def _require_mapping_of_lists(value: object, where: str) -> dict[str, tuple[str, ...]]:
    if not isinstance(value, dict):
        raise SchemaError(f"{where} must be a table, got {type(value).__name__}")
    return {key: _require_str_list(val, f"{where}.{key}") for key, val in value.items()}


def _reject_unknown(keys: object, allowed: set[str], where: str) -> None:
    assert isinstance(keys, dict)
    unknown = sorted(set(keys) - allowed)
    if unknown:
        raise SchemaError(
            f"unknown key(s) in {where}: {', '.join(unknown)} "
            f"(allowed: {', '.join(sorted(allowed))})"
        )


def parse_schema(data: dict) -> Schema:
    """Build a Schema from parsed TOML, rejecting anything malformed."""
    _reject_unknown(data, _ALLOWED_TOP, "the schema file")

    raw_schema = data.get("schema", {})
    if not isinstance(raw_schema, dict):
        raise SchemaError("[schema] must be a table")
    _reject_unknown(raw_schema, _ALLOWED_SCHEMA, "[schema]")

    required = _require_str_list(raw_schema.get("required", []), "[schema].required")
    types = frozenset(_require_str_list(raw_schema.get("types", []), "[schema].types"))
    enums = {
        key: frozenset(val)
        for key, val in _require_mapping_of_lists(
            raw_schema.get("enums", {}), "[schema.enums]"
        ).items()
    }
    status = {
        key: frozenset(val)
        for key, val in _require_mapping_of_lists(
            raw_schema.get("status", {}), "[schema.status]"
        ).items()
    }
    required_for = _require_mapping_of_lists(
        raw_schema.get("required_for", {}), "[schema.required_for]"
    )

    # A `status` or `required_for` entry naming a type that does not exist is
    # a rule that can never fire. Silently accepting it produces a workspace
    # where the author believes a check is running and it is not, which is
    # worse than no check at all.
    for table, name in ((status, "[schema.status]"), (required_for, "[schema.required_for]")):
        for dtype in sorted(table):
            if types and dtype not in types:
                raise SchemaError(
                    f"{name} names type `{dtype}`, which is not in [schema].types -- "
                    f"this rule could never fire"
                )

    raw_md = data.get("markdown", {})
    if not isinstance(raw_md, dict):
        raise SchemaError("[markdown] must be a table")
    _reject_unknown(raw_md, _ALLOWED_MARKDOWN, "[markdown]")

    marker = raw_md.get("task_marker", MarkdownSettings.task_marker)
    if not isinstance(marker, str) or not marker or not marker.isidentifier():
        raise SchemaError(
            f"[markdown].task_marker must be a bare word (it is spliced into a regex "
            f"as `#{{marker}}`), got {marker!r}"
        )

    defaults = MarkdownSettings()
    markdown = MarkdownSettings(
        task_marker=marker,
        skip=frozenset(_require_str_list(raw_md["skip"], "[markdown].skip"))
        if "skip" in raw_md
        else defaults.skip,
        link_target_skip=frozenset(
            _require_str_list(raw_md["link_target_skip"], "[markdown].link_target_skip")
        )
        if "link_target_skip" in raw_md
        else defaults.link_target_skip,
    )

    return Schema(
        required=required,
        types=types,
        enums=enums,
        status=status,
        required_for=required_for,
        markdown=markdown,
    )


def default_schema() -> Schema:
    """The schema shipped with Structura, used when a workspace has none."""
    text = resources.files("structura.design").joinpath("default_schema.toml").read_text()
    return parse_schema(tomllib.loads(text))


def load_schema(workspace: Path) -> Schema:
    """The schema for a workspace. A missing file is not an error."""
    path = Path(workspace) / SCHEMA_FILENAME
    if not path.is_file():
        return default_schema()
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise SchemaError(f"{path}: not valid TOML -- {exc}") from exc
    return parse_schema(data)
