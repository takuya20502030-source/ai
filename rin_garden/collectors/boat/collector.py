"""BOAT RACE Collector。

config/boat.yaml の canonical_source が未確定のため、現時点ではダミー実装。
"""

from __future__ import annotations

from rin_garden.collectors.base import BaseCollector, CollectorResult


class BoatCollector(BaseCollector):
    sport = "boat"

    def get_schedule(self, date: str) -> CollectorResult:
        return CollectorResult.incomplete(
            f"BOAT canonical data source is not yet configured (config/boat.yaml); cannot fetch schedule for {date}"
        )

    def get_race_card(self, race_id: str) -> CollectorResult:
        return CollectorResult.incomplete(
            f"BOAT canonical data source is not yet configured; cannot fetch race card for {race_id}"
        )

    def get_market_odds(self, race_id: str) -> CollectorResult:
        return CollectorResult.incomplete(
            f"BOAT canonical data source is not yet configured; cannot fetch market odds for {race_id}"
        )

    def get_live_data(self, race_id: str) -> CollectorResult:
        return CollectorResult.incomplete(
            f"BOAT canonical data source is not yet configured; cannot fetch live data for {race_id}"
        )

    def get_result(self, race_id: str) -> CollectorResult:
        return CollectorResult.incomplete(
            f"BOAT canonical data source is not yet configured; cannot fetch result for {race_id}"
        )
