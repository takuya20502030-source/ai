"""競輪Collectorのファイルベーススナップショット取り込みの検証。

このセッションのネットワーク egress policy は競輪データソースへの到達を
ブロックしているため(www.keirin.jp 等で403/EGRESS_BLOCKEDを確認済み)、
ライブ取得は引き続きDATA_INCOMPLETEダミーのままであることも合わせて検証する。
"""

from __future__ import annotations

import json
from pathlib import Path

from rin_garden.collectors.keirin.collector import KeirinCollector
from rin_garden.core.validation import DataConfidence

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_live_fetch_still_returns_data_incomplete():
    collector = KeirinCollector()
    for result in (
        collector.get_schedule("2026-08-16"),
        collector.get_race_card("some-race-id"),
        collector.get_market_odds("some-race-id"),
        collector.get_live_data("some-race-id"),
        collector.get_result("some-race-id"),
    ):
        assert result.ok is False
        assert result.confidence == DataConfidence.INCOMPLETE


def test_load_race_card_from_file_succeeds_with_partial_confidence():
    collector = KeirinCollector()
    result = collector.load_race_card_from_file(FIXTURES_DIR / "keirin_race_card_sample.json")

    assert result.ok is True
    # entrant #5 has score=null in the fixture -> not fully CONFIRMED
    assert result.confidence == DataConfidence.ESTIMATED
    assert "5" in result.message
    assert result.data["venue"] == "matsudo"
    assert len(result.data["entrants"]) == 7


def test_load_race_card_from_file_rejects_missing_identity(tmp_path):
    bad = {"sport": "keirin", "date": "2026-08-16"}  # venue/race_number/event_id/scheduled_start欠落
    bad_path = tmp_path / "bad_card.json"
    bad_path.write_text(json.dumps(bad), encoding="utf-8")

    collector = KeirinCollector()
    result = collector.load_race_card_from_file(bad_path)

    assert result.ok is False
    assert result.confidence == DataConfidence.INCOMPLETE


def test_load_result_from_file_requires_race_id_and_payouts(tmp_path):
    good = {"race_id": "KEIRIN-2026-08-16-abc", "order": ["1", "2", "3"], "payouts": {"1": 250.0}}
    good_path = tmp_path / "result.json"
    good_path.write_text(json.dumps(good), encoding="utf-8")

    collector = KeirinCollector()
    result = collector.load_result_from_file(good_path)

    assert result.ok is True
    assert result.confidence == DataConfidence.CONFIRMED

    incomplete = {"race_id": "KEIRIN-2026-08-16-abc"}  # order/payouts欠落
    incomplete_path = tmp_path / "incomplete_result.json"
    incomplete_path.write_text(json.dumps(incomplete), encoding="utf-8")
    result2 = collector.load_result_from_file(incomplete_path)
    assert result2.ok is False
    assert result2.confidence == DataConfidence.INCOMPLETE
