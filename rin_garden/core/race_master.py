"""Race Master: 全競技共通のレース台帳。

Race IDまたはCanonical Locator(canonical_source + source_url + result_locator)を
中心にレース同一性を管理する。競技ごとの追加項目は `extra` に保持する。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rin_garden.core import storage
from rin_garden.core.timeutil import utcnow, to_iso


class RaceStatus:
    """Race Masterの状態遷移。settlement/audit以外での逆行を想定しない。"""

    SCHEDULED = "SCHEDULED"
    PRE_FIXED = "PRE_FIXED"
    FINAL_LOCKED = "FINAL_LOCKED"
    RESULT_LOCKED = "RESULT_LOCKED"
    SETTLED = "SETTLED"
    AUDITED = "AUDITED"


@dataclass
class RaceMaster:
    sport: str
    date: str
    venue: str
    race_number: int
    race_id: str
    event_id: str
    canonical_source: str
    source_url: str | None = None
    result_locator: str | None = None
    scheduled_start: str | None = None  # ISO8601, タイムゾーン付き
    status: str = RaceStatus.SCHEDULED
    pre_fixed_at: str | None = None
    final_locked_at: str | None = None
    result_locked_at: str | None = None
    settled_at: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def identity(self) -> dict[str, Any]:
        return {
            "sport": self.sport,
            "date": self.date,
            "venue": self.venue,
            "race_number": self.race_number,
            "race_id": self.race_id,
            "event_id": self.event_id,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "sport": self.sport,
            "date": self.date,
            "venue": self.venue,
            "race_number": self.race_number,
            "race_id": self.race_id,
            "event_id": self.event_id,
            "canonical_source": self.canonical_source,
            "source_url": self.source_url,
            "result_locator": self.result_locator,
            "scheduled_start": self.scheduled_start,
            "status": self.status,
            "pre_fixed_at": self.pre_fixed_at,
            "final_locked_at": self.final_locked_at,
            "result_locked_at": self.result_locked_at,
            "settled_at": self.settled_at,
            "extra": self.extra,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RaceMaster":
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**known)


class RaceMasterStore:
    """Race Masterの読み書きを担当する。data/normalized/{sport}/{date}/{race_id}.json。"""

    def __init__(self, normalized_dir: Path):
        self.normalized_dir = Path(normalized_dir)

    def _path(self, sport: str, date: str, race_id: str) -> Path:
        return self.normalized_dir / sport / date / f"{race_id}.json"

    def save(self, race_master: RaceMaster) -> None:
        storage.write_json(self._path(race_master.sport, race_master.date, race_master.race_id), race_master.to_dict())

    def load(self, sport: str, date: str, race_id: str) -> RaceMaster | None:
        data = storage.read_json_if_exists(self._path(sport, date, race_id))
        if data is None:
            return None
        return RaceMaster.from_dict(data)

    def list_race_ids(self, sport: str, date: str) -> list[str]:
        dir_path = self.normalized_dir / sport / date
        if not dir_path.exists():
            return []
        return sorted(p.stem for p in dir_path.glob("*.json"))

    def create_scheduled(
        self,
        sport: str,
        date: str,
        venue: str,
        race_number: int,
        race_id: str,
        event_id: str,
        canonical_source: str,
        scheduled_start: str,
        source_url: str | None = None,
        result_locator: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> RaceMaster:
        """新規Race Masterを冪等に作成する(既存があれば読み込んで返す)。"""
        existing = self.load(sport, date, race_id)
        if existing is not None:
            return existing
        rm = RaceMaster(
            sport=sport,
            date=date,
            venue=venue,
            race_number=race_number,
            race_id=race_id,
            event_id=event_id,
            canonical_source=canonical_source,
            source_url=source_url,
            result_locator=result_locator,
            scheduled_start=scheduled_start,
            status=RaceStatus.SCHEDULED,
            extra=extra or {},
        )
        self.save(rm)
        return rm
