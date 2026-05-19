"""
AnalysisAgent - 专注对查询结果进行分析和总结
Phase 3
"""
from __future__ import annotations

import os
from typing import AsyncGenerator, Optional

from langchain_core.messages import SystemMessage, HumanMessage

from agents.base import BaseAgent, AgentConfig

_ANALYSIS_CONFIG = AgentConfig(
    name="AnalysisAgent",
    role="ERP 数据分析专家",
    responsibilities=[
        "对 QueryAgent 返回的数据进行深度分析",
        "识别数据中的趋势、异常和关键信息",
        "用清晰简洁的语言给出业务洞察",
    ],
    constraints=[
        "只分析，不查询，不调用 ERP 工具",
        "结论必须基于传入的真实数据，不得推测或捏造",
        "不输出 Markdown 表格，前端已有原生表格",
    ],
    max_rounds=1,
)


class AnalysisAgent(BaseAgent):
    """ERP 数据分析 Agent"""

    def __init__(self, api_key: str):
        super().__init__(_ANALYSIS_CONFIG, api_key)

    async def execute(
        self,
        message: str,
        context: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        system_prompt = self.build_system_prompt()
        if context:
            system_prompt += f"\n\n# 查询结果上下文\n{context}"

        llm = self.get_llm(temperature=0.2)
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=f"请对以下查询结果进行分析并给出业务洞察：\n\n用户问题：{message}"),
        ]

        async for chunk in llm.astream(messages):
            text = chunk.content if isinstance(chunk.content, str) else ""
            if text:
                yield text
