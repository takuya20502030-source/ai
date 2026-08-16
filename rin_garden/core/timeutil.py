"""日時ユーティリティ。

このプロジェクトでは全ての時刻をUTCのタイムゾーン付きdatetimeとして扱う。
NO POST-HOC検証はタイムゾーン付き比較でしか正しく機能しないため、
naiveなdatetimeを扱う箇所を作らないこと。
"""

from __future__ import annotations

from datetime import datetime, timezone


def utcnow() -> datetime:
    """タイムゾーン付きの現在時刻(UTC)を返す。"""
    return datetime.now(timezone.utc)


def parse_iso(value: str) -> datetime:
    """ISO8601文字列をタイムゾーン付きdatetimeに変換する。

    'Z'サフィックスを '+00:00' に読み替える(Python 3.10以前のfromisoformat対策)。
    タイムゾーン情報が無い場合はUTCとして解釈する。
    """
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def to_iso(value: datetime) -> str:
    """タイムゾーン付きdatetimeをISO8601文字列に変換する。"""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()
