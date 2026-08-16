"""ファイルベースの永続化ユーティリティ。

RIN GARDENのローカルデータ(Race Master / PRE / FINAL / Result / Settlement)は
すべてJSONファイルとして保存する。ここでの書き込みは以下を保証する。

- 原子性: 一時ファイルへ書いてからrenameする(書きかけファイルが正データにならない)。
- 冪等性: 同じ内容を2回書いても壊れない。
- 不変レコード保護: `write_json_once` は既存ファイルと内容が異なる場合は例外を送出する。
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


class ImmutableRecordConflictError(Exception):
    """不変であるべきレコードを異なる内容で上書きしようとした場合に送出する。"""


def write_json(path: Path, data: dict[str, Any]) -> None:
    """JSONを原子的に書き込む(既存内容があれば無条件に置き換える)。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
            f.write("\n")
        os.replace(tmp_name, path)
    except BaseException:
        if os.path.exists(tmp_name):
            os.remove(tmp_name)
        raise


def write_json_once(path: Path, data: dict[str, Any]) -> bool:
    """不変レコードを書き込む。

    既存ファイルが無ければ新規作成しTrueを返す。
    既存ファイルがあり内容が完全一致すればNo-op(冪等)としてFalseを返す。
    既存ファイルがあり内容が異なる場合は ImmutableRecordConflictError を送出する。
    """
    if path.exists():
        existing = read_json(path)
        if existing == data:
            return False
        raise ImmutableRecordConflictError(
            f"immutable record already exists with different content: {path}"
        )
    write_json(path, data)
    return True


def read_json(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def read_json_if_exists(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return read_json(path)
