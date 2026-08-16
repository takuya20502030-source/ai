"""Google Sheets Safe Writer(Adapter)。

`config/sheet_write_policy.yaml` に明示されたタブ・列にしか書き込まない
whitelist方式。このAdapterを経由しない直接のgspread書き込みは行わないこと。

原則:
- タブは deny-by-default。policyファイルに定義の無いタブは UnknownTabError で
  拒否する(READ ONLY扱いにすらしない=存在を前提にしない)。
- mode=read_only のタブは常に拒否する。
- mode=write_whitelist は allowed_columns に無い列を絶対に書かない
  (数式列はallowed_columnsから意図的に除外することで保護する。blacklistではない)。
- 実際のヘッダー行と照合し、書こうとしている列が1つでも見つからなければ
  タブ全体への書き込みを拒否する(部分的に書いて部分的に無視する、という
  曖昧な状態を作らない)。
- Race Identity(Race ID)が RaceMaster と一致しなければ拒否する。
- NO POST-HOCをここでも再検証する:
  - write_prediction_fields(): FINAL-LOCKと同じタイミングゲート
    (発走前のみ・結果確定後は無条件拒否)
  - write_result_fields(): ResultLoaderServiceと同じゲート
    (SETTLED/AUDITED以降は拒否)
- 既存行への更新は、該当セルのみを`update_cell()`で個別に書き換える。
  行全体の範囲更新は行わない(whitelist外の列・数式列を巻き込まないため)。
- append_only のタブ(変更履歴)は新規行の追加のみ許可し、既存行の更新は
  一切行わない。レース単位のデータではないため RaceMaster を要求しない。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from rin_garden.core.identity import IdentityMismatchError
from rin_garden.core.locks import PostHocBlockedError, enforce_final_lock_timing
from rin_garden.core.logging import AuditLogger, OP_IDENTITY_MISMATCH, OP_POST_HOC_BLOCKED, OP_WRITE_FAILED, OP_WRITE_OK
from rin_garden.core.race_master import RaceMaster, RaceStatus
from rin_garden.core.timeutil import to_iso, utcnow
from rin_garden.sheets.inspector import get_worksheet_or_none

RACE_ID_FIELD = "Race ID"


class SheetWritePolicyViolation(Exception):
    """書き込み方針違反全般の基底クラス。"""


class UnknownTabError(SheetWritePolicyViolation):
    """sheet_write_policy.yaml に定義の無いタブへ書き込もうとした場合に送出する。"""


class ReadOnlyTabError(SheetWritePolicyViolation):
    """mode=read_only のタブへ書き込もうとした場合に送出する。"""


class ColumnNotWhitelistedError(SheetWritePolicyViolation):
    """allowed_columnsに無い列へ書き込もうとした場合に送出する(数式列の保護を含む)。"""


class HeaderMismatchError(SheetWritePolicyViolation):
    """書こうとしている列が実際のヘッダー行に見つからない場合に送出する。"""


class AppendOnlyViolationError(SheetWritePolicyViolation):
    """append_onlyタブに対して更新系メソッドを使おうとした場合に送出する。"""


@dataclass
class TabWritePolicy:
    title: str
    mode: str  # "read_only" | "write_whitelist" | "append_only"
    allowed_columns: list[str] = field(default_factory=list)
    key_columns: list[str] = field(default_factory=list)


class WritePolicyRegistry:
    """`config/sheet_write_policy.yaml` からタブごとの書き込み方針を読み込む。"""

    def __init__(self, policies: dict[str, TabWritePolicy]):
        self._policies = dict(policies)

    @classmethod
    def load(cls, path: Path, sport: str) -> "WritePolicyRegistry":
        path = Path(path)
        if not path.exists():
            return cls({})
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        entries = data.get(sport, {}).get("tabs", {})
        policies: dict[str, TabWritePolicy] = {}
        for title, cfg in entries.items():
            cfg = cfg or {}
            policies[title] = TabWritePolicy(
                title=title,
                mode=cfg.get("mode", "read_only"),
                allowed_columns=list(cfg.get("allowed_columns", [])),
                key_columns=list(cfg.get("key_columns", [])),
            )
        return cls(policies)

    @classmethod
    def from_policies(cls, policies: list[TabWritePolicy]) -> "WritePolicyRegistry":
        return cls({p.title: p for p in policies})

    def get(self, title: str) -> TabWritePolicy:
        policy = self._policies.get(title)
        if policy is None:
            raise UnknownTabError(f"tab {title!r} is not defined in sheet_write_policy.yaml (deny-by-default)")
        return policy


def load_header_row_index_map(layout_path: Path, sport: str) -> dict[str, int]:
    """config/sheet_tab_layout.yaml からタブごとのヘッダー行位置を読み込む。"""
    path = Path(layout_path)
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    entries = data.get(sport, {})
    return {title: cfg["header_row_index"] for title, cfg in entries.items() if cfg.get("header_row_index") is not None}


@dataclass
class WriteOutcome:
    tab: str
    action: str  # "UPDATED" | "APPENDED"
    row_number: int | None
    written_columns: list[str] = field(default_factory=list)


class SheetWriteAdapter:
    """whitelist方式のSafe Writer。ここを経由しない直接書き込みは行わないこと。"""

    def __init__(
        self,
        policy_registry: WritePolicyRegistry,
        audit_logger: AuditLogger,
        header_row_index_by_tab: dict[str, int] | None = None,
    ):
        self.policy_registry = policy_registry
        self.audit_logger = audit_logger
        self.header_row_index_by_tab = header_row_index_by_tab or {}

    # --- 内部ヘルパー ---

    def _resolve_header(self, spreadsheet: Any, tab: str) -> tuple[Any, list[list[str]], int, list[str]]:
        worksheet = get_worksheet_or_none(spreadsheet, tab)
        if worksheet is None:
            raise HeaderMismatchError(f"tab {tab!r} does not exist in the spreadsheet")
        header_row_index = self.header_row_index_by_tab.get(tab)
        if header_row_index is None:
            raise HeaderMismatchError(
                f"no header_row_index configured for tab {tab!r} (config/sheet_tab_layout.yaml); refusing to guess"
            )
        all_values = worksheet.get_all_values()
        if header_row_index >= len(all_values):
            raise HeaderMismatchError(f"tab {tab!r} has fewer rows than expected header_row_index={header_row_index}")
        actual_headers = all_values[header_row_index]
        return worksheet, all_values, header_row_index, actual_headers

    def _log(self, operation: str, sport: str, race_id: str, status: str, source: str, message: str, account: str | None) -> None:
        self.audit_logger.log(operation, sport, race_id, status, source, message, account=account)

    def _reject_unknown_tab_or_read_only(self, tab: str, source: str, sport: str, race_id: str, account: str | None) -> TabWritePolicy:
        try:
            policy = self.policy_registry.get(tab)
        except UnknownTabError as exc:
            self._log(OP_WRITE_FAILED, sport, race_id, "REJECTED", source, str(exc), account)
            raise
        if policy.mode == "read_only":
            exc = ReadOnlyTabError(f"tab {tab!r} is read_only; refusing to write")
            self._log(OP_WRITE_FAILED, sport, race_id, "REJECTED", source, str(exc), account)
            raise exc
        return policy

    def _reject_unwhitelisted_columns(self, policy: TabWritePolicy, fields: dict[str, Any], source: str, sport: str, race_id: str, account: str | None) -> None:
        unknown = [k for k in fields if k not in policy.allowed_columns]
        if unknown:
            exc = ColumnNotWhitelistedError(f"columns not whitelisted for tab {policy.title!r}: {unknown}")
            self._log(OP_WRITE_FAILED, sport, race_id, "REJECTED", source, str(exc), account)
            raise exc

    def _reject_header_mismatch(self, policy: TabWritePolicy, actual_headers: list[str], fields: dict[str, Any], source: str, sport: str, race_id: str, account: str | None) -> None:
        missing = [k for k in fields if k not in actual_headers]
        if missing:
            exc = HeaderMismatchError(
                f"columns not found in actual header row for tab {policy.title!r}: {missing} (actual header={actual_headers})"
            )
            self._log(OP_WRITE_FAILED, sport, race_id, "REJECTED", source, str(exc), account)
            raise exc
        missing_keys = [k for k in policy.key_columns if k not in actual_headers]
        if missing_keys:
            exc = HeaderMismatchError(
                f"key columns not found in actual header row for tab {policy.title!r}: {missing_keys} "
                f"(actual header={actual_headers})"
            )
            self._log(OP_WRITE_FAILED, sport, race_id, "REJECTED", source, str(exc), account)
            raise exc

    def _reject_race_identity_mismatch(self, race_master: RaceMaster, fields: dict[str, Any], source: str, account: str | None) -> None:
        if RACE_ID_FIELD in fields and fields[RACE_ID_FIELD] != race_master.race_id:
            exc = IdentityMismatchError(
                f"race identity mismatch: expected race_id={race_master.race_id!r}, got {fields[RACE_ID_FIELD]!r}"
            )
            self._log(OP_IDENTITY_MISMATCH, race_master.sport, race_master.race_id, "REJECTED", source, str(exc), account)
            raise exc

    def _reject_post_hoc(self, race_master: RaceMaster, timing_gate: str, source: str, account: str | None, now: str | None) -> None:
        if timing_gate == "prediction":
            if race_master.status in (RaceStatus.RESULT_LOCKED, RaceStatus.SETTLED, RaceStatus.AUDITED):
                exc = PostHocBlockedError(
                    f"race_id={race_master.race_id} already has a result (status={race_master.status}); "
                    "prediction-phase sheet write cannot happen after the fact"
                )
                self._log(OP_POST_HOC_BLOCKED, race_master.sport, race_master.race_id, "REJECTED", source, str(exc), account)
                raise exc
            if race_master.scheduled_start is None:
                raise ValueError("race_master.scheduled_start is required to enforce prediction-phase write timing")
            now = now or to_iso(utcnow())
            try:
                enforce_final_lock_timing(race_master.scheduled_start, now)
            except PostHocBlockedError as exc:
                self._log(OP_POST_HOC_BLOCKED, race_master.sport, race_master.race_id, "REJECTED", source, str(exc), account)
                raise
        elif timing_gate == "result":
            if race_master.status in (RaceStatus.SETTLED, RaceStatus.AUDITED):
                exc = PostHocBlockedError(
                    f"race_id={race_master.race_id} is already settled (status={race_master.status}); "
                    "result-phase sheet write cannot happen after settlement"
                )
                self._log(OP_POST_HOC_BLOCKED, race_master.sport, race_master.race_id, "REJECTED", source, str(exc), account)
                raise exc
        else:
            raise ValueError(f"unknown timing_gate: {timing_gate!r}")

    def _find_existing_row_index(
        self, all_values: list[list[str]], header_row_index: int, actual_headers: list[str], policy: TabWritePolicy, fields: dict[str, Any]
    ) -> int | None:
        """既存行を key_columns の値で特定する。見つからなければNone(=新規行として追加)。"""
        key_indices = {k: actual_headers.index(k) for k in policy.key_columns if k in actual_headers}
        if not key_indices:
            return None
        target = {k: str(fields.get(k, "")) for k in key_indices}
        for row_idx in range(header_row_index + 1, len(all_values)):
            row = all_values[row_idx]
            if all((row[idx] if idx < len(row) else "") == target[k] for k, idx in key_indices.items()):
                return row_idx
        return None

    def _apply_cells(
        self, worksheet: Any, all_values: list[list[str]], header_row_index: int, actual_headers: list[str],
        policy: TabWritePolicy, fields: dict[str, Any]
    ) -> WriteOutcome:
        existing_row_idx = self._find_existing_row_index(all_values, header_row_index, actual_headers, policy, fields)

        if existing_row_idx is not None:
            sheet_row_number = existing_row_idx + 1  # gspreadは1始まり
            written: list[str] = []
            for k, v in fields.items():
                col_idx = actual_headers.index(k)
                worksheet.update_cell(sheet_row_number, col_idx + 1, str(v))
                written.append(k)
            return WriteOutcome(tab=policy.title, action="UPDATED", row_number=sheet_row_number, written_columns=written)

        new_row = [""] * len(actual_headers)
        written = []
        for k, v in fields.items():
            idx = actual_headers.index(k)
            new_row[idx] = str(v)
            written.append(k)
        worksheet.append_row(new_row)
        return WriteOutcome(tab=policy.title, action="APPENDED", row_number=None, written_columns=written)

    # --- 公開API ---

    def write_prediction_fields(
        self,
        spreadsheet: Any,
        race_master: RaceMaster,
        tab: str,
        fields: dict[str, Any],
        account: str | None = None,
        now: str | None = None,
    ) -> WriteOutcome:
        """締切前の予測系フィールドを書き込む(race_id + account単位でupsert)。

        FINAL-LOCKと同じNO POST-HOCタイミングゲートを適用する
        (発走前のみ許可、結果確定後は理由を問わず拒否)。
        """
        source = "adapter.write_prediction_fields"
        policy = self._reject_unknown_tab_or_read_only(tab, source, race_master.sport, race_master.race_id, account)
        if policy.mode == "append_only":
            raise AppendOnlyViolationError(f"tab {tab!r} is append_only; use append_audit_row() instead")

        self._reject_unwhitelisted_columns(policy, fields, source, race_master.sport, race_master.race_id, account)
        self._reject_race_identity_mismatch(race_master, fields, source, account)
        self._reject_post_hoc(race_master, "prediction", source, account, now)

        worksheet, all_values, header_row_index, actual_headers = self._resolve_header(spreadsheet, tab)
        self._reject_header_mismatch(policy, actual_headers, fields, source, race_master.sport, race_master.race_id, account)

        outcome = self._apply_cells(worksheet, all_values, header_row_index, actual_headers, policy, fields)
        self._log(OP_WRITE_OK, race_master.sport, race_master.race_id, "OK", source, f"{outcome.action} tab={tab}", account)
        return outcome

    def write_result_fields(
        self,
        spreadsheet: Any,
        race_master: RaceMaster,
        tab: str,
        fields: dict[str, Any],
        account: str | None = None,
    ) -> WriteOutcome:
        """結果確定後のフィールドを書き込む(race_id [+ account]単位でupsert)。

        ResultLoaderServiceと同じNO POST-HOCタイミングゲートを適用する
        (SETTLED/AUDITED以降は拒否。RESULT_LOCKED時点までは許可)。
        """
        source = "adapter.write_result_fields"
        policy = self._reject_unknown_tab_or_read_only(tab, source, race_master.sport, race_master.race_id, account)
        if policy.mode == "append_only":
            raise AppendOnlyViolationError(f"tab {tab!r} is append_only; use append_audit_row() instead")

        self._reject_unwhitelisted_columns(policy, fields, source, race_master.sport, race_master.race_id, account)
        self._reject_race_identity_mismatch(race_master, fields, source, account)
        self._reject_post_hoc(race_master, "result", source, account, now=None)

        worksheet, all_values, header_row_index, actual_headers = self._resolve_header(spreadsheet, tab)
        self._reject_header_mismatch(policy, actual_headers, fields, source, race_master.sport, race_master.race_id, account)

        outcome = self._apply_cells(worksheet, all_values, header_row_index, actual_headers, policy, fields)
        self._log(OP_WRITE_OK, race_master.sport, race_master.race_id, "OK", source, f"{outcome.action} tab={tab}", account)
        return outcome

    def append_audit_row(self, spreadsheet: Any, sport: str, tab: str, fields: dict[str, Any]) -> WriteOutcome:
        """append_onlyタブ(変更履歴)へ新規行を追加する。既存行の更新は一切行わない。

        レース単位のデータではないため RaceMaster / Race Identity検証は行わない。
        """
        source = "adapter.append_audit_row"
        policy = self._reject_unknown_tab_or_read_only(tab, source, sport, "-", None)
        if policy.mode != "append_only":
            raise AppendOnlyViolationError(
                f"tab {tab!r} is mode={policy.mode!r}, not append_only; use write_prediction_fields/write_result_fields"
            )

        self._reject_unwhitelisted_columns(policy, fields, source, sport, "-", None)

        worksheet, all_values, header_row_index, actual_headers = self._resolve_header(spreadsheet, tab)
        self._reject_header_mismatch(policy, actual_headers, fields, source, sport, "-", None)

        new_row = [""] * len(actual_headers)
        written = []
        for k, v in fields.items():
            idx = actual_headers.index(k)
            new_row[idx] = str(v)
            written.append(k)
        worksheet.append_row(new_row)

        self._log(OP_WRITE_OK, sport, "-", "OK", source, f"APPENDED tab={tab}", None)
        return WriteOutcome(tab=tab, action="APPENDED", row_number=None, written_columns=written)
