"""
用户 Key 存储服务 - 持久化到 SQLite，加密可通过 ENABLE_ENCRYPTION 配置
"""
import os
import re
import time
import secrets
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from db import get_conn

# ===================== 加密配置 =====================

# ENABLE_ENCRYPTION=true 时启用 AES-256-GCM，否则明文存储
_ENABLE_ENCRYPTION = os.getenv("ENABLE_ENCRYPTION", "false").lower() == "true"
_ENCRYPTION_SECRET = os.getenv("ENCRYPTION_SECRET", "default-secret-key-change-me-32ch")
_KEY_BYTES = _ENCRYPTION_SECRET.ljust(32, "0")[:32].encode("utf-8")


# ===================== 加密/解密 =====================

def _encrypt(plain_text: str) -> str:
    if not _ENABLE_ENCRYPTION:
        return plain_text
    iv = secrets.token_bytes(12)
    aesgcm = AESGCM(_KEY_BYTES)
    ct_with_tag = aesgcm.encrypt(iv, plain_text.encode("utf-8"), None)
    cipher = ct_with_tag[:-16]
    tag = ct_with_tag[-16:]
    return f"{iv.hex()}:{tag.hex()}:{cipher.hex()}"


def _decrypt(cipher_text: str) -> str:
    if not _ENABLE_ENCRYPTION:
        return cipher_text
    parts = cipher_text.split(":")
    if len(parts) != 3:
        raise ValueError("Invalid encrypted format")
    iv_hex, tag_hex, cipher_hex = parts
    iv = bytes.fromhex(iv_hex)
    tag = bytes.fromhex(tag_hex)
    cipher = bytes.fromhex(cipher_hex)
    aesgcm = AESGCM(_KEY_BYTES)
    return aesgcm.decrypt(iv, cipher + tag, None).decode("utf-8")


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


def get_all_keys() -> dict[str, str]:
    """返回所有用户的解密后 key，供评测脚本使用"""
    conn = get_conn()
    rows = conn.execute("SELECT user_id, encrypted FROM user_keys").fetchall()
    conn.close()
    result = {}
    for row in rows:
        try:
            result[row["user_id"]] = _decrypt(row["encrypted"])
        except Exception:
            pass
    return result


def validate_key_format(key: str) -> bool:
    return bool(re.match(r"^sk-or-v1-[a-zA-Z0-9_-]{10,}$", key))
