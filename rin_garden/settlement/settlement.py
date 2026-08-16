"""精算(Settlement)。PRE/FINALを一切書き換えず、Resultから払戻・Profit・ROIを計算する。

race_id + account を一意キーとする。Resultはレース単位で1件のみだが、
Accountごとに独立して精算し、Profit/ROIもAccountごとに独立して計算する
(同じResultを参照しても、Account Aの計算がAccount Bへ影響することはない)。

RESULT_LOCKED -> SETTLED の遷移を担当する。

金額の単位は日本の公営競技の慣習に合わせ、`amounts` はbet_keyごとの購入金額(円)、
`payouts` はbet_keyごとの100円あたり払戻金(円)として扱う。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from rin_garden.core import storage
from rin_garden.core.account import AccountRegistry, UnknownAccountError
from rin_garden.core.final_lock import DEFAULT_ACCOUNT
from rin_garden.core.logging import AuditLogger, OP_SETTLED
from rin_garden.core.race_master import RaceMaster, RaceMasterStore, RaceStatus
from rin_garden.core.timeutil import to_iso, utcnow


@dataclass
class Settlement:
    race_id: str
    account: str
    settled_at: str
    decision: str
    stake: float
    payout: float
    profit: float
    roi: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def compute_payout(amounts: dict[str, float], payouts: dict[str, float]) -> tuple[float, float]:
    """amounts(bet_keyごとの購入金額)とpayouts(bet_keyごとの100円あたり払戻金)から
    (stake合計, payout合計)を計算する。的中していないbet_keyのpayoutは0として扱う。
    """
    stake = sum(amounts.values())
    payout = sum(amounts[key] / 100.0 * payouts.get(key, 0.0) for key in amounts)
    return stake, payout


class SettlementService:
    def __init__(
        self,
        results_dir: Path,
        race_master_store: RaceMasterStore,
        audit_logger: AuditLogger,
        account_registry: AccountRegistry,
    ):
        self.results_dir = Path(results_dir)
        self.race_master_store = race_master_store
        self.audit_logger = audit_logger
        self.account_registry = account_registry

    def _path(self, sport: str, date: str, race_id: str, account: str) -> Path:
        return self.results_dir / sport / date / race_id / "settlement" / f"{account}.json"

    def settle(
        self,
        race_master: RaceMaster,
        final: dict[str, Any],
        result: dict[str, Any],
        now: str | None = None,
    ) -> Settlement:
        """RESULT_LOCKED状態のレースを、finalが指すAccountについて精算する。

        冪等: 同一race_id+accountで既にSETTLED記録があれば既存記録を返す。
        他のAccountの精算記録には一切影響しない。
        """
        now = now or to_iso(utcnow())
        account = final.get("account") or DEFAULT_ACCOUNT

        try:
            self.account_registry.get(account)
        except UnknownAccountError as exc:
            self.audit_logger.log(
                "WRITE_FAILED",
                race_master.sport,
                race_master.race_id,
                "REJECTED",
                "settlement.settle",
                str(exc),
                account=account,
            )
            raise

        if race_master.status not in (RaceStatus.RESULT_LOCKED, RaceStatus.SETTLED, RaceStatus.AUDITED):
            raise ValueError(
                f"race_id={race_master.race_id} must be RESULT_LOCKED before settlement "
                f"(current status={race_master.status})"
            )

        path = self._path(race_master.sport, race_master.date, race_master.race_id, account)
        existing = storage.read_json_if_exists(path)
        if existing is not None:
            return Settlement(**existing)

        amounts: dict[str, float] = final.get("amounts", {})
        payouts: dict[str, float] = result.get("payouts", {})
        stake, payout = compute_payout(amounts, payouts)
        profit = payout - stake
        roi = (profit / stake) if stake > 0 else 0.0

        settlement = Settlement(
            race_id=race_master.race_id,
            account=account,
            settled_at=now,
            decision=final.get("decision", "SKIP"),
            stake=stake,
            payout=payout,
            profit=profit,
            roi=roi,
        )
        storage.write_json(path, settlement.to_dict())

        # RaceMasterはレース単位のまま。settled_atは「最初にどこかのAccountが
        # SETTLEDへ到達した時刻」という進捗参考値であり、Account固有の正式な
        # 精算時刻ではない(Account固有の正本は上のsettlementの settled_at
        # フィールドを参照すること。詳細は race_master.py のコメントを参照)。
        # 以後の別Accountの精算ではsettled_at/statusを上書きしない(=冪等)。
        if race_master.status == RaceStatus.RESULT_LOCKED:
            race_master.status = RaceStatus.SETTLED
            race_master.settled_at = now
            self.race_master_store.save(race_master)

        self.audit_logger.log(
            OP_SETTLED, race_master.sport, race_master.race_id, "OK", "settlement.settle", "", account=account
        )
        return settlement

    def load(self, sport: str, date: str, race_id: str, account: str = DEFAULT_ACCOUNT) -> dict[str, Any] | None:
        return storage.read_json_if_exists(self._path(sport, date, race_id, account))

    def list_accounts(self, sport: str, date: str, race_id: str) -> list[str]:
        """指定レースについて、実際に精算済みのAccount一覧を返す。"""
        dir_path = self.results_dir / sport / date / race_id / "settlement"
        if not dir_path.exists():
            return []
        return sorted(p.stem for p in dir_path.glob("*.json"))
