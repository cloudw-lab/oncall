"""Helper utilities for encrypting and masking sensitive fields such as phone numbers."""

from __future__ import annotations

import os
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from ..config import settings

_KEY_ENV = "ONCALL_PHONE_KEY"


def _ensure_fernet() -> Fernet:
    key = os.environ.get(_KEY_ENV) or settings.ONCALL_PHONE_KEY
    if not key:
        raise RuntimeError(
            f"Environment variable {_KEY_ENV} (or .env setting) is required for phone encryption/decryption"
        )
    try:
        return Fernet(key.encode("utf-8"))
    except Exception as exc:  # pragma: no cover - defensive guard
        raise RuntimeError("Invalid ONCALL_PHONE_KEY provided") from exc


_FERNET = _ensure_fernet()


def encrypt_phone(plain: Optional[str]) -> Optional[str]:
    """Encrypt a phone number before persisting it."""
    if not plain:
        return None
    return _FERNET.encrypt(plain.encode("utf-8")).decode("utf-8")


def decrypt_phone(cipher: Optional[str]) -> Optional[str]:
    """Decrypt a stored phone number, tolerating legacy plaintext rows."""
    if not cipher:
        return None
    try:
        return _FERNET.decrypt(cipher.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        # 兼容历史明文数据，方便迁移
        return cipher


def mask_phone(plain: Optional[str]) -> Optional[str]:
    """Return a masked representation such as 138****5678."""
    if not plain:
        return None
    digits_only = "".join(ch for ch in plain if ch.isdigit())
    if len(digits_only) >= 7:
        return f"{digits_only[:3]}****{digits_only[-4:]}"
    if len(plain) <= 2:
        return "*" * len(plain)
    return f"{plain[0]}{'*' * (len(plain) - 2)}{plain[-1]}"
