"""結果(Result)の登録。予想処理(PRE/FINAL)とは完全に分離し、それらを書き換えない。

PENDING -> RESULT_LOCKED -> SETTLED -> AUDITED の最初の遷移を担当する。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from rin_garden.core import storage
from rin_garden.core.identity import IdentityMismatchError, verify_identity
from rin_garden.core.logging import AuditLogger, OP_IDENTITY_MISMATCH, OP_RESULT_LOCKED, OP_WRITE_FAILED
from rin_garden.core.race_master import RaceMaster, RaceMasterStore, RaceStatus
from rin_garden.core.timeutil import to_iso, utcnow


@dataclass
class Result:
    race_id: str
    timestamp: str
    order: list[Any]
    payouts: dict[str, float]
    raw_source: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ResultAlreadySettledError(Exception):
    """精算済みレースのResultを再登録しようとした場合に送出する。"""


class ResultLoaderService:
    def __init__(self, results_dir: Path, race_master_store: RaceMasterStore, audit_logger: AuditLogger):
        self.results_dir = Path(results_dir)
        self.race_master_store = race_master_store
        self.audit_logger = audit_logger

    def _path(self, sport: str, date: str, race_id: str) -> Path:
        return self.results_dir / sport / date / race_id / "result.json"

    def load_result(self, race_master: RaceMaster, result: Result, now: str | None = None) -> RaceMaster:
        now = now or to_iso(utcnow())
        try:
            verify_identity(race_master.identity(), {"race_id": result.race_id})
        except IdentityMismatchError as exc:
            self.audit_logger.log(
                OP_IDENTITY_MISMATCH, race_master.sport, race_master.race_id, "REJECTED", "result_loader", str(exc)
            )
            raise

        if race_master.status in (RaceStatus.SETTLED, RaceStatus.AUDITED):
            self.audit_logger.log(
                OP_WRITE_FAILED,
                race_master.sport,
                race_master.race_id,
                "REJECTED",
                "result_loader",
                "cannot reload result for an already settled race",
            )
            raise ResultAlreadySettledError(f"race_id={race_master.race_id} is already settled")

        storage.write_json(self._path(race_master.sport, race_master.date, race_master.race_id), result.to_dict())

        race_master.status = RaceStatus.RESULT_LOCKED
        race_master.result_locked_at = now
        self.race_master_store.save(race_master)

        self.audit_logger.log(OP_RESULT_LOCKED, race_master.sport, race_master.race_id, "OK", "result_loader", "")
        return race_master

    def load(self, sport: str, date: str, race_id: str) -> dict[str, Any] | None:
        return storage.read_json_if_exists(self._path(sport, date, race_id))
