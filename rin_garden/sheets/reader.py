"""Google Sheetsからの読み込み処理。dry-runモードでは常に空の結果を返す。"""

from __future__ import annotations

from typing import Any

from rin_garden.sheets.client import SheetsClient
from rin_garden.sheets.schemas import RACE_MASTER_SHEET


def read_sheet_rows(client: SheetsClient, sport: str, sheet_name: str) -> list[dict[str, Any]]:
    """指定シートの全行をヘッダー付きdictのリストとして返す。dry-runでは[]。"""
    sheet_id = client.sheet_id_for(sport)
    if client.dry_run or not sheet_id:
        return []
    spreadsheet = client.open(sheet_id)
    try:
        worksheet = spreadsheet.worksheet(sheet_name)
    except Exception:  # noqa: BLE001
        return []
    return worksheet.get_all_records()


def find_row_by_race_id(client: SheetsClient, sport: str, sheet_name: str, race_id: str) -> dict[str, Any] | None:
    for row in read_sheet_rows(client, sport, sheet_name):
        if str(row.get("race_id")) == race_id:
            return row
    return None


def race_master_exists(client: SheetsClient, sport: str, race_id: str) -> bool:
    return find_row_by_race_id(client, sport, RACE_MASTER_SHEET, race_id) is not None
