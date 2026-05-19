"""
用户 Key 存储服务 - AES-256-GCM 加密，持久化到 SQLite
"""
import os
import re
import time
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import secrets

from db import get_conn

# ===================== 加密配置 =====================

_ENCRYPTION_SECRET = os.getenv("ENCRYPTION_SECRET", "default-secret-key-change-me-32ch")
_raw = _ENCRYPTION_SECRET.ljust(32, "0")[:32]
_KEY_BYTES = _raw.encode("utf-8")


# ===================== 加密/解密 =====================

def _encrypt(plain_text: str) -> str:
    iv = secrets.token_bytes(12)
    aesgcm = AESGCM(_KEY_BYTES)
    ct_with_tag = aesgcm.encrypt(iv, plain_text.encode("utf-8"), None)
    cipher = ct_with_tag[:-16]
    tag = ct_with_tag[-16:]
    return f"{iv.hex()}:{tag.hex()}:{cipher.hex()}"


def _decrypt(cipher_text: str) -> str:
    parts = cipher_text.split(":")
    if len(parts) != 3:
        raise ValueError("Invalid encrypted format")
    iv_hex, tag_hex, cipher_hex = parts
    iv = bytes.fromhex(iv_hex)
    tag = bytes.fromhex(tag_hex)
    cipher = bytes.fromhex(cipher_hex)
    aesgcm = AESGCM(_KEY_BYTES)
    plain = aesgcm.decrypt(iv, cipher + tag, None)
    return plain.decode("utf-8")


# ===================== 公开 API =====================

def save_user_key(user_id: str, openrouter_key: str) -> None:
    encrypted = _encrypt(openrouter_key)
    conn = get_conn()
    with conn:
        conn.execute(
            "INSERT INTO user_keys(user_id, encrypted, updated_at) VALUES(?,?,?) "
            "ON CONFLICT(user_id) DO UPDATE SET encrypted=excluded.encrypted, updated_at=excluded.updated_at",
            (user_id, encrypted, time.time()),
        )
    conn.close()


def get_user_key(user_id: str) -> str | None:
    conn = get_conn()
    row = conn.execute("SELECT encrypted FROM user_keys WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    if not row:
        return None
    try:
        return _decrypt(row["encrypted"])
    except Exception:
        delete_user_key(user_id)
        return None


def has_user_key(user_id: str) -> bool:
    conn = get_conn()
    row = conn.execute("SELECT 1 FROM user_keys WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    return row is not None


def delete_user_key(user_id: str) -> None:
    conn = get_conn()
    with conn:
        conn.execute("DELETE FROM user_keys WHERE user_id=?", (user_id,))
    conn.close()


def validate_key_format(key: str) -> bool:
    return bool(re.match(r"^sk-or-v1-[a-zA-Z0-9_-]{10,}$", key))
