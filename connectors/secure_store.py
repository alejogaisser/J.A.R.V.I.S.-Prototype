from __future__ import annotations

import json

SERVICE_NAME = "JARVIS-connected-accounts"


class SecureTokenStore:
    """Store OAuth tokens in the operating-system credential vault via keyring."""

    def __init__(self, provider: str, account: str = "default") -> None:
        self.key = f"{provider}:{account}"

    @staticmethod
    def _keyring():
        try:
            import keyring
        except ImportError as exc:
            raise RuntimeError("Missing dependency: install keyring to protect OAuth tokens.") from exc
        return keyring

    def load(self) -> dict | None:
        raw = self._keyring().get_password(SERVICE_NAME, self.key)
        return json.loads(raw) if raw else None

    def save(self, payload: dict) -> None:
        self._keyring().set_password(SERVICE_NAME, self.key, json.dumps(payload))

    def delete(self) -> None:
        keyring = self._keyring()
        try:
            keyring.delete_password(SERVICE_NAME, self.key)
        except keyring.errors.PasswordDeleteError:
            pass
