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
        if action == "find_folder":
            return json.dumps(connector.find_folder(
                str(args.get("name") or args.get("query", "")),
                str(args.get("parent_id", "")), int(args.get("limit", 20)),
            ), ensure_ascii=False)
        if action == "list_children":
            return json.dumps(connector.list_children(
                str(args.get("parent_id") or args.get("item_id", "")),
                int(args.get("limit", 50)),
            ), ensure_ascii=False)
        if action == "read":
            return json.dumps(connector.read(str(args["item_id"])), ensure_ascii=False)
        if action == "read_workspace_file":
            return json.dumps(connector.read_workspace_file(
                str(args["item_id"]),
                str(args.get("range", "")),
                int(args.get("max_chars", 20_000)),
            ), ensure_ascii=False)
        if action == "create_folder":
            created = connector.create_folder(
                str(args.get("name", "")), str(args.get("parent_id", ""))
            )
            return "Verified Google Drive folder creation: " + json.dumps(created, ensure_ascii=False)
        if action == "create_file":
            created = connector.create_file(
                str(args.get("name", "")), str(args.get("content", "")),
                str(args.get("parent_id", "")),
                str(args.get("mime_type", "text/plain")),
            )
            return "Verified Google Drive file creation: " + json.dumps(created, ensure_ascii=False)
        if action == "create_document":
            created = connector.create_document(
                str(args.get("name", "")),
                str(args.get("content", "")),
                str(args.get("parent_id", "")),
            )
            return "Verified Google Docs creation: " + json.dumps(created, ensure_ascii=False)
        if action == "append_document":
            updated = connector.append_document(
                str(args.get("item_id", "")),
                str(args.get("content", "")),
            )
            return "Verified Google Docs update: " + json.dumps(updated, ensure_ascii=False)
        if action == "create_spreadsheet":
            created = connector.create_spreadsheet(
                str(args.get("name", "")),
                args.get("values"),
                str(args.get("parent_id", "")),
                str(args.get("range", "A1")),
            )
            return "Verified Google Sheets creation: " + json.dumps(created, ensure_ascii=False)
        if action in {"write_sheet", "append_sheet"}:
            updated = connector.write_sheet(
                str(args.get("item_id", "")),
                str(args.get("range", "A1")),
                args.get("values"),
                append=action == "append_sheet",
            )
            return "Verified Google Sheets update: " + json.dumps(updated, ensure_ascii=False)
        if action == "create_presentation":
            created = connector.create_presentation(
                str(args.get("name", "")),
                str(args.get("title", "")),
                str(args.get("body", "")),
                str(args.get("parent_id", "")),
            )
            return "Verified Google Slides creation: " + json.dumps(created, ensure_ascii=False)
        if action == "append_slide":
            updated = connector.append_slide(
                str(args.get("item_id", "")),
                str(args.get("title", "")),
                str(args.get("body", "")),
            )
            return "Verified Google Slides update: " + json.dumps(updated, ensure_ascii=False)
        if action == "download":
            destination = Path(args.get("destination") or (Path.home() / "Downloads"))
            target = connector.download(str(args["item_id"]), str(args["attachment"]), destination)
            return f"Downloaded with {provider} to: {target}"
        raise ValueError(f"Unknown connector action: {action}. No change was made.")
    except Exception as exc:
        return f"Connector error ({provider}/{action}): {exc}"
