from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from .audit import record
from .base import AccountConnector, ConnectorCapabilities, ConnectorError
from .google_common import GoogleOAuthMixin, google_dependencies


class GoogleCalendarConnector(GoogleOAuthMixin, AccountConnector):
    provider = "google_calendar"
    scopes = ["https://www.googleapis.com/auth/calendar.readonly"]
    capabilities = ConnectorCapabilities(search=True, read=True)

    def __init__(self) -> None:
        self._init_google_oauth()

    def _service(self):
        build = google_dependencies()[3]
        return build("calendar", "v3", credentials=self._credentials(), cache_discovery=False)

    def connect(self) -> str:
        creds = self._credentials(interactive=True)
        service = google_dependencies()[3]("calendar", "v3", credentials=creds, cache_discovery=False)
        primary = service.calendars().get(calendarId="primary").execute()
        record(self.provider, "connect")
        return f"Google Calendar connected: {primary.get('summary', 'primary calendar')}"

    def status(self) -> dict[str, Any]:
        try:
            return {"provider": self.provider, "connected": bool(self._credentials().valid), "capabilities": asdict(self.capabilities)}
        except Exception as exc:
            return {"provider": self.provider, "connected": False, "reason": str(exc)}

    @staticmethod
    def _event(item: dict[str, Any]) -> dict[str, Any]:
        start = item.get("start") or {}
        end = item.get("end") or {}
        return {
            "id": item.get("id", ""),
            "summary": item.get("summary", "(no title)"),
            "start": start.get("dateTime") or start.get("date", ""),
            "end": end.get("dateTime") or end.get("date", ""),
            "location": item.get("location", ""),
            "status": item.get("status", ""),
            "html_link": item.get("htmlLink", ""),
        }

    def search(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        result = self._service().events().list(
            calendarId="primary", q=query or None, maxResults=max(1, min(limit, 50)),
            singleEvents=True, orderBy="startTime", timeMin="1970-01-01T00:00:00Z",
        ).execute()
        events = [self._event(item) for item in result.get("items", [])]
        record(self.provider, "search", count=len(events))
        return events

    def read(self, item_id: str) -> dict[str, Any]:
        item = self._service().events().get(calendarId="primary", eventId=item_id).execute()
        result = self._event(item)
        result["description"] = item.get("description", "")
        result["attendees"] = [entry.get("email", "") for entry in item.get("attendees", [])]
        record(self.provider, "read")
        return result

    def download(self, item_id: str, attachment: str, destination: Path) -> Path:
        raise ConnectorError("Google Calendar events do not support attachment downloads yet.")

