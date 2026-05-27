"""
Agent 协调器 - 整合 IntentRouter + TaskPlanner + 多 Agent
Phase 3

向后兼容：confidence < 0.8 时退回单 Agent（ai_service.chat_with_ai）
"""
from __future__ import annotations

import json
import os
from typing import AsyncGenerator

from trace.agent_trace import AgentTraceService, trace_service
from router.intent_router import IntentRouter, RoutingResult
from planner.task_planner import TaskPlanner
from agents.query_agent import QueryAgent
from agents.analysis_agent import AnalysisAgent
from logger import logger

ORCHESTRATOR_CONFIDENCE_THRESHOLD = float(os.getenv("ORCHESTRATOR_CONFIDENCE", "0.8"))


class AgentOrchestrator:
    """
    多 Agent 协调器。

    路由策略（向后兼容）：
      simple                → 快速轻量回答
      complex + conf≥0.8   → MultiAgent（QueryAgent → AnalysisAgent）
      complex + conf<0.8   → 单 Agent（ai_service.chat_with_ai）
      write                → 单 Agent（含 human_in_loop 审批）
    """

    def __init__(self, api_key: str, erp_config: dict):
        self.api_key = api_key
        self.erp_config = erp_config
        self.trace: AgentTraceService = trace_service
        self.router = IntentRouter(api_key, use_llm=False)
        self.planner = TaskPlanner(api_key, use_llm=False)
        self.query_agent = QueryAgent(api_key, erp_config)
        self.analysis_agent = AnalysisAgent(api_key)

    async def execute(self, request: dict) -> AsyncGenerator[str, None]:
        user_id = self.erp_config.get("user_id", "")
        run_id = self.trace.start_trace(
            request["message"],
            conversation_id=request.get("conversation_id", ""),
        )

        try:
            # ---- 1. 意图路由 ----
            routing: RoutingResult = await self.router.route(request["message"])
            self.trace.log_route(run_id, routing.model_dump())
            logger.ai("Orchestrator", f"意图={routing.intent} | 置信度={routing.confidence:.0%}")

            # ---- 2. simple：直接轻量回答 ----
            if routing.intent == "simple":
                async for chunk in self._simple_answer(request["message"]):
                    yield chunk
                self.trace.end_trace(run_id, "completed", user_id=user_id)
                yield f"\x00TRACE_SUMMARY:{json.dumps(self.trace.get_summary(run_id, slim=True), ensure_ascii=False)}"
                return

            # ---- 3. complex + 高置信度：多 Agent ----
            if routing.intent == "complex" and routing.confidence >= ORCHESTRATOR_CONFIDENCE_THRESHOLD:
                plan = await self.planner.create_plan(
                    request["message"],
                    available_agents=["query", "analysis"],
                )
                self.trace.log_agent(run_id, "TaskPlanner", request["message"], {
                    "tasks": [t.id for t in plan.tasks],
                    "strategy": plan.strategy,
                })
                logger.ai("Orchestrator", f"TaskPlanner 生成 {len(plan.tasks)} 个子任务")

                query_result_chunks: list[str] = []
                async for chunk in self.query_agent.execute(
                    request["message"],
                    full_request=request,
                ):
                    query_result_chunks.append(chunk) if not chunk.startswith("\x00") else None
                    yield chunk

                context = "".join(query_result_chunks)
                if context.strip():
                    async for chunk in self.analysis_agent.execute(request["message"], context):
                        yield chunk

                self.trace.end_trace(run_id, "completed", user_id=user_id)
                yield f"\x00TRACE_SUMMARY:{json.dumps(self.trace.get_summary(run_id, slim=True), ensure_ascii=False)}"
                return

            # ---- 4. 其余情况：退回单 Agent（向后兼容）----
            logger.ai("Orchestrator", "置信度不足或 write 意图，退回单 Agent 流程")
            async for chunk in self._fallback_single_agent(request, run_id):
                yield chunk

        except Exception as exc:
            self.trace.end_trace(run_id, "failed", str(exc), user_id=user_id)
            logger.error("Orchestrator", f"执行失败: {exc}")
            yield f"\x00TRACE_SUMMARY:{json.dumps(self.trace.get_summary(run_id, slim=True), ensure_ascii=False)}"
            raise

    async def _simple_answer(self, message: str) -> AsyncGenerator[str, None]:
        from langchain_openai import ChatOpenAI
        from langchain_core.messages import SystemMessage, HumanMessage
        from memory.user_preference import get_user_model
        user_id = self.erp_config.get("user_id", "")
        model = get_user_model(user_id) or os.getenv("DEFAULT_MODEL", "openai/gpt-4o-mini")
        llm = ChatOpenAI(
            api_key=self.api_key,
            model=model,
            temperature=0.3,
            base_url="https://openrouter.ai/api/v1",
        )
        async for chunk in llm.astream([
            SystemMessage(content="你是 ERP 系统智能助手，请简洁友好地回答用户问题。"),
            HumanMessage(content=message),
        ]):
            text = chunk.content if isinstance(chunk.content, str) else ""
            if text:
                yield text

    async def _fallback_single_agent(
        self, request: dict, run_id: str
    ) -> AsyncGenerator[str, None]:
        from ai_service import chat_with_ai
        async for chunk in chat_with_ai(
            request=request,
            openrouter_key=self.api_key,
            erp_cookie=self.erp_config.get("cookie", ""),
            erp_authorization=self.erp_config.get("authorization", ""),
            user_id=self.erp_config.get("user_id", ""),
            _run_id=run_id,
        ):
            yield chunk
        # fallback 复用 orchestrator 的 run_id，TRACE_SUMMARY 由 chat_with_ai 内部 yield
