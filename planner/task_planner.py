"""
任务规划层 - 将复杂请求拆分为有序子任务
Phase 2
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Literal, Optional

from langchain_openai import ChatOpenAI


# ===================== 数据模型 =====================

@dataclass
class SubTask:
    id: str
    type: Literal["query", "analysis", "write", "clarify"]
    description: str
    depends_on: list[str] = field(default_factory=list)
    params: dict = field(default_factory=dict)
    status: Literal["pending", "running", "done", "failed"] = "pending"


@dataclass
class ExecutionPlan:
    tasks: list[SubTask]
    estimated_rounds: int = 1
    strategy: str = ""

    def has_cycle(self) -> bool:
        """循环依赖检测（DFS）"""
        id_map = {t.id: t for t in self.tasks}
        visited: set[str] = set()
        in_stack: set[str] = set()

        def dfs(node_id: str) -> bool:
            visited.add(node_id)
            in_stack.add(node_id)
            for dep in id_map.get(node_id, SubTask(id=node_id, type="query", description="")).depends_on:
                if dep not in visited:
                    if dfs(dep):
                        return True
                elif dep in in_stack:
                    return True
            in_stack.discard(node_id)
            return False

        for task in self.tasks:
            if task.id not in visited:
                if dfs(task.id):
                    return True
        return False

    def ordered_tasks(self) -> list[SubTask]:
        """拓扑排序，按依赖顺序返回任务列表"""
        id_map = {t.id: t for t in self.tasks}
        done: set[str] = set()
        result: list[SubTask] = []

        def visit(task_id: str) -> None:
            if task_id in done:
                return
            t = id_map.get(task_id)
            if t:
                for dep in t.depends_on:
                    visit(dep)
                if task_id not in done:
                    done.add(task_id)
                    result.append(t)

        for t in self.tasks:
            visit(t.id)
        return result


# ===================== TaskPlanner =====================

class TaskPlanner:
    """将用户请求拆分为可执行的子任务序列"""

    _SYSTEM_PROMPT = (
        "你是 ERP 系统任务规划器。将用户请求拆分为有序的子任务列表。\n"
        "子任务类型：query（查询数据）、analysis（分析数据）、write（写操作）、clarify（需要追问）\n"
        "返回严格 JSON，不要任何其他文字：\n"
        '{"tasks":[{"id":"t1","type":"query","description":"...","depends_on":[],"params":{}}],'
        '"estimated_rounds":1,"strategy":"执行策略说明"}'
    )

    def __init__(self, api_key: str, use_llm: bool = True):
        self._api_key = api_key
        self._use_llm = use_llm
        self._llm: Optional[ChatOpenAI] = None

    def _get_llm(self) -> ChatOpenAI:
        if self._llm is None:
            self._llm = ChatOpenAI(
                api_key=self._api_key,
                model="openai/gpt-4o-mini",
                temperature=0,
                max_tokens=400,
                base_url="https://openrouter.ai/api/v1",
                default_headers={
                    "HTTP-Referer": os.getenv("OPENROUTER_REFERER", "http://localhost:8000"),
                    "X-Title": "ERP AI Planner",
                },
            )
        return self._llm

    async def create_plan(
        self,
        message: str,
        available_agents: Optional[list[str]] = None,
    ) -> ExecutionPlan:
        """创建执行计划；LLM 不可用时退化为单任务计划"""
        if self._use_llm and self._api_key:
            try:
                plan = await self._llm_plan(message, available_agents)
                if not plan.has_cycle():
                    return plan
            except Exception:
                pass

        return self._fallback_plan(message)

    async def _llm_plan(
        self,
        message: str,
        available_agents: Optional[list[str]],
    ) -> ExecutionPlan:
        agent_hint = f"\n可用处理器：{', '.join(available_agents)}" if available_agents else ""
        llm = self._get_llm()
        response = await llm.ainvoke([
            {"role": "system", "content": self._SYSTEM_PROMPT + agent_hint},
            {"role": "user", "content": message},
        ])
        content = response.content if hasattr(response, "content") else str(response)
        m = re.search(r"\{.*\}", content, re.DOTALL)
        if not m:
            raise ValueError("LLM 返回非 JSON")
        data = json.loads(m.group())
        tasks = [
            SubTask(
                id=t.get("id", f"t{i+1}"),
                type=t.get("type", "query"),
                description=t.get("description", ""),
                depends_on=t.get("depends_on", []),
                params=t.get("params", {}),
            )
            for i, t in enumerate(data.get("tasks", []))
        ]
        return ExecutionPlan(
            tasks=tasks,
            estimated_rounds=int(data.get("estimated_rounds", 1)),
            strategy=data.get("strategy", ""),
        )

    def _fallback_plan(self, message: str) -> ExecutionPlan:
        """无法调用 LLM 时的退化计划：单 query 任务"""
        return ExecutionPlan(
            tasks=[SubTask(id="t1", type="query", description=message)],
            estimated_rounds=1,
            strategy="单任务直接查询（规划器降级）",
        )
