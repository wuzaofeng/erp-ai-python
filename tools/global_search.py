'''
Author: zack.wu zack.wu@zuru.com
Date: 2026-04-20 12:08:34
LastEditors: zack.wu zack.wu@zuru.com
LastEditTime: 2026-04-20 12:24:10
FilePath: \erp-ai-nodejsc:\WorkSpace\erp-ai-python\tools\global_search.py
Description: 这是默认设置,请设置`customMade`, 打开koroFileHeader查看配置 进行设置: https://github.com/OBKoro1/koro1FileHeader/wiki/%E9%85%8D%E7%BD%AE
'''
"""
ERP 全局单据搜索工具 - 对应 src/tools/globalSearch.ts
"""
import json
from pydantic import BaseModel, Field
from langchain_core.tools import StructuredTool

from erp_client import call_global_search
from logger import logger

# ===================== 工具描述 =====================

GLOBAL_SEARCH_DESCRIPTION = (
    "在 ERP 系统中全局搜索单据（不知道是哪个业务模块时优先调用）。"
    "输入单据号或关键词，系统自动跨模块搜索采购单、销售单、工单、入库单等。"
    "适用场景：用户只给出单据号但不知道模块；快速定位单据所属模块。"
)


# ===================== 参数 Schema =====================

class GlobalSearchInput(BaseModel):
    keyword: str = Field(description="搜索关键词或单据号，如 'PO20240001' 或 '供应商名称'")
    pageSize: int = Field(default=20, ge=1, le=50, description="返回条数，默认 20")


# ===================== 工具工厂函数 =====================

def create_global_search_tool(erp_cookie: str, erp_auth: str) -> StructuredTool:
    """创建 GlobalSearch 工具实例"""

    async def global_search_handler(keyword: str, pageSize: int = 20) -> str:
        logger.info("GlobalSearch", f"全局搜索 | keyword={keyword} | pageSize={pageSize}")
        try:
            result = await call_global_search(
                keyword=keyword,
                erp_cookie=erp_cookie,
                erp_auth=erp_auth,
            )
            return result
        except Exception as e:
            logger.error("GlobalSearch", f"搜索失败 | keyword={keyword} | err={e}")
            return f"全局搜索失败：{str(e)}"

    return StructuredTool.from_function(
        coroutine=global_search_handler,
        name="search_erp_global",
        description=GLOBAL_SEARCH_DESCRIPTION,
        args_schema=GlobalSearchInput,
    )
