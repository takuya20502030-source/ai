"""レースランク / CHAOS の定義。ランクとCHAOSは独立した別軸。"""

from __future__ import annotations

RANK_SCALE = ("S", "A", "B", "C", "D", "E")
BUY_CANDIDATE_RANKS = ("S", "A", "B")

CHAOS_MIN = 0
CHAOS_MAX = 10


def validate_rank(rank: str) -> str:
    if rank not in RANK_SCALE:
        raise ValueError(f"invalid rank: {rank!r} (expected one of {RANK_SCALE})")
    return rank


def validate_chaos(chaos: float) -> float:
    if not (CHAOS_MIN <= chaos <= CHAOS_MAX):
        raise ValueError(f"chaos out of range: {chaos!r} (expected {CHAOS_MIN}..{CHAOS_MAX})")
    return chaos


def is_buy_candidate(rank: str) -> bool:
    return rank in BUY_CANDIDATE_RANKS
