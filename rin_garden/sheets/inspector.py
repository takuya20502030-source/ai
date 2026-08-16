"""既存Google Sheetsの構造を読み取り専用で調査する。

書き込み(`sheets/writer.py`)を行う前に必ずこのモジュールで既存シートの
タブ名・ヘッダー・既存Race IDを確認し、Mapping層(`sheets/mapping.py`)で
差異を吸収すること。ここに定義する関数は一切書き込みを行わない。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from rin_garden.sheets.client import SheetsClient
from rin_garden.sheets.schemas import (
    DAILY_SUMMARY_SHEET,
    FINAL_SHEET,
    PRE_SHEET,
    RACE_MASTER_SHEET,
    RESULT_SHEET,
    SETTLEMENT_SHEET,
)

KNOWN_SHEETS = (RACE_MASTER_SHEET, PRE_SHEET, FINAL_SHEET, RESULT_SHEET, SETTLEMENT_SHEET, DAILY_SUMMARY_SHEET)


@dataclass
class SheetTabInspection:
    """1タブ分の読み取り専用調査結果。"""

    exists: bool
    headers: list[str] = field(default_factory=list)
    row_count: int = 0
    race_ids: list[str] = field(default_factory=list)


@dataclass
class SpreadsheetInspection:
    """スプレッドシート全体の読み取り専用調査結果。"""

    sport: str
    connected: bool
    tabs: dict[str, SheetTabInspection] = field(default_factory=dict)
    message: str = ""


def get_worksheet_or_none(spreadsheet: Any, sheet_name: str) -> Any | None:
    try:
        return spreadsheet.worksheet(sheet_name)
    except Exception:  # noqa: BLE001 - gspread固有例外を「タブが存在しない」として扱う
        return None


def inspect_tab(spreadsheet: Any, sheet_name: str) -> SheetTabInspection:
    """1タブを読み取り専用で調査する。書き込みは一切行わない。"""
    worksheet = get_worksheet_or_none(spreadsheet, sheet_name)
    if worksheet is None:
        return SheetTabInspection(exists=False)

    all_values = worksheet.get_all_values()
    if not all_values:
        return SheetTabInspection(exists=True, headers=[], row_count=0, race_ids=[])

    headers = all_values[0]
    data_rows = all_values[1:]
    race_ids: list[str] = []
    if "race_id" in headers:
        idx = headers.index("race_id")
        race_ids = [row[idx] for row in data_rows if len(row) > idx and row[idx]]

    return SheetTabInspection(exists=True, headers=headers, row_count=len(data_rows), race_ids=race_ids)


def inspect_spreadsheet(client: SheetsClient, sport: str) -> SpreadsheetInspection:
    """指定sportのスプレッドシートを、こちらの正規タブ名(KNOWN_SHEETS)前提で
    読み取り専用調査する。

    既存の台帳が正規タブ名と異なる構成(例: 「Race Ledger」等の独自タブ名)を
    使っている場合、そのタブはここでは検出できない(全てexists=Falseになる)。
    タブ名を問わずスプレッドシート全体を調査したい場合は
    `inspect_spreadsheet_raw()` を使うこと。

    dry-run・Sheet ID未設定の場合は接続せず、その旨をmessageに記録して返す
    (処理は停止しない)。
    """
    sheet_id = client.sheet_id_for(sport)
    if client.dry_run:
        return SpreadsheetInspection(sport=sport, connected=False, message="dry-run mode: no credentials configured")
    if not sheet_id:
        return SpreadsheetInspection(sport=sport, connected=False, message=f"no sheet id configured for sport={sport}")

    spreadsheet = client.open(sheet_id)
    if spreadsheet is None:
        return SpreadsheetInspection(sport=sport, connected=False, message="client.open() returned no spreadsheet")

    tabs = {name: inspect_tab(spreadsheet, name) for name in KNOWN_SHEETS}
    return SpreadsheetInspection(sport=sport, connected=True, tabs=tabs, message="")


# --- タブ名を固定しない生の読み取り専用調査(既存Sheetの実際の構成を調べる用) ---


@dataclass
class RawTabInspection:
    """タブ名を問わず、実際のタブをそのまま読み取り専用で調査した結果。

    全データはダンプしない(sample_rowsのみ、既定3行)。書き込みは一切行わない。
    """

    title: str
    header_row: list[str]
    data_row_count: int
    sheet_col_count: int
    sample_rows: list[list[str]] = field(default_factory=list)


def list_all_tab_titles(spreadsheet: Any) -> list[str]:
    """スプレッドシート内の全タブ名を、実際のタブ順のまま読み取り専用で取得する。"""
    return [ws.title for ws in spreadsheet.worksheets()]


def inspect_raw_tab(spreadsheet: Any, title: str, sample_rows: int = 3) -> RawTabInspection | None:
    """タブ名を正規化・前提とせず、実際のヘッダー行・使用範囲・先頭数行のみを読む。

    タブが存在しなければNoneを返す。既存の値・列・行を一切変更しない。
    """
    worksheet = get_worksheet_or_none(spreadsheet, title)
    if worksheet is None:
        return None

    all_values = worksheet.get_all_values()
    header_row = all_values[0] if all_values else []
    data_rows = all_values[1:] if len(all_values) > 1 else []

    return RawTabInspection(
        title=title,
        header_row=header_row,
        data_row_count=len(data_rows),
        sheet_col_count=worksheet.col_count,
        sample_rows=data_rows[:sample_rows],
    )


def inspect_spreadsheet_raw(client: SheetsClient, sport: str, sample_rows: int = 3) -> dict[str, Any]:
    """タブ名を固定せず、スプレッドシート全体をそのまま読み取り専用で調査する。

    戻り値: {"connected": bool, "message": str, "spreadsheet_title": str,
             "tabs": {タブ名: RawTabInspection}}
    """
    sheet_id = client.sheet_id_for(sport)
    if client.dry_run:
        return {"connected": False, "message": "dry-run mode: no credentials configured", "tabs": {}}
    if not sheet_id:
        return {"connected": False, "message": f"no sheet id configured for sport={sport}", "tabs": {}}

    spreadsheet = client.open(sheet_id)
    if spreadsheet is None:
        return {"connected": False, "message": "client.open() returned no spreadsheet", "tabs": {}}

    titles = list_all_tab_titles(spreadsheet)
    tabs = {title: inspect_raw_tab(spreadsheet, title, sample_rows=sample_rows) for title in titles}
    return {
        "connected": True,
        "message": "",
        "spreadsheet_title": getattr(spreadsheet, "title", ""),
        "tabs": tabs,
    }
