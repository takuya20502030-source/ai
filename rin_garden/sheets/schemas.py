"""Google Sheetsのシート名・列定義を一元管理する。

セル座標をコード全体へ直接散らばらせないよう、ここで定義したヘッダー順を
`sheets/writer.py` / `sheets/reader.py` が参照する。列はヘッダー名で解決し、
固定のA1セル番地には依存しない。
"""

from __future__ import annotations

SHEET_ID_ENV_VARS = {
    "jra": "GOOGLE_SHEET_ID_JRA",
    "nar": "GOOGLE_SHEET_ID_NAR",
    "boat": "GOOGLE_SHEET_ID_BOAT",
    "keirin": "GOOGLE_SHEET_ID_KEIRIN",
}

RACE_MASTER_SHEET = "RaceMaster"
RACE_MASTER_HEADERS = [
    "sport",
    "date",
    "venue",
    "race_number",
    "race_id",
    "event_id",
    "canonical_source",
    "source_url",
    "scheduled_start",
    "status",
    "pre_fixed_at",
    "final_locked_at",
    "result_locked_at",
    "settled_at",
]

PRE_SHEET = "PRE"
PRE_HEADERS = [
    "race_id",
    "timestamp",
    "rank",
    "chaos",
    "confidence",
    "predicted_scenario",
    "bets",
    "fair_probability",
    "fair_odds",
    "market_odds",
    "expected_value",
]

FINAL_SHEET = "FINAL"
FINAL_HEADERS = [
    "race_id",
    "timestamp",
    "marks",
    "evaluation",
    "bets",
    "amounts",
    "decision",
    "revision_count",
]

RESULT_SHEET = "Result"
RESULT_HEADERS = [
    "race_id",
    "timestamp",
    "order",
    "payouts",
]

SETTLEMENT_SHEET = "Settlement"
SETTLEMENT_HEADERS = [
    "race_id",
    "settled_at",
    "decision",
    "stake",
    "payout",
    "profit",
    "roi",
]

DAILY_SUMMARY_SHEET = "DailySummary"
DAILY_SUMMARY_HEADERS = [
    "date",
    "sport",
    "scheduled_races",
    "pre_fixed",
    "final_locked",
    "settled",
    "missing",
    "profit",
    "roi",
]
