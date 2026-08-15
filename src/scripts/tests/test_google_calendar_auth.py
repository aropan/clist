import importlib.util
import json
import os
import stat
from pathlib import Path
from unittest.mock import Mock

import pytest

AUTH_PATH = next(
    parent / "legacy" / "api" / "google_calendar" / "auth.py"
    for parent in Path(__file__).parents
    if (parent / "legacy" / "api" / "google_calendar" / "auth.py").is_file()
)
SPEC = importlib.util.spec_from_file_location("google_calendar_auth", AUTH_PATH)
assert SPEC
assert SPEC.loader
auth = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(auth)


def test_load_credentials_converts_oauth2client_format(tmp_path):
    filename = tmp_path / "credentials"
    filename.write_text(
        json.dumps({
            "access_token": "access-token",
            "refresh_token": "refresh-token",
            "token_expiry": "2999-01-01T00:00:00Z",
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_id": "client-id",
            "client_secret": "client-secret",
            "scopes": auth.SCOPES,
            "token_response": {"access_token": "access-token", "token_type": "Bearer"},
        }),
        encoding="utf-8",
    )
    filename.chmod(0o640)

    credentials = auth.load_credentials(filename)

    assert credentials.valid
    assert credentials.token == "access-token"
    assert credentials.refresh_token == "refresh-token"
    saved = json.loads(filename.read_text(encoding="utf-8"))
    assert saved["token"] == "access-token"
    assert "access_token" not in saved
    assert stat.S_IMODE(filename.stat().st_mode) == 0o640


def test_create_flow_uses_calendar_scope_and_redirect_uri():
    flow = auth.create_flow("client-id", "client-secret")

    assert flow.redirect_uri == "https://legacy.clist.by/api/google_calendar/exchange-code.php"
    assert flow.oauth2session.scope == auth.SCOPES


def test_consume_authorization_code_truncates_file(tmp_path):
    filename = tmp_path / "code"
    filename.write_text("  one-time-code\n", encoding="utf-8")

    code = auth.consume_authorization_code(filename)

    assert code == "one-time-code"
    assert filename.read_text(encoding="utf-8") == ""


def test_consume_authorization_code_returns_none_for_missing_file(tmp_path):
    assert auth.consume_authorization_code(tmp_path / "missing-code") is None


def test_save_credentials_does_not_close_transferred_descriptor_twice(tmp_path, monkeypatch):
    credentials = Mock()
    credentials.to_json.return_value = '{"token": "test"}'
    close = Mock(wraps=os.close)
    monkeypatch.setattr(auth.os, "close", close)
    monkeypatch.setattr(auth.os, "replace", Mock(side_effect=OSError("replace failed")))

    with pytest.raises(OSError, match="replace failed"):
        auth.save_credentials(credentials, tmp_path / "credentials")

    close.assert_not_called()
    assert list(tmp_path.iterdir()) == []
