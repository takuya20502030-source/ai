"""地方競馬(NAR) Collector。

config/nar.yaml の canonical_source が未確定のため、現時点ではダミー実装。
帯広ばんえいは対象外(config/nar.yaml の excluded_venues 参照)。
"""

from __future__ import annotations

from rin_garden.collectors.base import BaseCollector, CollectorResult


class NarCollector(BaseCollector):
    sport = "nar"

    def get_schedule(self, date: str) -> CollectorResult:
        return CollectorResult.incomplete(
            f"NAR canonical data source is not yet configured (config/nar.yaml); cannot fetch schedule for {date}"
        )

    def get_race_card(self, race_id: str) -> CollectorResult:
        return CollectorResult.incomplete(
            f"NAR canonical data source is not yet configured; cannot fetch race card for {race_id}"
        )

    def get_market_odds(self, race_id: str) -> CollectorResult:
        return CollectorResult.incomplete(
            f"NAR canonical data source is not yet configured; cannot fetch market odds for {race_id}"
        )

    def get_live_data(self, race_id: str) -> CollectorResult:
        return CollectorResult.incomplete(
            f"NAR canonical data source is not yet configured; cannot fetch live data for {race_id}"
        )

    def get_result(self, race_id: str) -> CollectorResult:
        return CollectorResult.incomplete(
            f"NAR canonical data source is not yet configured; cannot fetch result for {race_id}"
        )
