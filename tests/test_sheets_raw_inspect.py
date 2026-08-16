"""既存Google Sheets(タブ名がこちらの正規スキーマと異なる場合)を、
タブ名を前提とせず読み取り専用で調査する `sheets/inspector.py` の
raw inspection機能を検証する。

書き込みメソッド(add_worksheet/append_row/update)を呼んだら例外を送出する
Fakeを使い、実際に一切書き込みが行われないことも直接検証する。
"""

from __future__ import annotations

from rin_garden.sheets.client import SheetsClient
from rin_garden.sheets.inspector import inspect_raw_tab, inspect_spreadsheet_raw, list_all_tab_titles
from tests.fakes.fake_gspread import FakeSpreadsheet


def _existing_ledger() -> FakeSpreadsheet:
    """ユーザーが説明した既存台帳を模したFake(タブ名・列構成は例示であり、
    実際のシート内容ではない)。"""
    spreadsheet = FakeSpreadsheet(title="RIN_GARDEN_Keirin_Virtual_Ledger_v2.1")
    spreadsheet.seed_worksheet(
        "Race Ledger",
        rows=[
            ["日付", "会場", "R", "Race ID", "印", "買い目", "着順", "払戻"],
            ["2026-08-16", "松戸", "7", "KEIRIN-2026-08-16-abc", "◎", "1-2", "1-2-3", "280"],
            ["2026-08-16", "川崎", "9", "KEIRIN-2026-08-16-def", "◯", "3-4", "", ""],
            ["2026-08-17", "平塚", "1", "KEIRIN-2026-08-17-ghi", "▲", "5", "", ""],
        ],
    )
    spreadsheet.seed_worksheet(
        "FORCED-ALL",
        rows=[["Race ID", "買い目", "金額"], ["KEIRIN-2026-08-16-abc", "1-2", "1000"]],
    )
    spreadsheet.seed_worksheet("日別", rows=[["日付", "収支"], ["2026-08-16", "+1800"]])
    spreadsheet.seed_worksheet("Coverage", rows=[])  # 空タブ
    return spreadsheet


def test_list_all_tab_titles_is_agnostic_to_our_canonical_names(monkeypatch):
    spreadsheet = _existing_ledger()
    client = SheetsClient(fake_backend=lambda sheet_id: spreadsheet)
    monkeypatch.setenv("GOOGLE_SHEET_ID_KEIRIN", "fake-sheet-id")

    titles = list_all_tab_titles(spreadsheet)

    assert titles == ["Race Ledger", "FORCED-ALL", "日別", "Coverage"]
    # こちらの正規スキーマ名(RaceMaster/PRE/FINAL等)は一つも含まれない
    assert "RaceMaster" not in titles


def test_inspect_raw_tab_reads_headers_range_and_sample_without_full_dump():
    spreadsheet = _existing_ledger()

    tab = inspect_raw_tab(spreadsheet, "Race Ledger", sample_rows=2)

    assert tab is not None
    assert tab.header_row == ["日付", "会場", "R", "Race ID", "印", "買い目", "着順", "払戻"]
    assert tab.data_row_count == 3  # ヘッダーを除く実データ行数
    assert tab.sheet_col_count == 8
    assert len(tab.sample_rows) == 2  # sample_rows=2で全件はダンプしない
    assert tab.sample_rows[0][3] == "KEIRIN-2026-08-16-abc"


def test_inspect_raw_tab_handles_empty_tab_and_missing_tab():
    spreadsheet = _existing_ledger()

    empty = inspect_raw_tab(spreadsheet, "Coverage")
    assert empty is not None
    assert empty.header_row == []
    assert empty.data_row_count == 0

    missing = inspect_raw_tab(spreadsheet, "変更履歴")  # 今回のFakeには無いタブ
    assert missing is None


def test_inspect_spreadsheet_raw_reports_all_real_tabs(monkeypatch):
    spreadsheet = _existing_ledger()
    monkeypatch.setenv("GOOGLE_SHEET_ID_KEIRIN", "fake-sheet-id")
    client = SheetsClient(fake_backend=lambda sheet_id: spreadsheet)

    result = inspect_spreadsheet_raw(client, "keirin", sample_rows=1)

    assert result["connected"] is True
    assert result["spreadsheet_title"] == "RIN_GARDEN_Keirin_Virtual_Ledger_v2.1"
    assert set(result["tabs"].keys()) == {"Race Ledger", "FORCED-ALL", "日別", "Coverage"}
    assert result["tabs"]["Race Ledger"].data_row_count == 3


def test_inspect_spreadsheet_raw_is_strictly_read_only(monkeypatch):
    """add_worksheet/append_row/updateを呼んだら即エラーになるFakeで、
    raw inspectionが実際に一切書き込みを行わないことを直接検証する。"""
    spreadsheet = _existing_ledger()

    def _forbidden(*args, **kwargs):
        raise AssertionError("read-only inspection must never call a write method")

    monkeypatch.setattr(spreadsheet, "add_worksheet", _forbidden)
    for ws in spreadsheet.worksheets():
        monkeypatch.setattr(ws, "append_row", _forbidden)
        monkeypatch.setattr(ws, "update", _forbidden)

    monkeypatch.setenv("GOOGLE_SHEET_ID_KEIRIN", "fake-sheet-id")
    client = SheetsClient(fake_backend=lambda sheet_id: spreadsheet)

    before = {title: ws.get_all_values() for title, ws in spreadsheet._worksheets.items()}
    result = inspect_spreadsheet_raw(client, "keirin", sample_rows=5)
    after = {title: ws.get_all_values() for title, ws in spreadsheet._worksheets.items()}

    assert result["connected"] is True
    assert before == after  # 内容が一切変化していない


def test_inspect_spreadsheet_raw_reports_dry_run_and_missing_sheet_id_without_raising(monkeypatch):
    monkeypatch.delenv("GOOGLE_SHEET_ID_KEIRIN", raising=False)
    dry_client = SheetsClient()
    dry_result = inspect_spreadsheet_raw(dry_client, "keirin")
    assert dry_result["connected"] is False
    assert dry_result["tabs"] == {}

    monkeypatch.setenv("GOOGLE_SHEET_ID_KEIRIN", "fake-sheet-id")
    no_sheet_client = SheetsClient(fake_backend=lambda sheet_id: None)
    monkeypatch.delenv("GOOGLE_SHEET_ID_KEIRIN", raising=False)
    result = inspect_spreadsheet_raw(no_sheet_client, "keirin")
    assert result["connected"] is False
