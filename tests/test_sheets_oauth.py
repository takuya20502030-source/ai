"""Google Sheets User OAuth認証(第一候補) / ADC / Service Account の優先順位・
トークン再利用・リフレッシュ・非露出性を検証する。

実際のブラウザ操作やネットワークへのトークンリフレッシュは行わない
(InstalledAppFlow・Credentials.refreshをモンキーパッチして検証する)。
"""

from __future__ import annotations

import datetime
import json
import stat

import pytest

from rin_garden.sheets.client import SheetsClient, SheetsConnectionError

pytest.importorskip("google.oauth2.credentials")

from google.oauth2.credentials import Credentials as UserCredentials  # noqa: E402


def _write_token_file(path, *, expiry: str | None, refresh_token: str | None = "rt-1") -> None:
    data = {
        "token": "access-token-value",
        "refresh_token": refresh_token,
        "client_id": "cid",
        "client_secret": "csecret",
        "scopes": ["https://www.googleapis.com/auth/spreadsheets"],
    }
    if expiry:
        data["expiry"] = expiry
    path.write_text(json.dumps(data), encoding="utf-8")


def _future_expiry(hours: int = 1) -> str:
    return (datetime.datetime.utcnow() + datetime.timedelta(hours=hours)).isoformat() + "Z"


def _past_expiry(hours: int = 1) -> str:
    return (datetime.datetime.utcnow() - datetime.timedelta(hours=hours)).isoformat() + "Z"


# --- dry_run自動判定: OAuthが使える場合はGOOGLE_APPLICATION_CREDENTIALSが無くてもdry-runにしない ---


def test_dry_run_is_false_when_valid_oauth_token_exists_without_service_account(tmp_path, monkeypatch):
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    token_path = tmp_path / "token.json"
    _write_token_file(token_path, expiry=_future_expiry())

    client = SheetsClient(
        oauth_client_secret_file=str(tmp_path / "credentials.json"),  # 存在しない
        oauth_token_file=str(token_path),
    )

    assert client.dry_run is False


def test_dry_run_is_true_when_nothing_is_configured(tmp_path, monkeypatch):
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    client = SheetsClient(
        oauth_client_secret_file=str(tmp_path / "credentials.json"),
        oauth_token_file=str(tmp_path / "token.json"),
    )
    assert client.dry_run is True


# --- 優先順位: user_oauth -> adc -> service_account -> 失敗ならSheetsConnectionError ---


def test_connect_prefers_user_oauth_over_adc_and_service_account(monkeypatch, tmp_path):
    client = SheetsClient(dry_run=False)
    monkeypatch.setattr(client, "_try_user_oauth", lambda: "OAUTH_CREDS")
    monkeypatch.setattr(client, "_try_adc", lambda: "ADC_CREDS")
    monkeypatch.setattr(client, "_try_service_account", lambda: "SA_CREDS")

    captured = {}

    class _FakeGspread:
        @staticmethod
        def authorize(creds):
            captured["creds"] = creds
            return "GC"

    monkeypatch.setitem(__import__("sys").modules, "gspread", _FakeGspread)

    gc = client._connect()

    assert gc == "GC"
    assert captured["creds"] == "OAUTH_CREDS"
    assert client.auth_method == "user_oauth"


def test_connect_falls_back_to_adc_when_oauth_unavailable(monkeypatch):
    client = SheetsClient(dry_run=False)
    monkeypatch.setattr(client, "_try_user_oauth", lambda: None)
    monkeypatch.setattr(client, "_try_adc", lambda: "ADC_CREDS")
    monkeypatch.setattr(client, "_try_service_account", lambda: "SA_CREDS")

    captured = {}

    class _FakeGspread:
        @staticmethod
        def authorize(creds):
            captured["creds"] = creds
            return "GC"

    monkeypatch.setitem(__import__("sys").modules, "gspread", _FakeGspread)

    client._connect()
    assert captured["creds"] == "ADC_CREDS"
    assert client.auth_method == "adc"


def test_connect_falls_back_to_service_account_when_oauth_and_adc_unavailable(monkeypatch):
    client = SheetsClient(dry_run=False)
    monkeypatch.setattr(client, "_try_user_oauth", lambda: None)
    monkeypatch.setattr(client, "_try_adc", lambda: None)
    monkeypatch.setattr(client, "_try_service_account", lambda: "SA_CREDS")

    captured = {}

    class _FakeGspread:
        @staticmethod
        def authorize(creds):
            captured["creds"] = creds
            return "GC"

    monkeypatch.setitem(__import__("sys").modules, "gspread", _FakeGspread)

    client._connect()
    assert captured["creds"] == "SA_CREDS"
    assert client.auth_method == "service_account"


def test_connect_raises_when_all_auth_methods_fail(monkeypatch):
    client = SheetsClient(dry_run=False)
    monkeypatch.setattr(client, "_try_user_oauth", lambda: None)
    monkeypatch.setattr(client, "_try_adc", lambda: None)
    monkeypatch.setattr(client, "_try_service_account", lambda: None)

    with pytest.raises(SheetsConnectionError):
        client._connect()


# --- User OAuth: トークン再利用・リフレッシュ・ブラウザ認証への段階的フォールバック ---


def test_try_user_oauth_reuses_valid_cached_token_without_opening_browser(tmp_path, monkeypatch):
    token_path = tmp_path / "token.json"
    _write_token_file(token_path, expiry=_future_expiry())
    client = SheetsClient(
        oauth_client_secret_file=str(tmp_path / "credentials.json"),  # 存在しない: 使われたら失敗させる
        oauth_token_file=str(token_path),
    )

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("browser flow must not be triggered when a valid cached token exists")

    monkeypatch.setattr(
        "google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file",
        staticmethod(_fail_if_called),
    )

    creds = client._try_user_oauth()

    assert isinstance(creds, UserCredentials)
    assert creds.valid is True


def test_try_user_oauth_refreshes_expired_token_and_saves_it(tmp_path, monkeypatch):
    token_path = tmp_path / "token.json"
    _write_token_file(token_path, expiry=_past_expiry())
    client = SheetsClient(
        oauth_client_secret_file=str(tmp_path / "credentials.json"),
        oauth_token_file=str(token_path),
    )

    def _fake_refresh(self, request):
        self.token = "refreshed-access-token"
        self.expiry = datetime.datetime.utcnow() + datetime.timedelta(hours=1)

    monkeypatch.setattr(UserCredentials, "refresh", _fake_refresh)

    creds = client._try_user_oauth()

    assert creds is not None
    assert creds.token == "refreshed-access-token"
    saved = json.loads(token_path.read_text(encoding="utf-8"))
    assert saved["token"] == "refreshed-access-token"


def test_try_user_oauth_returns_none_without_client_secret_or_token(tmp_path):
    client = SheetsClient(
        oauth_client_secret_file=str(tmp_path / "credentials.json"),
        oauth_token_file=str(tmp_path / "token.json"),
    )
    assert client._try_user_oauth() is None


def test_try_user_oauth_runs_browser_flow_when_only_client_secret_exists(tmp_path, monkeypatch):
    client_secret_path = tmp_path / "credentials.json"
    client_secret_path.write_text("{}", encoding="utf-8")  # 中身はモックするので実際の形式は不要
    token_path = tmp_path / "token.json"
    client = SheetsClient(oauth_client_secret_file=str(client_secret_path), oauth_token_file=str(token_path))

    class _FakeCreds:
        def to_json(self) -> str:
            return json.dumps({"token": "from-browser-flow"})

    class _FakeFlow:
        def run_local_server(self, port=0):
            return _FakeCreds()

    monkeypatch.setattr(
        "google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file",
        staticmethod(lambda path, scopes: _FakeFlow()),
    )

    creds = client._try_user_oauth()

    assert isinstance(creds, _FakeCreds)
    assert token_path.exists()
    assert json.loads(token_path.read_text(encoding="utf-8"))["token"] == "from-browser-flow"


def test_saved_token_file_permissions_are_restricted(tmp_path):
    token_path = tmp_path / "token.json"
    client = SheetsClient(oauth_client_secret_file=str(tmp_path / "credentials.json"), oauth_token_file=str(token_path))

    class _FakeCreds:
        def to_json(self) -> str:
            return json.dumps({"token": "secret-value"})

    client._save_oauth_token(_FakeCreds())

    mode = stat.S_IMODE(token_path.stat().st_mode)
    assert mode == 0o600


# --- 秘密情報の非露出性 ---


def test_status_never_exposes_token_or_key_contents(tmp_path, monkeypatch):
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    token_path = tmp_path / "token.json"
    _write_token_file(token_path, expiry=_future_expiry())

    client = SheetsClient(oauth_client_secret_file=str(tmp_path / "credentials.json"), oauth_token_file=str(token_path))
    status = client.status()

    # statusはパス・真偽値のみを持ち、トークン本体やシークレット文字列を含まない
    assert status.oauth_token_path == str(token_path)
    assert isinstance(status.oauth_token_exists, bool)
    for field_name in ("oauth_client_secret_path", "oauth_token_path"):
        value = getattr(status, field_name)
        assert "access-token-value" not in value
        assert "csecret" not in value


# --- ADC availability ---


def test_adc_available_true_when_google_application_credentials_points_to_existing_file(tmp_path, monkeypatch):
    fake_adc_file = tmp_path / "adc.json"
    fake_adc_file.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(fake_adc_file))

    client = SheetsClient(
        oauth_client_secret_file=str(tmp_path / "credentials.json"),
        oauth_token_file=str(tmp_path / "token.json"),
    )
    status = client.status()

    assert status.adc_available is True
    assert "adc" in status.available_auth_methods()
