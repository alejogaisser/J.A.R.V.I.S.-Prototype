from __future__ import annotations

import json
from pathlib import Path

from connectors import (
    GmailConnector,
    GoogleCalendarConnector,
    GoogleDriveConnector,
    OutlookConnector,
)
from core.tools import (
    EffectStatus,
    ExecutionStatus,
    RollbackStatus,
    ToolResult,
    VerificationStatus,
)

_VERIFIED_WRITES = {
    "create_file", "create_folder", "create_document", "append_document",
    "create_spreadsheet", "write_sheet", "append_sheet",
    "create_presentation", "append_slide", "create_event", "update_event",
    "delete_event",
}


def _result(
    action: str,
    message: str,
    data=None,
    *,
    verified: bool = False,
) -> ToolResult:
    effectful = action in _VERIFIED_WRITES or action in {"connect", "disconnect", "download"}
    return ToolResult(
        True,
        message,
        data=data,
        execution_status=ExecutionStatus.SUCCEEDED,
        effect_status=EffectStatus.APPLIED if effectful else EffectStatus.NONE,
        verification_status=(
            VerificationStatus.VERIFIED if verified else VerificationStatus.NOT_REQUESTED
        ),
        rollback_status=RollbackStatus.NOT_AVAILABLE,
        evidence=(f"connector:{action}:verified",) if verified else (),
    )


def _failure(provider: str, action: str, exc: Exception) -> ToolResult:
    message = f"Connector error ({provider}/{action}): {exc}"
    partial = "created and verified" in str(exc).casefold()
    return ToolResult(
        False,
        message,
        error_code="partial_effect" if partial else "connector_error",
        execution_status=ExecutionStatus.FAILED,
        effect_status=EffectStatus.PARTIAL if partial else EffectStatus.UNKNOWN,
        verification_status=(
            VerificationStatus.VERIFIED if partial else VerificationStatus.UNKNOWN
        ),
        rollback_status=RollbackStatus.NOT_AVAILABLE if partial else RollbackStatus.UNKNOWN,
        evidence=("remote_file_created",) if partial else (),
    )


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


def account_connector(parameters: dict, player=None) -> ToolResult:
    args = dict(parameters or {})
    provider = str(args.get("provider", "gmail"))
    action = str(args.get("action", "status")).lower()
    try:
        connector = _connector(provider)
        if action == "connect":
            message = connector.connect()
            return _result(action, message)
        if action == "disconnect":
            message = connector.disconnect()
            return _result(action, message)
        if action == "status":
            data = connector.status()
            return _result(action, json.dumps(data, ensure_ascii=False), data)
        if action == "search":
            data = connector.search(str(args.get("query", "")), int(args.get("limit", 10)))
            return _result(action, json.dumps(data, ensure_ascii=False), data)
        if action == "find_folder":
            data = connector.find_folder(
                str(args.get("name") or args.get("query", "")),
                str(args.get("parent_id", "")), int(args.get("limit", 20)),
            )
            return _result(action, json.dumps(data, ensure_ascii=False), data)
        if action == "list_children":
            data = connector.list_children(
                str(args.get("parent_id") or args.get("item_id", "")),
                int(args.get("limit", 50)),
            )
            return _result(action, json.dumps(data, ensure_ascii=False), data)
        if action == "read":
            data = connector.read(str(args["item_id"]))
            return _result(action, json.dumps(data, ensure_ascii=False), data)
        if action == "read_workspace_file":
            data = connector.read_workspace_file(
                str(args["item_id"]),
                str(args.get("range", "")),
                int(args.get("max_chars", 20_000)),
            )
            return _result(action, json.dumps(data, ensure_ascii=False), data)
        if action == "create_event":
            created = connector.create_event(
                str(args.get("summary") or args.get("name", "")),
                str(args.get("start", "")),
                str(args.get("end", "")),
                timezone=str(args.get("timezone", "")),
                description=str(args.get("description", "")),
                location=str(args.get("location", "")),
                attendees=args.get("attendees"),
                calendar_id=str(args.get("calendar_id", "primary")),
            )
            message = "Verified Google Calendar event creation: " + json.dumps(created, ensure_ascii=False)
            return _result(action, message, created, verified=True)
        if action == "update_event":
            updated = connector.update_event(
                str(args.get("item_id", "")),
                summary=args.get("summary"),
                start=args.get("start"),
                end=args.get("end"),
                timezone=str(args.get("timezone", "")),
                description=args.get("description"),
                location=args.get("location"),
                attendees=args.get("attendees"),
                calendar_id=str(args.get("calendar_id", "primary")),
            )
            message = "Verified Google Calendar event update: " + json.dumps(updated, ensure_ascii=False)
            return _result(action, message, updated, verified=True)
        if action == "delete_event":
            deleted = connector.delete_event(
                str(args.get("item_id", "")),
                str(args.get("calendar_id", "primary")),
            )
            message = "Verified Google Calendar event deletion: " + json.dumps(deleted, ensure_ascii=False)
            return _result(action, message, deleted, verified=True)
        if action == "create_folder":
            created = connector.create_folder(
                str(args.get("name", "")), str(args.get("parent_id", ""))
            )
            message = "Verified Google Drive folder creation: " + json.dumps(created, ensure_ascii=False)
            return _result(action, message, created, verified=True)
        if action == "create_file":
            created = connector.create_file(
                str(args.get("name", "")), str(args.get("content", "")),
                str(args.get("parent_id", "")),
                str(args.get("mime_type", "text/plain")),
            )
            message = "Verified Google Drive file creation: " + json.dumps(created, ensure_ascii=False)
            return _result(action, message, created, verified=True)
        if action == "create_document":
            created = connector.create_document(
                str(args.get("name", "")),
                str(args.get("content", "")),
                str(args.get("parent_id", "")),
            )
            message = "Verified Google Docs creation: " + json.dumps(created, ensure_ascii=False)
            return _result(action, message, created, verified=True)
        if action == "append_document":
            updated = connector.append_document(
                str(args.get("item_id", "")),
                str(args.get("content", "")),
            )
            message = "Verified Google Docs update: " + json.dumps(updated, ensure_ascii=False)
            return _result(action, message, updated, verified=True)
        if action == "create_spreadsheet":
            created = connector.create_spreadsheet(
                str(args.get("name", "")),
                args.get("values"),
                str(args.get("parent_id", "")),
                str(args.get("range", "A1")),
            )
            message = "Verified Google Sheets creation: " + json.dumps(created, ensure_ascii=False)
            return _result(action, message, created, verified=True)
        if action in {"write_sheet", "append_sheet"}:
            updated = connector.write_sheet(
                str(args.get("item_id", "")),
                str(args.get("range", "A1")),
                args.get("values"),
                append=action == "append_sheet",
            )
            message = "Verified Google Sheets update: " + json.dumps(updated, ensure_ascii=False)
            return _result(action, message, updated, verified=True)
        if action == "create_presentation":
            created = connector.create_presentation(
                str(args.get("name", "")),
                str(args.get("title", "")),
                str(args.get("body", "")),
                str(args.get("parent_id", "")),
            )
            message = "Verified Google Slides creation: " + json.dumps(created, ensure_ascii=False)
            return _result(action, message, created, verified=True)
        if action == "append_slide":
            updated = connector.append_slide(
                str(args.get("item_id", "")),
                str(args.get("title", "")),
                str(args.get("body", "")),
            )
            message = "Verified Google Slides update: " + json.dumps(updated, ensure_ascii=False)
            return _result(action, message, updated, verified=True)
        if action == "download":
            destination = Path(args.get("destination") or (Path.home() / "Downloads"))
            target = connector.download(str(args["item_id"]), str(args["attachment"]), destination)
            if not target.is_file():
                raise RuntimeError("The downloaded file could not be verified on disk.")
            return _result(action, f"Downloaded with {provider} to: {target}", str(target), verified=True)
        raise ValueError(f"Unknown connector action: {action}. No change was made.")
    except Exception as exc:
        return _failure(provider, action, exc)
