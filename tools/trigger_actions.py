"""
前端操作触发工具 - AI 调用此工具向前端推送可执行的操作指令
"""
import json
from typing import Optional, Any
from pydantic import BaseModel, Field
from langchain_core.tools import StructuredTool


class ActionItem(BaseModel):
    action: str = Field(
        description=(
            "操作类型："
            "refresh=刷新当前表格；"
            "filter=在当前页面带条件重新查询；"
            "navigate=仅跳转到目标页面（不带查询）；"
            "navigate_query=跳转到目标页面并自动执行带条件查询（跨页跳转+查询场景使用此类型）"
        )
    )
    label: str = Field(description="按钮显示文字，如「刷新数据」「查看供应商」「新增采购订单」")
    auto: bool = Field(
        default=False,
        description="是否自动触发。refresh/navigate_query 可设为 true，navigate 应设为 false 让用户确认"
    )
    params: Optional[dict[str, Any]] = Field(
        default=None,
        description=(
            "操作参数。"
            "filter: {filters:[{FieldName,Operator,Value}]}；"
            "navigate: {path:'/erp/...'}；"
            "navigate_query: {formCode:'fFunCode值', operation:'view'或'add', filters:[{FieldName,Operator,Value}]}；"
            "filters 中的 FieldName 必须使用 query_erp_list 查询结果中实际存在的字段名，禁止猜测或自造字段名"
        )
    )

class TriggerActionsInput(BaseModel):
    actions: list[ActionItem] = Field(description="要推送给前端的操作列表，至少1个")


TRIGGER_ACTIONS_DESCRIPTION = (
    "触发前端操作指令（刷新表格、带条件查询、跳转页面）。\n"
    "使用场景：\n"
    "- 用户说「刷新一下」→ action=refresh, auto=true\n"
    "- 用户说「只看未完成的」→ action=filter, params.filters=[...], auto=true\n"
    "- 查询到业务数据后，菜单中存在对应页面 → 必须额外调用本工具推送 navigate_query，"
    "auto=true，让前端自动打开该页面并带相同过滤条件，与文字摘要同时进行\n"
    "- 用户说「去供应商页面查华为」→ action=navigate_query, params.formCode=对应fFunCode, "
    "params.operation=view, params.filters=[{FieldName,Operator,Value}], auto=true\n"
    "- 用户说「新增一个供应商」→ action=navigate_query, params.formCode=对应fFunCode, "
    "params.operation=add, auto=false（新增需用户确认）\n"
    "fFunCode 从系统提示的【可跳转的 ERP 菜单】中查找对应页面名称获取。\n"
    "filters 中的 FieldName 必须使用 query_erp_list 返回结果中实际存在的字段名，禁止猜测或自造不存在的字段名。\n"
    "所有 action 都会渲染为可点击按钮，auto=true 的会立即自动执行。"
)


def create_trigger_actions_tool(**_kwargs) -> StructuredTool:
    def trigger_actions(actions: list[dict]) -> str:
        serializable = [
            a.model_dump() if hasattr(a, "model_dump") else dict(a)
            for a in actions
        ]
        payload = json.dumps({"actions": serializable}, ensure_ascii=False)
        return f"\x00ACTION_DATA:{payload}"

    return StructuredTool.from_function(
        func=trigger_actions,
        name="trigger_actions",
        description=TRIGGER_ACTIONS_DESCRIPTION,
        args_schema=TriggerActionsInput,
    )
