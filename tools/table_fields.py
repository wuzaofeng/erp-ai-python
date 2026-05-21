'''
Author: zack.wu zack.wu@zuru.com
Date: 2026-04-20 12:08:04
LastEditors: zack.wu zack.wu@zuru.com
LastEditTime: 2026-04-20 12:24:18
FilePath: \erp-ai-nodejsc:\WorkSpace\erp-ai-python\tools\table_fields.py
Description: 这是默认设置,请设置`customMade`, 打开koroFileHeader查看配置 进行设置: https://github.com/OBKoro1/koro1FileHeader/wiki/%E9%85%8D%E7%BD%AE
'''
"""
ERP 表字段列表查询工具 - 对应 src/tools/tableFields.ts
"""
import json
from pydantic import BaseModel, Field
from langchain_core.tools import StructuredTool

from erp_client import get_field_layout
from logger import logger

# 进程级字段缓存：form_code → (timestamp, result_str)，TTL 1 小时
_field_cache: dict[str, tuple[float, str]] = {}
_FIELD_CACHE_TTL = 3600


# ===================== 工具描述 =====================

TABLE_FIELDS_DESCRIPTION = (
    "获取 ERP 指定表单的真实字段列表（从 ERP getProgGridLayout 接口动态获取）。"
    "在调用 query_erp_list 传入 filters 过滤条件之前，必须先调用此工具获取真实字段名，"
    "严禁依赖训练知识猜测字段名。"
    "输入 formCode（如 PUM007_PurRequestQuery），工具自动返回对应的标准 tableName 和字段列表。"
    "后续调用 query_erp_list 时，tableName 必须使用本工具返回的 tableName 字段值。"
)


# ===================== 参数 Schema =====================

class TableFieldsInput(BaseModel):
    formCode: str = Field(
        description="表单代码，如 PUM007_PurRequestQuery、BDM007_VendorKindQuery，从数据表目录的 TableName 中取第一个 '.' 之前的部分"
    )


# ===================== 工具工厂函数 =====================

def create_table_fields_tool(erp_cookie: str, erp_auth: str, user_id: str = "") -> StructuredTool:
    """创建 TableFields 工具实例"""

    async def table_fields_handler(formCode: str) -> str:
        import time
        now = time.time()
        cached_ts, cached_result = _field_cache.get(formCode, (0.0, ""))
        if cached_result and now - cached_ts < _FIELD_CACHE_TTL:
            logger.info("TableFields", f"缓存命中 | form={formCode}")
            return cached_result

        logger.info("TableFields", f"获取字段列表 | form={formCode}")
        try:
            # 先从 SQLite 查出正确的 table_name
            from db import get_conn as _get_conn
            _conn = _get_conn()
            _row = _conn.execute(
                "SELECT table_name FROM erp_form_layout_cache WHERE form_code = ?",
                (formCode,),
            ).fetchone()
            _conn.close()
            table_name = _row["table_name"] if _row and _row["table_name"] else formCode

            fields = await get_field_layout(
                table_name=table_name,
                user_id=user_id,
                erp_cookie=erp_cookie,
                erp_auth=erp_auth,
            )
            if not fields:
                return f"未找到 '{formCode}' 的字段信息，请确认 formCode 是否正确或先执行 Sync。"

            logger.info("TableFields", f"获取到 {len(fields.field_labels)} 个字段 | form={formCode} | table={table_name}")
            result_str = json.dumps(
                {
                    "tableName": table_name,
                    "fields": fields.field_labels,
                    "hiddenFields": fields.hidden_fields,
                    "count": len(fields.field_labels),
                },
                ensure_ascii=False,
                indent=2,
            )
            _field_cache[formCode] = (now, result_str)
            return result_str
        except Exception as e:
            logger.error("TableFields", f"获取字段失败 | form={formCode} | err={e}")
            return f"获取字段列表失败：{str(e)}"

    return StructuredTool.from_function(
        coroutine=table_fields_handler,
        name="get_table_fields",
        description=TABLE_FIELDS_DESCRIPTION,
        args_schema=TableFieldsInput,
    )
