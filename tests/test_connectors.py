import json
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import MagicMock, patch

from connectors.base import ConnectorCapabilities
from connectors.gmail import _body
from connectors.google_calendar import GoogleCalendarConnector
from connectors.google_drive import GOOGLE_EXPORTS, GoogleDriveConnector
from connectors.outlook import OutlookConnector, _plain_text
from actions.account_connector import _connector


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
