"""
服务端对话历史记忆 — 持久化到 SQLite
按 (userId, conversationId) 隔离，每个对话独立历史，互不污染
"""
import os
import time
from dataclasses import dataclass, field

from db import get_conn
from logger import logger

MAX_HISTORY_ROUNDS = int(os.getenv("MEMORY_MAX_ROUNDS", "20"))
MEMORY_TTL_S = int(os.getenv("MEMORY_TTL_MS", str(2 * 60 * 60 * 1000))) / 1000
MAX_USER_MSG_CHARS   = int(os.getenv("MEMORY_MAX_USER_CHARS",   "500"))
MAX_ASSIST_MSG_CHARS = int(os.getenv("MEMORY_MAX_ASSIST_CHARS", "2000"))
def _truncate(content: str, max_chars: int) -> str:
    if len(content) <= max_chars:
        return content
    return content[:max_chars]


@dataclass
class ConversationMessage:
    role: str
    content: str
    timestamp: float = field(default_factory=time.time)


# ===================== 内部工具 =====================

def _delete_expired(user_id: str, conversation_id: str) -> None:
    cutoff = time.time() - MEMORY_TTL_S
    conn = get_conn()
    with conn:
        conn.execute(
            "DELETE FROM conversations WHERE user_id=? AND conversation_id=? AND created_at<?",
            (user_id, conversation_id, cutoff),
        )
    conn.close()


def _trim(user_id: str, conversation_id: str) -> None:
    max_rows = MAX_HISTORY_ROUNDS * 2
    conn = get_conn()
    with conn:
        row = conn.execute(
            "SELECT id FROM conversations WHERE user_id=? AND conversation_id=? ORDER BY created_at DESC LIMIT 1 OFFSET ?",
            (user_id, conversation_id, max_rows - 1),
        ).fetchone()
        if row:
            conn.execute(
                "DELETE FROM conversations WHERE user_id=? AND conversation_id=? AND id<?",
                (user_id, conversation_id, row["id"]),
            )
    conn.close()


# ===================== 公开 API =====================

def get_history(user_id: str, conversation_id: str = "") -> list[ConversationMessage]:
    _delete_expired(user_id, conversation_id)
    conn = get_conn()
    rows = conn.execute(
        "SELECT role, content, created_at FROM conversations WHERE user_id=? AND conversation_id=? ORDER BY created_at ASC",
        (user_id, conversation_id),
    ).fetchall()
    conn.close()
    return [
        ConversationMessage(
            role=r["role"],
            content=_truncate(r["content"], MAX_USER_MSG_CHARS if r["role"] == "user" else MAX_ASSIST_MSG_CHARS),
            timestamp=r["created_at"],
        )
        for r in rows
    ]


def append_user_message(user_id: str, content: str, conversation_id: str = "") -> None:
    _delete_expired(user_id, conversation_id)
    conn = get_conn()
    with conn:
        conn.execute(
            "INSERT INTO conversations(user_id, conversation_id, role, content, created_at) VALUES(?,?,?,?,?)",
            (user_id, conversation_id, "user", _truncate(content, MAX_USER_MSG_CHARS), time.time()),
        )
    conn.close()
    _trim(user_id, conversation_id)


def append_assistant_message(user_id: str, content: str, conversation_id: str = "", verified: bool = False) -> None:
    conn = get_conn()
    with conn:
        conn.execute(
            "INSERT INTO conversations(user_id, conversation_id, role, content, created_at, verified) VALUES(?,?,?,?,?,?)",
            (user_id, conversation_id, "assistant", _truncate(content, MAX_ASSIST_MSG_CHARS), time.time(), 1 if verified else 0),
        )
    conn.close()
    _trim(user_id, conversation_id)
    history_len = len(get_history(user_id, conversation_id))
    logger.info("Memory", f"对话历史已更新 | userId={user_id} | convId={conversation_id} | 当前轮数={history_len // 2} | verified={verified}")


def clear_history(user_id: str, conversation_id: str = "") -> None:
    conn = get_conn()
    with conn:
        if conversation_id:
            conn.execute("DELETE FROM conversations WHERE user_id=? AND conversation_id=?", (user_id, conversation_id))
        else:
            conn.execute("DELETE FROM conversations WHERE user_id=?", (user_id,))
    conn.close()
    logger.info("Memory", f"对话历史已清除 | userId={user_id} | convId={conversation_id or 'ALL'}")


def get_memory_stats() -> dict:
    conn = get_conn()
    row = conn.execute("SELECT COUNT(DISTINCT user_id) as cnt FROM conversations").fetchone()
    conn.close()
    return {
        "activeUsers": row["cnt"] if row else 0,
        "maxRounds": MAX_HISTORY_ROUNDS,
        "ttlMs": int(MEMORY_TTL_S * 1000),
    }
