from __future__ import annotations

import json
from pathlib import Path

from .base import ConnectorError
from .secure_store import SecureTokenStore

CLIENT_FILE = Path(__file__).resolve().parents[1] / "config" / "google_oauth_client.json"


def google_dependencies():
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload
    except ImportError as exc:
        raise ConnectorError(
            "Google account dependencies are missing. Install requirements.txt first."
        ) from exc
    return Request, Credentials, InstalledAppFlow, build, MediaIoBaseDownload, MediaIoBaseUpload


class GoogleOAuthMixin:
    provider: str
    scopes: list[str]

    def _init_google_oauth(self) -> None:
        self.store = SecureTokenStore(self.provider)

    def _credentials(self, interactive: bool = False):
        Request, Credentials, InstalledAppFlow, *_ = google_dependencies()
        saved = self.store.load()
        saved_scopes = set((saved or {}).get("scopes") or [])
        required_scopes = set(self.scopes)
        scopes_changed = bool(saved and not required_scopes.issubset(saved_scopes))
        try:
            creds = (
                Credentials.from_authorized_user_info(saved, self.scopes)
                if saved and not scopes_changed else None
            )
        except ValueError:
            creds = None
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            self.store.save(json.loads(creds.to_json()))
        if (not creds or not creds.valid) and interactive:
            if not CLIENT_FILE.exists():
                raise ConnectorError(f"OAuth client file not found: {CLIENT_FILE}")
            flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_FILE), self.scopes)
            creds = flow.run_local_server(port=0, open_browser=True, prompt="consent")
            self.store.save(json.loads(creds.to_json()))
        if not creds or not creds.valid:
            if scopes_changed:
                raise ConnectorError(
                    f"{self.provider} needs authorization for its new capabilities. "
                    "Run account_connector action=connect once and approve the requested access."
                )
            raise ConnectorError(
                f"{self.provider} is not connected. Run account_connector action=connect first."
            )
        return creds

    def disconnect(self) -> str:
        from .audit import record

        self.store.delete()
        record(self.provider, "disconnect")
        return f"{self.provider} disconnected and its local token was removed from the credential vault."
