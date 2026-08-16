"""GARDEN-6: 6人の独立分析担当による多角的分析と、凜による統合。

人格・口調の定義は `agents/*.md` を正とする。ここではその構造(誰が何を担当し、
最終的にどう統合されるか)のみを扱う。実際の分析内容(LLMによる推論結果)は
呼び出し側が `MemberFinding` として渡す想定であり、このモジュール自体は
推論を行わない。

全員が同じ結論へ寄せるのではなく、独立分析→最後に凜が統合する構造を守ること。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from rin_garden.analysis.ranking import validate_chaos, validate_rank
from rin_garden.analysis.value import Decision, ValueAssessment, decide
from rin_garden.core.validation import DataConfidence

MEMBER_IDS = ("rin", "miuka", "kana", "erisa", "kurone", "luna")

MEMBER_ROLES = {
    "rin": "総合責任者・最終決裁",
    "miuka": "データ担当",
    "kana": "現場担当",
    "erisa": "監査担当",
    "kurone": "穴・シナリオ担当",
    "luna": "検証担当",
}

MEMBER_NAMES = {
    "rin": "凜",
    "miuka": "美羽香",
    "kana": "花奈",
    "erisa": "英梨紗",
    "kurone": "黒音",
    "luna": "瑠那",
}


@dataclass
class MemberFinding:
    """GARDEN-6の1メンバーによる独立分析結果。"""

    member_id: str
    comment: str
    data_confidence: str = DataConfidence.CONFIRMED
    structured: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.member_id not in MEMBER_IDS:
            raise ValueError(f"unknown GARDEN-6 member_id: {self.member_id!r}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "member_id": self.member_id,
            "member_name": MEMBER_NAMES[self.member_id],
            "role": MEMBER_ROLES[self.member_id],
            "comment": self.comment,
            "data_confidence": self.data_confidence,
            "structured": self.structured,
        }


@dataclass
class Garden6Analysis:
    """凜が統合した最終分析結果。"""

    race_id: str
    findings: list[MemberFinding]
    rank: str
    chaos: float
    confidence: str
    decision: str
    value: ValueAssessment | None = None
    rin_summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "race_id": self.race_id,
            "findings": [f.to_dict() for f in self.findings],
            "rank": self.rank,
            "chaos": self.chaos,
            "confidence": self.confidence,
            "decision": self.decision,
            "value": None
            if self.value is None
            else {
                "estimated_probability": self.value.estimated_probability,
                "fair_odds": self.value.fair_odds,
                "market_odds": self.value.market_odds,
                "expected_value": self.value.expected_value,
            },
            "rin_summary": self.rin_summary,
        }


def integrate(
    race_id: str,
    findings: list[MemberFinding],
    rank: str,
    chaos: float,
    value: ValueAssessment | None = None,
    rin_summary: str = "",
    min_expected_value_to_buy: float = 1.05,
    high_chaos_threshold: float = 7,
) -> Garden6Analysis:
    """各メンバーの独立分析を凜が統合し、最終判断(rank/chaos/decision)を確定する。

    - データ不足のfindingが1件でもあれば confidence は DATA_INCOMPLETE に倒す。
    - decisionは value が与えられていれば機械的な期待値判定を出発点とし、
      与えられていなければ WAIT とする(材料不足で断定しない)。
    """
    validate_rank(rank)
    validate_chaos(chaos)

    if any(f.data_confidence == DataConfidence.INCOMPLETE for f in findings):
        confidence = DataConfidence.INCOMPLETE
    elif any(f.data_confidence == DataConfidence.ESTIMATED for f in findings):
        confidence = DataConfidence.ESTIMATED
    else:
        confidence = DataConfidence.CONFIRMED

    if value is None or confidence == DataConfidence.INCOMPLETE:
        decision = Decision.WAIT
    else:
        decision = decide(
            value,
            chaos,
            min_expected_value_to_buy=min_expected_value_to_buy,
            high_chaos_threshold=high_chaos_threshold,
        )

    return Garden6Analysis(
        race_id=race_id,
        findings=findings,
        rank=rank,
        chaos=chaos,
        confidence=confidence,
        decision=decision,
        value=value,
        rin_summary=rin_summary,
    )
