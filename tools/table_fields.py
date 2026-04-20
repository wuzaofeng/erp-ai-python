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
from typing import Optional
import json
from pydantic import BaseModel, Field
from langchain_core.tools import StructuredTool

from erp_client import get_field_layout
from logger import logger

# ===================== 工具描述 =====================

TABLE_FIELDS_DESCRIPTION = (
    "获取 ERP 指定数据表的真实字段列表（从 ERP getProgGridLayout 接口动态获取）。"
    "在调用 query_erp_list 传入 filters 过滤条件之前，必须先调用此工具获取真实字段名，"
    "严禁依赖训练知识猜测字段名。"
    "返回字段列表包含：字段名(FieldName)、中文标题(label)、字段类型(fieldType)。"
)


# ===================== 参数 Schema =====================

class TableFieldsInput(BaseModel):
    tableName: str = Field(
        description="要查询字段列表的表名，格式如 BDM007_VendorKindQuery.BDM007_VendorKindQuery"
    )


# ===================== 工具工厂函数 =====================

def create_table_fields_tool(erp_cookie: str, erp_auth: str, user_id: str = "") -> StructuredTool:
    """创建 TableFields 工具实例"""

    async def table_fields_handler(tableName: str) -> str:
        logger.info("TableFields", f"获取字段列表 | table={tableName}")
        try:
            fields = await get_field_layout(
                table_name=tableName,
                user_id=user_id,
                erp_cookie=erp_cookie,
                erp_auth=erp_auth,
            )
            if not fields:
                return f"未找到表 '{tableName}' 的字段信息，请确认表名是否正确。"

            logger.info("TableFields", f"获取到 {len(fields.field_labels)} 个字段 | table={tableName}")
            return json.dumps(
                {
                    "tableName": tableName,
                    "fields": fields.field_labels,
                    "hiddenFields": fields.hidden_fields,
                    "count": len(fields.field_labels),
                },
                ensure_ascii=False,
                indent=2,
            )
        except Exception as e:
            logger.error("TableFields", f"获取字段失败 | table={tableName} | err={e}")
            return f"获取字段列表失败：{str(e)}"

    return StructuredTool.from_function(
        coroutine=table_fields_handler,
        name="get_table_fields",
        description=TABLE_FIELDS_DESCRIPTION,
        args_schema=TableFieldsInput,
    )
