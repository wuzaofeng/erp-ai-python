"""
QueryAgent - 专注 ERP 数据查询
Phase 3
"""
from __future__ import annotations

import os
from typing import AsyncGenerator, Optional

from langchain_core.messages import SystemMessage, HumanMessage

from agents.base import BaseAgent, AgentConfig

_QUERY_CONFIG = AgentConfig(
    name="QueryAgent",
    role="ERP 数据查询专家",
    responsibilities=[
        "根据用户需求精准查询 ERP 数据",
        "选择正确的数据表和过滤条件",
        "将查询结果以结构化方式返回",
    ],
    constraints=[
        "只查询，不分析，不做推理",
        "不捏造数据，所有数据来自 ERP 工具返回",
        "字段名必须使用 ERP 系统真实字段名",
    ],
    max_rounds=3,
)


class QueryAgent(BaseAgent):
    """ERP 数据查询 Agent，复用现有 ai_service.chat_with_ai"""

    def __init__(self, api_key: str, erp_config: dict):
        super().__init__(_QUERY_CONFIG, api_key)
        self.erp_config = erp_config  # {cookie, authorization, user_id}

    async def execute(
        self,
        message: str,
        context: Optional[str] = None,
        full_request: Optional[dict] = None,
    ) -> AsyncGenerator[str, None]:
        """full_request 优先，兼容直接传 message 的调用方"""
        from ai_service import chat_with_ai
        request = full_request or {
            "message": message,
            "pageContext": self.erp_config.get("pageContext"),
            "model": os.getenv("DEFAULT_MODEL", "openai/gpt-4o-mini"),
            "skillKey": None,
            "skill": None,
            "navIndex": None,
        }
        async for chunk in chat_with_ai(
            request=request,
            openrouter_key=self.api_key,
            erp_cookie=self.erp_config.get("cookie", ""),
            erp_authorization=self.erp_config.get("authorization", ""),
            user_id=self.erp_config.get("user_id", ""),
        ):
            yield chunk
