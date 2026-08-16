"""Account概念(race_id + account単位のFINAL-LOCK/Ticket/Settlement)の検証。

共通PRE(1 race_id = 1 PRE) -> AccountPolicy -> Account別FINAL-LOCK ->
Account別Tickets -> 共通Result(1 race_id = 1件) -> Account別Settlement
という流れを、10項目の要求シナリオに沿って確認する。
"""

from __future__ import annotations

import pytest

from rin_garden.audit.integrity import compute_hash
from rin_garden.core.account import UnknownAccountError
from rin_garden.core.final_lock import FinalLock, FinalLockAlreadyExistsError
from rin_garden.core.identity import IdentityMismatchError
from rin_garden.core.locks import PostHocBlockedError
from rin_garden.core.pre_fix import PreFix
from rin_garden.core.race_master import RaceStatus
from rin_garden.core.storage import ImmutableRecordConflictError, read_json_if_exists
from rin_garden.core.ticket import Ticket
from rin_garden.core.timeutil import to_iso, utcnow
from rin_garden.settlement.result_loader import Result
from tests.conftest import make_final_kwargs, make_pre_kwargs, make_ticket_kwargs


# --- 1. 同一race_idで複数AccountのFINAL-LOCKを作成できる ---


def test_1_multiple_accounts_can_have_final_lock_for_same_race(make_race_master, final_lock_service):
    rm = make_race_master(starts_in_minutes=60)

    rm = final_lock_service.create(rm, FinalLock(**make_final_kwargs(rm.race_id, account="FORCED-ALL")))
    rm = final_lock_service.create(rm, FinalLock(**make_final_kwargs(rm.race_id, account="SELECT-B+")))

    accounts = final_lock_service.list_accounts(rm.sport, rm.date, rm.race_id)
    assert accounts == ["FORCED-ALL", "SELECT-B+"]
    assert rm.status == RaceStatus.FINAL_LOCKED  # レース単位、1回だけ遷移


# --- 2. 同一race_id + 同一accountのFINAL直接上書きは禁止 ---


def test_2_same_race_and_account_direct_overwrite_is_rejected(make_race_master, final_lock_service):
    rm = make_race_master(starts_in_minutes=60)
    rm = final_lock_service.create(rm, FinalLock(**make_final_kwargs(rm.race_id, account="FORCED-ALL")))

    with pytest.raises(FinalLockAlreadyExistsError):
        final_lock_service.create(
            rm, FinalLock(**make_final_kwargs(rm.race_id, decision="SKIP", account="FORCED-ALL"))
        )


# --- 3. Account AのFINAL変更がAccount Bへ影響しない ---


def test_3_revising_account_a_does_not_affect_account_b(make_race_master, final_lock_service):
    rm = make_race_master(starts_in_minutes=60)
    rm = final_lock_service.create(rm, FinalLock(**make_final_kwargs(rm.race_id, account="FORCED-ALL")))
    rm = final_lock_service.create(rm, FinalLock(**make_final_kwargs(rm.race_id, account="SELECT-B+")))

    before_b = final_lock_service.load(rm.sport, rm.date, rm.race_id, account="SELECT-B+")

    revised_a = FinalLock(**make_final_kwargs(rm.race_id, decision="SKIP", account="FORCED-ALL"))
    final_lock_service.revise(rm, revised_a, reason="account A changed its mind")

    after_a = final_lock_service.load(rm.sport, rm.date, rm.race_id, account="FORCED-ALL")
    after_b = final_lock_service.load(rm.sport, rm.date, rm.race_id, account="SELECT-B+")

    assert after_a["decision"] == "SKIP"
    assert len(after_a["revisions"]) == 1
    assert after_b == before_b  # Account Bは一切変化していない


# --- 4. ResultはAccountに関係なく1件 ---


def test_4_result_is_single_record_independent_of_account(
    make_race_master, final_lock_service, result_loader_service, data_root
):
    rm = make_race_master(starts_in_minutes=60)
    final_lock_service.create(rm, FinalLock(**make_final_kwargs(rm.race_id, account="FORCED-ALL")))

    result = Result(race_id=rm.race_id, timestamp=to_iso(utcnow()), order=["1"], payouts={"1": 250.0})
    rm = result_loader_service.load_result(rm, result)

    result_dir = data_root["results_dir"] / rm.sport / rm.date / rm.race_id
    result_files = list(result_dir.glob("result.json"))
    assert len(result_files) == 1  # Accountの数に関わらず1件のみ
    assert rm.status == RaceStatus.RESULT_LOCKED


# --- 5. 同一Resultから複数Accountを独立精算できる ---


def test_5_same_result_settles_independently_per_account(
    make_race_master, final_lock_service, result_loader_service, settlement_service
):
    rm = make_race_master(starts_in_minutes=60)
    final_a = FinalLock(**make_final_kwargs(rm.race_id, account="FORCED-ALL"))
    final_b = FinalLock(**make_final_kwargs(rm.race_id, account="SELECT-B+"))
    rm = final_lock_service.create(rm, final_a)
    rm = final_lock_service.create(rm, final_b)

    result = Result(race_id=rm.race_id, timestamp=to_iso(utcnow()), order=["1"], payouts={"1": 250.0})
    rm = result_loader_service.load_result(rm, result)

    settlement_a = settlement_service.settle(rm, final_a.to_dict(), result.to_dict())
    settlement_b = settlement_service.settle(rm, final_b.to_dict(), result.to_dict())

    assert settlement_a.account == "FORCED-ALL"
    assert settlement_b.account == "SELECT-B+"
    assert settlement_service.list_accounts(rm.sport, rm.date, rm.race_id) == ["FORCED-ALL", "SELECT-B+"]


# --- 6. Account別Profit/ROIが独立する ---


def test_6_profit_and_roi_are_independent_per_account(
    make_race_master, final_lock_service, result_loader_service, settlement_service
):
    rm = make_race_master(starts_in_minutes=60)
    final_a = FinalLock(**{**make_final_kwargs(rm.race_id, account="FORCED-ALL"), "amounts": {"1": 1000}})
    final_b = FinalLock(**{**make_final_kwargs(rm.race_id, account="FLEX-ALL"), "amounts": {"1": 3000}})
    rm = final_lock_service.create(rm, final_a)
    rm = final_lock_service.create(rm, final_b)

    result = Result(race_id=rm.race_id, timestamp=to_iso(utcnow()), order=["1"], payouts={"1": 250.0})
    rm = result_loader_service.load_result(rm, result)

    settlement_a = settlement_service.settle(rm, final_a.to_dict(), result.to_dict())
    settlement_b = settlement_service.settle(rm, final_b.to_dict(), result.to_dict())

    assert settlement_a.stake == 1000
    assert settlement_a.payout == pytest.approx(2500.0)
    assert settlement_a.profit == pytest.approx(1500.0)
    assert settlement_a.roi == pytest.approx(1.5)

    assert settlement_b.stake == 3000
    assert settlement_b.payout == pytest.approx(7500.0)
    assert settlement_b.profit == pytest.approx(4500.0)
    assert settlement_b.roi == pytest.approx(1.5)

    assert settlement_a.profit != settlement_b.profit  # 独立して計算されている


# --- 7. Settlement後もPREは不変 ---


def test_7_pre_is_unchanged_after_multi_account_settlement(
    make_race_master, pre_fix_service, final_lock_service, result_loader_service, settlement_service, data_root
):
    rm = make_race_master(starts_in_minutes=60)
    rm = pre_fix_service.create(rm, PreFix(**make_pre_kwargs(rm.race_id)))
    rm = final_lock_service.create(rm, FinalLock(**make_final_kwargs(rm.race_id, account="FORCED-ALL")))
    rm = final_lock_service.create(rm, FinalLock(**make_final_kwargs(rm.race_id, account="SELECT-B+")))

    pre_path = data_root["pre_dir"] / rm.sport / rm.date / f"{rm.race_id}.json"
    hash_before = compute_hash(read_json_if_exists(pre_path))

    final_a = final_lock_service.load(rm.sport, rm.date, rm.race_id, account="FORCED-ALL")
    final_b = final_lock_service.load(rm.sport, rm.date, rm.race_id, account="SELECT-B+")
    result = Result(race_id=rm.race_id, timestamp=to_iso(utcnow()), order=["1"], payouts={"1": 150.0})
    rm = result_loader_service.load_result(rm, result)
    settlement_service.settle(rm, final_a, result.to_dict())
    settlement_service.settle(rm, final_b, result.to_dict())

    hash_after = compute_hash(read_json_if_exists(pre_path))
    assert hash_before == hash_after


# --- 8. 発走後の新規Account FINAL生成は禁止 ---


def test_8_new_account_final_lock_after_result_is_blocked(
    make_race_master, final_lock_service, result_loader_service
):
    rm = make_race_master(starts_in_minutes=60)
    rm = final_lock_service.create(rm, FinalLock(**make_final_kwargs(rm.race_id, account="FORCED-ALL")))

    result = Result(race_id=rm.race_id, timestamp=to_iso(utcnow()), order=["1"], payouts={"1": 200.0})
    rm = result_loader_service.load_result(rm, result)
    assert rm.status == RaceStatus.RESULT_LOCKED

    # 既に確定していたFORCED-ALLとは別の、新規Account(SELECT-B+)を後から作ろうとする
    with pytest.raises(PostHocBlockedError):
        final_lock_service.create(rm, FinalLock(**make_final_kwargs(rm.race_id, account="SELECT-B+")))


# --- 9. 未知Accountはconfig未登録なら拒否する ---


def test_9_unknown_account_is_rejected(make_race_master, final_lock_service, audit_logger):
    rm = make_race_master(starts_in_minutes=60)

    with pytest.raises(UnknownAccountError):
        final_lock_service.create(rm, FinalLock(**make_final_kwargs(rm.race_id, account="NOT-REGISTERED")))

    # 無効化(enabled=false)されたAccountも同様に拒否されることを確認する
    from rin_garden.core.account import AccountPolicy, AccountRegistry

    disabled_registry = AccountRegistry.from_policies(
        [AccountPolicy(id="DISABLED-ACCOUNT", enabled=False)]
    )
    with pytest.raises(UnknownAccountError):
        disabled_registry.get("DISABLED-ACCOUNT")


# --- 10. Ticketは必ずrace_id + accountに紐付く ---


def test_10_ticket_must_be_bound_to_race_id_and_account(make_race_master, ticket_service):
    rm = make_race_master(starts_in_minutes=60)

    ticket = Ticket(**make_ticket_kwargs(rm.race_id, account="FORCED-ALL", ticket_id="T-001"))
    created = ticket_service.create(rm, ticket)
    assert created.race_id == rm.race_id
    assert created.account == "FORCED-ALL"

    tickets = ticket_service.list_tickets(rm.sport, rm.date, rm.race_id, "FORCED-ALL")
    assert len(tickets) == 1
    assert tickets[0]["ticket_id"] == "T-001"

    # race_id不一致は拒否される
    with pytest.raises(IdentityMismatchError):
        ticket_service.create(rm, Ticket(**make_ticket_kwargs("some-other-race-id", account="FORCED-ALL")))

    # 未登録Accountは拒否される
    with pytest.raises(UnknownAccountError):
        ticket_service.create(rm, Ticket(**make_ticket_kwargs(rm.race_id, account="NOT-REGISTERED")))

    # 別Accountの同じticket_idは別レコードとして共存できる(race_id+accountで一意)
    other_account_ticket = ticket_service.create(
        rm, Ticket(**make_ticket_kwargs(rm.race_id, account="SELECT-B+", ticket_id="T-001"))
    )
    assert other_account_ticket.account == "SELECT-B+"
    assert len(ticket_service.list_tickets(rm.sport, rm.date, rm.race_id, "SELECT-B+")) == 1
    assert len(ticket_service.list_tickets(rm.sport, rm.date, rm.race_id, "FORCED-ALL")) == 1  # 影響なし

    # 同一race_id+account+ticket_idの再作成(異なる内容)は不変性違反として拒否される
    with pytest.raises(ImmutableRecordConflictError):
        ticket_service.create(
            rm, Ticket(**{**make_ticket_kwargs(rm.race_id, account="FORCED-ALL", ticket_id="T-001"), "stake": 9999})
        )
