"""VALUE思想: 人気順ではなく、推定確率と市場オッズの差で評価する。

estimated_probability(推定勝率) / fair_odds(公正オッズ) / market_odds(市場オッズ) /
expected_value(期待値) を扱う。人気薄だから買う・人気馬だから切る、という判断はしない。
"""

from __future__ import annotations

from dataclasses import dataclass


class Decision:
    BUY = "BUY"
    WAIT = "WAIT"
    SKIP = "SKIP"


def fair_odds(estimated_probability: float) -> float:
    """推定勝率から公正オッズ(手数料等を考慮しない理論オッズ)を求める。"""
    if not (0 < estimated_probability <= 1):
        raise ValueError(f"estimated_probability must be in (0, 1]: {estimated_probability!r}")
    return 1.0 / estimated_probability


def expected_value(estimated_probability: float, market_odds: float) -> float:
    """期待値 = 推定勝率 × 市場オッズ。1.0が損益分岐点。"""
    if not (0 < estimated_probability <= 1):
        raise ValueError(f"estimated_probability must be in (0, 1]: {estimated_probability!r}")
    if market_odds <= 0:
        raise ValueError(f"market_odds must be positive: {market_odds!r}")
    return estimated_probability * market_odds


@dataclass
class ValueAssessment:
    estimated_probability: float
    fair_odds: float
    market_odds: float
    expected_value: float

    @classmethod
    def build(cls, estimated_probability: float, market_odds: float) -> "ValueAssessment":
        return cls(
            estimated_probability=estimated_probability,
            fair_odds=fair_odds(estimated_probability),
            market_odds=market_odds,
            expected_value=expected_value(estimated_probability, market_odds),
        )


def decide(
    value: ValueAssessment,
    chaos: float,
    min_expected_value_to_buy: float = 1.05,
    high_chaos_threshold: float = 7,
) -> str:
    """期待値としきい値からBUY/WAIT/SKIPを決定する。

    これは補助的な機械的判断であり、GARDEN-6(特に凜)の最終判断を置き換えるものではない。
    """
    if value.expected_value < 1.0:
        return Decision.SKIP
    if value.expected_value < min_expected_value_to_buy:
        return Decision.WAIT
    if chaos > high_chaos_threshold:
        return Decision.WAIT
    return Decision.BUY
