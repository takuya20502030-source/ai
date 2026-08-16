"""Google Sheetsへの書き込み処理。責務ごとに関数を分離する。

save_race_master() / save_pre_fix() / save_final_lock() / save_result() /
settle_race() / update_daily_summary()

書き込み前に必ずRace Identity(date/sport/venue/race_number/race_id/event_id)を
検証し、矛盾があれば書き込みを拒否する。既存PREセルへの結果後上書きも禁止する。
dry-runモード(認証情報未設定時)では実書き込みを行わず、ログのみ残す。
"""

from __future__ import annotations

from typing import Any

from rin_garden.core.identity import IdentityMismatchError, verify_identity
from rin_garden.core.logging import AuditLogger, OP_IDENTITY_MISMATCH, OP_WRITE_FAILED
from rin_garden.core.race_master import RaceMaster, RaceStatus
from rin_garden.sheets.client import SheetsClient
from rin_garden.sheets.schemas import (
    DAILY_SUMMARY_HEADERS,
    DAILY_SUMMARY_SHEET,
    FINAL_HEADERS,
    FINAL_SHEET,
    PRE_HEADERS,
    PRE_SHEET,
    RACE_MASTER_HEADERS,
    RACE_MASTER_SHEET,
    RESULT_HEADERS,
    RESULT_SHEET,
    SETTLEMENT_HEADERS,
    SETTLEMENT_SHEET,
)


class SheetsWriteRejectedError(Exception):
    """Identity検証失敗・結果後PRE上書き等、書き込みを拒否した場合に送出する。"""


def _upsert_row(client: SheetsClient, sport: str, sheet_name: str, headers: list[str], key: str, row: dict[str, Any]) -> str:
    """1行をupsertする。dry-runの場合は実書き込みを行わずステータス文字列を返す。"""
    sheet_id = client.sheet_id_for(sport)
    if client.dry_run or not sheet_id:
        return "DRY_RUN"

    spreadsheet = client.open(sheet_id)
    try:
        worksheet = spreadsheet.worksheet(sheet_name)
    except Exception:  # noqa: BLE001 - gspread固有例外を薄く握りつぶし、シート未作成として扱う
        worksheet = spreadsheet.add_worksheet(title=sheet_name, rows=1000, cols=len(headers))
        worksheet.append_row(headers)

    values = [str(row.get(h, "")) for h in headers]
    key_col = headers.index(key) + 1
    existing_cells = worksheet.col_values(key_col)
    row_key_value = str(row.get(key, ""))
    if row_key_value in existing_cells:
        row_number = existing_cells.index(row_key_value) + 1
        worksheet.update(f"A{row_number}", [values])
    else:
        worksheet.append_row(values)
    return "WRITTEN"


def _validate_or_raise(
    expected: dict[str, Any], candidate: dict[str, Any], audit_logger: AuditLogger, sport: str, race_id: str, source: str
) -> None:
    try:
        verify_identity(expected, candidate)
    except IdentityMismatchError as exc:
        audit_logger.log(OP_IDENTITY_MISMATCH, sport, race_id, "REJECTED", source, str(exc))
        raise


def save_race_master(client: SheetsClient, audit_logger: AuditLogger, race_master: RaceMaster) -> str:
    row = race_master.to_dict()
    return _upsert_row(client, race_master.sport, RACE_MASTER_SHEET, RACE_MASTER_HEADERS, "race_id", row)


def save_pre_fix(client: SheetsClient, audit_logger: AuditLogger, race_master: RaceMaster, pre: dict[str, Any]) -> str:
    _validate_or_raise(race_master.identity(), {"race_id": pre.get("race_id")}, audit_logger, race_master.sport, race_master.race_id, "sheets.save_pre_fix")

    if race_master.status in (RaceStatus.RESULT_LOCKED, RaceStatus.SETTLED, RaceStatus.AUDITED):
        audit_logger.log(
            OP_WRITE_FAILED,
            race_master.sport,
            race_master.race_id,
            "REJECTED",
            "sheets.save_pre_fix",
            "refusing to write/overwrite PRE after result is known",
        )
        raise SheetsWriteRejectedError(
            f"race_id={race_master.race_id} already has a result; PRE cannot be written after the fact"
        )

    return _upsert_row(client, race_master.sport, PRE_SHEET, PRE_HEADERS, "race_id", pre)


def save_final_lock(client: SheetsClient, audit_logger: AuditLogger, race_master: RaceMaster, final: dict[str, Any]) -> str:
    _validate_or_raise(race_master.identity(), {"race_id": final.get("race_id")}, audit_logger, race_master.sport, race_master.race_id, "sheets.save_final_lock")
    row = {**final, "revision_count": len(final.get("revisions", []))}
    return _upsert_row(client, race_master.sport, FINAL_SHEET, FINAL_HEADERS, "race_id", row)


def save_result(client: SheetsClient, audit_logger: AuditLogger, race_master: RaceMaster, result: dict[str, Any]) -> str:
    _validate_or_raise(race_master.identity(), {"race_id": result.get("race_id")}, audit_logger, race_master.sport, race_master.race_id, "sheets.save_result")
    return _upsert_row(client, race_master.sport, RESULT_SHEET, RESULT_HEADERS, "race_id", result)


def settle_race(client: SheetsClient, audit_logger: AuditLogger, race_master: RaceMaster, settlement: dict[str, Any]) -> str:
    _validate_or_raise(race_master.identity(), {"race_id": settlement.get("race_id")}, audit_logger, race_master.sport, race_master.race_id, "sheets.settle_race")
    return _upsert_row(client, race_master.sport, SETTLEMENT_SHEET, SETTLEMENT_HEADERS, "race_id", settlement)


def update_daily_summary(client: SheetsClient, audit_logger: AuditLogger, sport: str, date: str, summary: dict[str, Any]) -> str:
    row = {"date": date, "sport": sport, **summary}
    key_row = {**row}
    key_row.setdefault("date", date)
    sheet_id = client.sheet_id_for(sport)
    if client.dry_run or not sheet_id:
        return "DRY_RUN"
    spreadsheet = client.open(sheet_id)
    try:
        worksheet = spreadsheet.worksheet(DAILY_SUMMARY_SHEET)
    except Exception:  # noqa: BLE001
        worksheet = spreadsheet.add_worksheet(title=DAILY_SUMMARY_SHEET, rows=1000, cols=len(DAILY_SUMMARY_HEADERS))
        worksheet.append_row(DAILY_SUMMARY_HEADERS)
    values = [str(row.get(h, "")) for h in DAILY_SUMMARY_HEADERS]
    worksheet.append_row(values)
    return "WRITTEN"
