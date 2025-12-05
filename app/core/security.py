"""Application level authentication primitives."""
from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

from app.core.errors import APIError, get_error


@dataclass
class Credential:
    app_id: str
    app_key: str
    name: str | None = None
    disabled: bool = False


@dataclass
class AuthConfig:
    required: bool = True
    secrets_path: Path | None = None


class CredentialStore:
    """Filesystem backed credential store for appid/key lookups."""

    def __init__(self, config: AuthConfig) -> None:
        self.config = config
        self._cache: Dict[str, Credential] = {}
        self._load()

    def _load(self) -> None:
        self._cache.clear()
        if not self.config.secrets_path or not self.config.secrets_path.exists():
            return
        try:
            data = json.loads(self.config.secrets_path.read_text())
        except json.JSONDecodeError:
            return
        for entry in data:
            credential = Credential(
                app_id=entry.get("app_id"),
                app_key=entry.get("app_key"),
                name=entry.get("name"),
                disabled=entry.get("disabled", False),
            )
            if credential.app_id:
                self._cache[credential.app_id] = credential

    def refresh(self) -> None:
        self._load()

    def issue(self, name: str | None = None) -> Credential:
        app_id = secrets.token_hex(8)
        app_key = secrets.token_hex(16)
        credential = Credential(app_id=app_id, app_key=app_key, name=name)
        self._cache[app_id] = credential
        self._persist()
        return credential

    def revoke(self, app_id: str) -> None:
        if app_id in self._cache:
            self._cache[app_id].disabled = True
            self._persist()

    def _persist(self) -> None:
        if not self.config.secrets_path:
            return
        payload = [cred.__dict__ for cred in self._cache.values()]
        self.config.secrets_path.write_text(json.dumps(payload, indent=2))

    def validate(self, app_id: str, app_key: str) -> Credential:
        credential = self._cache.get(app_id)
        if not credential or credential.disabled or credential.app_key != app_key:
            raise APIError(get_error("ERR_AUTH_INVALID"))
        return credential


class AuthManager:
    def __init__(self, config: AuthConfig) -> None:
        self.config = config
        self.store = CredentialStore(config)

    def assert_credentials(self, app_id: Optional[str], app_key: Optional[str]) -> Credential:
        if not self.config.required:
            return Credential(app_id="anonymous", app_key="", name="anonymous")
        if not app_id or not app_key:
            raise APIError(get_error("ERR_AUTH_REQUIRED"))
        return self.store.validate(app_id, app_key)
