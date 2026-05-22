"""
元认知层 - 查询失败后的自动反思与参数调整
Phase 0.8
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class QueryAdjustment:
    adjustment_type: str   # amount_unit | date_format | field_name
    field: Optional[str] = None
    original: Any = None
    adjusted: Any = None
    confidence: float = 0.0


@dataclass
class ReflectionResult:
    success: bool
    reason: Optional[str] = None
    adjustment: Optional[QueryAdjustment] = None
    confidence: float = 0.0


# ===================== 反思规则基类 =====================

class ReflectionRule:
    name: str = ""
    confidence: float = 0.0

    def can_handle(self, query: dict, result: dict, table_meta: dict) -> bool:
        raise NotImplementedError

    async def apply(self, query: dict, result: dict, table_meta: dict) -> QueryAdjustment:
        raise NotImplementedError


# ===================== 具体规则 =====================

class AmountUnitRule(ReflectionRule):
    """金额单位检查：用户输入元，数据库存分"""
    name = "金额单位检查"
    confidence = 0.9

    def can_handle(self, query: dict, result: dict, table_meta: dict) -> bool:
        has_no_rows = not result.get("rows")
        has_amount_filter = any(
            "amount" in str(f.get("field", "")).lower()
            for f in (query.get("filters") or [])
        )
        return has_no_rows and has_amount_filter

    async def apply(self, query: dict, result: dict, table_meta: dict) -> QueryAdjustment:
        for field_meta in table_meta.get("fields", []):
            if "amount" in field_meta.get("name", "").lower() and field_meta.get("unit") == "fen":
                for f in (query.get("filters") or []):
                    if "amount" in str(f.get("field", "")).lower():
                        original = f.get("value")
                        return QueryAdjustment(
                            adjustment_type="amount_unit",
                            field=field_meta["name"],
                            original=original,
                            adjusted=int(float(original) * 100) if original is not None else None,
                            confidence=self.confidence,
                        )
        raise ValueError("非金额单位问题")


class DateFormatRule(ReflectionRule):
    """日期格式检查：自动识别并统一格式为 YYYY-MM-DD"""
    name = "日期格式检查"
    confidence = 0.85

    _DATE_PATTERNS = [
        (r"(\d{4})[/.](\d{1,2})[/.](\d{1,2})", "{}-{:02d}-{:02d}"),  # 2024/01/01
        (r"(\d{1,2})[/.](\d{1,2})[/.](\d{4})", "{3}-{1:02d}-{2:02d}"),  # 01/01/2024
    ]

    def can_handle(self, query: dict, result: dict, table_meta: dict) -> bool:
        has_no_rows = not result.get("rows")
        has_date_filter = any(
            "date" in str(f.get("field", "")).lower() or "time" in str(f.get("field", "")).lower()
            for f in (query.get("filters") or [])
        )
        return has_no_rows and has_date_filter

    async def apply(self, query: dict, result: dict, table_meta: dict) -> QueryAdjustment:
        for f in (query.get("filters") or []):
            field_name = str(f.get("field", ""))
            if "date" not in field_name.lower() and "time" not in field_name.lower():
                continue
            value = str(f.get("value", ""))
            for pattern, fmt in self._DATE_PATTERNS:
                m = re.match(pattern, value)
                if m:
                    groups = [int(g) for g in m.groups()]
                    try:
                        adjusted = fmt.format(*groups)
                    except (IndexError, KeyError):
                        continue
                    if adjusted != value:
                        return QueryAdjustment(
                            adjustment_type="date_format",
                            field=field_name,
                            original=value,
                            adjusted=adjusted,
                            confidence=self.confidence,
                        )
        raise ValueError("非日期格式问题")


# ===================== 元认知服务 =====================

class MetaCognition:
    """查询失败后的反思服务：先走规则，再走 LLM"""

    def __init__(self, llm=None):
        self.llm = llm
        self.rules: list[ReflectionRule] = [
            AmountUnitRule(),
            DateFormatRule(),
        ]

    async def reflect_on_failure(
        self,
        query: dict,
        result: dict,
        table_meta: dict,
    ) -> ReflectionResult:
        for rule in self.rules:
            try:
                if rule.can_handle(query, result, table_meta):
                    adjustment = await rule.apply(query, result, table_meta)
                    return ReflectionResult(
                        success=True,
                        adjustment=adjustment,
                        confidence=rule.confidence,
                    )
            except (ValueError, TypeError, AttributeError):
                continue

        if self.llm:
            return await self._llm_reflection(query, result, table_meta)

        return ReflectionResult(success=False, reason="无匹配规则，且未启用 LLM 反思")

    async def _llm_reflection(
        self,
        query: dict,
        result: dict,
        table_meta: dict,
    ) -> ReflectionResult:
        prompt = (
            "场景：ERP 订单查询返回空结果。\n"
            f"原始查询: {json.dumps(query, ensure_ascii=False)}\n"
            f"查询结果: {json.dumps(result, ensure_ascii=False)}\n"
            f"表结构摘要: {json.dumps(table_meta, ensure_ascii=False)}\n\n"
            '请分析失败原因并给出参数调整建议。\n'
            '返回严格 JSON，格式：{"reason":"...","adjustment":{"adjustment_type":"...","field":"...","original":null,"adjusted":null},"confidence":0.0}'
        )
        try:
            response = await self.llm.ainvoke([{"role": "user", "content": prompt}])
            content = response.content if hasattr(response, "content") else str(response)
            data = json.loads(content)
            adj_data = data.get("adjustment") or {}
            adjustment = QueryAdjustment(**adj_data) if adj_data else None
            return ReflectionResult(
                success=True,
                reason=data.get("reason"),
                adjustment=adjustment,
                confidence=float(data.get("confidence", 0.5)),
            )
        except Exception as exc:
            return ReflectionResult(success=False, reason=f"LLM 反思解析失败: {exc}")


meta_cognition = MetaCognition()
