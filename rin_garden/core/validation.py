"""データ完全性・整合性の検証ヘルパー。

事実・推測・シナリオを分離し、データが不足している場合は明示する。
架空データによる補完や、検索結果だけを根拠にしたRace Identity確定を避けるための
共通チェックをここに集約する。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class DataConfidence:
    """データの確信度を明示するための定数群。推測で埋めた値には必ず付与する。"""

    CONFIRMED = "CONFIRMED"        # 一次ソースで確認済み
    ESTIMATED = "ESTIMATED"        # 二次情報からの推定
    INCOMPLETE = "DATA_INCOMPLETE"  # 取得できていない


@dataclass
class FieldValue:
    """1つの値と、その確信度・出典をセットで保持する。"""

    value: Any
    confidence: str = DataConfidence.CONFIRMED
    source: str | None = None

    def is_usable_for_bet(self) -> bool:
        """賭け判断の根拠として使ってよいか。DATA_INCOMPLETEは不可。"""
        return self.confidence != DataConfidence.INCOMPLETE


REQUIRED_IDENTITY_FIELDS = ("sport", "date", "venue", "race_number", "race_id", "event_id")


def require_identity_fields(payload: dict[str, Any]) -> list[str]:
    """Identityフィールドの欠落を検出する(欠落フィールド名のリストを返す)。"""
    return [f for f in REQUIRED_IDENTITY_FIELDS if not payload.get(f)]


@dataclass
class ValidationResult:
    ok: bool
    reason: str = ""
    missing_fields: list[str] = field(default_factory=list)
