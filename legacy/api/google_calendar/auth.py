import json
import os
import tempfile
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow

DIR_NAME = Path(__file__).resolve().parent
CODE_FILE = DIR_NAME / "code"
CREDENTIALS_FILE = DIR_NAME / "credentials"
REDIRECT_URI = "https://legacy.clist.by/api/google_calendar/exchange-code.php"
SCOPES = ["https://www.googleapis.com/auth/calendar"]
AUTH_URI = "https://accounts.google.com/o/oauth2/auth"
TOKEN_URI = "https://oauth2.googleapis.com/token"


def _parse_expiry(value):
    if not value:
        return None
    expiry = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if expiry.tzinfo is not None:
        expiry = expiry.astimezone(UTC).replace(tzinfo=None)
    return expiry


def _normalize_scopes(scopes):
    if not scopes:
        return SCOPES
    if isinstance(scopes, str):
        return scopes.split()
    return scopes


def credentials_from_info(info):
    if "access_token" not in info:
        return Credentials.from_authorized_user_info(info, scopes=SCOPES)

    token_response = info.get("token_response") or {}
    return Credentials(
        token=info.get("access_token") or token_response.get("access_token"),
        refresh_token=info.get("refresh_token"),
        token_uri=info.get("token_uri") or TOKEN_URI,
        client_id=info.get("client_id"),
        client_secret=info.get("client_secret"),
        scopes=_normalize_scopes(info.get("scopes") or token_response.get("scope")),
        expiry=_parse_expiry(info.get("token_expiry")),
    )


def save_credentials(credentials, filename=CREDENTIALS_FILE):
    filename = Path(filename)
    mode = filename.stat().st_mode & 0o777 if filename.exists() else 0o600
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{filename.name}.", dir=filename.parent, text=True)
    try:
        os.fchmod(descriptor, mode)
        output = os.fdopen(descriptor, "w", encoding="utf-8")
        descriptor = None
        with output:
            output.write(credentials.to_json())
            output.write("\n")
        os.replace(temporary_name, filename)
    except BaseException:
        if descriptor is not None:
            with suppress(OSError):
                os.close(descriptor)
        with suppress(FileNotFoundError):
            os.unlink(temporary_name)
        raise


def consume_authorization_code(filename=CODE_FILE):
    filename = Path(filename)
    if not filename.exists():
        return None
    code = filename.read_text(encoding="utf-8").strip()
    filename.write_text("", encoding="utf-8")
    return code or None


def load_credentials(filename=CREDENTIALS_FILE):
    filename = Path(filename)
    info = json.loads(filename.read_text(encoding="utf-8"))
    old_format = "access_token" in info
    credentials = credentials_from_info(info)

    if credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
        save_credentials(credentials, filename)
    elif not credentials.valid:
        raise RuntimeError("Google Calendar credentials are invalid; run create-token.py")
    elif old_format:
        save_credentials(credentials, filename)

    return credentials


def create_flow(client_id, client_secret, redirect_uri=REDIRECT_URI):
    client_config = {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": AUTH_URI,
            "token_uri": TOKEN_URI,
            "redirect_uris": [redirect_uri],
        },
    }
    return Flow.from_client_config(client_config, scopes=SCOPES, redirect_uri=redirect_uri)
