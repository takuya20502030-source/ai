"""既存Google Sheetsの数式構造を読み取り専用(FORMULA表示)で調査する。

`value_render_option='FORMULA'` でセル内容を取得する(Sheets APIの
spreadsheets.values.get相当、GETのみでREAD ONLY)。これにより、通常の
`get_all_values()`では見えない「このセルは数式か、値そのものか」を区別できる。

書き込み系メソッド(update/append_row/clear/add_worksheet等)はこのモジュールの
どこからも一切呼び出さない。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from rin_garden.sheets.client import SheetsClient
from rin_garden.sheets.inspector import get_worksheet_or_none


def is_formula_cell(value: Any) -> bool:
    """セルの内容(FORMULA表示で取得した文字列)が数式かどうかを判定する。"""
    return isinstance(value, str) and value.startswith("=")


def column_letter(index: int) -> str:
    """0始まりの列indexをA1形式の列アルファベット(A, B, ..., Z, AA, ...)に変換する。"""
    letters = ""
    index += 1
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


@dataclass
class ColumnFormulaSummary:
    """1列分の数式/値セル集計。"""

    column_index: int  # 0始まり
    header: str
    formula_cell_count: int
    value_cell_count: int
    sample_formulas: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        return self.header or f"col{self.column_index + 1}({column_letter(self.column_index)})"

    @property
    def is_formula_column(self) -> bool:
        """このタブ内でこの列が数式主体かどうか(非空セルの過半数が数式なら数式列とみなす)。
        1件でも数式があれば書き込み候補からは除外すべきだが、列としての性格を
        判定するための目安としてこの閾値を用いる。
        """
        total = self.formula_cell_count + self.value_cell_count
        return total > 0 and self.formula_cell_count >= self.value_cell_count


@dataclass
class TabFormulaInspection:
    """1タブ分のFORMULA読み取り専用調査結果。"""

    title: str
    header_row_index: int | None
    header_row_values: list[str]
    total_data_rows: int
    total_cols: int
    total_formula_cells: int
    total_value_cells: int
    columns: list[ColumnFormulaSummary] = field(default_factory=list)
    sample_formulas: list[dict[str, str]] = field(default_factory=list)  # [{"cell": "M5", "formula": "=..."}]

    @property
    def has_any_formula(self) -> bool:
        return self.total_formula_cells > 0

    @property
    def columns_with_formulas(self) -> list[str]:
        """1件でも数式セルを含む列(=書き込み禁止候補)。"""
        return [c.label for c in self.columns if c.formula_cell_count > 0]

    @property
    def value_only_columns(self) -> list[str]:
        """数式セルを1件も含まず、値のみで構成される列(=書き込み候補)。"""
        return [
            c.label
            for c in self.columns
            if c.formula_cell_count == 0 and c.value_cell_count > 0
        ]


def inspect_tab_formulas(
    spreadsheet: Any,
    title: str,
    header_row_index: int | None = None,
    max_sample_formulas: int = 5,
) -> TabFormulaInspection | None:
    """1タブをFORMULA表示で読み取り専用調査する。

    header_row_index: ヘッダー行の0始まりインデックス。タブごとにバナー行等の
    深さが異なり自動推定は誤検出のリスクがあるため、呼び出し側が明示的に
    指定する(config/sheet_tab_layout.yaml 等)。未指定(None)の場合は
    列ヘッダー名を付けずに集計する(0行目からすべてデータ行として扱う)。

    タブが存在しなければNoneを返す。read系のget_values()以外は一切呼ばない。
    """
    worksheet = get_worksheet_or_none(spreadsheet, title)
    if worksheet is None:
        return None

    formula_grid: list[list[str]] = worksheet.get_values(value_render_option="FORMULA")
    if not formula_grid:
        return TabFormulaInspection(
            title=title,
            header_row_index=header_row_index,
            header_row_values=[],
            total_data_rows=0,
            total_cols=0,
            total_formula_cells=0,
            total_value_cells=0,
        )

    offset = header_row_index if header_row_index is not None else -1
    header_row_values = formula_grid[offset] if 0 <= offset < len(formula_grid) else []
    data_rows = formula_grid[offset + 1 :]

    max_cols = max((len(row) for row in formula_grid), default=0)
    columns: list[ColumnFormulaSummary] = []
    total_formula = 0
    total_value = 0
    sample_formulas: list[dict[str, str]] = []

    for col_idx in range(max_cols):
        header = header_row_values[col_idx] if col_idx < len(header_row_values) else ""
        formula_count = 0
        value_count = 0
        col_samples: list[str] = []
        for row_offset, row in enumerate(data_rows):
            cell = row[col_idx] if col_idx < len(row) else ""
            if cell == "":
                continue
            if is_formula_cell(cell):
                formula_count += 1
                if len(sample_formulas) < max_sample_formulas:
                    sheet_row_number = offset + 2 + row_offset  # 1始まりのシート実行番号
                    sample_formulas.append({"cell": f"{column_letter(col_idx)}{sheet_row_number}", "formula": cell})
                if len(col_samples) < 3:
                    col_samples.append(cell)
            else:
                value_count += 1
        total_formula += formula_count
        total_value += value_count
        columns.append(
            ColumnFormulaSummary(
                column_index=col_idx,
                header=header,
                formula_cell_count=formula_count,
                value_cell_count=value_count,
                sample_formulas=col_samples,
            )
        )

    return TabFormulaInspection(
        title=title,
        header_row_index=header_row_index,
        header_row_values=header_row_values,
        total_data_rows=len(data_rows),
        total_cols=max_cols,
        total_formula_cells=total_formula,
        total_value_cells=total_value,
        columns=columns,
        sample_formulas=sample_formulas,
    )


def inspect_spreadsheet_formulas(
    client: SheetsClient,
    sport: str,
    tab_titles: list[str],
    header_row_index_by_tab: dict[str, int] | None = None,
    max_sample_formulas: int = 5,
) -> dict[str, Any]:
    """指定したタブ一覧をFORMULA表示で読み取り専用調査する。

    書き込みは一切行わない。dry-run・Sheet ID未設定の場合は接続せず、
    その旨をmessageに記録して返す(処理は停止しない)。
    """
    header_row_index_by_tab = header_row_index_by_tab or {}

    sheet_id = client.sheet_id_for(sport)
    if client.dry_run:
        return {"connected": False, "message": "dry-run mode: no credentials configured", "tabs": {}}
    if not sheet_id:
        return {"connected": False, "message": f"no sheet id configured for sport={sport}", "tabs": {}}

    spreadsheet = client.open(sheet_id)
    if spreadsheet is None:
        return {"connected": False, "message": "client.open() returned no spreadsheet", "tabs": {}}

    tabs: dict[str, TabFormulaInspection | None] = {}
    for title in tab_titles:
        tabs[title] = inspect_tab_formulas(
            spreadsheet,
            title,
            header_row_index=header_row_index_by_tab.get(title),
            max_sample_formulas=max_sample_formulas,
        )

    return {
        "connected": True,
        "message": "",
        "spreadsheet_title": getattr(spreadsheet, "title", ""),
        "tabs": tabs,
    }
