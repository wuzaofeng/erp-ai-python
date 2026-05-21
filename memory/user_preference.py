"""
用户查询偏好记忆 — 持久化到 SQLite
按 userId 隔离，记录常用表、常用过滤条件和偏好 pageSize
"""
import json
import time
from dataclasses import dataclass, field
from typing import Optional

from db import get_conn
from logger import logger

MAX_FREQUENT_TABLES = 5
MAX_FREQUENT_FILTERS = 10
FILTER_EXPIRE_DAYS = 30


@dataclass
class FrequentTable:
    tableName: str
    displayName: str
    queryCount: int = 0
    lastUsedAt: float = field(default_factory=time.time)


@dataclass
class FrequentFilter:
    tableName: str
    fieldName: str
    operator: str
    value: str
    useCount: int = 0
    lastUsedAt: float = field(default_factory=time.time)


@dataclass
class UserPreference:
    userId: str
    frequentTables: list[FrequentTable] = field(default_factory=list)
    frequentFilters: list[FrequentFilter] = field(default_factory=list)
    preferredPageSize: int = 20
    updatedAt: float = field(default_factory=time.time)


@dataclass
class QueryInfo:
    tableName: str
    displayName: Optional[str] = None
    filters: Optional[list[dict]] = None
    pageSize: Optional[int] = None


# ===================== 内部工具 =====================

def _load(user_id: str) -> UserPreference:
    conn = get_conn()
    row = conn.execute(
        "SELECT frequent_tables, frequent_filters, preferred_page_size, updated_at "
        "FROM user_preference WHERE user_id=?",
        (user_id,),
    ).fetchone()
    conn.close()
    if not row:
        return UserPreference(userId=user_id)
    return UserPreference(
        userId=user_id,
        frequentTables=[FrequentTable(**t) for t in json.loads(row["frequent_tables"])],
        frequentFilters=[FrequentFilter(**f) for f in json.loads(row["frequent_filters"])],
        preferredPageSize=row["preferred_page_size"],
        updatedAt=row["updated_at"],
    )


def _save(pref: UserPreference) -> None:
    conn = get_conn()
    with conn:
        conn.execute(
            "INSERT INTO user_preference(user_id, frequent_tables, frequent_filters, preferred_page_size, updated_at) "
            "VALUES(?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET "
            "frequent_tables=excluded.frequent_tables, "
            "frequent_filters=excluded.frequent_filters, "
            "preferred_page_size=excluded.preferred_page_size, "
            "updated_at=excluded.updated_at",
            (
                pref.userId,
                json.dumps([t.__dict__ for t in pref.frequentTables], ensure_ascii=False),
                json.dumps([f.__dict__ for f in pref.frequentFilters], ensure_ascii=False),
                pref.preferredPageSize,
                pref.updatedAt,
            ),
        )
    conn.close()


def _clean_expired_filters(pref: UserPreference) -> None:
    expire_s = FILTER_EXPIRE_DAYS * 24 * 60 * 60
    now = time.time()
    pref.frequentFilters = [f for f in pref.frequentFilters if now - f.lastUsedAt <= expire_s]


# ===================== 公开 API =====================

def update_preference(user_id: str, info: QueryInfo) -> None:
    pref = _load(user_id)
    now = time.time()

    # 更新常用表
    exist = next((t for t in pref.frequentTables if t.tableName == info.tableName), None)
    if exist:
        exist.queryCount += 1
        exist.lastUsedAt = now
        if info.displayName:
            exist.displayName = info.displayName
    else:
        pref.frequentTables.append(FrequentTable(
            tableName=info.tableName,
            displayName=info.displayName or info.tableName,
            queryCount=1,
            lastUsedAt=now,
        ))
    pref.frequentTables.sort(key=lambda t: t.queryCount, reverse=True)
    pref.frequentTables = pref.frequentTables[:MAX_FREQUENT_TABLES]

    # 更新常用过滤条件
    for f in (info.filters or []):
        exist_f = next(
            (ff for ff in pref.frequentFilters
             if ff.tableName == info.tableName
             and ff.fieldName == f.get("FieldName")
             and ff.operator == f.get("Operator")
             and ff.value == f.get("Value")),
            None,
        )
        if exist_f:
            exist_f.useCount += 1
            exist_f.lastUsedAt = now
        else:
            pref.frequentFilters.append(FrequentFilter(
                tableName=info.tableName,
                fieldName=f.get("FieldName", ""),
                operator=f.get("Operator", ""),
                value=f.get("Value", ""),
                useCount=1,
                lastUsedAt=now,
            ))

    _clean_expired_filters(pref)
    pref.frequentFilters.sort(key=lambda ff: ff.useCount, reverse=True)
    pref.frequentFilters = pref.frequentFilters[:MAX_FREQUENT_FILTERS]

    pref.updatedAt = now
    _save(pref)
    logger.info(
        "Preference",
        f"偏好已更新 | userId={user_id} | 常用表={len(pref.frequentTables)} | 常用过滤={len(pref.frequentFilters)}",
    )


def get_preference_prompt(user_id: str) -> str:
    pref = _load(user_id)
    if not pref.frequentTables and not pref.frequentFilters:
        return ""

    lines = ["【个性化提示（根据你的使用习惯）】"]

    if pref.frequentTables:
        table_list = "、".join(
            t.displayName if t.displayName != t.tableName else t.tableName
            for t in pref.frequentTables
        )
        lines.append(f"- 该用户常查询：{table_list}")

    if pref.frequentFilters:
        by_table: dict[str, list[FrequentFilter]] = {}
        for f in pref.frequentFilters:
            by_table.setdefault(f.tableName, []).append(f)
        for table_name, filters in by_table.items():
            display = next(
                (t.displayName for t in pref.frequentTables if t.tableName == table_name),
                table_name,
            )
            cond_list = ", ".join(f"{ff.fieldName}{ff.operator}{ff.value}" for ff in filters[:3])
            lines.append(f"- 常用条件（{display}）：{cond_list}")

    lines.append("如果用户没有明确指定表名或条件，优先按以上偏好推断。")
    return "\n".join(lines)


def get_preference(user_id: str) -> Optional[UserPreference]:
    pref = _load(user_id)
    return pref if (pref.frequentTables or pref.frequentFilters) else None


def clear_preference(user_id: str) -> None:
    conn = get_conn()
    with conn:
        conn.execute("DELETE FROM user_preference WHERE user_id=?", (user_id,))
    conn.close()
