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


def _get_worksheet(spreadsheet: Any, sheet_name: str) -> Any | None:
    try:
        return spreadsheet.worksheet(sheet_name)
    except Exception:  # noqa: BLE001 - gspread固有例外を「タブが存在しない」として扱う
        return None


def inspect_tab(spreadsheet: Any, sheet_name: str) -> SheetTabInspection:
    """1タブを読み取り専用で調査する。書き込みは一切行わない。"""
    worksheet = _get_worksheet(spreadsheet, sheet_name)
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
    """指定sportのスプレッドシートを読み取り専用で調査する。

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
