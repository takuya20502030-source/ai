"""実際のgspreadを使わずにsheets/writer.py・sheets/inspector.pyを検証するための
最小限のインメモリ実装。SheetsClient(fake_backend=...)へ注入して使う。
"""

from __future__ import annotations

import re
from typing import Any


class WorksheetNotFound(Exception):
    pass


class FakeWorksheet:
    def __init__(
        self,
        title: str,
        seed_rows: list[list[str]] | None = None,
        seed_formulas: dict[tuple[int, int], str] | None = None,
    ):
        self.title = title
        self.rows: list[list[str]] = [list(r) for r in seed_rows] if seed_rows else []
        # (row_idx, col_idx) 0始まり -> "=..." 形式の数式文字列。
        # value_render_option='FORMULA' で取得したときだけ、対応するセルの
        # 値をこの数式文字列に置き換える(通常のget_all_values()には影響しない)。
        self.formulas: dict[tuple[int, int], str] = dict(seed_formulas) if seed_formulas else {}

    @property
    def col_count(self) -> int:
        return max((len(r) for r in self.rows), default=0)

    def set_formula(self, row_idx: int, col_idx: int, formula: str) -> None:
        self.formulas[(row_idx, col_idx)] = formula

    def append_row(self, values: list[Any]) -> None:
        self.rows.append([str(v) for v in values])

    def clear(self) -> None:
        self.rows = []
        self.formulas = {}

    def get_all_values(self) -> list[list[str]]:
        return [list(r) for r in self.rows]

    def get_values(self, value_render_option: str | None = None, **kwargs: Any) -> list[list[str]]:
        if value_render_option != "FORMULA" or not self.formulas:
            return self.get_all_values()
        grid = [list(r) for r in self.rows]
        for (row_idx, col_idx), formula in self.formulas.items():
            while len(grid) <= row_idx:
                grid.append([])
            row = grid[row_idx]
            while len(row) <= col_idx:
                row.append("")
            row[col_idx] = formula
        return grid

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
    def __init__(self, title: str = "Fake Spreadsheet"):
        self.title = title
        self._worksheets: dict[str, FakeWorksheet] = {}

    def seed_worksheet(
        self, title: str, rows: list[list[str]], formulas: dict[tuple[int, int], str] | None = None
    ) -> FakeWorksheet:
        ws = FakeWorksheet(title, seed_rows=rows, seed_formulas=formulas)
        self._worksheets[title] = ws
        return ws

    def worksheet(self, name: str) -> FakeWorksheet:
        if name not in self._worksheets:
            raise WorksheetNotFound(name)
        return self._worksheets[name]

    def worksheets(self) -> list[FakeWorksheet]:
        return list(self._worksheets.values())

    def add_worksheet(self, title: str, rows: int = 1000, cols: int = 10) -> FakeWorksheet:
        ws = FakeWorksheet(title)
        self._worksheets[title] = ws
        return ws
