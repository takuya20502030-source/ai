"""ファイルベースのRace Snapshot取り込み(競輪)。

このセッションのサンドボックス環境はネットワーク送出ポリシーにより
競輪関連のデータソースへ到達できない(www.keirin.jp等は組織のegressポリシーで
ブロックされていることを確認済み)。見たことのないページ構造に対して
スクレイピングのセレクタを推測で書くことは「取得できない情報を推測で埋めない」
という本システムの原則に反するため、ここでは実装しない。

代わりに、ユーザー自身が正規の一次情報源(公式サイト・契約済みAPI等)から
取得したデータをJSONファイルとして与える取り込み経路を用意する。これにより、
ネットワークアクセスが無い環境でも「架空データを補完しない」まま実データを
パイプラインへ通すことができる。

JSONの形は config/keirin.yaml の race_fields / result_fields に対応する。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rin_garden.core.validation import DataConfidence

# Race Master構築に最低限必要なIdentityフィールド
IDENTITY_KEYS = ("sport", "date", "venue", "race_number", "event_id", "scheduled_start")

# config/keirin.yaml race_fields に対応する出走者ごとのフィールド(英語キー: 日本語ラベル)
ENTRANT_FIELDS = {
    "number": "車番",
    "name": "選手",
    "prefecture": "府県",
    "score": "競走得点",
    "style": "脚質",
    "recent_results": "直近成績",
    "line": "ライン",
    "lineup": "並び",
}

RESULT_KEYS = ("order", "payouts")


class SnapshotFormatError(Exception):
    """スナップショットJSONの形式が不正な場合(必須Identityが無い等)に送出する。"""


@dataclass
class SnapshotValidation:
    ok: bool
    missing_identity_fields: list[str] = field(default_factory=list)
    incomplete_entrant_fields: dict[str, list[str]] = field(default_factory=dict)


def load_json_snapshot(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def validate_race_card_snapshot(data: dict[str, Any]) -> SnapshotValidation:
    """Identityフィールドと出走者ごとのフィールド充足状況を検証する。

    出走者側のフィールド欠落は許容する(DATA_INCOMPLETEとして呼び出し側へ伝える)。
    Identityフィールドの欠落は致命的(ok=False)として扱う。
    """
    missing_identity = [k for k in IDENTITY_KEYS if not data.get(k)]

    incomplete: dict[str, list[str]] = {}
    for entrant in data.get("entrants", []):
        missing = [f for f in ENTRANT_FIELDS if entrant.get(f) in (None, "")]
        if missing:
            key = str(entrant.get("number", "unknown"))
            incomplete[key] = missing

    return SnapshotValidation(ok=not missing_identity, missing_identity_fields=missing_identity, incomplete_entrant_fields=incomplete)


def validate_result_snapshot(data: dict[str, Any]) -> SnapshotValidation:
    missing_identity = [k for k in ("race_id",) if not data.get(k)]
    missing_result = [k for k in RESULT_KEYS if not data.get(k)]
    return SnapshotValidation(ok=not missing_identity and not missing_result, missing_identity_fields=missing_identity + missing_result)


def snapshot_confidence(validation: SnapshotValidation) -> str:
    if not validation.ok:
        return DataConfidence.INCOMPLETE
    if validation.incomplete_entrant_fields:
        return DataConfidence.ESTIMATED
    return DataConfidence.CONFIRMED
