'''
Author: zack.wu zack.wu@zuru.com
Date: 2026-04-20 11:44:07
LastEditors: zack.wu zack.wu@zuru.com
LastEditTime: 2026-04-20 11:44:14
FilePath: \erp-ai-nodejsc:\WorkSpace\erp-ai-python\key_service.py
Description: 这是默认设置,请设置`customMade`, 打开koroFileHeader查看配置 进行设置: https://github.com/OBKoro1/koro1FileHeader/wiki/%E9%85%8D%E7%BD%AE
'''
"""
用户 Key 存储服务 - 对应 src/keyService.ts
AES-256-GCM 加密存储 OpenRouter API Key
"""
import os
import re
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import secrets

# ===================== 加密配置 =====================

_ENCRYPTION_SECRET = os.getenv("ENCRYPTION_SECRET", "default-secret-key-change-me-32ch")
# AES-256 需要 32 字节密钥
_raw = _ENCRYPTION_SECRET.ljust(32, "0")[:32]
_KEY_BYTES = _raw.encode("utf-8")

# 内存存储：userId -> 加密后的 Key（格式：iv_hex:tag_hex:cipher_hex）
_key_store: dict[str, str] = {}


# ===================== 加密/解密 =====================

def _encrypt(plain_text: str) -> str:
    """AES-256-GCM 加密"""
    iv = secrets.token_bytes(12)          # GCM 推荐 12 字节 IV
    aesgcm = AESGCM(_KEY_BYTES)
    # AESGCM.encrypt 返回 ciphertext + tag（tag 附在末尾 16 字节）
    ct_with_tag = aesgcm.encrypt(iv, plain_text.encode("utf-8"), None)
    # 分离密文和 auth tag
    cipher = ct_with_tag[:-16]
    tag = ct_with_tag[-16:]
    return f"{iv.hex()}:{tag.hex()}:{cipher.hex()}"


def _decrypt(cipher_text: str) -> str:
    """AES-256-GCM 解密"""
    parts = cipher_text.split(":")
    if len(parts) != 3:
        raise ValueError("Invalid encrypted format")
    iv_hex, tag_hex, cipher_hex = parts
    iv = bytes.fromhex(iv_hex)
    tag = bytes.fromhex(tag_hex)
    cipher = bytes.fromhex(cipher_hex)
    aesgcm = AESGCM(_KEY_BYTES)
    # AESGCM.decrypt 需要 ciphertext+tag 拼接
    plain = aesgcm.decrypt(iv, cipher + tag, None)
    return plain.decode("utf-8")


# ===================== 公开 API =====================

def save_user_key(user_id: str, openrouter_key: str) -> None:
    """保存用户的 OpenRouter Key（加密存储）"""
    encrypted = _encrypt(openrouter_key)
    _key_store[user_id] = encrypted


def get_user_key(user_id: str) -> str | None:
    """获取用户的 OpenRouter Key（解密后返回）"""
    encrypted = _key_store.get(user_id)
    if not encrypted:
        return None
    try:
        return _decrypt(encrypted)
    except Exception:
        # 解密失败（密钥被修改或数据损坏）
        _key_store.pop(user_id, None)
        return None


def has_user_key(user_id: str) -> bool:
    """检查用户是否已配置 Key"""
    return user_id in _key_store


def delete_user_key(user_id: str) -> None:
    """删除用户的 Key"""
    _key_store.pop(user_id, None)


def validate_key_format(key: str) -> bool:
    """验证 OpenRouter Key 格式是否合法（sk-or-v1-xxxxxxxx）"""
    return bool(re.match(r"^sk-or-v1-[a-zA-Z0-9]{40,}$", key))
