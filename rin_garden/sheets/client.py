"""Google Sheets クライアントの薄いラッパー。

Sheetsは表示・確認・集計用途であり、唯一のデータベースにはしない。
認証情報(`GOOGLE_APPLICATION_CREDENTIALS`)が無い場合は自動的に dry-run モードへ
フォールバックし、実際の書き込みは行わずログのみを残す。これにより認証情報が
無くてもテスト・開発を進められる。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Callable

from rin_garden.sheets.schemas import SHEET_ID_ENV_VARS

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
]


class SheetsConnectionError(Exception):
    """実際のgspread接続確立に失敗した場合に送出する(dry-runでは発生しない)。"""


@dataclass
class SheetsConnectionStatus:
    """接続に必要な設定が揃っているかの非破壊的な自己申告。処理を止めずに使う。"""

    dry_run: bool
    credentials_path: str | None
    credentials_file_exists: bool
    sheet_ids: dict[str, str | None] = field(default_factory=dict)

    def missing_items(self) -> list[str]:
        missing = []
        if not self.credentials_path:
            missing.append("GOOGLE_APPLICATION_CREDENTIALS (未設定)")
        elif not self.credentials_file_exists:
            missing.append(f"GOOGLE_APPLICATION_CREDENTIALS (ファイルが見つかりません: {self.credentials_path})")
        for sport, env_var in SHEET_ID_ENV_VARS.items():
            if not self.sheet_ids.get(sport):
                missing.append(f"{env_var} ({sport}用 Sheet ID未設定)")
        return missing


class SheetsClient:
    """gspreadへの接続を遅延生成するクライアント。

    credentials_pathが未指定/ファイル不在の場合はdry_run=Trueとなり、
    open()はNoneを返す(呼び出し側はNoneをdry-runの合図として扱う)。
    テスト用に `fake_backend` (sheet_id -> スプレッドシート風オブジェクトを返す
    callable) を渡すと、実際のgspread/ネットワークなしで動作を検証できる。
    """

    def __init__(
        self,
        credentials_path: str | None = None,
        dry_run: bool | None = None,
        fake_backend: Callable[[str], Any] | None = None,
    ):
        self.credentials_path = credentials_path or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        has_credentials = bool(self.credentials_path) and os.path.exists(self.credentials_path or "")
        self._fake_backend = fake_backend
        if fake_backend is not None:
            self.dry_run = False
        else:
            self.dry_run = (not has_credentials) if dry_run is None else dry_run
        self._gc: Any = None

    def _connect(self) -> Any:
        if self._gc is None:
            try:
                import gspread  # imported lazily so dry-run mode has no hard dependency
                from google.oauth2.service_account import Credentials
            except ImportError as exc:  # pragma: no cover - depends on optional deps
                raise SheetsConnectionError(
                    "gspread/google-auth is not installed; run `pip install -r requirements.txt`"
                ) from exc
            try:
                creds = Credentials.from_service_account_file(self.credentials_path, scopes=_SCOPES)
                self._gc = gspread.authorize(creds)
            except Exception as exc:  # noqa: BLE001 - surface any auth/network failure clearly
                raise SheetsConnectionError(f"failed to connect to Google Sheets: {exc}") from exc
        return self._gc

    def open(self, sheet_id: str) -> Any:
        """スプレッドシートを開く。dry-runモードではNoneを返す。"""
        if self._fake_backend is not None:
            return self._fake_backend(sheet_id)
        if self.dry_run:
            return None
        return self._connect().open_by_key(sheet_id)

    def status(self) -> SheetsConnectionStatus:
        """処理を止めずに、接続に必要な設定が揃っているかを報告する。"""
        return SheetsConnectionStatus(
            dry_run=self.dry_run,
            credentials_path=self.credentials_path,
            credentials_file_exists=bool(self.credentials_path) and os.path.exists(self.credentials_path or ""),
            sheet_ids={sport: os.environ.get(env_var) for sport, env_var in SHEET_ID_ENV_VARS.items()},
        )

    @staticmethod
    def sheet_id_for(sport: str) -> str | None:
        env_var = SHEET_ID_ENV_VARS.get(sport.strip().lower())
        if env_var is None:
            raise ValueError(f"no sheet id env var configured for sport: {sport!r}")
        return os.environ.get(env_var)
