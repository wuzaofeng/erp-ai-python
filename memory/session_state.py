"""
会话级查询状态 — 按 conversation_id 存储最近一次 query_erp_list 的参数
用于翻页、追问时向 AI 注入结构化上下文，避免依赖关键词匹配
"""
import time
from dataclasses import dataclass, field
from typing import Optional

_TTL = 2 * 3600  # 2小时过期，与 conversation_memory 对齐


@dataclass
class LastQueryState:
    table_name: str
    page_size: int
    page_index: int
    filters: list[dict] = field(default_factory=list)
    total: int = 0
    updated_at: float = field(default_factory=time.time)


_store: dict[str, LastQueryState] = {}


def save_query_state(conversation_id: str, state: LastQueryState) -> None:
    if not conversation_id:
        return
    _store[conversation_id] = state
    _evict()


def get_query_state(conversation_id: str) -> Optional[LastQueryState]:
    if not conversation_id:
        return None
    # 1. 先查内存
    s = _store.get(conversation_id)
    if s and time.time() - s.updated_at <= _TTL:
        return s
    _store.pop(conversation_id, None)
    # 2. 内存 miss，从 agent_traces SQLite 里找这个会话最近一次 query_erp_list 调用参数
    return _load_from_traces(conversation_id)


def _load_from_traces(conversation_id: str) -> Optional[LastQueryState]:
    """从 agent_traces 恢复最近一次查询状态（用于重启后兜底）"""
    try:
        import json
        from db import get_conn
        conn = get_conn()
        rows = conn.execute(
            "SELECT steps FROM agent_traces WHERE conversation_id=? ORDER BY created_at DESC LIMIT 10",
            (conversation_id,),
        ).fetchall()
        conn.close()
        for row in rows:
            steps = json.loads(row["steps"])
            for step in reversed(steps):
                if step.get("type") == "tool" and step.get("name") == "query_erp_list":
                    inp = step.get("input") or {}
                    if not inp.get("tableName"):
                        continue
                    # 从 output 里解析 total
                    total = 0
                    out = step.get("output") or ""
                    if isinstance(out, str):
                        j_start = out.find("{")
                        if j_start >= 0:
                            try:
                                parsed = json.loads(out[j_start:])
                                total = parsed.get("total", 0)
                            except Exception:
                                pass
                    state = LastQueryState(
                        table_name=inp.get("tableName", ""),
                        page_size=int(inp.get("pageSize", 20) or 20),
                        page_index=int(inp.get("pageIndex", 1) or 1),
                        filters=inp.get("filters", []),
                        total=int(total or 0),
                    )
                    _store[conversation_id] = state  # 回填内存
                    return state
    except Exception:
        pass
    return None


def _evict() -> None:
    now = time.time()
    expired = [k for k, v in _store.items() if now - v.updated_at > _TTL]
    for k in expired:
        del _store[k]
