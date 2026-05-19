"""
BaseAgent 抽象基类
Phase 3
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import AsyncGenerator, Optional

from langchain_openai import ChatOpenAI
from pydantic import BaseModel


class AgentConfig(BaseModel):
    name: str
    role: str
    responsibilities: list[str]
    constraints: list[str]
    tools: list[str] = []
    max_rounds: int = 3


class BaseAgent(ABC):
    def __init__(self, config: AgentConfig, api_key: str):
        self.config = config
        self.api_key = api_key
        self._llm: Optional[ChatOpenAI] = None

    def get_llm(self, model: str = "openai/gpt-4o-mini", temperature: float = 0.1) -> ChatOpenAI:
        if self._llm is None:
            self._llm = ChatOpenAI(
                api_key=self.api_key,
                model=model,
                temperature=temperature,
                base_url="https://openrouter.ai/api/v1",
                default_headers={
                    "HTTP-Referer": os.getenv("OPENROUTER_REFERER", "http://localhost:8000"),
                    "X-Title": f"ERP AI {self.config.name}",
                },
            )
        return self._llm

    @abstractmethod
    async def execute(
        self,
        message: str,
        context: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """执行 Agent，返回流式输出"""
        ...

    def build_system_prompt(self) -> str:
        parts = [
            f"# 角色：{self.config.role}",
            "\n## 职责：",
            *[f"- {r}" for r in self.config.responsibilities],
            "\n## 约束：",
            *[f"- {c}" for c in self.config.constraints],
        ]
        return "\n".join(parts)
