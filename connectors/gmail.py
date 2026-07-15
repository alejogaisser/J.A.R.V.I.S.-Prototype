from __future__ import annotations

import base64
import html
import json
import re
from dataclasses import asdict
from email.header import decode_header, make_header
from pathlib import Path
from typing import Any

from .audit import record
from .base import AccountConnector, ConnectorCapabilities, ConnectorError
from .secure_store import SecureTokenStore

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
CLIENT_FILE = Path(__file__).resolve().parents[1] / "config" / "google_oauth_client.json"


def _deps():
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise ConnectorError(
            "Gmail dependencies are missing. Install requirements.txt first."
        ) from exc
    return Request, Credentials, InstalledAppFlow, build


def _decode(value: str) -> str:
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def _body(payload: dict) -> str:
    candidates: list[tuple[str, str]] = []

    def visit(part: dict) -> None:
        data = (part.get("body") or {}).get("data")
        if data:
            candidates.append((part.get("mimeType", ""), data))
        for child in part.get("parts") or []:
            visit(child)

    visit(payload)
    for wanted in ("text/plain", "text/html"):
        for mime, data in candidates:
            if mime == wanted:
                text = base64.urlsafe_b64decode(data + "===").decode("utf-8", errors="replace")
                if mime == "text/html":
                    text = re.sub(r"<[^>]+>", " ", html.unescape(text))
                return re.sub(r"\s+", " ", text).strip()
    return ""


class GmailConnector(AccountConnector):
    provider = "gmail"
    capabilities = ConnectorCapabilities(search=True, read=True, download=True)

    def __init__(self) -> None:
        self.store = SecureTokenStore(self.provider)

    def _credentials(self, interactive: bool = False):
        Request, Credentials, InstalledAppFlow, _ = _deps()
        saved = self.store.load()
        creds = Credentials.from_authorized_user_info(saved, SCOPES) if saved else None
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            self.store.save(json.loads(creds.to_json()))
        if (not creds or not creds.valid) and interactive:
            if not CLIENT_FILE.exists():
                raise ConnectorError(
                    f"OAuth client file not found: {CLIENT_FILE}. See config/google_oauth_client.example.json."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_FILE), SCOPES)
            creds = flow.run_local_server(port=0, open_browser=True, prompt="consent")
            self.store.save(json.loads(creds.to_json()))
        if not creds or not creds.valid:
            raise ConnectorError("Gmail is not connected. Run account_connector action=connect first.")
        return creds

    def _service(self):
        *_, build = _deps()
        return build("gmail", "v1", credentials=self._credentials(), cache_discovery=False)

    def connect(self) -> str:
        creds = self._credentials(interactive=True)
        profile = _deps()[3]("gmail", "v1", credentials=creds, cache_discovery=False).users().getProfile(userId="me").execute()
        record(self.provider, "connect")
        return f"Gmail connected: {profile.get('emailAddress', 'account authorized')}"

    def disconnect(self) -> str:
        self.store.delete()
        record(self.provider, "disconnect")
        return "Gmail disconnected and its local token was removed from the credential vault."

    def status(self) -> dict[str, Any]:
        try:
            creds = self._credentials()
            return {"provider": self.provider, "connected": bool(creds.valid), "capabilities": asdict(self.capabilities)}
        except Exception as exc:
            return {"provider": self.provider, "connected": False, "reason": str(exc)}

    def search(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        service = self._service()
        found = service.users().messages().list(userId="me", q=query, maxResults=max(1, min(limit, 25))).execute()
        results = []
        for ref in found.get("messages", []):
            msg = service.users().messages().get(userId="me", id=ref["id"], format="metadata", metadataHeaders=["From", "Subject", "Date"]).execute()
            headers = {h["name"].lower(): _decode(h["value"]) for h in msg.get("payload", {}).get("headers", [])}
            results.append({"id": ref["id"], "from": headers.get("from", ""), "subject": headers.get("subject", ""), "date": headers.get("date", ""), "snippet": msg.get("snippet", "")})
        record(self.provider, "search", count=len(results))
        return results

    def read(self, item_id: str) -> dict[str, Any]:
        msg = self._service().users().messages().get(userId="me", id=item_id, format="full").execute()
        payload = msg.get("payload", {})
        headers = {h["name"].lower(): _decode(h["value"]) for h in payload.get("headers", [])}
        attachments = []

        def visit(part: dict) -> None:
            if part.get("filename") and (part.get("body") or {}).get("attachmentId"):
                attachments.append({"filename": part["filename"], "attachment_id": part["body"]["attachmentId"]})
            for child in part.get("parts") or []:
                visit(child)

        visit(payload)
        record(self.provider, "read")
        return {"id": item_id, "from": headers.get("from", ""), "to": headers.get("to", ""), "subject": headers.get("subject", ""), "date": headers.get("date", ""), "body": _body(payload), "attachments": attachments}

    def download(self, item_id: str, attachment: str, destination: Path) -> Path:
        message = self.read(item_id)
        match = next((item for item in message["attachments"] if item["filename"].lower() == attachment.lower() or item["attachment_id"] == attachment), None)
        if not match:
            raise ConnectorError(f"Attachment not found: {attachment}")
        raw = self._service().users().messages().attachments().get(userId="me", messageId=item_id, id=match["attachment_id"]).execute()["data"]
        destination.mkdir(parents=True, exist_ok=True)
        target = destination / Path(match["filename"]).name
        target.write_bytes(base64.urlsafe_b64decode(raw + "==="))
        record(self.provider, "download", destination=str(target))
        return target
