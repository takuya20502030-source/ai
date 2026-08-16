"""Google Sheets: 接続状態レポート・読み取り専用調査・Mapping・書き込みの検証。

実際のgspreadやネットワークは使わず、tests/fakes/fake_gspread.py のインメモリ
実装を SheetsClient(fake_backend=...) に注入して検証する。
"""

from __future__ import annotations

import pytest

from rin_garden.core.logging import AuditLogger
from rin_garden.core.race_master import RaceMaster, RaceStatus
from rin_garden.sheets.client import SheetsClient
from rin_garden.sheets.inspector import inspect_spreadsheet, inspect_tab
from rin_garden.sheets.mapping import build_mapping
from rin_garden.sheets.schemas import PRE_HEADERS, PRE_SHEET, RACE_MASTER_HEADERS, RACE_MASTER_SHEET
from rin_garden.sheets.writer import SheetsWriteRejectedError, save_pre_fix, save_race_master
from tests.fakes.fake_gspread import FakeSpreadsheet


def _race_master(status: str = RaceStatus.SCHEDULED) -> RaceMaster:
    return RaceMaster(
        sport="keirin",
        date="2026-08-16",
        venue="matsudo",
        race_number=1,
        race_id="KEIRIN-2026-08-16-abc123",
        event_id="evt-1",
        canonical_source="test-fixture",
        scheduled_start="2026-08-16T23:00:00+00:00",
        status=status,
    )


# --- 接続状態レポート(処理を止めずに不足項目を報告する) ---


def test_status_reports_missing_credentials_without_raising(monkeypatch):
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    for env_var in ("GOOGLE_SHEET_ID_JRA", "GOOGLE_SHEET_ID_NAR", "GOOGLE_SHEET_ID_BOAT", "GOOGLE_SHEET_ID_KEIRIN"):
        monkeypatch.delenv(env_var, raising=False)

    client = SheetsClient()
    status = client.status()

    assert client.dry_run is True
    missing = status.missing_items()
    assert any("GOOGLE_APPLICATION_CREDENTIALS" in m for m in missing)
    assert any("GOOGLE_SHEET_ID_KEIRIN" in m for m in missing)


# --- Mapping層 ---


def test_build_mapping_exact_and_case_insensitive_and_unmapped():
    canonical = ["race_id", "timestamp", "rank", "chaos"]
    actual = ["Race_ID", "note", "rank"]  # timestampもchaosも既存シートに無い想定

    mapping = build_mapping(canonical, actual)

    assert mapping.canonical_to_index["race_id"] == 0  # 大小無視で一致
    assert mapping.canonical_to_index["rank"] == 2
    assert set(mapping.unmapped_fields) == {"timestamp", "chaos"}
    assert mapping.extra_actual_headers == ["note"]


def test_mapping_row_from_places_values_at_existing_columns_only():
    canonical = ["race_id", "rank"]
    actual = ["note", "rank", "race_id"]
    mapping = build_mapping(canonical, actual)

    row = mapping.row_from({"race_id": "R1", "rank": "A"})

    assert row == ["", "A", "R1"]


# --- 読み取り専用調査 ---


def test_inspect_tab_missing_tab_reports_not_exists():
    spreadsheet = FakeSpreadsheet()
    result = inspect_tab(spreadsheet, RACE_MASTER_SHEET)
    assert result.exists is False


def test_inspect_tab_reads_headers_and_race_ids_without_writing():
    spreadsheet = FakeSpreadsheet()
    spreadsheet.seed_worksheet(
        RACE_MASTER_SHEET,
        rows=[
            ["race_id", "venue"],
            ["KEIRIN-2026-08-16-abc123", "matsudo"],
            ["KEIRIN-2026-08-16-def456", "kawasaki"],
        ],
    )

    result = inspect_tab(spreadsheet, RACE_MASTER_SHEET)

    assert result.exists is True
    assert result.headers == ["race_id", "venue"]
    assert result.race_ids == ["KEIRIN-2026-08-16-abc123", "KEIRIN-2026-08-16-def456"]
    # 読み取り専用: 内容が変化していないこと
    assert spreadsheet.worksheet(RACE_MASTER_SHEET).get_all_values()[0] == ["race_id", "venue"]


def test_inspect_spreadsheet_without_sheet_id_does_not_connect(monkeypatch):
    monkeypatch.delenv("GOOGLE_SHEET_ID_KEIRIN", raising=False)
    client = SheetsClient(dry_run=False, fake_backend=lambda sheet_id: FakeSpreadsheet())
    # sheet_id_forがNoneを返す限り、fake_backendでも接続扱いにならない
    result = inspect_spreadsheet(client, "keirin")
    assert result.connected is False


# --- 書き込み(既存タブが無い場合は新規作成、既存タブがあればMappingを尊重) ---


def test_save_race_master_creates_new_tab_when_absent(monkeypatch, tmp_path):
    monkeypatch.setenv("GOOGLE_SHEET_ID_KEIRIN", "fake-sheet-id")
    spreadsheet = FakeSpreadsheet()
    client = SheetsClient(fake_backend=lambda sheet_id: spreadsheet)
    audit_logger = AuditLogger(tmp_path / "audit.log")
    rm = _race_master()

    result = save_race_master(client, audit_logger, rm)

    assert result == "WRITTEN"
    ws = spreadsheet.worksheet(RACE_MASTER_SHEET)
    assert ws.get_all_values()[0] == RACE_MASTER_HEADERS
    assert ws.get_all_values()[1][RACE_MASTER_HEADERS.index("race_id")] == rm.race_id


def test_save_race_master_upserts_existing_row_in_place(monkeypatch, tmp_path):
    monkeypatch.setenv("GOOGLE_SHEET_ID_KEIRIN", "fake-sheet-id")
    spreadsheet = FakeSpreadsheet()
    client = SheetsClient(fake_backend=lambda sheet_id: spreadsheet)
    audit_logger = AuditLogger(tmp_path / "audit.log")
    rm = _race_master()

    save_race_master(client, audit_logger, rm)
    rm.status = RaceStatus.PRE_FIXED
    save_race_master(client, audit_logger, rm)

    ws = spreadsheet.worksheet(RACE_MASTER_SHEET)
    data_rows = ws.get_all_values()[1:]
    assert len(data_rows) == 1  # 追記ではなくupsertされていること
    assert data_rows[0][RACE_MASTER_HEADERS.index("status")] == "PRE_FIXED"


def test_write_respects_existing_sheet_structure_and_does_not_alter_it(monkeypatch, tmp_path):
    """既存シートの列構成・既存行は変更・並び替えしない。無いフィールドはスキップしてログする。"""
    monkeypatch.setenv("GOOGLE_SHEET_ID_KEIRIN", "fake-sheet-id")
    spreadsheet = FakeSpreadsheet()
    # 既存シートは列順が違い、canonical_sourceが存在しない(実運用でありうる差異)
    existing_headers = ["status", "race_id", "venue"]
    spreadsheet.seed_worksheet(
        RACE_MASTER_SHEET,
        rows=[existing_headers, ["SCHEDULED", "KEIRIN-2026-08-16-zzz999", "someplace"]],
    )
    client = SheetsClient(fake_backend=lambda sheet_id: spreadsheet)
    audit_logger = AuditLogger(tmp_path / "audit.log")
    rm = _race_master()

    result = save_race_master(client, audit_logger, rm)

    assert result == "WRITTEN"
    ws = spreadsheet.worksheet(RACE_MASTER_SHEET)
    all_values = ws.get_all_values()
    assert all_values[0] == existing_headers  # ヘッダーは変更されない
    assert len(all_values) == 3  # 既存行(zzz999)は残り、新しい行が追加される
    assert all_values[1] == ["SCHEDULED", "KEIRIN-2026-08-16-zzz999", "someplace"]
    new_row = all_values[2]
    assert new_row[existing_headers.index("race_id")] == rm.race_id
    assert new_row[existing_headers.index("venue")] == rm.venue

    ops = [e["operation"] for e in audit_logger.read_all()]
    assert "DATA_INCOMPLETE" in ops  # canonical_source等、対応列が無いフィールドを報告している


def test_write_rejects_when_key_column_missing_from_existing_sheet(monkeypatch, tmp_path):
    monkeypatch.setenv("GOOGLE_SHEET_ID_KEIRIN", "fake-sheet-id")
    spreadsheet = FakeSpreadsheet()
    spreadsheet.seed_worksheet(RACE_MASTER_SHEET, rows=[["venue", "status"]])  # race_id列が無い
    client = SheetsClient(fake_backend=lambda sheet_id: spreadsheet)
    audit_logger = AuditLogger(tmp_path / "audit.log")
    rm = _race_master()

    with pytest.raises(SheetsWriteRejectedError):
        save_race_master(client, audit_logger, rm)

    ws = spreadsheet.worksheet(RACE_MASTER_SHEET)
    assert len(ws.get_all_values()) == 1  # 何も書き込まれていない
    ops = [e["operation"] for e in audit_logger.read_all()]
    assert "WRITE_FAILED" in ops


def test_save_pre_fix_refuses_after_result_known(monkeypatch, tmp_path):
    monkeypatch.setenv("GOOGLE_SHEET_ID_KEIRIN", "fake-sheet-id")
    spreadsheet = FakeSpreadsheet()
    client = SheetsClient(fake_backend=lambda sheet_id: spreadsheet)
    audit_logger = AuditLogger(tmp_path / "audit.log")
    rm = _race_master(status=RaceStatus.SETTLED)

    pre = {"race_id": rm.race_id, "timestamp": "2026-08-16T10:00:00+00:00"}
    with pytest.raises(SheetsWriteRejectedError):
        save_pre_fix(client, audit_logger, rm, pre)

    assert PRE_SHEET not in spreadsheet._worksheets  # 何もタブを作っていない
