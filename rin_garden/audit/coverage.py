"""全レース検証の欠損確認用Coverage機構。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rin_garden.core import storage
from rin_garden.core.race_master import RaceMaster, RaceMasterStore, RaceStatus


def race_coverage(race_master: RaceMaster, pre_dir: Path, final_dir: Path, results_dir: Path) -> dict[str, Any]:
    """1レース分のCoverage状態を返す。"""
    pre_exists = (Path(pre_dir) / race_master.sport / race_master.date / f"{race_master.race_id}.json").exists()
    final_exists = (Path(final_dir) / race_master.sport / race_master.date / f"{race_master.race_id}.json").exists()
    result_exists = (Path(results_dir) / race_master.sport / race_master.date / race_master.race_id / "result.json").exists()
    settled_exists = (
        Path(results_dir) / race_master.sport / race_master.date / race_master.race_id / "settlement.json"
    ).exists()

    return {
        "race_id": race_master.race_id,
        "race_exists": True,
        "data_loaded": bool(race_master.source_url or race_master.extra),
        "pre_fixed": pre_exists,
        "final_locked": final_exists,
        "result_loaded": result_exists,
        "settled": settled_exists,
        "audited": race_master.status == RaceStatus.AUDITED,
    }


def daily_coverage(
    sport: str,
    date: str,
    race_master_store: RaceMasterStore,
    pre_dir: Path,
    final_dir: Path,
    results_dir: Path,
) -> dict[str, Any]:
    """当日のCoverageを集計する。予定レース数/PRE作成数/FINAL作成数/精算数/欠損数。"""
    race_ids = race_master_store.list_race_ids(sport, date)
    rows = []
    for race_id in race_ids:
        rm = race_master_store.load(sport, date, race_id)
        if rm is None:
            continue
        rows.append(race_coverage(rm, pre_dir, final_dir, results_dir))

    scheduled = len(rows)
    pre_fixed = sum(1 for r in rows if r["pre_fixed"])
    final_locked = sum(1 for r in rows if r["final_locked"])
    settled = sum(1 for r in rows if r["settled"])
    missing = sum(1 for r in rows if not r["pre_fixed"])

    return {
        "sport": sport,
        "date": date,
        "scheduled_races": scheduled,
        "pre_fixed": pre_fixed,
        "final_locked": final_locked,
        "settled": settled,
        "missing": missing,
        "races": rows,
    }
