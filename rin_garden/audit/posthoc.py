"""NO POST-HOCの独立監査。書き込み時点のLock強制(core/locks.py)とは別に、
保存済みデータを事後的に横断チェックする第二の防衛線として使う。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rin_garden.core import storage
from rin_garden.core.race_master import RaceMasterStore
from rin_garden.core.timeutil import parse_iso


def scan_day_for_post_hoc_violations(
    sport: str,
    date: str,
    race_master_store: RaceMasterStore,
) -> list[dict[str, Any]]:
    """当日のRace Masterを走査し、pre_fixed_at/final_locked_atがscheduled_start以降に
    なっているレース(=書き込み時点のLockをすり抜けた疑いがあるもの)を検出する。
    """
    violations: list[dict[str, Any]] = []
    for race_id in race_master_store.list_race_ids(sport, date):
        rm = race_master_store.load(sport, date, race_id)
        if rm is None or rm.scheduled_start is None:
            continue
        start = parse_iso(rm.scheduled_start)

        if rm.pre_fixed_at is not None and parse_iso(rm.pre_fixed_at) >= start:
            violations.append(
                {
                    "race_id": race_id,
                    "field": "pre_fixed_at",
                    "scheduled_start": rm.scheduled_start,
                    "recorded_at": rm.pre_fixed_at,
                }
            )
        if rm.final_locked_at is not None and parse_iso(rm.final_locked_at) >= start:
            violations.append(
                {
                    "race_id": race_id,
                    "field": "final_locked_at",
                    "scheduled_start": rm.scheduled_start,
                    "recorded_at": rm.final_locked_at,
                }
            )
    return violations
