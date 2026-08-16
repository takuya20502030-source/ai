"""予想シナリオ(黒音の担当領域)。事実・推測・シナリオを分離して扱う。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Scenario:
    """1つの展開シナリオ。事実に基づく根拠(evidence)と、それに対する推測を分離する。"""

    label: str
    description: str
    evidence: list[str] = field(default_factory=list)
    in_collapse: bool = False  # BOAT RACE: イン逃げ崩れ等の"IN COLLAPSE"想定
    probability_hint: float | None = None  # 0-1の目安。無ければ確信度を明示しないこと

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "description": self.description,
            "evidence": self.evidence,
            "in_collapse": self.in_collapse,
            "probability_hint": self.probability_hint,
        }
