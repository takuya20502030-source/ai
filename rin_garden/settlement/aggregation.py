"""日次・ランク別・券種別の集計。Resultおよび確定済みSettlementのみを対象とする。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rin_garden.core import storage
from rin_garden.core.race_master import RaceMasterStore


def aggregate_day(sport: str, date: str, results_dir: Path, race_master_store: RaceMasterStore) -> dict[str, Any]:
    """指定sport/dateの精算済みレースを集計する。"""
    race_ids = race_master_store.list_race_ids(sport, date)
    settlements: list[dict[str, Any]] = []
    for race_id in race_ids:
        path = Path(results_dir) / sport / date / race_id / "settlement.json"
        data = storage.read_json_if_exists(path)
        if data is not None:
            settlements.append(data)

    stake_total = sum(s["stake"] for s in settlements)
    payout_total = sum(s["payout"] for s in settlements)
    profit_total = payout_total - stake_total
    roi_total = (profit_total / stake_total) if stake_total > 0 else 0.0

    by_decision: dict[str, dict[str, float]] = {}
    for s in settlements:
        bucket = by_decision.setdefault(s.get("decision", "UNKNOWN"), {"stake": 0.0, "payout": 0.0, "count": 0})
        bucket["stake"] += s["stake"]
        bucket["payout"] += s["payout"]
        bucket["count"] += 1

    return {
        "sport": sport,
        "date": date,
        "races_settled": len(settlements),
        "stake": stake_total,
        "payout": payout_total,
        "profit": profit_total,
        "roi": roi_total,
        "by_decision": by_decision,
    }
