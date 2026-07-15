from __future__ import annotations

import html
import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any

import requests

from .audit import record
from .base import AccountConnector, ConnectorCapabilities, ConnectorError
from .secure_store import SecureTokenStore

CONFIG_FILE = Path(__file__).resolve().parents[1] / "config" / "microsoft_oauth_client.json"
GRAPH_ROOT = "https://graph.microsoft.com/v1.0"
SCOPES = ["Mail.Read", "User.Read"]


def microsoft_dependency():
    try:
        import msal
    except ImportError as exc:
        raise ConnectorError("Microsoft account dependencies are missing. Install requirements.txt first.") from exc
    return msal


def _plain_text(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html.unescape(value or ""))
    return re.sub(r"\s+", " ", text).strip()


class OutlookConnector(AccountConnector):
    provider = "outlook"
    capabilities = ConnectorCapabilities(search=True, read=True, download=True)

    def __init__(self) -> None:
        self.store = SecureTokenStore(self.provider)

    def _settings(self) -> dict[str, str]:
        if not CONFIG_FILE.exists():
            raise ConnectorError(
                f"Microsoft OAuth client file not found: {CONFIG_FILE}. "
                "Create it from config/microsoft_oauth_client.example.json."
            )
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ConnectorError("Microsoft OAuth client file is not valid JSON.") from exc
        client_id = str(data.get("client_id", "")).strip()
        authority = str(data.get("authority", "https://login.microsoftonline.com/organizations")).rstrip("/")
        if not client_id:
            raise ConnectorError("Microsoft OAuth client_id is missing.")
        return {"client_id": client_id, "authority": authority}

    def _application(self):
        msal = microsoft_dependency()
        settings = self._settings()
        cache = msal.SerializableTokenCache()
        saved = self.store.load() or {}
        if saved.get("cache"):
            cache.deserialize(saved["cache"])
        app = msal.PublicClientApplication(
            settings["client_id"], authority=settings["authority"], token_cache=cache
        )
        return app, cache

    def _save_cache(self, cache) -> None:
        if cache.has_state_changed:
            self.store.save({"cache": cache.serialize()})

    def _token(self, interactive: bool = False) -> str:
        app, cache = self._application()
        accounts = app.get_accounts()
        result = app.acquire_token_silent(SCOPES, account=accounts[0]) if accounts else None
        if not result and interactive:
            result = app.acquire_token_interactive(
                scopes=SCOPES,
                prompt="select_account",
                timeout=180,
            )
        self._save_cache(cache)
        if result and result.get("access_token"):
            return result["access_token"]
        detail = (result or {}).get("error_description") or (result or {}).get("error")
        if detail:
            raise ConnectorError(f"Microsoft authorization failed: {detail}")
        raise ConnectorError("Outlook is not connected. Run account_connector action=connect first.")

    def _request(self, method: str, path: str, **kwargs):
        headers = dict(kwargs.pop("headers", {}))
        headers["Authorization"] = f"Bearer {self._token()}"
        response = requests.request(method, f"{GRAPH_ROOT}{path}", headers=headers, timeout=30, **kwargs)
        if response.status_code >= 400:
            try:
                message = response.json().get("error", {}).get("message", response.text)
            except ValueError:
                message = response.text
            raise ConnectorError(f"Microsoft Graph error {response.status_code}: {message}")
        return response

    def connect(self) -> str:
        token = self._token(interactive=True)
        response = requests.get(
            f"{GRAPH_ROOT}/me",
            headers={"Authorization": f"Bearer {token}"},
            params={"$select": "displayName,mail,userPrincipalName"},
            timeout=30,
        )
        if response.status_code >= 400:
            raise ConnectorError(f"Microsoft Graph connection check failed: {response.text}")
        profile = response.json()
        record(self.provider, "connect")
        identity = profile.get("mail") or profile.get("userPrincipalName") or profile.get("displayName")
        return f"Outlook connected: {identity or 'authorized account'}"

    def disconnect(self) -> str:
        self.store.delete()
        record(self.provider, "disconnect")
        return "Outlook disconnected and its local token was removed from the credential vault."

    def status(self) -> dict[str, Any]:
        try:
            return {"provider": self.provider, "connected": bool(self._token()), "capabilities": asdict(self.capabilities)}
        except Exception as exc:
            return {"provider": self.provider, "connected": False, "reason": str(exc)}

    @staticmethod
    def _message(item: dict[str, Any]) -> dict[str, Any]:
        sender = ((item.get("from") or {}).get("emailAddress") or {})
        return {
            "id": item.get("id", ""),
            "from": sender.get("address", ""),
            "from_name": sender.get("name", ""),
            "subject": item.get("subject", ""),
            "date": item.get("receivedDateTime", ""),
            "snippet": item.get("bodyPreview", ""),
            "has_attachments": bool(item.get("hasAttachments")),
            "web_link": item.get("webLink", ""),
        }

    def search(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        params = {
            "$select": "id,from,subject,receivedDateTime,bodyPreview,hasAttachments,webLink",
            "$top": max(1, min(limit, 25)),
        }
        headers = {}
        if query.strip():
            params["$search"] = f'"{query.strip()}"'
            headers["ConsistencyLevel"] = "eventual"
        else:
            params["$orderby"] = "receivedDateTime desc"
        items = self._request("GET", "/me/messages", params=params, headers=headers).json().get("value", [])
        results = [self._message(item) for item in items]
        record(self.provider, "search", count=len(results))
        return results

    def read(self, item_id: str) -> dict[str, Any]:
        params = {
            "$select": "id,from,toRecipients,subject,receivedDateTime,body,hasAttachments,webLink"
        }
        item = self._request(
            "GET", f"/me/messages/{item_id}", params=params,
            headers={"Prefer": 'outlook.body-content-type="text"'},
        ).json()
        result = self._message(item)
        result["to"] = [
            (entry.get("emailAddress") or {}).get("address", "")
            for entry in item.get("toRecipients", [])
        ]
        body = (item.get("body") or {}).get("content", "")
        result["body"] = body if (item.get("body") or {}).get("contentType") == "text" else _plain_text(body)
        result["attachments"] = []
        if item.get("hasAttachments"):
            attachments = self._request(
                "GET", f"/me/messages/{item_id}/attachments",
                params={"$select": "id,name,contentType,size,isInline"},
            ).json().get("value", [])
            result["attachments"] = [
                {"attachment_id": value.get("id", ""), "filename": value.get("name", ""),
                 "content_type": value.get("contentType", ""), "size": value.get("size", 0)}
                for value in attachments if not value.get("isInline")
            ]
        record(self.provider, "read")
        return result

    def download(self, item_id: str, attachment: str, destination: Path) -> Path:
        message = self.read(item_id)
        match = next(
            (item for item in message["attachments"]
             if item["filename"].lower() == attachment.lower() or item["attachment_id"] == attachment),
            None,
        )
        if not match:
            raise ConnectorError(f"Attachment not found: {attachment}")
        response = self._request(
            "GET", f"/me/messages/{item_id}/attachments/{match['attachment_id']}/$value"
        )
        destination.mkdir(parents=True, exist_ok=True)
        target = destination / Path(match["filename"]).name
        target.write_bytes(response.content)
        record(self.provider, "download", destination=str(target))
        return target
