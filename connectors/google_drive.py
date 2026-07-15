from __future__ import annotations

import io
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .audit import record
from .base import AccountConnector, ConnectorCapabilities, ConnectorError
from .google_common import GoogleOAuthMixin, google_dependencies

GOOGLE_EXPORTS = {
    "application/vnd.google-apps.document": ("application/pdf", ".pdf"),
    "application/vnd.google-apps.spreadsheet": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".xlsx"),
    "application/vnd.google-apps.presentation": ("application/vnd.openxmlformats-officedocument.presentationml.presentation", ".pptx"),
}


class GoogleDriveConnector(GoogleOAuthMixin, AccountConnector):
    provider = "google_drive"
    scopes = ["https://www.googleapis.com/auth/drive.readonly"]
    capabilities = ConnectorCapabilities(search=True, read=True, download=True)

    def __init__(self) -> None:
        self._init_google_oauth()

    def _service(self):
        build = google_dependencies()[3]
        return build("drive", "v3", credentials=self._credentials(), cache_discovery=False)

    def connect(self) -> str:
        creds = self._credentials(interactive=True)
        service = google_dependencies()[3]("drive", "v3", credentials=creds, cache_discovery=False)
        about = service.about().get(fields="user(displayName,emailAddress)").execute().get("user", {})
        record(self.provider, "connect")
        return f"Google Drive connected: {about.get('emailAddress') or about.get('displayName', 'authorized account')}"

    def status(self) -> dict[str, Any]:
        try:
            return {"provider": self.provider, "connected": bool(self._credentials().valid), "capabilities": asdict(self.capabilities)}
        except Exception as exc:
            return {"provider": self.provider, "connected": False, "reason": str(exc)}

    @staticmethod
    def _file(item: dict[str, Any]) -> dict[str, Any]:
        return {key: item.get(key, "") for key in ("id", "name", "mimeType", "modifiedTime", "size", "webViewLink")}

    def search(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        safe = (query or "").replace("\\", "\\\\").replace("'", "\\'")
        q = "trashed = false"
        if safe:
            q += f" and fullText contains '{safe}'"
        result = self._service().files().list(
            q=q, pageSize=max(1, min(limit, 50)),
            fields="files(id,name,mimeType,modifiedTime,size,webViewLink)",
            orderBy="modifiedTime desc",
        ).execute()
        files = [self._file(item) for item in result.get("files", [])]
        record(self.provider, "search", count=len(files))
        return files

    def read(self, item_id: str) -> dict[str, Any]:
        item = self._service().files().get(
            fileId=item_id,
            fields="id,name,mimeType,modifiedTime,size,webViewLink,description,owners(displayName,emailAddress)",
        ).execute()
        result = self._file(item)
        result["description"] = item.get("description", "")
        result["owners"] = [owner.get("displayName") or owner.get("emailAddress", "") for owner in item.get("owners", [])]
        record(self.provider, "read")
        return result

    def download(self, item_id: str, attachment: str, destination: Path) -> Path:
        service = self._service()
        item = service.files().get(fileId=item_id, fields="id,name,mimeType").execute()
        name = Path(item.get("name") or attachment or item_id).name
        mime = item.get("mimeType", "")
        if mime in GOOGLE_EXPORTS:
            export_mime, suffix = GOOGLE_EXPORTS[mime]
            request = service.files().export_media(fileId=item_id, mimeType=export_mime)
            if not name.lower().endswith(suffix):
                name += suffix
        elif mime.startswith("application/vnd.google-apps."):
            raise ConnectorError(f"This Google file type cannot be exported yet: {mime}")
        else:
            request = service.files().get_media(fileId=item_id)
        destination.mkdir(parents=True, exist_ok=True)
        target = destination / name
        stream = io.FileIO(target, "wb")
        downloader = google_dependencies()[4](stream, request)
        done = False
        try:
            while not done:
                _, done = downloader.next_chunk()
        finally:
            stream.close()
        record(self.provider, "download", destination=str(target))
        return target

