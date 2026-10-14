"""Remembered board passwords (v7).  Windows Credential Manager via `keyring`; never plaintext.

Normal logins use the SSH key that the existing connect flow installs, so a stored password is only
needed to (re)install that key on a fresh board.  If keyring is unavailable nothing is stored.
"""
from __future__ import annotations

from typing import Any

SERVICE = "CaptureStudio-board"


def _backend(backend: Any = None) -> Any:
    if backend is not None:
        return backend
    try:
        import keyring
        return keyring
    except Exception:
        return None


def available(backend: Any = None) -> bool:
    return _backend(backend) is not None


def account(user: str, host: str) -> str:
    return f"{user}@{host}"


def save(user: str, host: str, password: str, backend: Any = None) -> bool:
    kr = _backend(backend)
    if kr is None or not password:
        return False
    try:
        kr.set_password(SERVICE, account(user, host), password)
        return True
    except Exception:
        return False


def load(user: str, host: str, backend: Any = None) -> str:
    kr = _backend(backend)
    if kr is None:
        return ""
    try:
        return kr.get_password(SERVICE, account(user, host)) or ""
    except Exception:
        return ""


def forget(user: str, host: str, backend: Any = None) -> None:
    kr = _backend(backend)
    if kr is None:
        return
    try:
        kr.delete_password(SERVICE, account(user, host))
    except Exception:
        pass
