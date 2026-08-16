"""JRA中央競馬 Collector。

config/jra.yaml の canonical_source が未確定のため、現時点ではダミー実装。
全メソッドが DATA_INCOMPLETE を返す。公式API/正規データソースが確定次第、
実際の取得処理をここに実装する(利用規約・robots制限を遵守すること)。
"""

from __future__ import annotations

from rin_garden.collectors.base import BaseCollector, CollectorResult


class JraCollector(BaseCollector):
    sport = "jra"

    def get_schedule(self, date: str) -> CollectorResult:
        return CollectorResult.incomplete(
            f"JRA canonical data source is not yet configured (config/jra.yaml); cannot fetch schedule for {date}"
        )

    def get_race_card(self, race_id: str) -> CollectorResult:
        return CollectorResult.incomplete(
            f"JRA canonical data source is not yet configured; cannot fetch race card for {race_id}"
        )

    def get_market_odds(self, race_id: str) -> CollectorResult:
        return CollectorResult.incomplete(
            f"JRA canonical data source is not yet configured; cannot fetch market odds for {race_id}"
        )

    def get_live_data(self, race_id: str) -> CollectorResult:
        return CollectorResult.incomplete(
            f"JRA canonical data source is not yet configured; cannot fetch live data for {race_id}"
        )

    def get_result(self, race_id: str) -> CollectorResult:
        return CollectorResult.incomplete(
            f"JRA canonical data source is not yet configured; cannot fetch result for {race_id}"
        )
