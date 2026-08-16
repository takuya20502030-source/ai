"""SETTLED -> AUDITED の監査確定と、そのための多重防御ガードの検証。"""

from __future__ import annotations

import pytest

from rin_garden.audit.finalize import AuditNotReadyError, audit_race
from rin_garden.core.final_lock import FinalLock
from rin_garden.core.pre_fix import PreFix
from rin_garden.core.race_master import RaceStatus
from rin_garden.core.locks import PostHocBlockedError
from tests.conftest import make_final_kwargs, make_pre_kwargs


def test_audit_race_requires_settled_status(make_race_master, race_master_store, data_root, audit_logger):
    rm = make_race_master(starts_in_minutes=60)  # まだSCHEDULEDのまま

    with pytest.raises(AuditNotReadyError):
        audit_race(rm, race_master_store, data_root["pre_dir"], data_root["final_dir"], data_root["results_dir"], audit_logger)


def test_audit_race_marks_audited_after_settlement(
    make_race_master, pre_fix_service, final_lock_service, result_loader_service, settlement_service, race_master_store, data_root, audit_logger
):
    rm = make_race_master(starts_in_minutes=60)
    rm = pre_fix_service.create(rm, PreFix(**make_pre_kwargs(rm.race_id)))
    rm = final_lock_service.create(rm, FinalLock(**make_final_kwargs(rm.race_id)))

    from rin_garden.settlement.result_loader import Result
    from rin_garden.core.timeutil import to_iso, utcnow

    result = Result(race_id=rm.race_id, timestamp=to_iso(utcnow()), order=["1"], payouts={"1": 200.0})
    rm = result_loader_service.load_result(rm, result)
    final = {**make_final_kwargs(rm.race_id), "amounts": {"1": 1000}}
    settlement_service.settle(rm, final, result.to_dict())

    rm = audit_race(rm, race_master_store, data_root["pre_dir"], data_root["final_dir"], data_root["results_dir"], audit_logger)

    assert rm.status == RaceStatus.AUDITED
    assert rm.audited_at is not None

    # 冪等: もう一度呼んでもAUDITEDのまま、エラーにならない
    rm2 = audit_race(rm, race_master_store, data_root["pre_dir"], data_root["final_dir"], data_root["results_dir"], audit_logger)
    assert rm2.status == RaceStatus.AUDITED


def test_pre_fix_refused_once_result_known_even_if_clock_says_before_start(
    make_race_master, pre_fix_service, result_loader_service
):
    """時刻比較だけに頼らない多重防御: statusがRESULT_LOCKED以降ならPRE新規作成は拒否される。"""
    rm = make_race_master(starts_in_minutes=60)  # scheduled_startはまだ未来

    from rin_garden.settlement.result_loader import Result
    from rin_garden.core.timeutil import to_iso, utcnow

    result = Result(race_id=rm.race_id, timestamp=to_iso(utcnow()), order=["1"], payouts={"1": 200.0})
    rm = result_loader_service.load_result(rm, result)
    assert rm.status == RaceStatus.RESULT_LOCKED

    with pytest.raises(PostHocBlockedError):
        pre_fix_service.create(rm, PreFix(**make_pre_kwargs(rm.race_id)))
