"""PRE-FIX / FINAL-LOCK / NO POST-HOC のタイミング強制。

RIN GARDENの最重要ルール: 結果を知った後にPREやFINALを新規作成したり、
既存のPRE/FINALを有利な方向へ書き換えたりしてはならない。

このモジュールは `scheduled_start`(発走予定時刻)と操作時刻(`now`)を比較し、
違反する操作を例外で拒否する。呼び出し側(core.pre_fix / core.final_lock)は
必ずこれらの関数を経由してから実際の書き込みを行うこと。
"""

from __future__ import annotations

from datetime import datetime

from rin_garden.core.timeutil import parse_iso


class PostHocBlockedError(Exception):
    """結果を知った後の予想作成・改変を試みた場合に送出する。"""


def _as_datetime(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    return parse_iso(value)


def enforce_pre_fix_timing(scheduled_start: str | datetime, now: str | datetime) -> None:
    """PRE-FIXの新規作成は発走予定時刻より前でなければならない。"""
    start = _as_datetime(scheduled_start)
    current = _as_datetime(now)
    if current >= start:
        raise PostHocBlockedError(
            f"PRE-FIX must be created before scheduled_start "
            f"(scheduled_start={start.isoformat()}, now={current.isoformat()})"
        )


def enforce_final_lock_timing(scheduled_start: str | datetime, now: str | datetime) -> None:
    """FINAL-LOCKの新規作成・revisionは発走予定時刻より前でなければならない。"""
    start = _as_datetime(scheduled_start)
    current = _as_datetime(now)
    if current >= start:
        raise PostHocBlockedError(
            f"FINAL-LOCK (create/revise) must happen before scheduled_start "
            f"(scheduled_start={start.isoformat()}, now={current.isoformat()})"
        )


def enforce_no_revision_after_start(scheduled_start: str | datetime, now: str | datetime) -> None:
    """発走後のFINAL-LOCK revisionは無条件で禁止する。"""
    enforce_final_lock_timing(scheduled_start, now)
