"""Google Sheets クライアントの薄いラッパー。

Sheetsは表示・確認・集計用途であり、唯一のデータベースにはしない。
認証情報(`GOOGLE_APPLICATION_CREDENTIALS`)が無い場合は自動的に dry-run モードへ
フォールバックし、実際の書き込みは行わずログのみを残す。これにより認証情報が
無くてもテスト・開発を進められる。
"""

from __future__ import annotations

import os
from typing import Any

from rin_garden.sheets.schemas import SHEET_ID_ENV_VARS

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
]


class SheetsClient:
    """gspreadへの接続を遅延生成するクライアント。

    credentials_pathが未指定/ファイル不在の場合はdry_run=Trueとなり、
    open()はNoneを返す(呼び出し側はNoneをdry-runの合図として扱う)。
    """

    def __init__(self, credentials_path: str | None = None, dry_run: bool | None = None):
        self.credentials_path = credentials_path or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        has_credentials = bool(self.credentials_path) and os.path.exists(self.credentials_path or "")
        self.dry_run = (not has_credentials) if dry_run is None else dry_run
        self._gc: Any = None

    def _connect(self) -> Any:
        if self._gc is None:
            import gspread  # imported lazily so dry-run mode has no hard dependency
            from google.oauth2.service_account import Credentials

            creds = Credentials.from_service_account_file(self.credentials_path, scopes=_SCOPES)
            self._gc = gspread.authorize(creds)
        return self._gc

    def open(self, sheet_id: str) -> Any:
        """スプレッドシートを開く。dry-runモードではNoneを返す。"""
        if self.dry_run:
            return None
        return self._connect().open_by_key(sheet_id)

    @staticmethod
    def sheet_id_for(sport: str) -> str | None:
        env_var = SHEET_ID_ENV_VARS.get(sport.strip().lower())
        if env_var is None:
            raise ValueError(f"no sheet id env var configured for sport: {sport!r}")
        return os.environ.get(env_var)
