"""Qt models over query results.

The view pane shows whatever a pipeline produced, whatever kind that is. That
is only possible because a `Result` is already rows of labelled values, so the
model is a thin adapter rather than a per-kind table -- the same reason
`where` and `sort` did not need one either.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt

from structura.query.format import cell
from structura.query.rows import Result, Row
from structura.theme import Theme, load

#: Columns that read better right-aligned: they are quantities, not labels.
NUMERIC = {"age", "inbound", "line"}


class ResultModel(QAbstractTableModel):
    """One query result, as a table."""

    def __init__(self, theme: Theme | None = None) -> None:
        super().__init__()
        self.theme = theme or load()
        self._rows: list[Row] = []
        self._columns: list[str] = []
        self._kind = ""

    # --- content -------------------------------------------------------

    def set_result(self, result: Result) -> None:
        self.beginResetModel()
        self._rows = list(result.rows)
        self._columns = list(result.columns) or self._infer(result)
        self._kind = result.kind
        self.endResetModel()

    @staticmethod
    def _infer(result: Result) -> list[str]:
        seen: dict[str, None] = {}
        for row in result.rows:
            for key in row.values:
                seen.setdefault(key, None)
        return list(seen)

    @property
    def kind(self) -> str:
        return self._kind

    def row_at(self, index: QModelIndex) -> Row | None:
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return None
        return self._rows[index.row()]

    # --- QAbstractTableModel -------------------------------------------

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802, B008
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802, B008
        return 0 if parent.isValid() else len(self._columns)

    def headerData(  # noqa: N802
        self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole
    ) -> Any:
        if role != Qt.ItemDataRole.DisplayRole or orientation != Qt.Orientation.Horizontal:
            return None
        return self._columns[section] if 0 <= section < len(self._columns) else None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        row = self.row_at(index)
        if row is None:
            return None
        column = self._columns[index.column()]

        if role == Qt.ItemDataRole.DisplayRole:
            return cell(row.get(column))
        if role == Qt.ItemDataRole.TextAlignmentRole and column in NUMERIC:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if role == Qt.ItemDataRole.ToolTipRole:
            return "\n".join(f"{key}: {cell(value)}" for key, value in row.values.items())
        return None
