'''
Author: zack.wu zack.wu@zuru.com
Date: 2026-04-20 12:09:06
LastEditors: zack.wu zack.wu@zuru.com
LastEditTime: 2026-04-20 12:22:11
FilePath: \erp-ai-nodejsc:\WorkSpace\erp-ai-python\tools\__init__.py
Description: 这是默认设置,请设置`customMade`, 打开koroFileHeader查看配置 进行设置: https://github.com/OBKoro1/koro1FileHeader/wiki/%E9%85%8D%E7%BD%AE
'''
"""
ERP 工具注册表 - 对应 src/tools/index.ts

新增工具步骤：
1. 在 tools/ 目录下新建文件，实现 create_xxx_tool 工厂函数和 XXX_DESCRIPTION 常量
2. 在 TOOL_REGISTRY 中追加一项
3. promptConfig.py 中的能力说明会自动更新，无需手动修改
"""
from dataclasses import dataclass, field
from typing import Callable, Any, Literal

from tools.common_query import create_common_query_tool, COMMON_QUERY_DESCRIPTION
from tools.table_fields import create_table_fields_tool, TABLE_FIELDS_DESCRIPTION
from tools.global_search import create_global_search_tool, GLOBAL_SEARCH_DESCRIPTION
from tools.trigger_actions import create_trigger_actions_tool, TRIGGER_ACTIONS_DESCRIPTION
from tools.search_tables import create_search_tables_tool, SEARCH_TABLES_DESCRIPTION
from tools.web_search import create_web_search_tool, WEB_SEARCH_DESCRIPTION


# ===================== 工具元数据注册表 =====================

@dataclass
class ToolMeta:
    name: str
    description: str
    category: Literal["query", "filter", "display", "stats", "other"]
    auto_prompt: bool
    factory: Callable[..., Any]


TOOL_REGISTRY: list[ToolMeta] = [
    # ---- 数据表搜索（不知道用哪张表时优先调用，替代系统提示词中的全量 catalog）----
    ToolMeta(
        name="search_erp_tables",
        description=SEARCH_TABLES_DESCRIPTION,
        category="query",
        auto_prompt=True,
        factory=lambda cookie, auth, uid="", run_id="": create_search_tables_tool(run_id),
    ),

    # ---- 全局单据搜索（用户只给单据号、不知道是哪个模块时优先调用）----
    ToolMeta(
        name="search_erp_global",
        description=GLOBAL_SEARCH_DESCRIPTION,
        category="query",
        auto_prompt=True,
        factory=lambda cookie, auth, uid="", run_id="": create_global_search_tool(cookie, auth),
    ),

    # ---- 获取表字段列表（必须在有条件查询前调用）----
    ToolMeta(
        name="get_table_fields",
        description=TABLE_FIELDS_DESCRIPTION,
        category="query",
        auto_prompt=True,
        factory=lambda cookie, auth, uid="", run_id="": create_table_fields_tool(cookie, auth, uid),
    ),

    # ---- 通用列表查询（CommonQuery）----
    ToolMeta(
        name="query_erp_list",
        description=COMMON_QUERY_DESCRIPTION,
        category="query",
        auto_prompt=True,
        factory=lambda cookie, auth, uid="", run_id="": create_common_query_tool(cookie, auth, uid),
    ),

    # ---- 前端操作触发（刷新/过滤/跳转）----
    ToolMeta(
        name="trigger_actions",
        description=TRIGGER_ACTIONS_DESCRIPTION,
        category="other",
        auto_prompt=False,
        factory=lambda cookie, auth, uid="", run_id="": create_trigger_actions_tool(),
    ),
]


WEB_SEARCH_TOOL = ToolMeta(
    name="web_search",
    description=WEB_SEARCH_DESCRIPTION,
    category="other",
    auto_prompt=True,
    factory=lambda cookie, auth, uid="", run_id="": create_web_search_tool(run_id),
)


def create_all_tools(erp_cookie: str, erp_auth: str, user_id: str = "", run_id: str = "", enable_web_search: bool = False) -> list:
    """创建工具实例列表。enable_web_search=True 时追加联网搜索工具"""
    tools = [meta.factory(erp_cookie, erp_auth, user_id, run_id) for meta in TOOL_REGISTRY]
    if enable_web_search:
        tools.append(WEB_SEARCH_TOOL.factory(erp_cookie, erp_auth, user_id, run_id))
    return tools


def get_auto_prompt_descriptions() -> str:
    """获取所有 auto_prompt=True 的工具描述，自动注入 System Prompt 能力说明"""
    return "\n".join(
        f"- {meta.description}"
        for meta in TOOL_REGISTRY
        if meta.auto_prompt
    )
