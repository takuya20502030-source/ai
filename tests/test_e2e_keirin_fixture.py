"""End-to-End: 競輪1レースを Race Master -> PRE-FIX -> FINAL-LOCK -> Result ->
RESULT_LOCKED -> Settlement -> Audit(AUDITED) -> Google Sheets まで通す。

このセッションのサンドボックス環境はネットワーク送出ポリシーにより競輪データ
ソース・一般的なGoogle認証情報のいずれにも到達できないため(egressポリシーで
www.keirin.jp等が403/EGRESS_BLOCKEDになることを確認済み。googleapis.comへの
到達は可能だが認証情報自体が未設定)、この実行環境内では「実レース」を用いた
検証は不可能。

そのためユーザーの指示に基づき、
- データ取得(get_race_card相当)は Phase2 で実装したファイルベース取り込み経路
  (tests/fixtures/keirin_race_card_sample.json、フィクスチャであることを明記)
- PRE以降のタイミングはテストfixture(動的に発走前/発走後を作り出す)
で全経路を検証する。Google Sheetsへの反映は fake_backend による書き込み経路検証と、
認証情報が無い場合のdry-run経路の両方を確認する。
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest

from rin_garden.analysis.garden6 import integrate
from rin_garden.analysis.members import run_garden6
from rin_garden.analysis.snapshot import RaceSnapshot
from rin_garden.analysis.value import ValueAssessment
from rin_garden.audit.coverage import daily_coverage
from rin_garden.audit.finalize import audit_race
from rin_garden.collectors.keirin.collector import KeirinCollector
from rin_garden.core.final_lock import FinalLock, FinalLockService
from rin_garden.core.identity import build_race_id
from rin_garden.core.logging import AuditLogger
from rin_garden.core.pre_fix import PreFix, PreFixService
from rin_garden.core.race_master import RaceMasterStore, RaceStatus
from rin_garden.core.timeutil import to_iso, utcnow
from rin_garden.settlement.result_loader import Result, ResultLoaderService
from rin_garden.settlement.settlement import SettlementService
from rin_garden.sheets import writer as sheets_writer
from rin_garden.sheets.client import SheetsClient
from rin_garden.sheets.writer import SheetsWriteRejectedError
from tests.fakes.fake_gspread import FakeSpreadsheet

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_keirin_race_end_to_end_through_sheets(tmp_path, monkeypatch):
    # === データ取得: get_schedule()/get_race_card() 相当 ===
    # ネットワークが遮断されているため、正規の一次情報を模したフィクスチャファイル
    # (ライブサイトから取得したものではない旨を明記したJSON)を取り込む。
    collector = KeirinCollector()
    card_result = collector.load_race_card_from_file(FIXTURES_DIR / "keirin_race_card_sample.json")
    assert card_result.ok is True
    card = card_result.data

    race_id = build_race_id(card["sport"], card["date"], card["venue"], card["race_number"], card["event_id"])

    normalized_dir = tmp_path / "data" / "normalized"
    pre_dir = tmp_path / "data" / "pre"
    final_dir = tmp_path / "data" / "final"
    results_dir = tmp_path / "data" / "results"
    audit_logger = AuditLogger(tmp_path / "logs" / "audit.log")
    race_master_store = RaceMasterStore(normalized_dir)

    monkeypatch.setenv("GOOGLE_SHEET_ID_KEIRIN", "fake-sheet-id")
    spreadsheet = FakeSpreadsheet()
    sheets_client = SheetsClient(fake_backend=lambda sheet_id: spreadsheet)

    # === Race Master ===
    # フィクスチャ内の日時をそのまま使わず、テスト実行時刻基準で「まだ発走していない」
    # 状態を作る(発走前PREが作れることを検証するため)。
    scheduled_start = to_iso(utcnow() + timedelta(minutes=30))
    rm = race_master_store.create_scheduled(
        sport=card["sport"],
        date=card["date"],
        venue=card["venue"],
        race_number=card["race_number"],
        race_id=race_id,
        event_id=card["event_id"],
        canonical_source=card["canonical_source"],
        scheduled_start=scheduled_start,
        extra={"entrant_count": len(card["entrants"])},
    )
    assert rm.status == RaceStatus.SCHEDULED
    assert sheets_writer.save_race_master(sheets_client, audit_logger, rm) == "WRITTEN"

    # === GARDEN-6: 同一snapshotを6担当へ渡し、独立分析 -> 凜が統合 ===
    snapshot = RaceSnapshot(
        race_id=race_id,
        sport=card["sport"],
        captured_at=to_iso(utcnow()),
        race_card=card,
        market_odds={"1": 3.0},
        live_data={},
        source_confidence=card_result.confidence,
    )
    findings = run_garden6(snapshot)
    assert len(findings) == 6
    value = ValueAssessment.build(estimated_probability=0.35, market_odds=3.0)
    g6 = integrate(race_id, findings, rank="A", chaos=4, value=value, rin_summary="E2Eフィクスチャ検証")

    # === PRE-FIX(発走前) ===
    pre_service = PreFixService(pre_dir, race_master_store, audit_logger)
    pre = PreFix(
        race_id=race_id,
        timestamp=to_iso(utcnow()),
        data_snapshot=snapshot.to_dict(),
        garden6_analysis=g6.to_dict(),
        rank=g6.rank,
        chaos=g6.chaos,
        confidence=g6.confidence,
        predicted_scenario={"label": "fixture scenario"},
        bets=[{"type": "win", "target": "1", "amount": 1000}],
        fair_probability={"1": value.estimated_probability},
        fair_odds={"1": value.fair_odds},
        market_odds={"1": value.market_odds},
        expected_value={"1": value.expected_value},
    )
    rm = pre_service.create(rm, pre)
    assert rm.status == RaceStatus.PRE_FIXED
    assert sheets_writer.save_pre_fix(sheets_client, audit_logger, rm, pre.to_dict()) == "WRITTEN"

    # === FINAL-LOCK(発走前) ===
    final_service = FinalLockService(final_dir, race_master_store, audit_logger)
    final = FinalLock(
        race_id=race_id,
        timestamp=to_iso(utcnow()),
        marks={"1": "◎"},
        evaluation={"1": g6.rank},
        bets=[{"type": "win", "target": "1"}],
        amounts={"1": 1000},
        decision=g6.decision,
    )
    rm = final_service.create(rm, final)
    assert rm.status == RaceStatus.FINAL_LOCKED
    assert sheets_writer.save_final_lock(sheets_client, audit_logger, rm, {**final.to_dict(), "revisions": []}) == "WRITTEN"

    # === Result登録 ===
    # 結果データもネットワーク遮断のためファイル取り込み経路を使う。
    result_fixture = {"race_id": race_id, "order": ["1", "3", "2"], "payouts": {"1": 280.0}}
    result_path = tmp_path / "result.json"
    result_path.write_text(json.dumps(result_fixture), encoding="utf-8")
    result_load = collector.load_result_from_file(result_path)
    assert result_load.ok is True

    result_service = ResultLoaderService(results_dir, race_master_store, audit_logger)
    result_obj = Result(
        race_id=race_id,
        timestamp=to_iso(utcnow()),
        order=result_load.data["order"],
        payouts=result_load.data["payouts"],
    )
    rm = result_service.load_result(rm, result_obj)
    assert rm.status == RaceStatus.RESULT_LOCKED
    assert sheets_writer.save_result(sheets_client, audit_logger, rm, result_obj.to_dict()) == "WRITTEN"

    # === Settlement ===
    settlement_service = SettlementService(results_dir, race_master_store, audit_logger)
    settlement = settlement_service.settle(rm, final.to_dict(), result_obj.to_dict())
    assert rm.status == RaceStatus.SETTLED
    assert settlement.stake == 1000
    assert settlement.payout == pytest.approx(2800.0)
    assert settlement.profit == pytest.approx(1800.0)
    assert sheets_writer.settle_race(sheets_client, audit_logger, rm, settlement.to_dict()) == "WRITTEN"

    # === Audit finalize (SETTLED -> AUDITED) ===
    rm = audit_race(rm, race_master_store, pre_dir, final_dir, results_dir, audit_logger)
    assert rm.status == RaceStatus.AUDITED
    assert rm.audited_at is not None
    assert sheets_writer.save_race_master(sheets_client, audit_logger, rm) == "WRITTEN"

    # === Coverage: 予定1件、PRE/FINAL/Result/精算すべて1件ずつ揃っていること ===
    coverage = daily_coverage(card["sport"], card["date"], race_master_store, pre_dir, final_dir, results_dir)
    assert coverage["scheduled_races"] == 1
    assert coverage["pre_fixed"] == 1
    assert coverage["final_locked"] == 1
    assert coverage["settled"] == 1
    assert coverage["missing"] == 0

    # === NO POST-HOC: 結果確定後にPREを新規生成しようとすると拒否されることを再確認 ===
    with pytest.raises(SheetsWriteRejectedError):
        sheets_writer.save_pre_fix(sheets_client, audit_logger, rm, pre.to_dict())

    # === Sheets: 認証情報が無い環境でも同じ呼び出しが処理を止めずDRY_RUNで完了すること ===
    dry_client = SheetsClient()
    assert dry_client.dry_run is True
    assert sheets_writer.save_race_master(dry_client, audit_logger, rm) == "DRY_RUN"

    # === PRE/FINAL本体の内容がここまでの一連の処理で書き換わっていないこと ===
    stored_pre = pre_service.load(rm.sport, rm.date, rm.race_id)
    assert stored_pre["rank"] == g6.rank
    assert stored_pre["bets"] == pre.bets
