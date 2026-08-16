"""実際のgspreadを使わずにsheets/writer.py・sheets/inspector.pyを検証するための
最小限のインメモリ実装。SheetsClient(fake_backend=...)へ注入して使う。
"""

from __future__ import annotations

import re
from typing import Any


class WorksheetNotFound(Exception):
    pass


class FakeWorksheet:
    def __init__(self, title: str, seed_rows: list[list[str]] | None = None):
        self.title = title
        self.rows: list[list[str]] = [list(r) for r in seed_rows] if seed_rows else []

    def append_row(self, values: list[Any]) -> None:
        self.rows.append([str(v) for v in values])

    def get_all_values(self) -> list[list[str]]:
        return [list(r) for r in self.rows]

    def get_all_records(self) -> list[dict[str, Any]]:
        if not self.rows:
            return []
        headers = self.rows[0]
        records = []
        for r in self.rows[1:]:
            records.append({headers[i]: (r[i] if i < len(r) else "") for i in range(len(headers))})
        return records

    def col_values(self, col_idx: int) -> list[str]:
        idx = col_idx - 1
        return [r[idx] if idx < len(r) else "" for r in self.rows]

    def update(self, range_str: str, values: list[list[Any]]) -> None:
        match = re.match(r"A(\d+)", range_str)
        if not match:
            raise ValueError(f"unsupported range for fake worksheet: {range_str}")
        row_number = int(match.group(1))
        while len(self.rows) < row_number:
            self.rows.append([])
        self.rows[row_number - 1] = [str(v) for v in values[0]]


class FakeSpreadsheet:
    def __init__(self):
        self._worksheets: dict[str, FakeWorksheet] = {}

    def seed_worksheet(self, title: str, rows: list[list[str]]) -> FakeWorksheet:
        ws = FakeWorksheet(title, seed_rows=rows)
        self._worksheets[title] = ws
        return ws

    def worksheet(self, name: str) -> FakeWorksheet:
        if name not in self._worksheets:
            raise WorksheetNotFound(name)
        return self._worksheets[name]

    def add_worksheet(self, title: str, rows: int = 1000, cols: int = 10) -> FakeWorksheet:
        ws = FakeWorksheet(title)
        self._worksheets[title] = ws
        return ws
