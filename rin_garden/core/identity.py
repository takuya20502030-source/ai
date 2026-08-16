"""Race Identity: レースの同一性を厳密に管理する。

「8月16日 中京11R」のような日付+会場+R番号だけを主キーにしない。
`race_id` は sport/date/venue/race_number/event_id から決定的に生成し、
`event_id`(データソース側の一次識別子)と組み合わせて同一性を検証する。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any


class IdentityMismatchError(Exception):
    """異なるレースのデータが混入しようとした場合に送出する。"""


IDENTITY_FIELDS = ("sport", "date", "venue", "race_number", "race_id", "event_id")


def build_race_id(sport: str, date: str, venue: str, race_number: int, event_id: str) -> str:
    """sport/date/venue/race_number/event_idから決定的なrace_idを生成する。

    同じ入力からは常に同じrace_idが生成される(冪等性)。event_idを含めることで、
    単純な日付+会場+R番号の一致だけでは同一レースと誤認しないようにする。
    """
    if not event_id:
        raise ValueError("event_id is required to build a race_id (do not key races on date+venue+R only)")
    raw = "|".join([sport.strip().lower(), date.strip(), venue.strip(), str(race_number), event_id.strip()])
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"{sport.strip().upper()}-{date.strip()}-{digest[:16]}"


@dataclass(frozen=True)
class RaceIdentity:
    """レース同一性検証に必要な最小フィールドの集合。"""

    sport: str
    date: str
    venue: str
    race_number: int
    race_id: str
    event_id: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "sport": self.sport,
            "date": self.date,
            "venue": self.venue,
            "race_number": self.race_number,
            "race_id": self.race_id,
            "event_id": self.event_id,
        }


def verify_identity(expected: dict[str, Any], candidate: dict[str, Any]) -> None:
    """expected(Race Masterなど正データ)とcandidate(書き込もうとしているデータ)の
    Identityフィールドが完全一致することを検証する。1つでも不一致なら
    IdentityMismatchErrorを送出する。R番号だけの一致では合格としない。
    """
    mismatches = []
    for field_name in IDENTITY_FIELDS:
        if field_name not in candidate:
            continue
        if expected.get(field_name) != candidate.get(field_name):
            mismatches.append((field_name, expected.get(field_name), candidate.get(field_name)))
    if mismatches:
        detail = ", ".join(f"{f}: expected={e!r} actual={a!r}" for f, e, a in mismatches)
        raise IdentityMismatchError(f"race identity mismatch: {detail}")
