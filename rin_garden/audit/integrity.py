"""PRE/FINALスナップショットの改ざん検知用ハッシュユーティリティ。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from rin_garden.core import storage


def compute_hash(data: dict[str, Any]) -> str:
    """dictを正規化(キーソート)してsha256ハッシュを計算する。"""
    canonical = json.dumps(data, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def verify_file_hash(path: Path, expected_hash: str) -> bool:
    """指定パスのJSONファイル内容が期待するハッシュと一致するか検証する。"""
    data = storage.read_json_if_exists(Path(path))
    if data is None:
        return False
    return compute_hash(data) == expected_hash
