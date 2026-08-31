"""The local index: a cache over the files, with no authority.

Deleting `index.db` must lose nothing but a second. Everything a user types
goes to a file first; the index is updated from the file, never the other way
round.
"""

from .db import Database, index_path
from .query import DocumentRow, Index, Placeholder, TaskRow
from .sync import Indexer, SyncReport

__all__ = [
    "Database",
    "DocumentRow",
    "Index",
    "Indexer",
    "Placeholder",
    "SyncReport",
    "TaskRow",
    "index_path",
]
