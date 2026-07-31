from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from .audit import record
from .base import AccountConnector, ConnectorCapabilities, ConnectorError
from .google_common import GoogleOAuthMixin, google_dependencies


class GoogleCalendarConnector(GoogleOAuthMixin, AccountConnector):
    provider = "google_calendar"
    scopes = [
        "https://www.googleapis.com/auth/calendar.events",
        "https://www.googleapis.com/auth/calendar.readonly",
    ]
    capabilities = ConnectorCapabilities(
        search=True,
        read=True,
        create_event=True,
        update_event=True,
        delete=True,
    )

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

    @staticmethod
    def _event_time(value: str, timezone: str) -> dict[str, str]:
        clean = str(value or "").strip()
        if not clean:
            raise ConnectorError("Calendar event start and end are required.")
        if len(clean) == 10:
            try:
                datetime.fromisoformat(clean)
            except ValueError as exc:
                raise ConnectorError("All-day event dates must use YYYY-MM-DD.") from exc
            return {"date": clean}
        try:
            datetime.fromisoformat(clean.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ConnectorError("Event times must use ISO-8601 format.") from exc
        payload = {"dateTime": clean}
        if timezone:
            payload["timeZone"] = timezone
        return payload

    @staticmethod
    def _attendees(values: Any) -> list[dict[str, str]]:
        if values is None:
            return []
        if not isinstance(values, list) or len(values) > 50:
            raise ConnectorError("Calendar attendees must be an array of at most 50 emails.")
        attendees: list[dict[str, str]] = []
        for value in values:
            email = str(value or "").strip()
            if not email or "@" not in email or len(email) > 254:
                raise ConnectorError("Every calendar attendee must be a valid email address.")
            attendees.append({"email": email})
        return attendees

    def create_event(
        self,
        summary: str,
        start: str,
        end: str,
        *,
        timezone: str = "",
        description: str = "",
        location: str = "",
        attendees: Any = None,
        calendar_id: str = "primary",
    ) -> dict[str, Any]:
        clean_summary = str(summary or "").strip()
        if not clean_summary:
            raise ConnectorError("A calendar event title is required.")
        body = {
            "summary": clean_summary[:500],
            "start": self._event_time(start, timezone),
            "end": self._event_time(end, timezone),
        }
        if description:
            body["description"] = str(description)[:20_000]
        if location:
            body["location"] = str(location)[:1_000]
        if attendees:
            body["attendees"] = self._attendees(attendees)
        created = self._service().events().insert(
            calendarId=calendar_id or "primary",
            body=body,
            sendUpdates="none",
        ).execute()
        event_id = str(created.get("id", ""))
        if not event_id:
            raise ConnectorError("Google Calendar returned no event ID.")
        observed = self._service().events().get(
            calendarId=calendar_id or "primary", eventId=event_id
        ).execute()
        if observed.get("summary") != body["summary"]:
            raise ConnectorError("The Google Calendar event could not be verified by readback.")
        result = self._event(observed)
        result["verified"] = True
        record(self.provider, "create_event", count=1)
        return result

    def update_event(
        self,
        item_id: str,
        *,
        summary: str | None = None,
        start: str | None = None,
        end: str | None = None,
        timezone: str = "",
        description: str | None = None,
        location: str | None = None,
        attendees: Any = None,
        calendar_id: str = "primary",
    ) -> dict[str, Any]:
        if not item_id:
            raise ConnectorError("A calendar event ID is required.")
        body: dict[str, Any] = {}
        if summary is not None:
            clean_summary = str(summary).strip()
            if not clean_summary:
                raise ConnectorError("A calendar event title cannot be empty.")
            body["summary"] = clean_summary[:500]
        if start is not None:
            body["start"] = self._event_time(start, timezone)
        if end is not None:
            body["end"] = self._event_time(end, timezone)
        if description is not None:
            body["description"] = str(description)[:20_000]
        if location is not None:
            body["location"] = str(location)[:1_000]
        if attendees is not None:
            body["attendees"] = self._attendees(attendees)
        if not body:
            raise ConnectorError("At least one calendar event field must change.")
        events = self._service().events()
        events.patch(
            calendarId=calendar_id or "primary",
            eventId=item_id,
            body=body,
            sendUpdates="none",
        ).execute()
        observed = events.get(
            calendarId=calendar_id or "primary", eventId=item_id
        ).execute()
        for key in ("summary", "description", "location"):
            if key in body and observed.get(key, "") != body[key]:
                raise ConnectorError("The Google Calendar update could not be verified by readback.")
        result = self._event(observed)
        result["verified"] = True
        record(self.provider, "update_event", count=1)
        return result

    def delete_event(self, item_id: str, calendar_id: str = "primary") -> dict[str, Any]:
        if not item_id:
            raise ConnectorError("A calendar event ID is required.")
        events = self._service().events()
        events.delete(
            calendarId=calendar_id or "primary",
            eventId=item_id,
            sendUpdates="none",
        ).execute()
        try:
            events.get(
                calendarId=calendar_id or "primary", eventId=item_id
            ).execute()
        except Exception as exc:
            status = getattr(getattr(exc, "resp", None), "status", None)
            if status not in {404, 410}:
                raise
        else:
            raise ConnectorError("The Google Calendar deletion could not be verified.")
        record(self.provider, "delete_event", count=1)
        return {"id": item_id, "deleted": True, "verified": True}

    def download(self, item_id: str, attachment: str, destination: Path) -> Path:
        raise ConnectorError("Google Calendar events do not support attachment downloads yet.")
