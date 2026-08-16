"""FORMULA READ ONLY調査(`sheets/formula_inspector.py`)の検証。

value_render_option='FORMULA' で取得したセル内容をもとに、数式セルと値セルを
区別できること、書き込み候補/禁止候補の分類が正しいこと、そして
update/append_row/clear/add_worksheet等の書き込み系メソッドが
一度も呼ばれないことを直接検証する。
"""

from __future__ import annotations

from rin_garden.sheets.client import SheetsClient
from rin_garden.sheets.formula_inspector import (
    column_letter,
    inspect_spreadsheet_formulas,
    inspect_tab_formulas,
    is_formula_cell,
)
from tests.fakes.fake_gspread import FakeSpreadsheet


def _ledger_with_formulas() -> FakeSpreadsheet:
    """Race Ledgerを模したFake。D列(Profit)とE列(ROI)だけが数式、他は値。
    (列構成・数式内容は例示であり、実際のシート内容ではない。)
    """
    spreadsheet = FakeSpreadsheet(title="RIN_GARDEN_Keirin_Virtual_Ledger_v2.1")
    spreadsheet.seed_worksheet(
        "Race Ledger",
        rows=[
            ["banner", "", "", "", ""],
            ["", "", "", "", ""],
            ["note", "", "", "", ""],
            ["Race ID", "Account", "Stake", "Profit", "ROI"],
            ["V-1", "FORCED-ALL", "1000", "=D5", "=E5/C5"],  # 見せかけの数式(row_idx=4)
            ["V-2", "SELECT-B+", "1000", "=D6", "=E6/C6"],
        ],
        formulas={
            (4, 3): "=SUM(C5)",  # Profit列(D列, col_idx=3)
            (4, 4): "=D5/C5",  # ROI列(E列, col_idx=4)
            (5, 3): "=SUM(C6)",
            (5, 4): "=D6/C6",
        },
    )
    spreadsheet.seed_worksheet(
        "Tickets",
        rows=[
            ["banner"],
            [""],
            ["Ticket ID", "Race ID", "Stake"],
            ["T-1", "V-1", "1000"],
        ],
    )
    return spreadsheet


# --- 基本ユーティリティ ---


def test_is_formula_cell_detects_leading_equals():
    assert is_formula_cell("=SUM(A1:A2)") is True
    assert is_formula_cell("1000") is False
    assert is_formula_cell("") is False
    assert is_formula_cell(None) is False


def test_column_letter_conversion():
    assert column_letter(0) == "A"
    assert column_letter(25) == "Z"
    assert column_letter(26) == "AA"


# --- 1タブ調査 ---


def test_inspect_tab_formulas_separates_formula_and_value_columns():
    spreadsheet = _ledger_with_formulas()

    tab = inspect_tab_formulas(spreadsheet, "Race Ledger", header_row_index=3, max_sample_formulas=5)

    assert tab is not None
    assert tab.header_row_values == ["Race ID", "Account", "Stake", "Profit", "ROI"]
    assert tab.total_data_rows == 2
    assert tab.total_formula_cells == 4  # Profit x2 + ROI x2
    assert tab.total_value_cells == 6  # Race ID/Account/Stake x2

    assert set(tab.columns_with_formulas) == {"Profit", "ROI"}
    assert set(tab.value_only_columns) == {"Race ID", "Account", "Stake"}
    assert tab.has_any_formula is True


def test_inspect_tab_formulas_sample_formulas_include_cell_reference():
    spreadsheet = _ledger_with_formulas()
    tab = inspect_tab_formulas(spreadsheet, "Race Ledger", header_row_index=3, max_sample_formulas=2)

    assert tab is not None
    assert len(tab.sample_formulas) == 2
    for sample in tab.sample_formulas:
        assert sample["formula"].startswith("=")
        assert sample["cell"][0].isalpha()  # 列アルファベットを含む(例: "D5")


def test_inspect_tab_formulas_tab_without_formulas_is_write_candidate():
    spreadsheet = _ledger_with_formulas()
    tab = inspect_tab_formulas(spreadsheet, "Tickets", header_row_index=2, max_sample_formulas=5)

    assert tab is not None
    assert tab.total_formula_cells == 0
    assert tab.has_any_formula is False
    assert tab.columns_with_formulas == []
    assert set(tab.value_only_columns) == {"Ticket ID", "Race ID", "Stake"}


def test_inspect_tab_formulas_missing_tab_returns_none():
    spreadsheet = _ledger_with_formulas()
    assert inspect_tab_formulas(spreadsheet, "Nonexistent Tab") is None


def test_inspect_tab_formulas_without_header_row_index_still_counts_cells():
    spreadsheet = _ledger_with_formulas()
    tab = inspect_tab_formulas(spreadsheet, "Race Ledger", header_row_index=None)

    assert tab is not None
    assert tab.header_row_values == []
    # header_row_index未指定なので、バナー行や空行もすべて「データ行」として数える
    assert tab.total_data_rows == 6


# --- スプレッドシート全体調査 ---


def test_inspect_spreadsheet_formulas_reports_multiple_tabs(monkeypatch):
    spreadsheet = _ledger_with_formulas()
    monkeypatch.setenv("GOOGLE_SHEET_ID_KEIRIN", "fake-sheet-id")
    client = SheetsClient(fake_backend=lambda sheet_id: spreadsheet)

    result = inspect_spreadsheet_formulas(
        client,
        "keirin",
        tab_titles=["Race Ledger", "Tickets"],
        header_row_index_by_tab={"Race Ledger": 3, "Tickets": 2},
    )

    assert result["connected"] is True
    assert result["tabs"]["Race Ledger"].has_any_formula is True
    assert result["tabs"]["Tickets"].has_any_formula is False


def test_inspect_spreadsheet_formulas_dry_run_and_missing_sheet_id_do_not_raise(monkeypatch):
    monkeypatch.delenv("GOOGLE_SHEET_ID_KEIRIN", raising=False)
    dry_client = SheetsClient()
    result = inspect_spreadsheet_formulas(dry_client, "keirin", tab_titles=["Race Ledger"])
    assert result["connected"] is False
    assert result["tabs"] == {}


# --- 厳格なREAD ONLY保証: 書き込み系メソッドが1回でも呼ばれたら失敗する ---


def test_inspect_spreadsheet_formulas_never_calls_any_write_method(monkeypatch):
    spreadsheet = _ledger_with_formulas()

    def _forbidden(*args, **kwargs):
        raise AssertionError("FORMULA read-only inspection must never call a write method")

    monkeypatch.setattr(spreadsheet, "add_worksheet", _forbidden)
    for ws in spreadsheet.worksheets():
        monkeypatch.setattr(ws, "append_row", _forbidden)
        monkeypatch.setattr(ws, "update", _forbidden)
        monkeypatch.setattr(ws, "clear", _forbidden)

    monkeypatch.setenv("GOOGLE_SHEET_ID_KEIRIN", "fake-sheet-id")
    client = SheetsClient(fake_backend=lambda sheet_id: spreadsheet)

    before = {title: (ws.get_all_values(), dict(ws.formulas)) for title, ws in spreadsheet._worksheets.items()}
    result = inspect_spreadsheet_formulas(
        client,
        "keirin",
        tab_titles=["Race Ledger", "Tickets"],
        header_row_index_by_tab={"Race Ledger": 3, "Tickets": 2},
    )
    after = {title: (ws.get_all_values(), dict(ws.formulas)) for title, ws in spreadsheet._worksheets.items()}

    assert result["connected"] is True
    assert before == after  # 内容が一切変化していない
