"""Schema validation for the markdown store.

Ported from the legacy validator with every rule and every message intact. The
phase 0 acceptance gate is lint parity: for the same content, Structura must
report exactly the legacy violation list -- same strings, same order. So the
message wording is frozen here even where it has aged (it still names Foam,
the tool being replaced). Re-wording a message is a deliberate later change
with the parity baseline updated in the same commit; doing it during the port
would destroy the one signal proving the port did not alter a rule.

What the port adds is structure, not substitution: each check yields a
`Violation` carrying a code, a path and a line alongside the legacy string, so
a lint pane can group by rule and jump to the fault.

What the port removes is the module-level constants. The rules now come from a
`Schema`, so a second workspace can disagree about its enums without a code
change.
"""

from __future__ import annotations

from structura.core.document import Document
from structura.core.schema import Schema, default_schema
from structura.core.violations import Violation

from . import parse

# Violation codes. Stable identifiers for rules whose messages are frozen.
FRONTMATTER_UNPARSEABLE = "frontmatter-unparseable"
MISSING_REQUIRED_KEY = "missing-required-key"
MISSING_TYPE_REQUIRED_KEY = "missing-type-required-key"
UNKNOWN_TYPE = "unknown-type"
ENUM_INVALID = "enum-invalid"
STATUS_INVALID = "status-invalid"
WIKILINK_IN_FRONTMATTER = "wikilink-in-frontmatter"
TASK_NO_ASSET = "task-no-asset"
TASK_NO_OWNER = "task-no-owner"
TASK_NO_RAISED = "task-no-raised"
TASK_DUPLICATE_KEY = "task-duplicate-key"
PART_OF_NOT_AT_LINE_START = "part-of-not-at-line-start"
TASK_NEAR_MISS = "task-near-miss"


def validate(documents: list[Document], schema: Schema | None = None) -> list[Violation]:
    """Schema violations, in the legacy order. An empty list means clean."""
    schema = schema or default_schema()
    marker = schema.markdown.task_marker
    grammar = parse.grammar(marker)
    problems: list[Violation] = []

    def add(code: str, message: str, doc: Document, line: int | None = None) -> None:
        problems.append(Violation(code=code, message=message, path=doc.path, line=line))

    for doc in documents:
        where = doc.path.name

        # R10: when frontmatter is present but fails to parse as YAML,
        # `fields` is {} -- every required key would otherwise appear
        # "missing", burying the real fault (a YAML syntax error) under four
        # misleading ones. Report the parse failure distinctly instead, and
        # skip the missing-key checks for this document; the enum and wikilink
        # checks below are no-ops anyway since `fields` is empty.
        if doc.frontmatter_error:
            add(
                FRONTMATTER_UNPARSEABLE,
                f"{where}: frontmatter present but failed to parse as YAML — "
                f"{doc.frontmatter_error}",
                doc,
            )
        else:
            for key in schema.required:
                if not doc.fields.get(key):
                    add(
                        MISSING_REQUIRED_KEY,
                        f"{where}: missing required frontmatter key `{key}`",
                        doc,
                    )

            # R35: type-specific required keys. Inside the same else-branch as
            # the check above so the R10 parse-failure suppression covers it
            # too -- an unparseable document reports one YAML error, not a pile
            # of derived missing-key noise.
            for key in schema.required_keys_for(str(doc.dtype or "")):
                if not doc.fields.get(key):
                    add(
                        MISSING_TYPE_REQUIRED_KEY,
                        f"{where}: missing required frontmatter key `{key}` for type `{doc.dtype}`",
                        doc,
                    )

        # `str()` rather than the value itself: a list or dict in `type:` is
        # unhashable, and a set membership test on it would raise and take
        # every other document's violations down with it.
        if doc.dtype and str(doc.dtype) not in schema.types:
            add(UNKNOWN_TYPE, f"{where}: unknown type `{doc.dtype}`", doc)

        for key, allowed in schema.enums.items():
            value = doc.fields.get(key)
            if value and str(value) not in allowed:
                add(
                    ENUM_INVALID,
                    f"{where}: `{key}` value `{value}` is not in the allowed set",
                    doc,
                )

        allowed_status = schema.status_for(str(doc.dtype or ""))
        status = doc.fields.get("status")
        if allowed_status and status and str(status) not in allowed_status:
            add(
                STATUS_INVALID,
                f"{where}: `status` value `{status}` is not valid for type `{doc.dtype}`",
                doc,
            )

        # The trap that motivated the whole schema: markdown tooling does not
        # resolve wikilinks inside YAML, so a link here is invisible to
        # everything that reads the workspace.
        for key, value in doc.fields.items():
            if "[[" in str(value):
                add(
                    WIKILINK_IN_FRONTMATTER,
                    f"{where}: frontmatter key `{key}` contains a wikilink — "
                    f"Foam cannot see it; move the link into the note body",
                    doc,
                )

        for task in doc.tasks:
            loc = f"{where}:{task.line_no}"
            if not task.asset:
                add(TASK_NO_ASSET, f"{loc}: item has no [[asset]] link", doc, task.line_no)
            if not task.owner:
                add(TASK_NO_OWNER, f"{loc}: item has no `owner:`", doc, task.line_no)
            if not task.raised:
                add(
                    TASK_NO_RAISED,
                    f"{loc}: item has no valid `raised:` date",
                    doc,
                    task.line_no,
                )

        # R39: everything above can only inspect tasks that already PARSED. A
        # line that meant to be a task and missed the grammar by one character
        # -- `* [ ]`, a doubled space, `[]`, no space after `]` -- produces no
        # task, no warning and no violation, so the work it records vanishes
        # from the register with nothing anywhere saying so. For a register
        # whose whole value is making unexecuted work visible, that is the
        # worst failure mode and the only one the tool cannot otherwise see.
        # Walk the fence-stripped text and flag any marker mention that did not
        # become a task.
        #
        # Inline code spans are stripped FIRST: notes that discuss the marker
        # in running prose must not be flagged.
        for offset, line in enumerate(doc.live_text.splitlines(), start=1):
            loc = f"{where}:{offset}"
            if parse.parse_task_line(line, marker) is not None:
                for key in parse.duplicate_meta_keys(line, marker):
                    add(
                        TASK_DUPLICATE_KEY,
                        f"{loc}: item line repeats `{key}:` — only the last value is kept, "
                        f"so the item silently carries a value nobody chose",
                        doc,
                        offset,
                    )
                continue
            if parse.dropped_part_of(line):
                add(
                    PART_OF_NOT_AT_LINE_START,
                    f"{loc}: `Part of [[...]]` is not at the start of its line, so the "
                    f"membership is dropped -- give it a line of its own with a blank "
                    f"line above it, or Prettier's `proseWrap: always` will reflow it "
                    f"back onto the line before",
                    doc,
                    offset,
                )
            if f"#{marker}" not in parse.strip_inline_code(line):
                continue
            add(
                TASK_NEAR_MISS,
                f"{loc}: line mentions `#{marker}` but does not parse as an item, so it is "
                f"dropped from the register — expected `{grammar.description}` (a `-` bullet, "
                f"one space, `[ ]` or `[x]` with exactly one character between the brackets, "
                f"then at least one space before `#{marker}`)",
                doc,
                offset,
            )

    return problems
