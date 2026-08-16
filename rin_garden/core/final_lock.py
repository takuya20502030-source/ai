"""FINAL-LOCK: 直前情報取得後の最終判断。

race_id + account を一意キーとする。共通PRE-FIXから、Account(FORCED-ALL /
SELECT-B+ / FLEX-ALL / FLEX-SELECT等、`config/accounts.yaml` で定義)ごとに
独立したFINAL-LOCKが1レースに複数存在してよい。Account Aの変更はAccount Bへ
一切影響しない(ファイルも完全に分離される)。

FINAL-LOCK後は印・評価・買い目・金額・BUY/WAIT/SKIPを直接上書きできない。
変更が必要な場合は `revise()` を使い、差分をrevision履歴として残す。
発走後のrevision・新規作成はNO POST-HOCにより禁止する(Account単位でも例外なし)。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from rin_garden.core import storage
from rin_garden.core.account import AccountRegistry, UnknownAccountError
from rin_garden.core.identity import IdentityMismatchError, verify_identity
from rin_garden.core.locks import PostHocBlockedError, enforce_final_lock_timing, enforce_no_revision_after_start
from rin_garden.core.logging import (
    AuditLogger,
    OP_FINAL_LOCKED,
    OP_FINAL_REVISED,
    OP_IDENTITY_MISMATCH,
    OP_POST_HOC_BLOCKED,
)
from rin_garden.core.race_master import RaceMaster, RaceMasterStore, RaceStatus
from rin_garden.core.timeutil import to_iso, utcnow

DEFAULT_ACCOUNT = "DEFAULT"


class FinalLockAlreadyExistsError(Exception):
    """既にFINAL-LOCKが存在する状態で create() (直接上書き)を試みた場合に送出する。"""


@dataclass
class FinalLock:
    race_id: str
    timestamp: str
    marks: dict[str, Any]
    evaluation: dict[str, Any]
    bets: list[dict[str, Any]]
    amounts: dict[str, Any]
    decision: str  # "BUY" | "WAIT" | "SKIP"
    account: str = DEFAULT_ACCOUNT

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class FinalLockService:
    """FINAL-LOCKの作成・revisionを担当する(race_id + account単位)。"""

    def __init__(
        self,
        final_dir: Path,
        race_master_store: RaceMasterStore,
        audit_logger: AuditLogger,
        account_registry: AccountRegistry,
    ):
        self.final_dir = Path(final_dir)
        self.race_master_store = race_master_store
        self.audit_logger = audit_logger
        self.account_registry = account_registry

    def _path(self, sport: str, date: str, race_id: str, account: str) -> Path:
        return self.final_dir / sport / date / race_id / f"{account}.json"

    def _check_common(self, race_master: RaceMaster, final: FinalLock, now: str) -> None:
        try:
            verify_identity(race_master.identity(), {"race_id": final.race_id})
        except IdentityMismatchError as exc:
            self.audit_logger.log(
                OP_IDENTITY_MISMATCH,
                race_master.sport,
                race_master.race_id,
                "REJECTED",
                "final_lock",
                str(exc),
                account=final.account,
            )
            raise

        try:
            self.account_registry.get(final.account)
        except UnknownAccountError as exc:
            self.audit_logger.log(
                "WRITE_FAILED",
                race_master.sport,
                race_master.race_id,
                "REJECTED",
                "final_lock",
                str(exc),
                account=final.account,
            )
            raise

        if race_master.status in (RaceStatus.RESULT_LOCKED, RaceStatus.SETTLED, RaceStatus.AUDITED):
            # scheduled_startの時計比較に依存しない多重防御: 結果が既に判明している
            # レースのFINAL-LOCK作成/改訂は、Accountがどれであっても・時刻がどうであれ
            # 無条件で拒否する。
            exc = PostHocBlockedError(
                f"race_id={race_master.race_id} already has a result (status={race_master.status}); "
                "FINAL-LOCK cannot be created or revised after the fact"
            )
            self.audit_logger.log(
                OP_POST_HOC_BLOCKED,
                race_master.sport,
                race_master.race_id,
                "REJECTED",
                "final_lock",
                str(exc),
                account=final.account,
            )
            raise exc

        if race_master.scheduled_start is None:
            raise ValueError("race_master.scheduled_start is required to enforce FINAL-LOCK timing")

    def create(self, race_master: RaceMaster, final: FinalLock, now: str | None = None) -> RaceMaster:
        """FINAL-LOCKを新規作成する(race_id + account単位)。

        既に同じ race_id + account の組み合わせで存在する場合は revise() を
        使うこと(直接上書き禁止)。同一race_idの別Accountには一切影響しない。
        """
        now = now or to_iso(utcnow())
        self._check_common(race_master, final, now)

        path = self._path(race_master.sport, race_master.date, race_master.race_id, final.account)
        if path.exists():
            self.audit_logger.log(
                "WRITE_FAILED",
                race_master.sport,
                race_master.race_id,
                "REJECTED",
                "final_lock.create",
                "FINAL-LOCK already exists for this race_id+account; direct overwrite is forbidden, use revise()",
                account=final.account,
            )
            raise FinalLockAlreadyExistsError(
                f"FINAL-LOCK already exists for race_id={race_master.race_id} account={final.account}; "
                "use revise() instead of create()"
            )

        try:
            enforce_final_lock_timing(race_master.scheduled_start, now)
        except PostHocBlockedError as exc:
            self.audit_logger.log(
                OP_POST_HOC_BLOCKED,
                race_master.sport,
                race_master.race_id,
                "REJECTED",
                "final_lock.create",
                str(exc),
                account=final.account,
            )
            raise

        record = {**final.to_dict(), "revisions": []}
        storage.write_json(path, record)

        # RaceMasterはレース単位(1 race_id = 1 race)のまま、Accountごとに複製しない。
        # 「このレースで少なくとも1つのFINAL-LOCKが確定した」という最初の時点のみ記録する
        # (以後の別Accountの作成ではfinal_locked_at/statusを上書きしない=冪等)。
        if race_master.final_locked_at is None:
            race_master.final_locked_at = now
            race_master.status = RaceStatus.FINAL_LOCKED
            self.race_master_store.save(race_master)

        self.audit_logger.log(
            OP_FINAL_LOCKED, race_master.sport, race_master.race_id, "OK", "final_lock.create", "", account=final.account
        )
        return race_master

    def revise(
        self, race_master: RaceMaster, updated_final: FinalLock, reason: str, now: str | None = None
    ) -> dict[str, Any]:
        """既存FINAL-LOCK(race_id + account)を改訂する。上書きではなくrevision履歴として
        差分を残す。他のAccountのFINAL-LOCKには一切影響しない。

        発走時刻を過ぎている場合は無条件で拒否する(発走後のrevision禁止)。
        """
        now = now or to_iso(utcnow())
        self._check_common(race_master, updated_final, now)

        path = self._path(race_master.sport, race_master.date, race_master.race_id, updated_final.account)
        existing = storage.read_json_if_exists(path)
        if existing is None:
            raise FileNotFoundError(
                f"no existing FINAL-LOCK to revise for race_id={race_master.race_id} account={updated_final.account}"
            )

        try:
            enforce_no_revision_after_start(race_master.scheduled_start, now)
        except PostHocBlockedError as exc:
            self.audit_logger.log(
                OP_POST_HOC_BLOCKED,
                race_master.sport,
                race_master.race_id,
                "REJECTED",
                "final_lock.revise",
                str(exc),
                account=updated_final.account,
            )
            raise

        previous_snapshot = {k: v for k, v in existing.items() if k != "revisions"}
        revisions = existing.get("revisions", [])
        revisions.append(
            {
                "revised_at": now,
                "reason": reason,
                "previous": previous_snapshot,
            }
        )
        record = {**updated_final.to_dict(), "revisions": revisions}
        storage.write_json(path, record)

        self.audit_logger.log(
            OP_FINAL_REVISED,
            race_master.sport,
            race_master.race_id,
            "OK",
            "final_lock.revise",
            reason,
            account=updated_final.account,
        )
        return record

    def load(self, sport: str, date: str, race_id: str, account: str = DEFAULT_ACCOUNT) -> dict[str, Any] | None:
        return storage.read_json_if_exists(self._path(sport, date, race_id, account))

    def list_accounts(self, sport: str, date: str, race_id: str) -> list[str]:
        """指定レースについて、実際にFINAL-LOCKが作成済みのAccount一覧を返す。"""
        dir_path = self.final_dir / sport / date / race_id
        if not dir_path.exists():
            return []
        return sorted(p.stem for p in dir_path.glob("*.json"))
