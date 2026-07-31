"""Native Google Docs, Sheets, and Slides operations for Google Drive.

This module is an implementation detail of :class:`GoogleDriveConnector`.
Keeping the Workspace APIs behind that connector preserves one OAuth owner and
one audited tool route while avoiding browser automation for external writes.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any
from uuid import uuid4

from .base import ConnectorError

GOOGLE_DOCUMENT_MIME = "application/vnd.google-apps.document"
GOOGLE_SPREADSHEET_MIME = "application/vnd.google-apps.spreadsheet"
GOOGLE_PRESENTATION_MIME = "application/vnd.google-apps.presentation"

_MAX_CONTENT_CHARS = 100_000
_MAX_READ_CHARS = 50_000
_MAX_SHEET_ROWS = 1_000
_MAX_SHEET_COLUMNS = 50
_MAX_SHEET_CELLS = 10_000
_MAX_SLIDE_TEXT_CHARS = 20_000


class GoogleWorkspaceService:
    """Perform bounded native Workspace operations using shared credentials."""

    def __init__(
        self,
        credentials: Any,
        service_builder: Callable[..., Any],
    ) -> None:
        self._credentials = credentials
        self._build = service_builder

    def _service(self, api: str, version: str) -> Any:
        return self._build(
            api,
            version,
            credentials=self._credentials,
            cache_discovery=False,
        )

    @staticmethod
    def _bounded_text(
        value: Any,
        *,
        field: str,
        allow_empty: bool = True,
        max_chars: int = _MAX_CONTENT_CHARS,
    ) -> str:
        text = str(value or "")
        if not allow_empty and not text.strip():
            raise ConnectorError(f"{field} cannot be empty.")
        if len(text) > max_chars:
            raise ConnectorError(
                f"{field} exceeds the {max_chars:,}-character safety limit."
            )
        return text

    @staticmethod
    def _document_content(elements: Sequence[dict[str, Any]]) -> str:
        """Flatten Docs structural elements without exposing formatting metadata."""
        chunks: list[str] = []
        for element in elements:
            paragraph = element.get("paragraph")
            if paragraph:
                for part in paragraph.get("elements", []):
                    text_run = part.get("textRun") or {}
                    chunks.append(str(text_run.get("content", "")))
            table = element.get("table")
            if table:
                for row in table.get("tableRows", []):
                    cells = [
                        GoogleWorkspaceService._document_content(
                            cell.get("content", [])
                        ).rstrip("\n")
                        for cell in row.get("tableCells", [])
                    ]
                    chunks.append("\t".join(cells) + "\n")
            table_of_contents = element.get("tableOfContents")
            if table_of_contents:
                chunks.append(
                    GoogleWorkspaceService._document_content(
                        table_of_contents.get("content", [])
                    )
                )
        return "".join(chunks)

    @staticmethod
    def _slide_text(page: dict[str, Any]) -> str:
        chunks: list[str] = []
        for element in page.get("pageElements", []):
            shape = element.get("shape") or {}
            for text_element in (shape.get("text") or {}).get("textElements", []):
                chunks.append(
                    str((text_element.get("textRun") or {}).get("content", ""))
                )
            table = element.get("table") or {}
            for row in table.get("tableRows", []):
                cells: list[str] = []
                for cell in row.get("tableCells", []):
                    cell_text = "".join(
                        str((part.get("textRun") or {}).get("content", ""))
                        for part in (cell.get("text") or {}).get("textElements", [])
                    )
                    cells.append(cell_text.strip())
                chunks.append("\t".join(cells) + "\n")
        return "".join(chunks).strip()

    @staticmethod
    def _values(values: Any) -> list[list[Any]]:
        """Validate a small two-dimensional scalar matrix for the Sheets API."""
        if not isinstance(values, list):
            raise ConnectorError("Sheet values must be a two-dimensional array.")
        if len(values) > _MAX_SHEET_ROWS:
            raise ConnectorError(f"Sheet writes are limited to {_MAX_SHEET_ROWS} rows.")
        normalized: list[list[Any]] = []
        cells = 0
        characters = 0
        for row in values:
            if not isinstance(row, list):
                raise ConnectorError("Every sheet row must be an array.")
            if len(row) > _MAX_SHEET_COLUMNS:
                raise ConnectorError(
                    f"Sheet writes are limited to {_MAX_SHEET_COLUMNS} columns."
                )
            normalized_row: list[Any] = []
            for value in row:
                if not isinstance(value, (str, int, float, bool, type(None))):
                    raise ConnectorError("Sheet cells must contain scalar values.")
                normalized_row.append(value)
                characters += len(str(value or ""))
            cells += len(normalized_row)
            normalized.append(normalized_row)
        if cells > _MAX_SHEET_CELLS:
            raise ConnectorError(f"Sheet writes are limited to {_MAX_SHEET_CELLS} cells.")
        if characters > _MAX_CONTENT_CHARS:
            raise ConnectorError(
                f"Sheet writes are limited to {_MAX_CONTENT_CHARS:,} characters."
            )
        return normalized

    def read_document(self, document_id: str, max_chars: int = _MAX_READ_CHARS) -> dict[str, Any]:
        document = self._service("docs", "v1").documents().get(
            documentId=document_id
        ).execute()
        content = self._document_content((document.get("body") or {}).get("content", []))
        limit = max(1, min(int(max_chars), _MAX_READ_CHARS))
        return {
            "id": document_id,
            "title": document.get("title", ""),
            "mimeType": GOOGLE_DOCUMENT_MIME,
            "content": content[:limit],
            "truncated": len(content) > limit,
        }

    def append_document(self, document_id: str, content: str) -> dict[str, Any]:
        clean_content = self._bounded_text(
            content, field="Document content", allow_empty=False
        )
        service = self._service("docs", "v1")
        document = service.documents().get(documentId=document_id).execute()
        structural = (document.get("body") or {}).get("content", [])
        end_index = max(
            (int(element.get("endIndex", 1)) for element in structural),
            default=1,
        )
        inserted = clean_content if end_index <= 2 else f"\n{clean_content}"
        service.documents().batchUpdate(
            documentId=document_id,
            body={"requests": [{"insertText": {
                "location": {"index": max(1, end_index - 1)},
                "text": inserted,
            }}]},
        ).execute()
        updated = service.documents().get(documentId=document_id).execute()
        updated_content = self._document_content(
            (updated.get("body") or {}).get("content", [])
        )
        if not updated_content.rstrip("\n").endswith(clean_content.rstrip("\n")):
            raise ConnectorError("The Google Doc update could not be verified by readback.")
        return {
            "id": document_id,
            "mimeType": GOOGLE_DOCUMENT_MIME,
            "verified": True,
            "inserted_characters": len(clean_content),
        }

    def read_spreadsheet(
        self,
        spreadsheet_id: str,
        range_name: str = "A1:Z1000",
    ) -> dict[str, Any]:
        service = self._service("sheets", "v4")
        metadata = service.spreadsheets().get(
            spreadsheetId=spreadsheet_id,
            fields="properties(title)",
        ).execute()
        response = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=range_name or "A1:Z1000",
            valueRenderOption="FORMATTED_VALUE",
        ).execute()
        values = response.get("values", [])
        cells = sum(len(row) for row in values)
        if cells > _MAX_SHEET_CELLS:
            raise ConnectorError(
                "The requested sheet range is too large; request a smaller A1 range."
            )
        characters = sum(len(str(value or "")) for row in values for value in row)
        if characters > _MAX_CONTENT_CHARS:
            raise ConnectorError(
                "The requested sheet range contains too much text; request a smaller A1 range."
            )
        return {
            "id": spreadsheet_id,
            "title": (metadata.get("properties") or {}).get("title", ""),
            "mimeType": GOOGLE_SPREADSHEET_MIME,
            "range": response.get("range", range_name),
            "values": values,
            "cells": cells,
        }

    def write_spreadsheet(
        self,
        spreadsheet_id: str,
        range_name: str,
        values: Any,
        *,
        append: bool,
    ) -> dict[str, Any]:
        clean_range = str(range_name or "A1").strip()
        normalized = self._values(values)
        if not normalized:
            raise ConnectorError("At least one sheet row is required.")
        service = self._service("sheets", "v4")
        values_api = service.spreadsheets().values()
        body = {"majorDimension": "ROWS", "values": normalized}
        if append:
            response = values_api.append(
                spreadsheetId=spreadsheet_id,
                range=clean_range,
                valueInputOption="USER_ENTERED",
                insertDataOption="INSERT_ROWS",
                includeValuesInResponse=True,
                body=body,
            ).execute()
            updates = response.get("updates", {})
        else:
            updates = values_api.update(
                spreadsheetId=spreadsheet_id,
                range=clean_range,
                valueInputOption="USER_ENTERED",
                includeValuesInResponse=True,
                body=body,
            ).execute()
        updated_range = updates.get("updatedRange", "")
        updated_cells = int(updates.get("updatedCells", 0))
        if not updated_range or updated_cells <= 0:
            raise ConnectorError("The Google Sheets write returned no verifiable updated range.")
        observed = values_api.get(
            spreadsheetId=spreadsheet_id,
            range=updated_range,
            valueRenderOption="FORMATTED_VALUE",
        ).execute()
        expects_visible_value = any(
            value not in {"", None}
            for row in normalized
            for value in row
        )
        if expects_visible_value and not observed.get("values"):
            raise ConnectorError("The Google Sheets write could not be verified by readback.")
        return {
            "id": spreadsheet_id,
            "mimeType": GOOGLE_SPREADSHEET_MIME,
            "range": updated_range,
            "updated_cells": updated_cells,
            "verified": True,
        }

    def read_presentation(
        self,
        presentation_id: str,
        max_chars: int = _MAX_READ_CHARS,
    ) -> dict[str, Any]:
        presentation = self._service("slides", "v1").presentations().get(
            presentationId=presentation_id
        ).execute()
        limit = max(1, min(int(max_chars), _MAX_READ_CHARS))
        remaining = limit
        slides: list[dict[str, Any]] = []
        truncated = False
        for number, slide in enumerate(presentation.get("slides", []), 1):
            text = self._slide_text(slide)
            visible = text[:remaining]
            slides.append({"number": number, "text": visible})
            remaining -= len(visible)
            if len(visible) < len(text) or remaining <= 0:
                truncated = True
                break
        return {
            "id": presentation_id,
            "title": presentation.get("title", ""),
            "mimeType": GOOGLE_PRESENTATION_MIME,
            "slides": slides,
            "truncated": truncated,
        }

    def append_slide(
        self,
        presentation_id: str,
        title: str,
        body: str,
    ) -> dict[str, Any]:
        clean_title = self._bounded_text(
            title, field="Slide title", max_chars=_MAX_SLIDE_TEXT_CHARS
        )
        clean_body = self._bounded_text(
            body, field="Slide body", max_chars=_MAX_SLIDE_TEXT_CHARS
        )
        if not clean_title.strip() and not clean_body.strip():
            raise ConnectorError("A slide title or body is required.")

        token = uuid4().hex
        page_id = f"jarvis_slide_{token}"
        requests: list[dict[str, Any]] = [{
            "createSlide": {
                "objectId": page_id,
                "slideLayoutReference": {"predefinedLayout": "BLANK"},
            }
        }]
        if clean_title:
            requests.extend(self._text_box_requests(
                page_id, f"jarvis_title_{token}", clean_title,
                x=457_200, y=274_320, width=8_229_600, height=914_400,
            ))
        if clean_body:
            requests.extend(self._text_box_requests(
                page_id, f"jarvis_body_{token}", clean_body,
                x=457_200, y=1_371_600, width=8_229_600, height=3_200_400,
            ))
        service = self._service("slides", "v1")
        service.presentations().batchUpdate(
            presentationId=presentation_id,
            body={"requests": requests},
        ).execute()
        presentation = service.presentations().get(
            presentationId=presentation_id
        ).execute()
        page = next(
            (slide for slide in presentation.get("slides", [])
             if slide.get("objectId") == page_id),
            None,
        )
        if page is None:
            raise ConnectorError("The new Google Slides page could not be verified.")
        observed = self._slide_text(page)
        if clean_title and clean_title not in observed:
            raise ConnectorError("The new slide title could not be verified by readback.")
        if clean_body and clean_body not in observed:
            raise ConnectorError("The new slide body could not be verified by readback.")
        return {
            "id": presentation_id,
            "mimeType": GOOGLE_PRESENTATION_MIME,
            "slide_id": page_id,
            "verified": True,
        }

    @staticmethod
    def _text_box_requests(
        page_id: str,
        object_id: str,
        text: str,
        *,
        x: int,
        y: int,
        width: int,
        height: int,
    ) -> list[dict[str, Any]]:
        return [
            {"createShape": {
                "objectId": object_id,
                "shapeType": "TEXT_BOX",
                "elementProperties": {
                    "pageObjectId": page_id,
                    "size": {
                        "width": {"magnitude": width, "unit": "EMU"},
                        "height": {"magnitude": height, "unit": "EMU"},
                    },
                    "transform": {
                        "scaleX": 1,
                        "scaleY": 1,
                        "translateX": x,
                        "translateY": y,
                        "unit": "EMU",
                    },
                },
            }},
            {"insertText": {
                "objectId": object_id,
                "insertionIndex": 0,
                "text": text,
            }},
        ]
