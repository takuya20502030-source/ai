"""Google Sheets クライアントの薄いラッパー。

Sheetsは表示・確認・集計用途であり、唯一のデータベースにはしない。

認証方式は優先順位付きで自動選択する(いずれも失敗した場合のみ dry-run):

    1. User OAuth  ... ユーザー本人のGoogleアカウントでのOAuth 2.0
                        (Desktop App `credentials.json` + キャッシュされた `token.json`)
    2. ADC          ... Application Default Credentials
                        (`GOOGLE_APPLICATION_CREDENTIALS` や `gcloud auth application-default login`)
    3. Service Account ... サービスアカウントJSONキー(組織ポリシーでキー発行が
                        禁止されている環境向けの後方互換Fallback。削除しない)
    4. dry-run      ... 上記すべてが利用できない場合のみ。実際の書き込みは行わず
                        ログのみを残す。

認証情報の中身(トークン・秘密鍵)はログにも画面にも出力しない。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from rin_garden.sheets.schemas import SHEET_ID_ENV_VARS

# Google Sheets APIの読み取り・書き込みに必要な最小限のscope。
# (Driveスコープ等は使わない。open_by_key()はSheets APIのみで完結する)
_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
]

_DEFAULT_OAUTH_CLIENT_SECRET_FILE = "credentials.json"
_DEFAULT_OAUTH_TOKEN_FILE = "token.json"


class SheetsConnectionError(Exception):
    """実際のgspread接続確立に失敗した場合に送出する(dry-runでは発生しない)。

    メッセージには認証情報の中身(トークン・秘密鍵等)を含めないこと。
    """


def _adc_well_known_path() -> Path:
    """`gcloud auth application-default login` が書き出すADCファイルの既定パス。"""
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", ""))
    else:
        base = Path.home() / ".config"
    return base / "gcloud" / "application_default_credentials.json"


def _adc_available() -> bool:
    """ADCが利用可能そうかをファイル存在のみで判定する(ネットワークアクセスなし)。"""
    gac = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if gac and Path(gac).exists():
        return True
    return _adc_well_known_path().exists()


@dataclass
class SheetsConnectionStatus:
    """接続に必要な設定が揃っているかの非破壊的な自己申告。処理を止めずに使う。

    ファイルの「有無」のみを報告し、中身は一切含めない。
    """

    dry_run: bool
    oauth_client_secret_path: str
    oauth_client_secret_exists: bool
    oauth_token_path: str
    oauth_token_exists: bool
    adc_available: bool
    credentials_path: str | None
    credentials_file_exists: bool
    sheet_ids: dict[str, str | None] = field(default_factory=dict)

    def available_auth_methods(self) -> list[str]:
        """優先順位順に、利用可能そうな認証方式の名前を返す(ファイル存在ベース)。"""
        methods = []
        if self.oauth_client_secret_exists or self.oauth_token_exists:
            methods.append("user_oauth")
        if self.adc_available:
            methods.append("adc")
        if self.credentials_file_exists:
            methods.append("service_account")
        return methods

    def missing_items(self) -> list[str]:
        missing = []
        if not self.available_auth_methods():
            missing.append(
                "認証方法が一つも設定されていません。次のいずれかを用意してください: "
                f"(1) User OAuth: {self.oauth_client_secret_path} を配置し初回にブラウザ認証 / "
                "(2) ADC: `gcloud auth application-default login` を実行 / "
                "(3) Service Account: GOOGLE_APPLICATION_CREDENTIALS にJSONキーのパスを設定"
            )
        for sport, env_var in SHEET_ID_ENV_VARS.items():
            if not self.sheet_ids.get(sport):
                missing.append(f"{env_var} ({sport}用 Sheet ID未設定)")
        return missing


class SheetsClient:
    """gspreadへの接続を遅延生成するクライアント。

    利用可能な認証情報が一つも無い場合はdry_run=Trueとなり、open()はNoneを返す
    (呼び出し側はNoneをdry-runの合図として扱う)。dry_runの自動判定はファイルの
    有無のみを見て行い、実際の認証(ブラウザを開く等)は`.open()`が呼ばれて
    `_connect()`が実行されるまで発生しない。

    テスト用に `fake_backend` (sheet_id -> スプレッドシート風オブジェクトを返す
    callable) を渡すと、実際のgspread/ネットワークなしで動作を検証できる。
    """

    def __init__(
        self,
        credentials_path: str | None = None,
        dry_run: bool | None = None,
        fake_backend: Callable[[str], Any] | None = None,
        oauth_client_secret_file: str | None = None,
        oauth_token_file: str | None = None,
    ):
        self.credentials_path = credentials_path or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        self.oauth_client_secret_file = Path(
            oauth_client_secret_file
            or os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET_FILE")
            or _DEFAULT_OAUTH_CLIENT_SECRET_FILE
        )
        self.oauth_token_file = Path(
            oauth_token_file or os.environ.get("GOOGLE_OAUTH_TOKEN_FILE") or _DEFAULT_OAUTH_TOKEN_FILE
        )
        self._fake_backend = fake_backend
        self._gc: Any = None
        self._auth_method: str | None = None

        if fake_backend is not None:
            self.dry_run = False
        elif dry_run is not None:
            self.dry_run = dry_run
        else:
            has_oauth = self.oauth_client_secret_file.exists() or self.oauth_token_file.exists()
            has_adc = _adc_available()
            has_service_account = bool(self.credentials_path) and os.path.exists(self.credentials_path)
            self.dry_run = not (has_oauth or has_adc or has_service_account)

    # --- 認証方式ごとのresolver。いずれも例外を外へ漏らさずNoneで失敗を表す ---
    # (優先順位: user_oauth -> adc -> service_account)

    def _try_user_oauth(self) -> Any | None:
        try:
            from google.auth.transport.requests import Request as GoogleAuthRequest
            from google.oauth2.credentials import Credentials as UserCredentials
        except ImportError:
            return None

        creds = None
        if self.oauth_token_file.exists():
            try:
                creds = UserCredentials.from_authorized_user_file(str(self.oauth_token_file), _SCOPES)
            except Exception:  # noqa: BLE001 - 壊れたtoken.jsonは「無い」扱いにして次の手段へ進む
                creds = None

        if creds is not None and creds.valid:
            return creds

        if creds is not None and creds.expired and creds.refresh_token:
            try:
                creds.refresh(GoogleAuthRequest())
                self._save_oauth_token(creds)
                return creds
            except Exception:  # noqa: BLE001
                creds = None

        if not self.oauth_client_secret_file.exists():
            return None

        try:
            from google_auth_oauthlib.flow import InstalledAppFlow
        except ImportError:
            return None

        try:
            # 初回のみブラウザを開いてユーザー本人のGoogleログイン・承認を求める。
            flow = InstalledAppFlow.from_client_secrets_file(str(self.oauth_client_secret_file), _SCOPES)
            creds = flow.run_local_server(port=0)
        except Exception:  # noqa: BLE001 - ブラウザ操作不可・拒否等は次の認証方式へフォールバック
            return None

        self._save_oauth_token(creds)
        return creds

    def _save_oauth_token(self, creds: Any) -> None:
        """取得したユーザートークンをローカルへ保存する(次回以降の再利用のため)。

        内容自体をログ・画面へ出力することはない。保存に失敗しても認証結果は
        そのまま使い、次回また認証が必要になるだけとする。
        """
        try:
            self.oauth_token_file.parent.mkdir(parents=True, exist_ok=True)
            self.oauth_token_file.write_text(creds.to_json(), encoding="utf-8")
            os.chmod(self.oauth_token_file, 0o600)
        except OSError:
            pass

    def _try_adc(self) -> Any | None:
        try:
            import google.auth
        except ImportError:
            return None
        try:
            creds, _project = google.auth.default(scopes=_SCOPES)
            return creds
        except Exception:  # noqa: BLE001 - google.auth.default()はADC未設定時にDefaultCredentialsErrorを送出する
            return None

    def _try_service_account(self) -> Any | None:
        if not self.credentials_path or not os.path.exists(self.credentials_path):
            return None
        try:
            from google.oauth2.service_account import Credentials as ServiceAccountCredentials
        except ImportError:
            return None
        try:
            return ServiceAccountCredentials.from_service_account_file(self.credentials_path, scopes=_SCOPES)
        except Exception:  # noqa: BLE001
            return None

    def _connect(self) -> Any:
        if self._gc is None:
            try:
                import gspread  # imported lazily so dry-run mode has no hard dependency
            except ImportError as exc:  # pragma: no cover - depends on optional deps
                raise SheetsConnectionError(
                    "gspread is not installed; run `pip install -r requirements.txt`"
                ) from exc

            creds = None
            method = None
            for name, resolver in (
                ("user_oauth", self._try_user_oauth),
                ("adc", self._try_adc),
                ("service_account", self._try_service_account),
            ):
                creds = resolver()
                if creds is not None:
                    method = name
                    break

            if creds is None:
                raise SheetsConnectionError(
                    "no usable Google credentials found (tried in order: user_oauth, adc, service_account)"
                )

            self._gc = gspread.authorize(creds)
            self._auth_method = method
        return self._gc

    def open(self, sheet_id: str) -> Any:
        """スプレッドシートを開く。dry-runモードではNoneを返す。"""
        if self._fake_backend is not None:
            return self._fake_backend(sheet_id)
        if self.dry_run:
            return None
        return self._connect().open_by_key(sheet_id)

    @property
    def auth_method(self) -> str | None:
        """実際に使われた認証方式("user_oauth"/"adc"/"service_account")。未接続ならNone。"""
        return self._auth_method

    def status(self) -> SheetsConnectionStatus:
        """処理を止めずに、接続に必要な設定が揃っているかを報告する(ファイル存在のみ)。"""
        return SheetsConnectionStatus(
            dry_run=self.dry_run,
            oauth_client_secret_path=str(self.oauth_client_secret_file),
            oauth_client_secret_exists=self.oauth_client_secret_file.exists(),
            oauth_token_path=str(self.oauth_token_file),
            oauth_token_exists=self.oauth_token_file.exists(),
            adc_available=_adc_available(),
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
