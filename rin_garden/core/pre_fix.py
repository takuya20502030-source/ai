"""PRE-FIX: 結果を知らない時点で作成した予想の原本。

一度保存すると通常処理からは変更できない(immutable)。NO POST-HOCの中核。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from rin_garden.core import storage
from rin_garden.core.identity import IdentityMismatchError, verify_identity
from rin_garden.core.locks import PostHocBlockedError, enforce_pre_fix_timing
from rin_garden.core.logging import AuditLogger, OP_IDENTITY_MISMATCH, OP_POST_HOC_BLOCKED, OP_PRE_FIXED, OP_WRITE_FAILED
from rin_garden.core.race_master import RaceMaster, RaceMasterStore, RaceStatus
from rin_garden.core.storage import ImmutableRecordConflictError
from rin_garden.core.timeutil import to_iso, utcnow


@dataclass
class PreFix:
    race_id: str
    timestamp: str
    data_snapshot: dict[str, Any]
    garden6_analysis: dict[str, Any]
    rank: str
    chaos: float
    confidence: str
    predicted_scenario: dict[str, Any]
    bets: list[dict[str, Any]]
    fair_probability: dict[str, Any]
    fair_odds: dict[str, Any]
    market_odds: dict[str, Any]
    expected_value: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PreFixService:
    """PRE-FIXの作成を担当する。作成は不変(immutable)かつPOST_HOC禁止。"""

    def __init__(self, pre_dir: Path, race_master_store: RaceMasterStore, audit_logger: AuditLogger):
        self.pre_dir = Path(pre_dir)
        self.race_master_store = race_master_store
        self.audit_logger = audit_logger

    def _path(self, sport: str, date: str, race_id: str) -> Path:
        return self.pre_dir / sport / date / f"{race_id}.json"

    def create(self, race_master: RaceMaster, pre: PreFix, now: str | None = None) -> RaceMaster:
        """PRE-FIXを作成する。

        - 発走予定時刻より後であれば PostHocBlockedError。
        - race_masterとpreのidentityが一致しなければ IdentityMismatchError。
        - 既に同一内容のPREがあれば冪等にNo-op、異なる内容があれば
          ImmutableRecordConflictError(=改変禁止)。
        """
        now = now or to_iso(utcnow())

        try:
            verify_identity(race_master.identity(), {"race_id": pre.race_id})
        except IdentityMismatchError as exc:
            self.audit_logger.log(
                OP_IDENTITY_MISMATCH, race_master.sport, race_master.race_id, "REJECTED", "pre_fix.create", str(exc)
            )
            raise

        if race_master.status in (RaceStatus.RESULT_LOCKED, RaceStatus.SETTLED, RaceStatus.AUDITED):
            # scheduled_startの時計比較に依存しない多重防御: 結果が既に判明している
            # レースへのPRE新規作成は、時刻がどうであれ無条件で拒否する。
            exc = PostHocBlockedError(
                f"race_id={race_master.race_id} already has a result (status={race_master.status}); "
                "PRE-FIX cannot be created after the fact"
            )
            self.audit_logger.log(
                OP_POST_HOC_BLOCKED, race_master.sport, race_master.race_id, "REJECTED", "pre_fix.create", str(exc)
            )
            raise exc

        if race_master.scheduled_start is None:
            raise ValueError("race_master.scheduled_start is required to enforce PRE-FIX timing")

        try:
            enforce_pre_fix_timing(race_master.scheduled_start, now)
        except PostHocBlockedError as exc:
            self.audit_logger.log(
                OP_POST_HOC_BLOCKED, race_master.sport, race_master.race_id, "REJECTED", "pre_fix.create", str(exc)
            )
            raise

        path = self._path(race_master.sport, race_master.date, race_master.race_id)
        try:
            storage.write_json_once(path, pre.to_dict())
        except ImmutableRecordConflictError as exc:
            self.audit_logger.log(
                OP_WRITE_FAILED, race_master.sport, race_master.race_id, "REJECTED", "pre_fix.create", str(exc)
            )
            raise

        if race_master.pre_fixed_at is None:
            race_master.pre_fixed_at = now
            race_master.status = RaceStatus.PRE_FIXED
            self.race_master_store.save(race_master)

        self.audit_logger.log(OP_PRE_FIXED, race_master.sport, race_master.race_id, "OK", "pre_fix.create", "")
        return race_master

    def load(self, sport: str, date: str, race_id: str) -> dict[str, Any] | None:
        return storage.read_json_if_exists(self._path(sport, date, race_id))
