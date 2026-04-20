"""
服务端对话历史记忆 - 对应 src/memory/conversationMemory.ts
按 userId 维护每个用户的对话历史
"""
import os
import time
from dataclasses import dataclass, field
from typing import Optional
from logger import logger

# ===================== 配置 =====================

MAX_HISTORY_ROUNDS = int(os.getenv("MEMORY_MAX_ROUNDS", "20"))
MEMORY_TTL_S = int(os.getenv("MEMORY_TTL_MS", str(2 * 60 * 60 * 1000))) / 1000  # 转换为秒，默认 2 小时


# ===================== 类型 =====================

@dataclass
class ConversationMessage:
    role: str   # "user" | "assistant"
    content: str
    timestamp: float = field(default_factory=time.time)


@dataclass
class MemoryEntry:
    messages: list[ConversationMessage] = field(default_factory=list)
    last_active_at: float = field(default_factory=time.time)


# ===================== 存储 =====================

_store: dict[str, MemoryEntry] = {}


# ===================== 工具函数 =====================

def _cleanup_if_expired(user_id: str) -> None:
    """惰性清理过期 Memory"""
    entry = _store.get(user_id)
    if entry and (time.time() - entry.last_active_at) > MEMORY_TTL_S:
        del _store[user_id]
        logger.info("Memory", f"会话已过期，已清理 | userId={user_id}")


def _trim(messages: list[ConversationMessage]) -> list[ConversationMessage]:
    """确保消息数不超出上限（滚动窗口）"""
    max_messages = MAX_HISTORY_ROUNDS * 2
    if len(messages) > max_messages:
        return messages[len(messages) - max_messages:]
    return messages


# ===================== 公开 API =====================

def get_history(user_id: str) -> list[ConversationMessage]:
    """获取指定用户的对话历史"""
    _cleanup_if_expired(user_id)
    entry = _store.get(user_id)
    if not entry:
        return []
    entry.last_active_at = time.time()
    return entry.messages


def append_turn(user_id: str, user_message: str, assistant_message: str) -> None:
    """追加一轮对话（user + assistant）"""
    _cleanup_if_expired(user_id)
    entry = _store.get(user_id)
    if not entry:
        entry = MemoryEntry()
        _store[user_id] = entry

    now = time.time()
    entry.messages.append(ConversationMessage(role="user", content=user_message, timestamp=now))
    entry.messages.append(ConversationMessage(role="assistant", content=assistant_message, timestamp=now))
    entry.messages = _trim(entry.messages)
    entry.last_active_at = now

    logger.info("Memory", f"对话历史已更新 | userId={user_id} | 当前轮数={len(entry.messages) // 2}")


def append_user_message(user_id: str, content: str) -> None:
    """只追加用户消息（用于流式场景）"""
    _cleanup_if_expired(user_id)
    entry = _store.get(user_id)
    if not entry:
        entry = MemoryEntry()
        _store[user_id] = entry

    entry.messages.append(ConversationMessage(role="user", content=content, timestamp=time.time()))
    entry.messages = _trim(entry.messages)
    entry.last_active_at = time.time()


def append_assistant_message(user_id: str, content: str) -> None:
    """追加 AI 回复消息（流式输出完成后调用）"""
    _cleanup_if_expired(user_id)
    entry = _store.get(user_id)
    if not entry:
        return
    entry.messages.append(ConversationMessage(role="assistant", content=content, timestamp=time.time()))
    entry.messages = _trim(entry.messages)
    entry.last_active_at = time.time()


def clear_history(user_id: str) -> None:
    """清除指定用户的对话历史"""
    _store.pop(user_id, None)
    logger.info("Memory", f"对话历史已清除 | userId={user_id}")


def get_memory_stats() -> dict:
    """获取内存统计信息"""
    return {
        "activeUsers": len(_store),
        "maxRounds": MAX_HISTORY_ROUNDS,
        "ttlMs": int(MEMORY_TTL_S * 1000),
    }
