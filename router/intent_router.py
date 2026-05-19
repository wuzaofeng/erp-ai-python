"""
意图路由层 - 判断用户请求类型并分流
Phase 1

意图类型：
  simple  - 问候/闲聊/无需查数据
  complex - 需要查询 ERP 数据或分析
  write   - 需要写操作（新增/修改/删除）
"""
from __future__ import annotations

import json
import os
import re
from typing import Literal, Optional

from langchain_openai import ChatOpenAI
from pydantic import BaseModel

# ---- 关键词快速分类（不消耗 LLM token）----

_SIMPLE_KEYWORDS = [
    "你好", "hi", "hello", "帮助", "help", "谢谢", "感谢", "再见", "bye",
    "你是谁", "你能干什么", "有什么功能", "介绍一下",
]

_WRITE_KEYWORDS = [
    "新增", "添加", "创建", "修改", "更新", "编辑", "删除", "移除",
    "审批", "提交", "保存", "录入", "导入",
    "add", "create", "insert", "update", "edit", "delete", "remove", "import",
]

_COMPLEX_KEYWORDS = [
    "查询", "查找", "搜索", "列出", "显示", "统计", "汇总", "分析",
    "订单", "采购", "销售", "库存", "客户", "供应商", "财务", "发票",
    "报表", "数据", "记录", "明细", "汇总",
]


def _keyword_route(message: str) -> Optional[Literal["simple", "complex", "write"]]:
    msg_lower = message.lower()
    if any(kw in msg_lower for kw in _WRITE_KEYWORDS):
        return "write"
    if any(kw in msg_lower for kw in _SIMPLE_KEYWORDS):
        return "simple"
    if any(kw in msg_lower for kw in _COMPLEX_KEYWORDS):
        return "complex"
    return None


# ===================== 数据模型 =====================

class RoutingResult(BaseModel):
    intent: Literal["simple", "complex", "write"]
    confidence: float
    suggested_agent: Optional[str] = None
    reasoning: str
    params: Optional[dict] = None


# ===================== IntentRouter =====================

class IntentRouter:
    """意图路由器：先关键词快速判断，再 LLM 精判（可选）"""

    _SYSTEM_PROMPT = (
        "你是 ERP 系统意图分类器。"
        "根据用户消息判断意图类型，只返回 JSON，不要任何额外文字。\n"
        "意图类型：\n"
        "  simple  - 问候、闲聊、功能询问、无需 ERP 数据的问题\n"
        "  complex - 需要查询 ERP 数据、统计分析、报表的请求\n"
        "  write   - 需要新增、修改、删除 ERP 记录的请求\n"
        '返回格式：{"intent":"类型","confidence":0.0-1.0,"reasoning":"判断理由"}'
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
                max_tokens=120,
                base_url="https://openrouter.ai/api/v1",
                default_headers={
                    "HTTP-Referer": os.getenv("OPENROUTER_REFERER", "http://localhost:8000"),
                    "X-Title": "ERP AI Router",
                },
            )
        return self._llm

    async def route(
        self,
        message: str,
        history: Optional[list] = None,
    ) -> RoutingResult:
        # 1. 关键词快速判断（零成本）
        quick = _keyword_route(message)
        if quick and quick in ("write",):
            return RoutingResult(
                intent=quick,
                confidence=0.95,
                reasoning=f"关键词快速分类：{quick}",
            )

        # 2. LLM 精判
        if self._use_llm and self._api_key:
            try:
                result = await self._llm_route(message)
                if result.confidence >= 0.6:
                    return result
            except Exception:
                pass  # 降级到关键词结果

        # 3. 兜底：关键词或 complex
        intent = quick or "complex"
        return RoutingResult(
            intent=intent,
            confidence=0.7,
            reasoning="关键词规则兜底分类",
        )

    async def _llm_route(self, message: str) -> RoutingResult:
        llm = self._get_llm()
        response = await llm.ainvoke([
            {"role": "system", "content": self._SYSTEM_PROMPT},
            {"role": "user", "content": message},
        ])
        content = response.content if hasattr(response, "content") else str(response)

        # 提取 JSON（防止模型多余输出）
        m = re.search(r"\{.*\}", content, re.DOTALL)
        if not m:
            raise ValueError("LLM 返回非 JSON")
        data = json.loads(m.group())
        intent = data.get("intent", "complex")
        if intent not in ("simple", "complex", "write"):
            intent = "complex"
        return RoutingResult(
            intent=intent,
            confidence=float(data.get("confidence", 0.7)),
            reasoning=data.get("reasoning", ""),
        )
