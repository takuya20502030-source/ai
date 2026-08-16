"""全レース検証の欠損確認用Coverage機構。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rin_garden.core import storage
from rin_garden.core.race_master import RaceMaster, RaceMasterStore, RaceStatus


def _final_lock_accounts(final_dir: Path, race_master: RaceMaster) -> list[str]:
    """FINAL-LOCKが作成済みのAccount名一覧を返す(race_id + account単位で保存されるため)。"""
    dir_path = Path(final_dir) / race_master.sport / race_master.date / race_master.race_id
    if not dir_path.exists():
        return []
    return sorted(p.stem for p in dir_path.glob("*.json"))


def _settlement_accounts(results_dir: Path, race_master: RaceMaster) -> list[str]:
    """精算済みのAccount名一覧を返す(race_id + account単位で保存されるため)。"""
    dir_path = Path(results_dir) / race_master.sport / race_master.date / race_master.race_id / "settlement"
    if not dir_path.exists():
        return []
    return sorted(p.stem for p in dir_path.glob("*.json"))


def race_coverage(race_master: RaceMaster, pre_dir: Path, final_dir: Path, results_dir: Path) -> dict[str, Any]:
    """1レース分のCoverage状態を返す。

    PRE-FIXとResultはレース単位(1件)。FINAL-LOCKとSettlementはAccount単位で
    複数存在しうるため、Account一覧を報告する(final_locked/settledは
    「少なくとも1 Account分が存在するか」の真偽値)。
    """
    pre_exists = (Path(pre_dir) / race_master.sport / race_master.date / f"{race_master.race_id}.json").exists()
    final_accounts = _final_lock_accounts(final_dir, race_master)
    result_exists = (Path(results_dir) / race_master.sport / race_master.date / race_master.race_id / "result.json").exists()
    settlement_accounts = _settlement_accounts(results_dir, race_master)

    return {
        "race_id": race_master.race_id,
        "race_exists": True,
        "data_loaded": bool(race_master.source_url or race_master.extra),
        "pre_fixed": pre_exists,
        "final_locked": len(final_accounts) > 0,
        "final_locked_accounts": final_accounts,
        "result_loaded": result_exists,
        "settled": len(settlement_accounts) > 0,
        "settled_accounts": settlement_accounts,
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
