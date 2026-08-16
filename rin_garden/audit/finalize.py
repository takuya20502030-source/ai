"""監査による最終確定(SETTLED -> AUDITED)。

Settlementの計算そのものは`settlement/settlement.py`が担当する。ここでは
「PRE/FINAL/Result/Settlementが揃っているか」をCoverageで確認した上で、
Race Masterを AUDITED として確定させる。PRE/FINAL/Result/Settlementの内容は
一切書き換えない。
"""

from __future__ import annotations

from pathlib import Path

from rin_garden.audit.coverage import race_coverage
from rin_garden.core.logging import AuditLogger, OP_AUDITED, OP_DATA_INCOMPLETE
from rin_garden.core.race_master import RaceMaster, RaceMasterStore, RaceStatus
from rin_garden.core.timeutil import to_iso, utcnow


class AuditNotReadyError(Exception):
    """精算(SETTLED)前のレースを監査確定しようとした場合に送出する。"""


def audit_race(
    race_master: RaceMaster,
    race_master_store: RaceMasterStore,
    pre_dir: Path,
    final_dir: Path,
    results_dir: Path,
    audit_logger: AuditLogger,
    now: str | None = None,
) -> RaceMaster:
    """SETTLED状態のレースをAUDITEDへ確定する。冪等: 既にAUDITEDならそのまま返す。"""
    now = now or to_iso(utcnow())

    if race_master.status == RaceStatus.AUDITED:
        return race_master

    if race_master.status != RaceStatus.SETTLED:
        raise AuditNotReadyError(
            f"race_id={race_master.race_id} must be SETTLED before audit (current status={race_master.status})"
        )

    coverage = race_coverage(race_master, pre_dir, final_dir, results_dir)
    incomplete = [k for k in ("pre_fixed", "final_locked", "result_loaded", "settled") if not coverage[k]]
    if incomplete:
        audit_logger.log(
            OP_DATA_INCOMPLETE,
            race_master.sport,
            race_master.race_id,
            "INCOMPLETE",
            "audit.audit_race",
            f"missing coverage before audit: {incomplete}",
        )

    race_master.status = RaceStatus.AUDITED
    race_master.audited_at = now
    race_master_store.save(race_master)

    audit_logger.log(OP_AUDITED, race_master.sport, race_master.race_id, "OK", "audit.audit_race", "")
    return race_master
