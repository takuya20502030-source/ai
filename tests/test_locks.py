"""RIN GARDEN 最重要ルールの検証: PRE-FIX / FINAL-LOCK / NO POST-HOC / Race Identity。"""

from __future__ import annotations

from rin_garden.audit.integrity import compute_hash
from rin_garden.core.final_lock import FinalLock, FinalLockAlreadyExistsError
from rin_garden.core.identity import IdentityMismatchError
from rin_garden.core.locks import PostHocBlockedError
from rin_garden.core.pre_fix import PreFix
from rin_garden.core.race_master import RaceStatus
from rin_garden.core.storage import read_json_if_exists
from rin_garden.core.timeutil import to_iso, utcnow
from rin_garden.settlement.result_loader import Result
from tests.conftest import make_final_kwargs, make_pre_kwargs


def test_1_pre_fix_before_start_succeeds(make_race_master, pre_fix_service):
    rm = make_race_master(starts_in_minutes=60)
    pre = PreFix(**make_pre_kwargs(rm.race_id))

    result = pre_fix_service.create(rm, pre)

    assert result.status == RaceStatus.PRE_FIXED
    assert result.pre_fixed_at is not None


def test_2_pre_fix_after_start_is_post_hoc_blocked(make_race_master, pre_fix_service, audit_logger):
    rm = make_race_master(starts_in_minutes=-10)  # 既に発走済み
    pre = PreFix(**make_pre_kwargs(rm.race_id))

    try:
        pre_fix_service.create(rm, pre)
        assert False, "expected PostHocBlockedError"
    except PostHocBlockedError:
        pass

    ops = [e["operation"] for e in audit_logger.read_all()]
    assert "POST_HOC_BLOCKED" in ops


def test_3_final_lock_direct_overwrite_is_rejected(make_race_master, final_lock_service):
    rm = make_race_master(starts_in_minutes=60)
    final = FinalLock(**make_final_kwargs(rm.race_id))
    rm = final_lock_service.create(rm, final)
    assert rm.status == RaceStatus.FINAL_LOCKED

    other_final = FinalLock(**make_final_kwargs(rm.race_id, decision="SKIP"))
    try:
        final_lock_service.create(rm, other_final)
        assert False, "expected FinalLockAlreadyExistsError (direct overwrite must be rejected)"
    except FinalLockAlreadyExistsError:
        pass


def test_4_race_id_mismatch_is_identity_mismatch(make_race_master, pre_fix_service, audit_logger):
    rm = make_race_master(starts_in_minutes=60)
    mismatched_pre = PreFix(**make_pre_kwargs("some-other-race-id"))

    try:
        pre_fix_service.create(rm, mismatched_pre)
        assert False, "expected IdentityMismatchError"
    except IdentityMismatchError:
        pass

    ops = [e["operation"] for e in audit_logger.read_all()]
    assert "IDENTITY_MISMATCH" in ops


def test_5_result_registration_locks_result(make_race_master, result_loader_service):
    rm = make_race_master(starts_in_minutes=-5)
    result = Result(
        race_id=rm.race_id,
        timestamp=to_iso(utcnow()),
        order=["1", "2", "3"],
        payouts={"1": 250.0},
    )

    rm = result_loader_service.load_result(rm, result)

    assert rm.status == RaceStatus.RESULT_LOCKED
    assert rm.result_locked_at is not None


def test_6_settlement_marks_settled(make_race_master, result_loader_service, settlement_service):
    rm = make_race_master(starts_in_minutes=-5)
    result = Result(
        race_id=rm.race_id,
        timestamp=to_iso(utcnow()),
        order=["1", "2", "3"],
        payouts={"1": 250.0},
    )
    rm = result_loader_service.load_result(rm, result)

    final = {**make_final_kwargs(rm.race_id), "amounts": {"1": 1000}}
    settlement = settlement_service.settle(rm, final, result.to_dict())

    assert rm.status == RaceStatus.SETTLED
    assert rm.settled_at is not None
    assert settlement.stake == 1000
    assert settlement.payout == 2500.0
    assert settlement.profit == 1500.0


def test_7_settlement_does_not_mutate_pre(
    make_race_master, pre_fix_service, result_loader_service, settlement_service, data_root
):
    rm = make_race_master(starts_in_minutes=60)
    pre = PreFix(**make_pre_kwargs(rm.race_id))
    rm = pre_fix_service.create(rm, pre)

    pre_path = data_root["pre_dir"] / rm.sport / rm.date / f"{rm.race_id}.json"
    hash_before = compute_hash(read_json_if_exists(pre_path))

    # 発走後、結果登録・精算を行う(PREを再度作り直したり書き換えたりはしない)
    rm.scheduled_start = to_iso(utcnow())
    result = Result(
        race_id=rm.race_id,
        timestamp=to_iso(utcnow()),
        order=["1"],
        payouts={"1": 150.0},
    )
    rm = result_loader_service.load_result(rm, result)
    final = {**make_final_kwargs(rm.race_id), "amounts": {"1": 500}}
    settlement_service.settle(rm, final, result.to_dict())

    hash_after = compute_hash(read_json_if_exists(pre_path))
    assert hash_before == hash_after
