"""
前端操作触发工具 - AI 调用此工具向前端推送可执行的操作指令
"""
import json
from typing import Optional, Any
from pydantic import BaseModel, Field
from langchain_core.tools import StructuredTool


class ActionItem(BaseModel):
    action: str = Field(description="操作类型：refresh=刷新表格, filter=带条件查询, navigate=跳转页面")
    label: str = Field(description="按钮显示文字，如「刷新数据」「只看未完成」")
    auto: bool = Field(default=False, description="是否自动触发，refresh 可设为 true，navigate 应设为 false")
    params: Optional[dict[str, Any]] = Field(default=None, description="操作参数，filter 需传 filters 数组，navigate 需传 path")


class TriggerActionsInput(BaseModel):
    actions: list[ActionItem] = Field(description="要推送给前端的操作列表，至少1个")


TRIGGER_ACTIONS_DESCRIPTION = (
    "触发前端操作指令（如刷新表格、带条件重新查询、跳转页面）。"
    "当用户说「刷新一下」「只看未完成的」「去采购订单页面」等操作性请求时调用此工具。"
    "工具会将操作列表推送给前端，auto=true 的操作自动执行，所有操作都会渲染为可点击按钮。"
)


def create_trigger_actions_tool(**_kwargs) -> StructuredTool:
    def trigger_actions(actions: list[dict]) -> str:
        payload = json.dumps({"actions": actions}, ensure_ascii=False)
        return f"\x00ACTION_DATA:{payload}"

    return StructuredTool.from_function(
        func=trigger_actions,
        name="trigger_actions",
        description=TRIGGER_ACTIONS_DESCRIPTION,
        args_schema=TriggerActionsInput,
    )
