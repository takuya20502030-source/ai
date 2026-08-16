"""競輪 Collector。

config/keirin.yaml の canonical_source(公式API/正規データソース)が未確定であり、
かつ本セッションのサンドボックス環境ではネットワーク送出ポリシーにより
競輪関連サイトへの到達がブロックされている(組織のegressポリシーによる403を確認済み)。
そのため get_schedule() 等のライブ取得系メソッドは引き続きダミー実装
(DATA_INCOMPLETE)のままとする。見たことのないページ構造に対して推測でスクレイピング
コードを書くことはしない。

代わりに、ユーザーが正規の一次情報源から取得したデータをJSONファイルとして
与えられる `load_race_card_from_file()` / `load_result_from_file()` を用意する。
これは実データをネットワーク経由の推測なしにパイプラインへ通すための経路であり、
Race Identityフィールドの欠落は拒否し、その他の欠落フィールドはDATA_INCOMPLETE/
ESTIMATEDとして明示する。
"""

from __future__ import annotations

from pathlib import Path

from rin_garden.collectors.base import BaseCollector, CollectorResult
from rin_garden.collectors.keirin.snapshot import (
    load_json_snapshot,
    snapshot_confidence,
    validate_race_card_snapshot,
    validate_result_snapshot,
)

_NETWORK_BLOCKED_NOTE = (
    "live fetch is not implemented: this session's network egress policy blocks keirin data sources, "
    "and no verified official API/page structure is available to parse without guessing; "
    "use load_race_card_from_file()/load_result_from_file() with a snapshot obtained from a primary source instead"
)


class KeirinCollector(BaseCollector):
    sport = "keirin"

    def get_schedule(self, date: str) -> CollectorResult:
        return CollectorResult.incomplete(f"{_NETWORK_BLOCKED_NOTE} (schedule, date={date})")

    def get_race_card(self, race_id: str) -> CollectorResult:
        return CollectorResult.incomplete(f"{_NETWORK_BLOCKED_NOTE} (race_card, race_id={race_id})")

    def get_market_odds(self, race_id: str) -> CollectorResult:
        return CollectorResult.incomplete(f"{_NETWORK_BLOCKED_NOTE} (market_odds, race_id={race_id})")

    def get_live_data(self, race_id: str) -> CollectorResult:
        return CollectorResult.incomplete(f"{_NETWORK_BLOCKED_NOTE} (live_data, race_id={race_id})")

    def get_result(self, race_id: str) -> CollectorResult:
        return CollectorResult.incomplete(f"{_NETWORK_BLOCKED_NOTE} (result, race_id={race_id})")

    # --- ファイルベースの実データ取り込み(このCollectorに固有の追加機能) ---

    def load_race_card_from_file(self, path: Path) -> CollectorResult:
        """ユーザーが用意したJSONスナップショットから出走表を取り込む。

        Identityフィールド(sport/date/venue/race_number/event_id/scheduled_start)が
        欠けている場合は取り込みを拒否する(DATA_INCOMPLETE、ok=False)。
        出走者個別フィールドの欠落は許容し、confidenceで明示する。
        """
        data = load_json_snapshot(Path(path))
        validation = validate_race_card_snapshot(data)
        if not validation.ok:
            return CollectorResult.incomplete(
                f"snapshot missing required identity fields: {validation.missing_identity_fields}",
                source=str(path),
            )
        message = (
            f"entrant fields incomplete: {validation.incomplete_entrant_fields}"
            if validation.incomplete_entrant_fields
            else ""
        )
        return CollectorResult(
            ok=True,
            confidence=snapshot_confidence(validation),
            data=data,
            source=str(path),
            message=message,
        )

    def load_result_from_file(self, path: Path) -> CollectorResult:
        """ユーザーが用意したJSONスナップショットから結果(着順・払戻)を取り込む。"""
        data = load_json_snapshot(Path(path))
        validation = validate_result_snapshot(data)
        if not validation.ok:
            return CollectorResult.incomplete(
                f"snapshot missing required fields: {validation.missing_identity_fields}",
                source=str(path),
            )
        return CollectorResult(ok=True, confidence=snapshot_confidence(validation), data=data, source=str(path), message="")
