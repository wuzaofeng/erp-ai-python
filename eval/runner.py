"""
评测执行引擎
- Mock ERP 工具返回（不依赖真实 ERP 环境）
- 捕获 LangChain 工具调用参数
- 支持多轮对话
"""
from __future__ import annotations

import json
import os
import asyncio
from typing import Optional
from unittest.mock import AsyncMock, patch

from langchain_core.messages import HumanMessage, AIMessage, ToolMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langchain_core.tools import StructuredTool

from eval.types import EvalCase, RunResult, ToolCall
from router.intent_router import IntentRouter
from logger import logger

# ---- Mock ERP 数据 ----

_DEFAULT_MOCK_ROWS = [
    {"fEmpCode": "EMP_A001", "fEmpName": "李明", "fDeptName": "研发部", "fStatus": "在职"},
    {"fEmpCode": "EMP_A002", "fEmpName": "张伟", "fDeptName": "财务部", "fStatus": "在职"},
    {"fEmpCode": "EMP_A003", "fEmpName": "吴芳", "fDeptName": "研发部", "fStatus": "在职"},
]

_DEFAULT_MOCK_RESULT = {
    "total": 3, "pageIndex": 1, "pageSize": 20,
    "rows": _DEFAULT_MOCK_ROWS,
}

_DEFAULT_FIELDS_RESULT = {
    "fields": [
        {"name": "fEmpCode", "label": "员工编码", "type": "string"},
        {"name": "fEmpName", "label": "员工姓名", "type": "string"},
        {"name": "fDeptName", "label": "部门", "type": "string"},
        {"name": "fStatus", "label": "状态", "type": "string"},
    ]
}


class EvalRunner:
    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model

    def _make_mock_tool(self, tool_name: str, captured: list[ToolCall], mock_result: dict, turn_index: int) -> StructuredTool:
        """创建捕获参数的 Mock 工具"""
        result_str = "⚠️ 以下是 ERP 系统返回的【真实数据】：\n" + json.dumps(mock_result, ensure_ascii=False)

        async def handler(**kwargs) -> str:
            captured.append(ToolCall(
                tool_name=tool_name,
                args=kwargs,
                result=mock_result,
                turn_index=turn_index,
            ))
            return result_str

        return StructuredTool.from_function(
            coroutine=handler,
            name=tool_name,
            description=f"Mock {tool_name}",
        )

    async def run_case(self, case: EvalCase) -> RunResult:
        result = RunResult(case_id=case.id, model=self.model)

        # 检查意图
        if case.check_intent:
            router = IntentRouter(self.api_key, use_llm=True)
            last_user_msg = next(
                (t["content"] for t in reversed(case.turns) if t["role"] == "user"), ""
            )
            try:
                routing = await router.route(last_user_msg)
                result.intent = routing.intent
            except Exception as e:
                result.intent = "unknown"
                logger.warn("EvalRunner", f"意图路由失败: {e}")

        try:
            if case.multi_turn:
                await self._run_multi_turn(case, result)
            else:
                await self._run_single_turn(case, result)
        except Exception as e:
            result.error = str(e)
            logger.error("EvalRunner", f"用例 {case.id} 执行失败: {e}")

        return result

    async def _run_single_turn(self, case: EvalCase, result: RunResult):
        user_msg = next(t["content"] for t in case.turns if t["role"] == "user")
        mock_data = (case.mock_tool_result or {}).get("query_erp_list", _DEFAULT_MOCK_RESULT)
        fields_data = (case.mock_tool_result or {}).get("get_table_fields", _DEFAULT_FIELDS_RESULT)

        captured: list[ToolCall] = []
        tools = [
            self._make_mock_tool("query_erp_list", captured, mock_data, turn_index=0),
            self._make_mock_tool("get_table_fields", captured, fields_data, turn_index=0),
            self._make_mock_tool("search_erp_global", captured, _DEFAULT_MOCK_RESULT, turn_index=0),
        ]

        answer = await self._invoke_agent(user_msg, [], tools)
        result.answer = answer
        result.tool_calls = captured

    async def _run_multi_turn(self, case: EvalCase, result: RunResult):
        """
        多轮测试：逐轮执行，第1轮获取真实回答后替换 __mock__ 占位符
        只验证最后一轮的工具调用
        """
        history: list[dict] = []
        captured: list[ToolCall] = []

        user_turns = [t for t in case.turns if t["role"] == "user"]
        mock_data = (case.mock_tool_result or {}).get("query_erp_list", _DEFAULT_MOCK_RESULT)
        fields_data = (case.mock_tool_result or {}).get("get_table_fields", _DEFAULT_FIELDS_RESULT)

        for turn_idx, user_turn_content in enumerate(t["content"] for t in case.turns if t["role"] == "user"):
            tools = [
                self._make_mock_tool("query_erp_list", captured, mock_data, turn_index=turn_idx),
                self._make_mock_tool("get_table_fields", captured, fields_data, turn_index=turn_idx),
                self._make_mock_tool("search_erp_global", captured, _DEFAULT_MOCK_RESULT, turn_index=turn_idx),
            ]
            answer = await self._invoke_agent(user_turn_content, history, tools)
            history.append({"role": "user", "content": user_turn_content})
            history.append({"role": "assistant", "content": answer})

        result.answer = answer  # noqa: F821 — 最后一轮的回答
        result.tool_calls = captured

    async def _invoke_agent(self, user_message: str, history: list[dict], tools) -> str:
        from config.prompt_config import build_system_prompt
        system_prompt = build_system_prompt(page_context="评测环境")

        llm = ChatOpenAI(
            api_key=self.api_key,
            model=self.model,
            temperature=0,
            max_tokens=1024,
            base_url="https://openrouter.ai/api/v1",
            default_headers={
                "HTTP-Referer": os.getenv("OPENROUTER_REFERER", "http://localhost:8000"),
                "X-Title": "ERP AI Eval",
            },
        )
        llm_with_tools = llm.bind_tools(tools)

        messages = [SystemMessage(content=system_prompt)]
        for h in history:
            if h["role"] == "user":
                messages.append(HumanMessage(content=h["content"]))
            elif h["role"] == "assistant":
                messages.append(AIMessage(content=h["content"]))
        messages.append(HumanMessage(content=user_message))

        max_rounds = int(os.getenv("MAX_TOOL_ROUNDS", "5"))
        final_answer = ""

        for _ in range(max_rounds):
            response = await llm_with_tools.ainvoke(messages)
            messages.append(response)

            if not response.tool_calls:
                final_answer = response.content if isinstance(response.content, str) else ""
                break

            # 执行工具调用
            for tc in response.tool_calls:
                tool_map = {t.name: t for t in tools}
                tool = tool_map.get(tc["name"])
                if tool:
                    tool_result = await tool.arun(tc["args"])
                else:
                    tool_result = json.dumps({"error": f"未知工具 {tc['name']}"})
                messages.append(ToolMessage(content=tool_result, tool_call_id=tc["id"]))

        return final_answer
