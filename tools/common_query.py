'''
Author: zack.wu zack.wu@zuru.com
Date: 2026-04-20 12:07:30
LastEditors: zack.wu zack.wu@zuru.com
LastEditTime: 2026-04-20 12:22:56
FilePath: \erp-ai-nodejsc:\WorkSpace\erp-ai-python\tools\common_query.py
Description: 这是默认设置,请设置`customMade`, 打开koroFileHeader查看配置 进行设置: https://github.com/OBKoro1/koro1FileHeader/wiki/%E9%85%8D%E7%BD%AE
'''
"""
ERP 通用列表查询工具 - 对应 src/tools/commonQuery.ts
"""
from typing import Optional, Any
from pydantic import BaseModel, Field
from langchain_core.tools import StructuredTool

from erp_client import call_common_query
from cache.query_cache import build_cache_key, get_cache, set_cache
from logger import logger

# ===================== 参数 Schema =====================

class FilterItem(BaseModel):
    FieldName: str = Field(description="字段名，参考数据表目录中的常用字段")
    Operator: str = Field(description="过滤操作符，使用 ERP 标准值：Equal / NotEqual / GreaterThan / GreaterThanOrEqual / LessThan / LessThanOrEqual / Like / NotLike / StartWith / EndWith / IsNull / IsNotNull / InList / NotInList")
    Value: str = Field(default="", description="过滤值，IsNull/IsNotNull 时可留空")
    Logic: Optional[str] = Field(default="and", description="当前条件与下一条件的逻辑关系：and（且）或 or（或），默认 and；最后一条填 and")
    LeftParen: Optional[str] = Field(default="", description="左括号，需要分组时填 \"(\"，否则留空")
    RightParen: Optional[str] = Field(default="", description="右括号，需要分组时填 \")\"，否则留空")


class CommonQueryInput(BaseModel):
    tableName: str = Field(description="必须从数据表目录中选取，格式如 BDM007_VendorKindQuery.BDM007_VendorKindQuery")
    filters: Optional[list[FilterItem]] = Field(default=None, description="过滤条件，不填则查询所有记录（最多10个）")
    pageSize: Optional[int] = Field(default=20, ge=1, le=100, description="返回条数，默认 20，最多 100")
    pageIndex: Optional[int] = Field(default=1, ge=1, description="页码，从 1 开始")
    apiPath: Optional[str] = Field(default=None, description="可选：业务模块接口路径，数据表目录中标注了 [apiPath=xxx] 的表必须填此字段")
    extraBody: Optional[dict[str, Any]] = Field(default=None, description="可选：追加到请求体的额外字段，数据表目录中标注了 [extraBody=...] 的表必须按标注传此参数")


# ===================== 工具描述 =====================

COMMON_QUERY_DESCRIPTION = (
    "查询 ERP 系统的业务列表数据。支持供应商、客户、物料、采购订单、销售订单、库存、应付/应收账款等。"
    '调用前必须从系统提示中的"数据表目录"找到正确的 tableName。'
    "【重要】若需要传入 filters 过滤条件，必须先调用 get_table_fields 工具获取该表的真实字段列表，"
    "然后从返回的字段名中选取正确的 FieldName，严禁依赖训练知识猜测字段名。"
    "支持多条件过滤：Operator 使用 ERP 标准值（Equal/NotEqual/GreaterThan/GreaterThanOrEqual/LessThan/LessThanOrEqual/Like/NotLike/StartWith/EndWith/IsNull/IsNotNull/InList/NotInList）；"
    "Logic 字段控制与上一条件的关系（and=且，or=或，默认 and）；"
    "LeftParen/RightParen 用于条件分组，如 (A or B) and C 时 A 填 LeftParen=\"(\"，B 填 RightParen=\")\"。"
    "适用场景：列表查询、条件筛选、分页浏览、跨表联查。"
)


# ===================== 工具工厂函数 =====================

def create_common_query_tool(erp_cookie: str, erp_auth: str, user_id: str = "") -> StructuredTool:
    """创建 CommonQuery 工具实例"""

    async def common_query_handler(
        tableName: str,
        filters: Optional[list[dict]] = None,
        pageSize: Optional[int] = 20,
        pageIndex: Optional[int] = 1,
        apiPath: Optional[str] = None,
        extraBody: Optional[dict] = None,
    ) -> str:
        page_size = min(pageSize or 20, 100)
        page_index = pageIndex or 1
        raw_filters = (filters or [])[:10]
        filter_list = [
            f.model_dump(exclude_none=True) if hasattr(f, "model_dump") else f
            for f in raw_filters
        ]

        params = {
            "tableName": tableName,
            "filters": filter_list,
            "pageSize": page_size,
            "pageIndex": page_index,
            "apiPath": apiPath,
            "extraBody": extraBody or {},
        }

        # 尝试缓存命中
        cache_key = build_cache_key(params, user_id=user_id)
        cached = get_cache(cache_key)
        if cached:
            logger.info("CommonQuery", f"缓存命中 | key={cache_key[:8]}... | table={tableName}")
            return cached

        # 调用 ERP 接口
        logger.info("CommonQuery", f"查询 | table={tableName} | pageSize={page_size} | filters={len(filter_list)}")
        result = await call_common_query(params, erp_cookie, erp_auth)

        result_str = str(result)
        set_cache(cache_key, result_str)
        return result_str

    return StructuredTool.from_function(
        coroutine=common_query_handler,
        name="query_erp_list",
        description=COMMON_QUERY_DESCRIPTION,
        args_schema=CommonQueryInput,
    )
