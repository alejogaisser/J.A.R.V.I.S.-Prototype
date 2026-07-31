import json
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import ANY, MagicMock, patch

from connectors.base import ConnectorCapabilities, ConnectorError
from connectors.gmail import _body
from connectors.google_calendar import GoogleCalendarConnector
from connectors.google_drive import GOOGLE_EXPORTS, GoogleDriveConnector
from connectors.google_workspace import (
    GOOGLE_DOCUMENT_MIME,
    GOOGLE_PRESENTATION_MIME,
    GOOGLE_SPREADSHEET_MIME,
    GoogleWorkspaceService,
)
from connectors.outlook import OutlookConnector, _plain_text
from actions.account_connector import _connector, account_connector


class ConnectorTests(unittest.TestCase):
    def test_capabilities_are_provider_neutral(self):
        caps = asdict(ConnectorCapabilities(search=True, read=True, download=True))
        self.assertTrue(caps["search"])
        self.assertFalse(caps["send"])

    def test_drive_supports_verified_writes(self):
        connector = GoogleDriveConnector()
        self.assertTrue(connector.capabilities.create_file)
        self.assertTrue(connector.capabilities.create_folder)
        service = MagicMock()
        service.files.return_value.create.return_value.execute.return_value = {
            "id": "new-id", "name": "urgent.txt"
        }
        service.files.return_value.get.return_value.execute.return_value = {
            "id": "new-id", "name": "urgent.txt", "mimeType": "text/plain",
            "parents": ["folder-id"], "trashed": False,
        }
        upload = MagicMock(return_value=object())
        with patch.object(connector, "_service", return_value=service), patch(
            "connectors.google_drive.google_dependencies",
            return_value=(None, None, None, None, None, upload),
        ), patch("connectors.google_drive.record"):
            created = connector.create_file("urgent.txt", "contenido", "folder-id")
        self.assertTrue(created["verified"])
        self.assertEqual(created["parents"], ["folder-id"])
        self.assertTrue(connector.capabilities.read_workspace)
        self.assertTrue(connector.capabilities.update_presentation)

    def test_workspace_reads_google_docs_as_bounded_plain_text(self):
        docs = MagicMock()
        docs.documents.return_value.get.return_value.execute.return_value = {
            "title": "Plan",
            "body": {"content": [
                {"paragraph": {"elements": [
                    {"textRun": {"content": "Hola "}},
                    {"textRun": {"content": "mundo"}},
                ]}},
                {"table": {"tableRows": [{"tableCells": [
                    {"content": [{"paragraph": {"elements": [
                        {"textRun": {"content": "A"}}
                    ]}}]},
                    {"content": [{"paragraph": {"elements": [
                        {"textRun": {"content": "B"}}
                    ]}}]},
                ]}]}},
            ]},
        }
        builder = MagicMock(return_value=docs)
        result = GoogleWorkspaceService(object(), builder).read_document("doc-id", 8)
        self.assertEqual(result["content"], "Hola mun")
        self.assertTrue(result["truncated"])
        builder.assert_called_once_with(
            "docs", "v1", credentials=ANY, cache_discovery=False
        )

    def test_workspace_document_append_verifies_the_new_trailing_content(self):
        docs = MagicMock()
        documents = docs.documents.return_value
        documents.get.return_value.execute.side_effect = [
            {"body": {"content": [{"endIndex": 6, "paragraph": {"elements": [
                {"textRun": {"content": "Antes\n"}}
            ]}}]}},
            {"body": {"content": [{"endIndex": 13, "paragraph": {"elements": [
                {"textRun": {"content": "Antes\nDespués\n"}}
            ]}}]}},
        ]
        result = GoogleWorkspaceService(
            object(), MagicMock(return_value=docs)
        ).append_document("doc-id", "Después")
        self.assertTrue(result["verified"])
        self.assertEqual(result["inserted_characters"], len("Después"))

    def test_workspace_sheet_write_is_verified_by_updated_range_readback(self):
        sheets = MagicMock()
        values_api = sheets.spreadsheets.return_value.values.return_value
        values_api.update.return_value.execute.return_value = {
            "updatedRange": "Hoja 1!A1:B1",
            "updatedCells": 2,
        }
        values_api.get.return_value.execute.return_value = {
            "range": "Hoja 1!A1:B1",
            "values": [["Materia", "Nota"]],
        }
        result = GoogleWorkspaceService(
            object(), MagicMock(return_value=sheets)
        ).write_spreadsheet(
            "sheet-id", "A1", [["Materia", "Nota"]], append=False
        )
        self.assertTrue(result["verified"])
        self.assertEqual(result["updated_cells"], 2)
        self.assertEqual(values_api.get.call_args.kwargs["range"], "Hoja 1!A1:B1")

    def test_workspace_slide_write_is_verified_by_page_and_text_readback(self):
        slides = MagicMock()
        presentations = slides.presentations.return_value
        presentations.batchUpdate.return_value.execute.return_value = {"replies": []}

        def presentation_readback(**_kwargs):
            requests = presentations.batchUpdate.call_args.kwargs["body"]["requests"]
            page_id = requests[0]["createSlide"]["objectId"]
            title = next(
                request["insertText"]["text"]
                for request in requests if request.get("insertText")
            )
            body = [
                request["insertText"]["text"]
                for request in requests if request.get("insertText")
            ][1]
            request = MagicMock()
            request.execute.return_value = {
                "slides": [{
                    "objectId": page_id,
                    "pageElements": [
                        {"shape": {"text": {"textElements": [
                            {"textRun": {"content": title}}
                        ]}}},
                        {"shape": {"text": {"textElements": [
                            {"textRun": {"content": body}}
                        ]}}},
                    ],
                }],
            }
            return request

        presentations.get.side_effect = presentation_readback
        result = GoogleWorkspaceService(
            object(), MagicMock(return_value=slides)
        ).append_slide("slides-id", "Título", "Contenido")
        self.assertTrue(result["verified"])
        self.assertTrue(result["slide_id"].startswith("jarvis_slide_"))

    def test_drive_routes_native_reads_by_mime_type(self):
        connector = GoogleDriveConnector()
        workspace = MagicMock()
        workspace.read_spreadsheet.return_value = {
            "id": "sheet-id",
            "mimeType": GOOGLE_SPREADSHEET_MIME,
            "values": [["ok"]],
        }
        with patch.object(
            connector, "_mime_type", return_value=GOOGLE_SPREADSHEET_MIME
        ), patch.object(
            connector, "_workspace", return_value=workspace
        ), patch("connectors.google_drive.record"):
            result = connector.read_workspace_file("sheet-id", "Datos!A1:B2")
        self.assertEqual(result["values"], [["ok"]])
        workspace.read_spreadsheet.assert_called_once_with(
            "sheet-id", "Datos!A1:B2"
        )

    def test_partial_native_creation_reports_the_verified_file_effect(self):
        connector = GoogleDriveConnector()
        workspace = MagicMock()
        workspace.append_document.side_effect = ConnectorError("Docs API disabled")
        with patch.object(
            connector,
            "_create_workspace_file",
            return_value={"id": "doc-id", "name": "Plan", "verified": True},
        ), patch.object(connector, "_workspace", return_value=workspace):
            with self.assertRaisesRegex(
                ConnectorError,
                "created and verified.*initial content was not applied",
            ):
                connector.create_document("Plan", "Contenido")

    def test_account_action_routes_verified_native_sheet_write(self):
        connector = MagicMock()
        connector.write_sheet.return_value = {
            "id": "sheet-id",
            "range": "Datos!A1:B1",
            "updated_cells": 2,
            "verified": True,
        }
        with patch(
            "actions.account_connector._connector", return_value=connector
        ):
            result = account_connector({
                "provider": "google_drive",
                "action": "write_sheet",
                "item_id": "sheet-id",
                "range": "Datos!A1",
                "values": [["A", "B"]],
            })
        self.assertTrue(result.startswith("Verified Google Sheets update:"))
        connector.write_sheet.assert_called_once_with(
            "sheet-id", "Datos!A1", [["A", "B"]], append=False
        )

    def test_native_mime_constants_cover_docs_sheets_and_slides(self):
        self.assertEqual(
            GOOGLE_EXPORTS[GOOGLE_DOCUMENT_MIME][0],
            "application/pdf",
        )
        self.assertIn("spreadsheet", GOOGLE_SPREADSHEET_MIME)
        self.assertIn("presentation", GOOGLE_PRESENTATION_MIME)

    def test_drive_write_audit_uses_supported_metadata_only(self):
        source = Path("connectors/google_drive.py").read_text(encoding="utf-8")
        self.assertNotIn("item_id=", source)
        self.assertIn('record(self.provider, "create_file", count=1)', source)
        self.assertIn('record(self.provider, "create_folder", count=1)', source)

    def test_plain_text_gmail_body_is_decoded(self):
        import base64
        data = base64.urlsafe_b64encode("Hola facultad".encode()).decode()
        self.assertEqual(_body({"mimeType": "text/plain", "body": {"data": data}}), "Hola facultad")

    def test_real_oauth_file_and_audit_are_ignored(self):
        ignored = Path(".gitignore").read_text(encoding="utf-8")
        self.assertIn("config/google_oauth_client.json", ignored)
        self.assertIn("config/microsoft_oauth_client.json", ignored)
        self.assertIn("config/connector_audit.jsonl", ignored)

    def test_google_providers_are_registered(self):
        self.assertIsInstance(_connector("calendar"), GoogleCalendarConnector)
        self.assertIsInstance(_connector("google_drive"), GoogleDriveConnector)
        self.assertIsInstance(_connector("outlook"), OutlookConnector)

    def test_outlook_message_is_normalized_and_html_is_cleaned(self):
        item = OutlookConnector._message({
            "id": "m", "subject": "Facultad", "from": {"emailAddress": {"address": "a@uni.edu"}},
            "receivedDateTime": "2026-07-15T12:00:00Z", "hasAttachments": True,
        })
        self.assertEqual(item["from"], "a@uni.edu")
        self.assertTrue(item["has_attachments"])
        self.assertEqual(_plain_text("<p>Hola <b>Alejo</b></p>"), "Hola Alejo")

    def test_calendar_event_is_normalized(self):
        event = GoogleCalendarConnector._event({
            "id": "evt", "summary": "Parcial", "start": {"dateTime": "2026-07-20T10:00:00-03:00"},
            "end": {"dateTime": "2026-07-20T12:00:00-03:00"},
        })
        self.assertEqual(event["summary"], "Parcial")
        self.assertEqual(event["id"], "evt")

    def test_drive_file_is_normalized_and_native_exports_are_safe(self):
        item = GoogleDriveConnector._file({"id": "f", "name": "Guía", "mimeType": "application/pdf"})
        self.assertEqual(item["name"], "Guía")
        self.assertEqual(GOOGLE_EXPORTS["application/vnd.google-apps.document"][1], ".pdf")

    def test_drive_folder_discovery_supports_shared_drives(self):
        connector = GoogleDriveConnector()
        service = MagicMock()
        service.files.return_value.list.return_value.execute.return_value = {
            "files": [{
                "id": "tmp-id", "name": "tmp",
                "mimeType": "application/vnd.google-apps.folder",
                "parents": ["root-id"],
            }]
        }
        with patch.object(connector, "_service", return_value=service), patch(
            "connectors.google_drive.record"
        ):
            folders = connector.find_folder("tmp")
        self.assertEqual(folders[0]["id"], "tmp-id")
        kwargs = service.files.return_value.list.call_args.kwargs
        self.assertTrue(kwargs["includeItemsFromAllDrives"])
        self.assertTrue(kwargs["supportsAllDrives"])
        self.assertIn("mimeType = 'application/vnd.google-apps.folder'", kwargs["q"])
