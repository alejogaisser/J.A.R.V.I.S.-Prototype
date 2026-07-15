"""Account connector interfaces and provider adapters."""

from .base import AccountConnector, ConnectorCapabilities, ConnectorError
from .gmail import GmailConnector
from .google_calendar import GoogleCalendarConnector
from .google_drive import GoogleDriveConnector
from .outlook import OutlookConnector

__all__ = [
    "AccountConnector", "ConnectorCapabilities", "ConnectorError", "GmailConnector",
    "GoogleCalendarConnector", "GoogleDriveConnector", "OutlookConnector",
]
