"""Account / AccountPolicy: 予測ロジックと資金・選別ロジックの分離。

共通PRE-FIX(予測)から、Account(FORCED-ALL / SELECT-B+ / FLEX-ALL / FLEX-SELECT等)
ごとに独立したFINAL-LOCK・Ticket・Settlementが派生する。Accountはコードへ
固定列挙せず、`config/accounts.yaml` から読み込む(AccountRegistry)。

    共通PRE
      ↓
    AccountPolicy
      ↓
    Account別FINAL-LOCK
      ↓
    Account別Tickets
      ↓
    共通Result
      ↓
    Account別Settlement

selection_rule/allocation_rule等の自動判定エンジンは未実装。現時点の
AccountPolicyは値を保持・検証する構造のみを提供する。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class UnknownAccountError(Exception):
    """config/accounts.yaml に登録されていないAccountを使おうとした場合に送出する。"""


_KNOWN_FIELDS = (
    "id",
    "display_name",
    "enabled",
    "selection_rule",
    "eligible_grades",
    "base_stake",
    "s_grade_stake",
    "skip_rule",
    "allocation_rule",
    "minimum_odds_rule",
)


@dataclass
class AccountPolicy:
    id: str
    display_name: str = ""
    enabled: bool = True
    selection_rule: str | None = None
    eligible_grades: list[str] = field(default_factory=list)
    base_stake: float | None = None
    s_grade_stake: float | None = None
    skip_rule: str | None = None
    allocation_rule: str | None = None
    minimum_odds_rule: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AccountPolicy":
        known = {k: v for k, v in data.items() if k in _KNOWN_FIELDS}
        extra = {k: v for k, v in data.items() if k not in _KNOWN_FIELDS}
        return cls(**known, extra=extra)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "display_name": self.display_name,
            "enabled": self.enabled,
            "selection_rule": self.selection_rule,
            "eligible_grades": self.eligible_grades,
            "base_stake": self.base_stake,
            "s_grade_stake": self.s_grade_stake,
            "skip_rule": self.skip_rule,
            "allocation_rule": self.allocation_rule,
            "minimum_odds_rule": self.minimum_odds_rule,
            "extra": self.extra,
        }


class AccountRegistry:
    """`config/accounts.yaml` からAccountPolicyを読み込み、検証する。"""

    def __init__(self, policies: dict[str, AccountPolicy]):
        self._policies = dict(policies)

    @classmethod
    def load(cls, path: Path) -> "AccountRegistry":
        """設定ファイルからAccountRegistryを構築する。ファイルが無ければ空で返す
        (=どのAccountも未登録として扱う。処理は止めず、利用側がUnknownAccountErrorで拒否する)。
        """
        path = Path(path)
        if not path.exists():
            return cls({})
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        policies: dict[str, AccountPolicy] = {}
        for entry in data.get("accounts", []):
            policy = AccountPolicy.from_dict(entry)
            policies[policy.id] = policy
        return cls(policies)

    @classmethod
    def from_policies(cls, policies: list[AccountPolicy]) -> "AccountRegistry":
        return cls({p.id: p for p in policies})

    def get(self, account_id: str) -> AccountPolicy:
        """登録済みAccountPolicyを返す。未登録・無効(enabled=False)ならUnknownAccountError。"""
        policy = self._policies.get(account_id)
        if policy is None:
            raise UnknownAccountError(
                f"unknown account: {account_id!r} (not registered in accounts.yaml; "
                f"known accounts: {sorted(self._policies)})"
            )
        if not policy.enabled:
            raise UnknownAccountError(f"account {account_id!r} is registered but disabled (enabled=false)")
        return policy

    def is_known(self, account_id: str) -> bool:
        policy = self._policies.get(account_id)
        return policy is not None and policy.enabled

    def all_ids(self) -> list[str]:
        return list(self._policies.keys())
