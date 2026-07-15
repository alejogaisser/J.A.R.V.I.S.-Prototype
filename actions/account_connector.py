from __future__ import annotations

import json
from pathlib import Path

from connectors import GmailConnector, GoogleCalendarConnector, GoogleDriveConnector, OutlookConnector


def _connector(provider: str):
    providers = {
        "gmail": GmailConnector,
        "google_calendar": GoogleCalendarConnector,
        "calendar": GoogleCalendarConnector,
        "google_drive": GoogleDriveConnector,
        "drive": GoogleDriveConnector,
        "outlook": OutlookConnector,
    }
    factory = providers.get(provider.lower())
    if factory:
        return factory()
    raise ValueError(
        f"Provider not implemented: {provider}. Available: gmail, outlook, google_calendar, google_drive"
    )


def account_connector(parameters: dict, player=None) -> str:
    args = dict(parameters or {})
    provider = str(args.get("provider", "gmail"))
    action = str(args.get("action", "status")).lower()
    try:
        connector = _connector(provider)
        if action == "connect":
            return connector.connect()
        if action == "disconnect":
            return connector.disconnect()
        if action == "status":
            return json.dumps(connector.status(), ensure_ascii=False)
        if action == "search":
            return json.dumps(connector.search(str(args.get("query", "")), int(args.get("limit", 10))), ensure_ascii=False)
        if action == "read":
            return json.dumps(connector.read(str(args["item_id"])), ensure_ascii=False)
        if action == "download":
            destination = Path(args.get("destination") or (Path.home() / "Downloads"))
            target = connector.download(str(args["item_id"]), str(args["attachment"]), destination)
            return f"Downloaded with {provider} to: {target}"
        raise ValueError(f"Unknown connector action: {action}")
    except Exception as exc:
        return f"Connector error ({provider}/{action}): {exc}"
