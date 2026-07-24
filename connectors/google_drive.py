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
    scopes = ["https://www.googleapis.com/auth/drive"]
    capabilities = ConnectorCapabilities(
        search=True, read=True, download=True, create_file=True, create_folder=True
    )

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
            spaces="drive", includeItemsFromAllDrives=True, supportsAllDrives=True,
        ).execute()
        files = [self._file(item) for item in result.get("files", [])]
        record(self.provider, "search", count=len(files))
        return files

    def find_folder(self, name: str, parent_id: str = "", limit: int = 20) -> list[dict[str, Any]]:
        clean_name = str(name or "").strip()
        if not clean_name:
            raise ConnectorError("A folder name is required.")
        safe = clean_name.replace("\\", "\\\\").replace("'", "\\'")
        q = (
            "trashed = false and "
            "mimeType = 'application/vnd.google-apps.folder' and "
            f"name contains '{safe}'"
        )
        if parent_id:
            q += f" and '{parent_id}' in parents"
        result = self._service().files().list(
            q=q, pageSize=max(1, min(limit, 50)),
            fields="files(id,name,mimeType,modifiedTime,size,webViewLink,parents)",
            orderBy="name",
            spaces="drive", includeItemsFromAllDrives=True, supportsAllDrives=True,
        ).execute()
        folders = []
        for item in result.get("files", []):
            normalized = self._file(item)
            normalized["parents"] = list(item.get("parents", []))
            folders.append(normalized)
        record(self.provider, "find_folder", count=len(folders))
        return folders

    def list_children(self, parent_id: str, limit: int = 50) -> list[dict[str, Any]]:
        if not parent_id:
            raise ConnectorError("A Google Drive parent folder ID is required.")
        result = self._service().files().list(
            q=f"trashed = false and '{parent_id}' in parents",
            pageSize=max(1, min(limit, 100)),
            fields="files(id,name,mimeType,modifiedTime,size,webViewLink,parents)",
            orderBy="folder,name",
            spaces="drive", includeItemsFromAllDrives=True, supportsAllDrives=True,
        ).execute()
        children = []
        for item in result.get("files", []):
            normalized = self._file(item)
            normalized["parents"] = list(item.get("parents", []))
            children.append(normalized)
        record(self.provider, "list_children", count=len(children))
        return children

    def create_folder(self, name: str, parent_id: str = "") -> dict[str, Any]:
        clean_name = Path(name or "").name.strip()
        if not clean_name or clean_name in {".", ".."}:
            raise ConnectorError("A non-empty folder name is required.")
        metadata: dict[str, Any] = {
            "name": clean_name,
            "mimeType": "application/vnd.google-apps.folder",
        }
        if parent_id:
            metadata["parents"] = [parent_id]
        created = self._service().files().create(
            body=metadata,
            fields="id,name,mimeType,modifiedTime,size,webViewLink,parents",
            supportsAllDrives=True,
        ).execute()
        verified = self._verify_created(created.get("id", ""), clean_name)
        record(self.provider, "create_folder", count=1)
        return verified

    def create_file(
        self, name: str, content: str = "", parent_id: str = "",
        mime_type: str = "text/plain",
    ) -> dict[str, Any]:
        clean_name = Path(name or "").name.strip()
        if not clean_name or clean_name in {".", ".."}:
            raise ConnectorError("A non-empty file name is required.")
        media_upload = google_dependencies()[5]
        media = media_upload(
            io.BytesIO(str(content).encode("utf-8")),
            mimetype=(mime_type or "text/plain").strip(), resumable=False,
        )
        metadata: dict[str, Any] = {"name": clean_name}
        if parent_id:
            metadata["parents"] = [parent_id]
        created = self._service().files().create(
            body=metadata, media_body=media,
            fields="id,name,mimeType,modifiedTime,size,webViewLink,parents",
            supportsAllDrives=True,
        ).execute()
        verified = self._verify_created(created.get("id", ""), clean_name)
        record(self.provider, "create_file", count=1)
        return verified

    def _verify_created(self, item_id: str, expected_name: str) -> dict[str, Any]:
        """Read the new item back so a success message always means it exists."""
        if not item_id:
            raise ConnectorError("Google Drive returned no ID for the created item.")
        item = self._service().files().get(
            fileId=item_id,
            fields="id,name,mimeType,modifiedTime,size,webViewLink,parents,trashed",
            supportsAllDrives=True,
        ).execute()
        if item.get("trashed") or item.get("name") != expected_name:
            raise ConnectorError(
                f"Creation could not be verified for {expected_name!r} (ID {item_id})."
            )
        result = self._file(item)
        result["parents"] = list(item.get("parents", []))
        result["verified"] = True
        return result

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
