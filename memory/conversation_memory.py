"""
服务端对话历史记忆 — 持久化到 SQLite
按 userId 维护每个用户的对话历史，支持 TTL 自动清理
"""
import os
import time
from dataclasses import dataclass, field

from db import get_conn
from logger import logger

MAX_HISTORY_ROUNDS = int(os.getenv("MEMORY_MAX_ROUNDS", "20"))
MEMORY_TTL_S = int(os.getenv("MEMORY_TTL_MS", str(2 * 60 * 60 * 1000))) / 1000


@dataclass
class ConversationMessage:
    role: str
    content: str
    timestamp: float = field(default_factory=time.time)


# ===================== 内部工具 =====================

def _delete_expired(user_id: str) -> None:
    """删除该用户超过 TTL 的所有消息"""
    cutoff = time.time() - MEMORY_TTL_S
    conn = get_conn()
    with conn:
        conn.execute(
            "DELETE FROM conversations WHERE user_id=? AND created_at<?",
            (user_id, cutoff),
        )
    conn.close()


def _trim(user_id: str) -> None:
    """只保留最近 MAX_HISTORY_ROUNDS*2 条消息，删除更早的"""
    max_rows = MAX_HISTORY_ROUNDS * 2
    conn = get_conn()
    with conn:
        # 找到第 max_rows 条消息的 id，删除比它更早的
        row = conn.execute(
            "SELECT id FROM conversations WHERE user_id=? ORDER BY created_at DESC LIMIT 1 OFFSET ?",
            (user_id, max_rows - 1),
        ).fetchone()
        if row:
            conn.execute(
                "DELETE FROM conversations WHERE user_id=? AND id<?",
                (user_id, row["id"]),
            )
    conn.close()


# ===================== 公开 API =====================

def get_history(user_id: str) -> list[ConversationMessage]:
    _delete_expired(user_id)
    conn = get_conn()
    rows = conn.execute(
        "SELECT role, content, created_at FROM conversations WHERE user_id=? ORDER BY created_at ASC",
        (user_id,),
    ).fetchall()
    conn.close()
    return [ConversationMessage(role=r["role"], content=r["content"], timestamp=r["created_at"]) for r in rows]


def append_user_message(user_id: str, content: str) -> None:
    _delete_expired(user_id)
    conn = get_conn()
    with conn:
        conn.execute(
            "INSERT INTO conversations(user_id, role, content, created_at) VALUES(?,?,?,?)",
            (user_id, "user", content, time.time()),
        )
    conn.close()
    _trim(user_id)


def append_assistant_message(user_id: str, content: str) -> None:
    conn = get_conn()
    with conn:
        conn.execute(
            "INSERT INTO conversations(user_id, role, content, created_at) VALUES(?,?,?,?)",
            (user_id, "assistant", content, time.time()),
        )
    conn.close()
    _trim(user_id)
    history_len = len(get_history(user_id))
    logger.info("Memory", f"对话历史已更新 | userId={user_id} | 当前轮数={history_len // 2}")


def append_turn(user_id: str, user_message: str, assistant_message: str) -> None:
    now = time.time()
    conn = get_conn()
    with conn:
        conn.execute(
            "INSERT INTO conversations(user_id, role, content, created_at) VALUES(?,?,?,?)",
            (user_id, "user", user_message, now),
        )
        conn.execute(
            "INSERT INTO conversations(user_id, role, content, created_at) VALUES(?,?,?,?)",
            (user_id, "assistant", assistant_message, now),
        )
    conn.close()
    _trim(user_id)


def clear_history(user_id: str) -> None:
    conn = get_conn()
    with conn:
        conn.execute("DELETE FROM conversations WHERE user_id=?", (user_id,))
    conn.close()
    logger.info("Memory", f"对话历史已清除 | userId={user_id}")


def get_memory_stats() -> dict:
    conn = get_conn()
    row = conn.execute("SELECT COUNT(DISTINCT user_id) as cnt FROM conversations").fetchone()
    conn.close()
    return {
        "activeUsers": row["cnt"] if row else 0,
        "maxRounds": MAX_HISTORY_ROUNDS,
        "ttlMs": int(MEMORY_TTL_S * 1000),
    }
