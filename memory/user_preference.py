"""
用户查询偏好记忆 - 对应 src/memory/userPreference.ts
按 userId 完全隔离，记录常用表、常用过滤条件和偏好 pageSize
"""
import time
from dataclasses import dataclass, field
from typing import Optional
from logger import logger

# ===================== 配置 =====================

MAX_FREQUENT_TABLES = 5
MAX_FREQUENT_FILTERS = 10
FILTER_EXPIRE_DAYS = 30

# ===================== 类型定义 =====================

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


# ===================== 存储 =====================

_store: dict[str, UserPreference] = {}


# ===================== 工具函数 =====================

def _get_or_create(user_id: str) -> UserPreference:
    if user_id not in _store:
        _store[user_id] = UserPreference(userId=user_id)
    return _store[user_id]


def _clean_expired_filters(pref: UserPreference) -> None:
    """清理超过 FILTER_EXPIRE_DAYS 天未使用的过滤条件"""
    expire_s = FILTER_EXPIRE_DAYS * 24 * 60 * 60
    now = time.time()
    pref.frequentFilters = [f for f in pref.frequentFilters if now - f.lastUsedAt <= expire_s]


# ===================== 公开 API =====================

def update_preference(user_id: str, info: QueryInfo) -> None:
    """查询成功后更新用户偏好"""
    pref = _get_or_create(user_id)
    now = time.time()

    # --- 更新常用表 ---
    exist_table = next((t for t in pref.frequentTables if t.tableName == info.tableName), None)
    if exist_table:
        exist_table.queryCount += 1
        exist_table.lastUsedAt = now
        if info.displayName:
            exist_table.displayName = info.displayName
    else:
        pref.frequentTables.append(FrequentTable(
            tableName=info.tableName,
            displayName=info.displayName or info.tableName,
            queryCount=1,
            lastUsedAt=now,
        ))

    pref.frequentTables.sort(key=lambda t: t.queryCount, reverse=True)
    pref.frequentTables = pref.frequentTables[:MAX_FREQUENT_TABLES]

    # --- 更新常用过滤条件 ---
    for f in (info.filters or []):
        exist_filter = next(
            (ff for ff in pref.frequentFilters
             if ff.tableName == info.tableName
             and ff.fieldName == f.get("FieldName")
             and ff.operator == f.get("Operator")
             and ff.value == f.get("Value")),
            None
        )
        if exist_filter:
            exist_filter.useCount += 1
            exist_filter.lastUsedAt = now
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
    logger.info(
        "Preference",
        f"偏好已更新 | userId={user_id} | 常用表={len(pref.frequentTables)} | 常用过滤={len(pref.frequentFilters)}"
    )


def get_preference_prompt(user_id: str) -> str:
    """获取指定用户的偏好，用于注入 System Prompt"""
    pref = _store.get(user_id)
    if not pref or (not pref.frequentTables and not pref.frequentFilters):
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
            table_display = next(
                (t.displayName for t in pref.frequentTables if t.tableName == table_name),
                table_name
            )
            cond_list = ", ".join(
                f"{ff.fieldName}{ff.operator}{ff.value}" for ff in filters[:3]
            )
            lines.append(f"- 常用条件（{table_display}）：{cond_list}")

    lines.append("如果用户没有明确指定表名或条件，优先按以上偏好推断。")
    return "\n".join(lines)


def get_preference(user_id: str) -> Optional[UserPreference]:
    """获取用户的原始偏好对象（供调试或扩展使用）"""
    return _store.get(user_id)


def clear_preference(user_id: str) -> None:
    """清除指定用户的偏好"""
    _store.pop(user_id, None)
