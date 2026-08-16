"""RaceSnapshot: GARDEN-6の6担当全員へ同一内容で渡されるレース時点データ。

Collectorが取得した(または`load_*_from_file`で取り込んだ)データをそのまま
保持する入れ物であり、ここでは推論・加工を行わない。事実(取得データ)と
推測を分離するため、confidenceはCollectorResultのものをそのまま引き継ぐ。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from rin_garden.core.validation import DataConfidence


@dataclass
class RaceSnapshot:
    race_id: str
    sport: str
    captured_at: str
    race_card: dict[str, Any] = field(default_factory=dict)
    market_odds: dict[str, Any] = field(default_factory=dict)
    live_data: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] | None = None
    source_confidence: str = DataConfidence.CONFIRMED

    def to_dict(self) -> dict[str, Any]:
        return {
            "race_id": self.race_id,
            "sport": self.sport,
            "captured_at": self.captured_at,
            "race_card": self.race_card,
            "market_odds": self.market_odds,
            "live_data": self.live_data,
            "result": self.result,
            "source_confidence": self.source_confidence,
        }

    def entrants(self) -> list[dict[str, Any]]:
        return self.race_card.get("entrants", [])
