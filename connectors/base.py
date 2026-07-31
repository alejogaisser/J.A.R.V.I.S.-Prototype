from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ConnectorError(RuntimeError):
    """A user-actionable connector failure."""


@dataclass(frozen=True, slots=True)
class ConnectorCapabilities:
    search: bool = False
    read: bool = False
    download: bool = False
    create_file: bool = False
    create_folder: bool = False
    read_workspace: bool = False
    create_document: bool = False
    update_document: bool = False
    create_spreadsheet: bool = False
    update_spreadsheet: bool = False
    create_presentation: bool = False
    update_presentation: bool = False
    create_event: bool = False
    update_event: bool = False
    send: bool = False
    delete: bool = False


class AccountConnector(ABC):
    provider: str
    capabilities: ConnectorCapabilities

    @abstractmethod
    def connect(self) -> str: ...

    @abstractmethod
    def disconnect(self) -> str: ...

    @abstractmethod
    def status(self) -> dict[str, Any]: ...

    @abstractmethod
    def search(self, query: str, limit: int = 10) -> list[dict[str, Any]]: ...

    @abstractmethod
    def read(self, item_id: str) -> dict[str, Any]: ...

    @abstractmethod
    def download(self, item_id: str, attachment: str, destination: Path) -> Path: ...
