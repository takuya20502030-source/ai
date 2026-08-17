"""Google Sheets Safe Writer(Adapter)の検証。

RIN GARDEN Google Sheets正本はv3.0へ全面移行し、v2.1(RIN_GARDEN_Keirin_
Virtual_Ledger_v2.1)はARCHIVE ONLYとなった。ここでは
`config/sheet_write_policy.yaml` / `config/sheet_tab_layout.yaml` の
"keirin_v2_1_archive" セクション(=旧v2.1の実タブ構成に基づく設定、ARCHIVE
ONLY)を、Adapterの一般的な安全機構(whitelist/read-only/header照合/
Race Identity/NO POST-HOC)を検証するための固定フィクスチャとして読み込む。
これはv2.1への書き込みを許可するものではない(v2.1は常にARCHIVE ONLYであり、
実行時のsport識別子が現行の"keirin"=v3.0とは異なるため、そもそも
policy_registry.get()で見つからない)。実際のGoogle Sheetsへは一切
接続・書き込みしない。

特に以下を重点的に検証する:
- 数式列(Profit/ROI/Hit等)へ書こうとすると必ず失敗する
- READ ONLYタブ(FORCED-ALL等)への書き込みは必ず失敗する
- ヘッダー位置が違う/該当列が見つからない場合は必ず失敗する
- Race IDが違えば必ず失敗する
- いずれの失敗もシート内容を一切変化させない(部分的に書いて失敗、が起きない)
- v2.1のMappingが現行の"keirin"(v3.0)へ誤って適用されないこと
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from rin_garden.core.identity import IdentityMismatchError
from rin_garden.core.locks import PostHocBlockedError
from rin_garden.core.logging import AuditLogger
from rin_garden.core.race_master import RaceMaster, RaceStatus
from rin_garden.core.timeutil import to_iso, utcnow
from rin_garden.sheets.adapter import (
    AppendOnlyViolationError,
    ColumnNotWhitelistedError,
    HeaderMismatchError,
    ReadOnlyTabError,
    SheetWriteAdapter,
    UnknownTabError,
    WritePolicyRegistry,
    load_header_row_index_map,
)
from rin_garden.core.config import PROJECT_ROOT
from tests.fakes.fake_gspread import FakeSpreadsheet

WRITE_POLICY_PATH = PROJECT_ROOT / "config" / "sheet_write_policy.yaml"
TAB_LAYOUT_PATH = PROJECT_ROOT / "config" / "sheet_tab_layout.yaml"
ARCHIVE_SPORT_KEY = "keirin_v2_1_archive"


def _race_master(**overrides) -> RaceMaster:
    base = dict(
        sport="keirin",
        date="2026-08-16",
        venue="matsudo",
        race_number=7,
        race_id="V-20260816-matsudo-7",
        event_id="evt-1",
        canonical_source="test-fixture",
        scheduled_start=to_iso(utcnow() + timedelta(minutes=60)),
        status=RaceStatus.PRE_FIXED,
    )
    base.update(overrides)
    return RaceMaster(**base)


def _ledger_spreadsheet() -> FakeSpreadsheet:
    """実際のヘッダー構成(前段のREAD ONLY調査結果)を模したFake。"""
    spreadsheet = FakeSpreadsheet(title="RIN_GARDEN_Keirin_Virtual_Ledger_v2.1")

    spreadsheet.seed_worksheet(
        "Race Log",
        rows=[
            ["Race Log | One row per race / 締切前固定"],
            [],
            [
                "Race ID", "Date", "Venue", "R", "Class", "Cutoff JST", "Lock JST", "Validation", "Version",
                "Lines", "Scenario", "Grade", "Forced", "Selective", "1st", "2nd", "3rd", "4th", "Result",
                "Result URL", "Notes", "Entry URL",
            ],
        ],
    )

    race_ledger_headers = [
        "Race ID", "Date / 開催日", "Venue / 会場", "R", "Class / クラス", "Cutoff JST / 締切",
        "Account / 口座", "Validation / 検証", "Grade / 評価", "Lines / ライン", "Scenario / 想定展開",
        "Bet Type / 券種", "Selections / 買い目・金額・取得オッズ", "Stake / 投資額", "Return / 払戻",
        "Profit / 利益", "ROI", "Finish / 結果", "Status / 状態", "Lock JST / 固定時刻",
        "Info JST / 情報取得時刻", "Source URL / 根拠URL", "Result URL / 結果URL", "Review / 反省・理由",
        "Hit / 的中", "Settled # / 確定順", "Block / ブロック", "Odds Band / オッズ帯",
        "Line Type / ライン型", "Version", "Structure Tags / 構造タグ", "Main Scenario / 本線",
        "Reverse Scenario / 逆転", "Collapse Scenario / 本線崩壊", "Chosen Scenario / 採用",
        "Rejected Reasons / 不採用理由", "Low Grade Reason / 低評価理由", "Best of Weak / 最もマシ",
        "Max Weakness / 最大弱点", "Odds/Popularity / 人気帯", "Pre-Race Quality / 品質状態",
        "Fingerprint / 重複監査", "Module Adopted JST / 導入時刻",
    ]
    spreadsheet.seed_worksheet(
        "Race Ledger",
        rows=[
            ["Race Ledger｜競輪RIN GARDEN v2.1"],
            [],
            ["締切前固定のみ。"],
            race_ledger_headers,
        ],
        formulas={
            (4, race_ledger_headers.index("Profit / 利益")): "=O5-N5",
            (4, race_ledger_headers.index("ROI")): "=P5/N5",
            (4, race_ledger_headers.index("Hit / 的中")): "=IF(R5=\"WIN\",1,0)",
        },
    )

    spreadsheet.seed_worksheet(
        "FORCED-ALL",
        rows=[["FORCED-ALL"], [], ["note"], ["Race ID", "Account / 口座"], ["V-1", "FORCED-ALL"]],
    )

    spreadsheet.seed_worksheet(
        "変更履歴",
        rows=[
            ["変更履歴"],
            [],
            ["台帳構造・検証ルールを監査可能に保持。"],
            ["Time JST / 時刻", "Version / 版", "Change / 変更種別", "Detail / 内容", "Reason / 理由", "Block Impact / ブロック影響"],
        ],
    )

    return spreadsheet


@pytest.fixture
def spreadsheet() -> FakeSpreadsheet:
    return _ledger_spreadsheet()


@pytest.fixture
def adapter(tmp_path) -> SheetWriteAdapter:
    policy_registry = WritePolicyRegistry.load(WRITE_POLICY_PATH, ARCHIVE_SPORT_KEY)
    header_row_index_by_tab = load_header_row_index_map(TAB_LAYOUT_PATH, ARCHIVE_SPORT_KEY)
    audit_logger = AuditLogger(tmp_path / "audit.log")
    return SheetWriteAdapter(policy_registry, audit_logger, header_row_index_by_tab)


def _snapshot(spreadsheet: FakeSpreadsheet) -> dict:
    return {title: (ws.get_all_values(), dict(ws.formulas)) for title, ws in spreadsheet._worksheets.items()}


# --- 1. 正常系: write_whitelist タブへの新規追加・更新 ---


def test_write_prediction_fields_appends_new_row_on_write_whitelist_tab(adapter, spreadsheet):
    rm = _race_master()
    outcome = adapter.write_prediction_fields(
        spreadsheet, rm, "Race Log", {"Race ID": rm.race_id, "Venue": "matsudo", "Grade": "A"}
    )

    assert outcome.action == "APPENDED"
    ws = spreadsheet.worksheet("Race Log")
    new_row = ws.get_all_values()[-1]
    headers = ws.get_all_values()[2]
    assert new_row[headers.index("Race ID")] == rm.race_id
    assert new_row[headers.index("Venue")] == "matsudo"
    assert new_row[headers.index("Grade")] == "A"
    # 書いていない列は空のまま
    assert new_row[headers.index("Result")] == ""


def test_write_prediction_fields_upserts_only_target_cells_not_whole_row(adapter, spreadsheet):
    rm = _race_master()
    adapter.write_prediction_fields(spreadsheet, rm, "Race Log", {"Race ID": rm.race_id, "Grade": "A"})

    ws = spreadsheet.worksheet("Race Log")
    headers = ws.get_all_values()[2]
    row_before = list(ws.get_all_values()[-1])
    row_before[headers.index("Notes")] = "SHOULD_NOT_BE_TOUCHED"
    ws.rows[-1] = row_before

    adapter.write_prediction_fields(spreadsheet, rm, "Race Log", {"Race ID": rm.race_id, "Grade": "B"})

    row_after = ws.get_all_values()[-1]
    assert row_after[headers.index("Grade")] == "B"  # 更新された
    assert row_after[headers.index("Notes")] == "SHOULD_NOT_BE_TOUCHED"  # 無関係な列は無傷
    assert len([r for r in ws.get_all_values() if r and r[headers.index("Race ID")] == rm.race_id]) == 1  # 追記されず更新


# --- 2. 数式列へは絶対に書けない ---


def test_writing_formula_column_is_always_rejected_and_does_not_touch_sheet(adapter, spreadsheet):
    rm = _race_master()
    before = _snapshot(spreadsheet)

    with pytest.raises(ColumnNotWhitelistedError):
        adapter.write_prediction_fields(
            spreadsheet, rm, "Race Ledger",
            {"Race ID": rm.race_id, "Account / 口座": "FORCED-ALL", "Profit / 利益": "9999"},
        )

    assert _snapshot(spreadsheet) == before


def test_writing_hit_column_on_race_ledger_is_rejected():
    """Hit/的中も数式列としてallowed_columnsから除外されていることを設定ファイルで確認する。"""
    policy_registry = WritePolicyRegistry.load(WRITE_POLICY_PATH, ARCHIVE_SPORT_KEY)
    policy = policy_registry.get("Race Ledger")
    assert "Hit / 的中" not in policy.allowed_columns
    assert "Profit / 利益" not in policy.allowed_columns
    assert "ROI" not in policy.allowed_columns


def test_writing_tickets_return_profit_columns_is_rejected_by_config():
    policy_registry = WritePolicyRegistry.load(WRITE_POLICY_PATH, ARCHIVE_SPORT_KEY)
    policy = policy_registry.get("Tickets")
    assert "Return" not in policy.allowed_columns
    assert "Profit" not in policy.allowed_columns


def test_coverage_progress_japanese_column_is_never_whitelisted():
    policy_registry = WritePolicyRegistry.load(WRITE_POLICY_PATH, ARCHIVE_SPORT_KEY)
    policy = policy_registry.get("Coverage")
    assert "進捗（日本語）" not in policy.allowed_columns


# --- 3. READ ONLYタブへの書き込みは必ず失敗する ---


def test_writing_to_read_only_tab_is_always_rejected_and_does_not_touch_sheet(adapter, spreadsheet):
    rm = _race_master()
    before = _snapshot(spreadsheet)

    with pytest.raises(ReadOnlyTabError):
        adapter.write_prediction_fields(spreadsheet, rm, "FORCED-ALL", {"Race ID": rm.race_id})

    assert _snapshot(spreadsheet) == before


@pytest.mark.parametrize("tab", ["FORCED-ALL", "SELECT-B+", "Summary", "日別", "FLEX-ALL", "FLEX-SELECT"])
def test_all_currently_read_only_tabs_are_configured_as_read_only(tab):
    policy_registry = WritePolicyRegistry.load(WRITE_POLICY_PATH, ARCHIVE_SPORT_KEY)
    assert policy_registry.get(tab).mode == "read_only"


# --- 4. ヘッダー位置が違う場合は必ず失敗する ---


def test_wrong_header_row_index_is_rejected_and_does_not_touch_sheet(spreadsheet, tmp_path):
    policy_registry = WritePolicyRegistry.load(WRITE_POLICY_PATH, ARCHIVE_SPORT_KEY)
    audit_logger = AuditLogger(tmp_path / "audit.log")
    # わざと誤ったheader_row_index(1=空行)を設定する
    wrong_layout = {"Race Log": 1}
    adapter = SheetWriteAdapter(policy_registry, audit_logger, wrong_layout)
    rm = _race_master()
    before = _snapshot(spreadsheet)

    with pytest.raises(HeaderMismatchError):
        adapter.write_prediction_fields(spreadsheet, rm, "Race Log", {"Race ID": rm.race_id, "Grade": "A"})

    assert _snapshot(spreadsheet) == before


def test_missing_header_row_index_config_is_rejected(spreadsheet, tmp_path):
    policy_registry = WritePolicyRegistry.load(WRITE_POLICY_PATH, ARCHIVE_SPORT_KEY)
    audit_logger = AuditLogger(tmp_path / "audit.log")
    adapter = SheetWriteAdapter(policy_registry, audit_logger, header_row_index_by_tab={})  # 未設定
    rm = _race_master()

    with pytest.raises(HeaderMismatchError):
        adapter.write_prediction_fields(spreadsheet, rm, "Race Log", {"Race ID": rm.race_id})


# --- 5. Race IDが違えば必ず失敗する ---


def test_race_id_mismatch_is_rejected_and_does_not_touch_sheet(adapter, spreadsheet):
    rm = _race_master()
    before = _snapshot(spreadsheet)

    with pytest.raises(IdentityMismatchError):
        adapter.write_prediction_fields(
            spreadsheet, rm, "Race Log", {"Race ID": "some-other-race-id", "Grade": "A"}
        )

    assert _snapshot(spreadsheet) == before


# --- 6. 未知タブは拒否される(deny-by-default) ---


def test_unknown_tab_is_rejected(adapter, spreadsheet):
    rm = _race_master()
    with pytest.raises(UnknownTabError):
        adapter.write_prediction_fields(spreadsheet, rm, "Nonexistent Tab", {"Race ID": rm.race_id})


# --- 7. NO POST-HOCをAdapterでも再検証する ---


def test_write_prediction_fields_after_start_is_blocked(adapter, spreadsheet):
    rm = _race_master(scheduled_start=to_iso(utcnow() - timedelta(minutes=5)))
    with pytest.raises(PostHocBlockedError):
        adapter.write_prediction_fields(spreadsheet, rm, "Race Log", {"Race ID": rm.race_id, "Grade": "A"})


def test_write_prediction_fields_after_result_known_is_blocked_even_before_scheduled_start(adapter, spreadsheet):
    rm = _race_master(status=RaceStatus.RESULT_LOCKED)  # scheduled_startはまだ未来
    with pytest.raises(PostHocBlockedError):
        adapter.write_prediction_fields(spreadsheet, rm, "Race Log", {"Race ID": rm.race_id, "Grade": "A"})


def test_write_result_fields_allowed_up_to_result_locked(adapter, spreadsheet):
    rm = _race_master(status=RaceStatus.RESULT_LOCKED)
    outcome = adapter.write_result_fields(spreadsheet, rm, "Race Log", {"Race ID": rm.race_id, "Result": "SETTLED"})
    assert outcome.action == "APPENDED"


def test_write_result_fields_blocked_after_settled(adapter, spreadsheet):
    rm = _race_master(status=RaceStatus.SETTLED)
    with pytest.raises(PostHocBlockedError):
        adapter.write_result_fields(spreadsheet, rm, "Race Log", {"Race ID": rm.race_id, "Result": "SETTLED"})


# --- 8. append-only(変更履歴) ---


def test_append_audit_row_always_appends_never_updates(adapter, spreadsheet):
    fields = {"Time JST / 時刻": "2026-08-16T10:00:00+00:00", "Change / 変更種別": "policy_update"}
    adapter.append_audit_row(spreadsheet, ARCHIVE_SPORT_KEY, "変更履歴", fields)
    adapter.append_audit_row(spreadsheet, ARCHIVE_SPORT_KEY, "変更履歴", fields)  # 同一内容でも別行として追加される

    ws = spreadsheet.worksheet("変更履歴")
    data_rows = ws.get_all_values()[4:]
    assert len(data_rows) == 2


def test_write_prediction_fields_on_append_only_tab_is_rejected(adapter, spreadsheet):
    rm = _race_master()
    with pytest.raises(AppendOnlyViolationError):
        adapter.write_prediction_fields(spreadsheet, rm, "変更履歴", {"Time JST / 時刻": "x"})


# --- 9. 全体として、失敗時は一切書き込みが行われない(まとめの確認) ---


def test_multiple_rejections_leave_sheet_completely_unchanged(adapter, spreadsheet):
    rm = _race_master()
    before = _snapshot(spreadsheet)

    for exc_type, tab, fields in [
        (ColumnNotWhitelistedError, "Race Ledger", {"Race ID": rm.race_id, "Account / 口座": "FORCED-ALL", "ROI": "1"}),
        (ReadOnlyTabError, "FORCED-ALL", {"Race ID": rm.race_id}),
        (IdentityMismatchError, "Race Log", {"Race ID": "wrong-id"}),
        (UnknownTabError, "Not A Real Tab", {"Race ID": rm.race_id}),
    ]:
        with pytest.raises(exc_type):
            adapter.write_prediction_fields(spreadsheet, rm, tab, fields)

    assert _snapshot(spreadsheet) == before


# --- 10. v3.0移行: v2.1のMappingが現行の"keirin"(v3.0)へ流用されないことの証明 ---


def test_v2_1_write_policy_is_not_loaded_under_the_live_keirin_sport_key():
    """`sheet_write_policy.yaml`の"keirin_v2_1_archive"は、現行のsport識別子
    "keirin"(=v3.0)としてロードしても一切見えないことを直接確認する。
    v2.1構造がv3.0へ誤って適用される事故を、コード上(設定ファイルのキー分離)で
    防いでいることの証明。
    """
    live_policy_registry = WritePolicyRegistry.load(WRITE_POLICY_PATH, "keirin")

    for tab in ("Race Ledger", "Race Log", "Tickets", "Coverage", "FORCED-ALL", "変更履歴"):
        with pytest.raises(UnknownTabError):
            live_policy_registry.get(tab)


def test_v2_1_header_layout_is_not_loaded_under_the_live_keirin_sport_key():
    live_header_map = load_header_row_index_map(TAB_LAYOUT_PATH, "keirin")
    assert live_header_map == {}


def test_v2_1_archive_fixture_still_loads_under_its_own_archive_key():
    """一方でARCHIVE_SPORT_KEYとしては引き続き読み込めること(参照用フィクスチャとして
    保持されているだけであり、削除されたわけではないことの確認)。
    """
    archived_policy_registry = WritePolicyRegistry.load(WRITE_POLICY_PATH, ARCHIVE_SPORT_KEY)
    assert archived_policy_registry.get("Race Ledger").mode == "write_whitelist"
