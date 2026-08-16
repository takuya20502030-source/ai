"""競技別Collectorの共通Interface。

公式API・正規データソースを優先し、Webサイト構造へ強く依存する脆弱な
スクレイピングは最後の手段とする。利用規約・robots制限を無視する処理は
実装しない。取得できない情報は補完せず `DATA_INCOMPLETE` として明示する。

このモジュールは取得インターフェースのみを定義する。各競技の本格的な
取得ロジックは `rin_garden/collectors/{sport}/collector.py` で実装する
(初回構築ではダミー実装のみ)。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from rin_garden.core.validation import DataConfidence


@dataclass
class CollectorResult:
    """Collectorの各メソッドが返す共通の結果コンテナ。

    データが取得できなかった場合でも例外にせず、confidence=DATA_INCOMPLETE と
    してこのコンテナで返す(取得不能情報を推測で埋めないため)。
    """

    ok: bool
    confidence: str
    data: Any = None
    source: str | None = None
    message: str = ""

    @classmethod
    def incomplete(cls, message: str, source: str | None = None) -> "CollectorResult":
        return cls(ok=False, confidence=DataConfidence.INCOMPLETE, data=None, source=source, message=message)

    @classmethod
    def confirmed(cls, data: Any, source: str) -> "CollectorResult":
        return cls(ok=True, confidence=DataConfidence.CONFIRMED, data=data, source=source, message="")


class BaseCollector(ABC):
    """競技別Collectorが実装すべき共通Interface。"""

    sport: str

    @abstractmethod
    def get_schedule(self, date: str) -> CollectorResult:
        """指定日の開催スケジュール(競技場・レース数等)を取得する。"""

    @abstractmethod
    def get_race_card(self, race_id: str) -> CollectorResult:
        """出走表(出走者・枠等)を取得する。"""

    @abstractmethod
    def get_market_odds(self, race_id: str) -> CollectorResult:
        """市場オッズを取得する。"""

    @abstractmethod
    def get_live_data(self, race_id: str) -> CollectorResult:
        """直前情報(展示・馬体重・気配等、競技固有)を取得する。"""

    @abstractmethod
    def get_result(self, race_id: str) -> CollectorResult:
        """レース結果(着順・払戻)を取得する。"""
