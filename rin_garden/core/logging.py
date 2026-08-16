"""監査ログ機構。

全ての重要操作(PRE_FIXED, FINAL_LOCKED, RESULT_LOCKED, SETTLED, POST_HOC_BLOCKED,
IDENTITY_MISMATCH, DATA_INCOMPLETE, WRITE_FAILED 等)を構造化JSON Linesとして
logs/audit.log に追記する。標準の`logging`モジュールとは別に、監査証跡として
消えない・改変しにくい形で残すことを目的とする。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rin_garden.core.timeutil import to_iso, utcnow

# 主要operation名(自由記述も許容するが、これらは必ずこの表記で統一する)
OP_PRE_FIXED = "PRE_FIXED"
OP_FINAL_LOCKED = "FINAL_LOCKED"
OP_FINAL_REVISED = "FINAL_REVISED"
OP_RESULT_LOCKED = "RESULT_LOCKED"
OP_SETTLED = "SETTLED"
OP_AUDITED = "AUDITED"
OP_POST_HOC_BLOCKED = "POST_HOC_BLOCKED"
OP_IDENTITY_MISMATCH = "IDENTITY_MISMATCH"
OP_DATA_INCOMPLETE = "DATA_INCOMPLETE"
OP_WRITE_FAILED = "WRITE_FAILED"
OP_WRITE_OK = "WRITE_OK"


class AuditLogger:
    """logs/audit.log へ構造化ログを追記するロガー。"""

    def __init__(self, log_path: Path):
        self.log_path = Path(log_path)

    def log(
        self,
        operation: str,
        sport: str,
        race_id: str,
        status: str,
        source: str,
        message: str = "",
        account: str | None = None,
    ) -> None:
        entry: dict[str, Any] = {
            "timestamp": to_iso(utcnow()),
            "operation": operation,
            "sport": sport,
            "race_id": race_id,
            "account": account,
            "status": status,
            "source": source,
            "message": message,
        }
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")

    def read_all(self) -> list[dict[str, Any]]:
        if not self.log_path.exists():
            return []
        entries = []
        with open(self.log_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
        return entries
