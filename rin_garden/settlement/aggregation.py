"""日次・ランク別・券種別・Account別の集計。Resultおよび確定済みSettlementのみを対象とする。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rin_garden.core import storage
from rin_garden.core.race_master import RaceMasterStore


def _load_settlements_for_race(results_dir: Path, sport: str, date: str, race_id: str) -> list[dict[str, Any]]:
    """1レース分の、Account別Settlementをすべて読み込む(race_id + account単位で保存されるため)。"""
    dir_path = Path(results_dir) / sport / date / race_id / "settlement"
    if not dir_path.exists():
        return []
    settlements = []
    for path in sorted(dir_path.glob("*.json")):
        data = storage.read_json_if_exists(path)
        if data is not None:
            settlements.append(data)
    return settlements


def aggregate_day(sport: str, date: str, results_dir: Path, race_master_store: RaceMasterStore) -> dict[str, Any]:
    """指定sport/dateの精算済み(race_id, account)を集計する。Account別Profit/ROIは
    それぞれ独立して積み上げる(同じレースでもAccountが違えば別集計となる)。
    """
    race_ids = race_master_store.list_race_ids(sport, date)
    settlements: list[dict[str, Any]] = []
    for race_id in race_ids:
        settlements.extend(_load_settlements_for_race(results_dir, sport, date, race_id))

    stake_total = sum(s["stake"] for s in settlements)
    payout_total = sum(s["payout"] for s in settlements)
    profit_total = payout_total - stake_total
    roi_total = (profit_total / stake_total) if stake_total > 0 else 0.0

    by_decision: dict[str, dict[str, float]] = {}
    by_account: dict[str, dict[str, float]] = {}
    for s in settlements:
        decision_bucket = by_decision.setdefault(s.get("decision", "UNKNOWN"), {"stake": 0.0, "payout": 0.0, "count": 0})
        decision_bucket["stake"] += s["stake"]
        decision_bucket["payout"] += s["payout"]
        decision_bucket["count"] += 1

        account = s.get("account", "DEFAULT")
        account_bucket = by_account.setdefault(
            account, {"stake": 0.0, "payout": 0.0, "profit": 0.0, "roi": 0.0, "count": 0}
        )
        account_bucket["stake"] += s["stake"]
        account_bucket["payout"] += s["payout"]
        account_bucket["count"] += 1

    for account, bucket in by_account.items():
        bucket["profit"] = bucket["payout"] - bucket["stake"]
        bucket["roi"] = (bucket["profit"] / bucket["stake"]) if bucket["stake"] > 0 else 0.0

    return {
        "sport": sport,
        "date": date,
        "races_settled": len(settlements),
        "stake": stake_total,
        "payout": payout_total,
        "profit": profit_total,
        "roi": roi_total,
        "by_decision": by_decision,
        "by_account": by_account,
    }
