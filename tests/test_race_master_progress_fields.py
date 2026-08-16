"""RaceMaster.final_locked_at / settled_at の意味を明確化するテスト。

これらは「レース全体で最初にどこかのAccountがその状態へ到達した時刻」という
進捗参考値であり、Account固有の正式なFINAL-LOCK/SETTLEMENT時刻の正本ではない。
Account固有の監査・NO POST-HOC判定には、必ず各FinalLock/Settlementレコード
自身のtimestamp/settled_atを使うこと(race_master側の値と乖離しうる)。
"""

from __future__ import annotations

from rin_garden.core.final_lock import FinalLock
from rin_garden.settlement.result_loader import Result
from rin_garden.core.timeutil import to_iso, utcnow
from tests.conftest import make_final_kwargs


def test_final_locked_at_reflects_first_account_only_and_does_not_move_for_later_accounts(
    make_race_master, final_lock_service
):
    rm = make_race_master(starts_in_minutes=60)

    final_a = FinalLock(**make_final_kwargs(rm.race_id, account="FORCED-ALL"))
    final_b = FinalLock(**make_final_kwargs(rm.race_id, account="SELECT-B+"))

    t0 = to_iso(utcnow())
    rm = final_lock_service.create(rm, final_a, now=t0)
    assert rm.final_locked_at == t0

    t1 = to_iso(utcnow())
    assert t1 != t0
    rm = final_lock_service.create(rm, final_b, now=t1)

    # race_master.final_locked_at は最初のAccount(FORCED-ALL)の時刻のまま変化しない
    assert rm.final_locked_at == t0
    assert rm.final_locked_at != t1

    # Account固有の正式な時刻は、それぞれのFinalLockレコード自身が持つ
    stored_a = final_lock_service.load(rm.sport, rm.date, rm.race_id, account="FORCED-ALL")
    stored_b = final_lock_service.load(rm.sport, rm.date, rm.race_id, account="SELECT-B+")
    assert stored_a["timestamp"] == final_a.timestamp
    assert stored_b["timestamp"] == final_b.timestamp
    # SELECT-B+のFINAL-LOCKはt1(create()呼び出し時刻)に行われたが、
    # race_master.final_locked_atはt0のまま=race_master側の値だけを見て
    # SELECT-B+の確定タイミングを判断してはならないことを示す。


def test_settled_at_reflects_first_account_only_and_does_not_move_for_later_accounts(
    make_race_master, final_lock_service, result_loader_service, settlement_service
):
    rm = make_race_master(starts_in_minutes=60)
    final_a = FinalLock(**make_final_kwargs(rm.race_id, account="FORCED-ALL"))
    final_b = FinalLock(**make_final_kwargs(rm.race_id, account="SELECT-B+"))
    rm = final_lock_service.create(rm, final_a)
    rm = final_lock_service.create(rm, final_b)

    result = Result(race_id=rm.race_id, timestamp=to_iso(utcnow()), order=["1"], payouts={"1": 200.0})
    rm = result_loader_service.load_result(rm, result)

    t0 = to_iso(utcnow())
    settlement_a = settlement_service.settle(rm, final_a.to_dict(), result.to_dict(), now=t0)
    assert rm.settled_at == t0

    t1 = to_iso(utcnow())
    assert t1 != t0
    settlement_b = settlement_service.settle(rm, final_b.to_dict(), result.to_dict(), now=t1)

    # race_master.settled_at は最初に精算されたAccount(FORCED-ALL)の時刻のまま
    assert rm.settled_at == t0
    # SELECT-B+自身の精算記録は独自のsettled_atを持ち、race_master側とは乖離しうる
    assert settlement_b.settled_at == t1
    assert settlement_b.settled_at != rm.settled_at
    assert settlement_a.settled_at == rm.settled_at  # 最初のAccountはたまたま一致する
