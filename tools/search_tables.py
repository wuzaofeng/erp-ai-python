"""
ERP 表结构搜索工具 — 按关键词从 SQLite 检索匹配的数据表及字段
取代系统提示词中的全量 catalog，将 ~32K token 压缩为按需调用
"""
import json
import re
from pydantic import BaseModel, Field
from langchain_core.tools import StructuredTool

from logger import logger

# ===================== 常量 =====================

SEARCH_TABLES_DESCRIPTION = (
    "搜索 ERP 系统中可查询的数据表。当需要查询 ERP 数据但不知道用哪张表时，"
    "先调用此工具输入业务关键词（如'采购申请'、'销售订单'、'员工'），"
    "返回匹配的表名和字段供后续 query_erp_list 使用。"
    "跨模块查询时可多次调用。"
)

# 进程级缓存：keyword → 结果字符串（重启清空）
_cache: dict[str, str] = {}


# ===================== 参数 Schema =====================

class SearchTablesInput(BaseModel):
    keyword: str = Field(description="业务关键词，如'采购申请'、'销售订单'、'员工信息'")


# ===================== 核心逻辑 =====================

def _search_tables(keyword: str) -> str:
    cache_key = keyword.strip().lower()
    if cache_key in _cache:
        logger.info("SearchTables", f"缓存命中 | keyword={keyword}")
        return _cache[cache_key]

    try:
        from db import get_conn
        conn = get_conn()

        # 用 LIKE 模糊匹配 module_name 和 form_code
        pattern = f"%{keyword}%"
        rows = conn.execute(
            """
            SELECT c.form_code, c.module_name, c.api_path, c.extra_body,
                   l.table_name, l.fields_json
            FROM erp_form_catalog c
            LEFT JOIN erp_form_layout_cache l ON c.form_code = l.form_code
            WHERE c.enabled = 1
              AND (c.module_name LIKE ? OR c.form_code LIKE ?)
            ORDER BY c.form_code
            LIMIT 10
            """,
            (pattern, pattern),
        ).fetchall()
        conn.close()

        if not rows:
            tip = f"未找到与「{keyword}」相关的表，请换关键词重试"
            result = json.dumps({"matched": 0, "tables": [], "tip": tip}, ensure_ascii=False)
            _cache[cache_key] = result
            return result

        tables = []
        for row in rows:
            fields_preview = []
            if row["fields_json"]:
                try:
                    fields = json.loads(row["fields_json"])
                    visible = [f for f in fields if not f.get("hidden") and f.get("field")]
                    fields_preview = [
                        {"field": f["field"], "label": f.get("label", "")}
                        for f in visible[:10]
                    ]
                except Exception:
                    pass

            entry: dict = {
                "tableName": row["table_name"] or row["form_code"],
                "moduleName": row["module_name"] or "",
                "fields": fields_preview,
            }
            if row["api_path"]:
                entry["apiPath"] = row["api_path"]
            if row["extra_body"]:
                entry["extraBody"] = row["extra_body"]
            tables.append(entry)

        result = json.dumps({"matched": len(tables), "tables": tables}, ensure_ascii=False, indent=2)
        _cache[cache_key] = result
        logger.info("SearchTables", f"命中 {len(tables)} 张表 | keyword={keyword}")
        return result

    except Exception as e:
        logger.error("SearchTables", f"搜索失败 | keyword={keyword} | {e}")
        return json.dumps({"error": f"表搜索失败：{e}"}, ensure_ascii=False)


# ===================== 工具工厂函数 =====================

def create_search_tables_tool(run_id: str = "") -> StructuredTool:
    """创建 SearchTables 工具实例（不需要 ERP cookie，纯本地 SQLite 查询）"""

    def handler(keyword: str) -> str:
        from logger import start_timer as _st
        cache_key = keyword.strip().lower()
        cache_hit = cache_key in _cache
        t = _st()
        result = _search_tables(keyword)
        duration = t()
        if run_id:
            try:
                import json as _json
                from trace.agent_trace import trace_service
                parsed = _json.loads(result)
                trace_service.log_table_search(run_id, keyword, parsed.get("matched", 0), parsed.get("tables", []), cache_hit, duration_ms=duration)
            except Exception:
                pass
        return result

    return StructuredTool.from_function(
        func=handler,
        name="search_erp_tables",
        description=SEARCH_TABLES_DESCRIPTION,
        args_schema=SearchTablesInput,
    )
