"""FINAL-LOCK: 直前情報取得後の最終判断。

FINAL-LOCK後は印・評価・買い目・金額・BUY/WAIT/SKIPを直接上書きできない。
変更が必要な場合は `revise()` を使い、差分をrevision履歴として残す。
発走後のrevision・新規作成はNO POST-HOCにより禁止する。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from rin_garden.core import storage
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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class FinalLockService:
    """FINAL-LOCKの作成・revisionを担当する。"""

    def __init__(self, final_dir: Path, race_master_store: RaceMasterStore, audit_logger: AuditLogger):
        self.final_dir = Path(final_dir)
        self.race_master_store = race_master_store
        self.audit_logger = audit_logger

    def _path(self, sport: str, date: str, race_id: str) -> Path:
        return self.final_dir / sport / date / f"{race_id}.json"

    def _check_common(self, race_master: RaceMaster, final: FinalLock, now: str) -> None:
        try:
            verify_identity(race_master.identity(), {"race_id": final.race_id})
        except IdentityMismatchError as exc:
            self.audit_logger.log(
                OP_IDENTITY_MISMATCH, race_master.sport, race_master.race_id, "REJECTED", "final_lock", str(exc)
            )
            raise

        if race_master.status in (RaceStatus.RESULT_LOCKED, RaceStatus.SETTLED, RaceStatus.AUDITED):
            # scheduled_startの時計比較に依存しない多重防御: 結果が既に判明している
            # レースのFINAL-LOCK作成/改訂は、時刻がどうであれ無条件で拒否する。
            exc = PostHocBlockedError(
                f"race_id={race_master.race_id} already has a result (status={race_master.status}); "
                "FINAL-LOCK cannot be created or revised after the fact"
            )
            self.audit_logger.log(
                OP_POST_HOC_BLOCKED, race_master.sport, race_master.race_id, "REJECTED", "final_lock", str(exc)
            )
            raise exc

        if race_master.scheduled_start is None:
            raise ValueError("race_master.scheduled_start is required to enforce FINAL-LOCK timing")

    def create(self, race_master: RaceMaster, final: FinalLock, now: str | None = None) -> RaceMaster:
        """FINAL-LOCKを新規作成する。既に存在する場合は revise() を使うこと(直接上書き禁止)。"""
        now = now or to_iso(utcnow())
        self._check_common(race_master, final, now)

        path = self._path(race_master.sport, race_master.date, race_master.race_id)
        if path.exists():
            self.audit_logger.log(
                "WRITE_FAILED",
                race_master.sport,
                race_master.race_id,
                "REJECTED",
                "final_lock.create",
                "FINAL-LOCK already exists; direct overwrite is forbidden, use revise()",
            )
            raise FinalLockAlreadyExistsError(
                f"FINAL-LOCK already exists for race_id={race_master.race_id}; use revise() instead of create()"
            )

        try:
            enforce_final_lock_timing(race_master.scheduled_start, now)
        except PostHocBlockedError as exc:
            self.audit_logger.log(
                OP_POST_HOC_BLOCKED, race_master.sport, race_master.race_id, "REJECTED", "final_lock.create", str(exc)
            )
            raise

        record = {**final.to_dict(), "revisions": []}
        storage.write_json(path, record)

        race_master.final_locked_at = now
        race_master.status = RaceStatus.FINAL_LOCKED
        self.race_master_store.save(race_master)

        self.audit_logger.log(OP_FINAL_LOCKED, race_master.sport, race_master.race_id, "OK", "final_lock.create", "")
        return race_master

    def revise(
        self, race_master: RaceMaster, updated_final: FinalLock, reason: str, now: str | None = None
    ) -> dict[str, Any]:
        """既存FINAL-LOCKを改訂する。上書きではなくrevision履歴として差分を残す。

        発走時刻を過ぎている場合は無条件で拒否する(発走後のrevision禁止)。
        """
        now = now or to_iso(utcnow())
        self._check_common(race_master, updated_final, now)

        path = self._path(race_master.sport, race_master.date, race_master.race_id)
        existing = storage.read_json_if_exists(path)
        if existing is None:
            raise FileNotFoundError(f"no existing FINAL-LOCK to revise for race_id={race_master.race_id}")

        try:
            enforce_no_revision_after_start(race_master.scheduled_start, now)
        except PostHocBlockedError as exc:
            self.audit_logger.log(
                OP_POST_HOC_BLOCKED, race_master.sport, race_master.race_id, "REJECTED", "final_lock.revise", str(exc)
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
            OP_FINAL_REVISED, race_master.sport, race_master.race_id, "OK", "final_lock.revise", reason
        )
        return record

    def load(self, sport: str, date: str, race_id: str) -> dict[str, Any] | None:
        return storage.read_json_if_exists(self._path(sport, date, race_id))
