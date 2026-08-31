"""The index schema.

The rule that governs every line of this file: **the index is a cache and
never a source.** Deleting it must lose nothing but a second. That is why
there is no migration machinery here -- a schema version mismatch drops the
database and rebuilds it, which is both simpler than migrating and a standing
proof that the rule holds.

Two shapes deserve explanation.

`documents` is keyed by an integer with `path` unique and `uid` unique but
nullable, rather than by the UID as the design doc first sketched. Phase 0
established that reading never writes, so a workspace can be indexed before
its documents have been stamped -- 138 of the first real workspace had no UID
at all. Keying on the UID would have meant rewriting every file before the
first query. The path is what sync actually works in (stat and hash are
per-path, deletions are per-path), the UID is the durable identity links
resolve to, and both are present.

`fields` is a key/value table rather than columns, so a free-form frontmatter
key needs no migration. Only the handful of keys the schema checks are
promoted to columns on `documents`, for indexing.
"""

from __future__ import annotations

SCHEMA_VERSION = 1

# Fields promoted from `fields` to columns on `documents`, because they are
# what queries filter and sort on. Everything else stays in the key/value
# table. Kept as a tuple so the DDL and the insert path cannot disagree.
PROMOTED_FIELDS = ("date", "area", "status")

DDL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
    id         INTEGER PRIMARY KEY,
    path       TEXT NOT NULL UNIQUE,
    uid        TEXT UNIQUE,
    store      TEXT NOT NULL,
    dtype      TEXT,
    title      TEXT NOT NULL,
    date       TEXT,
    area       TEXT,
    status     TEXT,
    mtime_ns   INTEGER NOT NULL,
    size       INTEGER NOT NULL,
    sha256     TEXT NOT NULL,
    indexed_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS documents_dtype  ON documents(dtype);
CREATE INDEX IF NOT EXISTS documents_area   ON documents(area);
CREATE INDEX IF NOT EXISTS documents_status ON documents(status);
CREATE INDEX IF NOT EXISTS documents_title  ON documents(title);

CREATE TABLE IF NOT EXISTS fields (
    doc_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    key    TEXT NOT NULL,
    value  TEXT NOT NULL,
    ord    INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS fields_doc ON fields(doc_id);
CREATE INDEX IF NOT EXISTS fields_kv  ON fields(key, value);

CREATE TABLE IF NOT EXISTS tags (
    doc_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    tag    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS tags_doc ON tags(doc_id);
CREATE INDEX IF NOT EXISTS tags_tag ON tags(tag);

-- Every title and alias, mapped to the document that owns it, so a link to
-- `[[PR4]]` and a link to `[[Post Rinse 4]]` resolve to the same row without
-- every query knowing about the alias map.
CREATE TABLE IF NOT EXISTS aliases (
    alias  TEXT NOT NULL,
    doc_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS aliases_alias ON aliases(alias);
CREATE INDEX IF NOT EXISTS aliases_doc   ON aliases(doc_id);

CREATE TABLE IF NOT EXISTS links (
    doc_id     INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    target_raw TEXT NOT NULL,
    -- The link text with any `#section` or `|display` suffix removed: what a
    -- reader means by "the note this points at".
    target_norm TEXT NOT NULL,
    section    TEXT,
    is_embed   INTEGER NOT NULL DEFAULT 0,
    line_no    INTEGER NOT NULL,
    -- Filled by the resolution pass after a sync. NULL means the target is
    -- not written yet, which is what makes it a placeholder.
    target_id  INTEGER REFERENCES documents(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS links_doc    ON links(doc_id);
CREATE INDEX IF NOT EXISTS links_target ON links(target_id);
CREATE INDEX IF NOT EXISTS links_norm   ON links(target_norm);

-- `Part of [[...]]` membership. Separate from links because it is a claim
-- about structure, not a mention, and the asset tree is built from it.
CREATE TABLE IF NOT EXISTS parents (
    doc_id      INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    target_norm TEXT NOT NULL,
    ord         INTEGER NOT NULL DEFAULT 0,
    target_id   INTEGER REFERENCES documents(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS parents_doc    ON parents(doc_id);
CREATE INDEX IF NOT EXISTS parents_target ON parents(target_id);

CREATE TABLE IF NOT EXISTS tasks (
    doc_id      INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    line_no     INTEGER NOT NULL,
    description TEXT NOT NULL,
    asset_raw   TEXT,
    asset_norm  TEXT,
    owner       TEXT,
    raised      TEXT,
    due         TEXT,
    ref         TEXT,
    done        INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS tasks_doc   ON tasks(doc_id);
CREATE INDEX IF NOT EXISTS tasks_done  ON tasks(done);
CREATE INDEX IF NOT EXISTS tasks_owner ON tasks(owner);
CREATE INDEX IF NOT EXISTS tasks_asset ON tasks(asset_norm);

-- Every on-disk filename a wikilink may legitimately name, and the file that
-- provides it. A non-markdown file is only nameable with its extension
-- (legacy R31); a markdown file is nameable with or without one. Keeping the
-- providing path lets a removal drop exactly the names that file supplied,
-- rather than guessing when two files share a stem.
--
-- Without this table the index cannot answer "is this link a placeholder?",
-- because a link may resolve to an attachment that is not a document.
CREATE TABLE IF NOT EXISTS link_targets (
    name TEXT NOT NULL,
    path TEXT NOT NULL,
    PRIMARY KEY (name, path)
);

CREATE INDEX IF NOT EXISTS link_targets_name ON link_targets(name);
CREATE INDEX IF NOT EXISTS link_targets_path ON link_targets(path);

-- A standalone FTS5 table rather than an external-content one. External
-- content would need the body to live in `documents` and triggers to keep the
-- two in step; a disposable cache does not need to pay for that, and the
-- bodies are not otherwise wanted as a column.
CREATE VIRTUAL TABLE IF NOT EXISTS fts USING fts5(
    title,
    body,
    doc_id UNINDEXED,
    tokenize = 'unicode61'
);
"""
