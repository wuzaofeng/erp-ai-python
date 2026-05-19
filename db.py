"""
SQLite 数据库初始化 — 统一管理连接和建表
数据库文件：data/erp_ai.db
"""
import sqlite3
import os
from pathlib import Path

_DB_PATH = Path(os.getenv("SQLITE_PATH", "data/erp_ai.db"))


def get_conn() -> sqlite3.Connection:
    """获取 SQLite 连接（check_same_thread=False 供多线程使用）"""
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")   # 提升并发写性能
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    """建表（幂等，重复执行无副作用）"""
    conn = get_conn()
    with conn:
        # ---- 用户 Key 表 ----
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_keys (
                user_id   TEXT PRIMARY KEY,
                encrypted TEXT NOT NULL,
                updated_at REAL NOT NULL
            )
        """)

        # ---- 对话历史表 ----
        conn.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id       TEXT    NOT NULL,
                role          TEXT    NOT NULL,
                content       TEXT    NOT NULL,
                created_at    REAL    NOT NULL
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_conv_user_time
            ON conversations(user_id, created_at)
        """)

        # ---- 用户偏好表 ----
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_preference (
                user_id             TEXT PRIMARY KEY,
                frequent_tables     TEXT NOT NULL DEFAULT '[]',
                frequent_filters    TEXT NOT NULL DEFAULT '[]',
                preferred_page_size INTEGER NOT NULL DEFAULT 20,
                updated_at          REAL    NOT NULL
            )
        """)

        # ---- Skills 表 ----
        conn.execute("""
            CREATE TABLE IF NOT EXISTS skills (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                key         TEXT UNIQUE NOT NULL,
                name        TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                rule        TEXT NOT NULL,
                pages       TEXT NOT NULL DEFAULT '[]',
                priority    INTEGER NOT NULL DEFAULT 0,
                enabled     INTEGER NOT NULL DEFAULT 1,
                updated_at  REAL    NOT NULL
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_skills_key
            ON skills(key)
        """)
    conn.close()
