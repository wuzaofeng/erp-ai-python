"""
评测基础类型定义
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class CheckResult:
    name: str
    fn: Callable[["RunResult"], bool]
    description: str = ""


@dataclass
class EvalCase:
    id: str
    dimension: str
    name: str
    turns: list[dict]                        # 对话轮次，role=user/assistant
    checks: list[CheckResult]
    multi_turn: bool = False                 # 是否多轮测试（需逐轮执行）
    check_intent: bool = False              # 是否同时检查意图路由结果
    mock_tool_result: Optional[dict] = None # 工具返回的 mock 数据，key=tool_name


@dataclass
class ToolCall:
    tool_name: str
    args: dict
    result: Any = None
    turn_index: int = 0  # 在第几轮执行的


@dataclass
class RunResult:
    case_id: str
    model: str
    answer: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    intent: Optional[str] = None
    error: Optional[str] = None

    # ---- 断言辅助方法 ----

    def tool_called(self, tool_name: str) -> bool:
        return any(tc.tool_name == tool_name for tc in self.tool_calls)

    def tool_called_in_turn(self, tool_name: str, turn: int) -> bool:
        """turn=0 第1次用户输入对应的工具调用，turn=1 第2次，以此类推"""
        return any(
            tc.tool_name == tool_name and tc.turn_index == turn
            for tc in self.tool_calls
        )

    def _get_tool_args(self, tool_name: str) -> Optional[dict]:
        for tc in reversed(self.tool_calls):
            if tc.tool_name == tool_name:
                return tc.args
        return None

    def tool_arg_contains(self, tool_name: str, arg_key: str, values: list[str] | str) -> bool:
        args = self._get_tool_args(tool_name)
        if not args:
            return False
        val = str(args.get(arg_key, "")).lower()
        if isinstance(values, str):
            values = [values]
        return any(v.lower() in val for v in values)

    def tool_arg_gt(self, tool_name: str, arg_key: str, threshold: int) -> bool:
        args = self._get_tool_args(tool_name)
        if not args:
            return False
        try:
            return int(args.get(arg_key, 0)) > threshold
        except (TypeError, ValueError):
            return False

    def _get_filters(self, tool_name: str) -> list[dict]:
        args = self._get_tool_args(tool_name)
        if not args:
            return []
        filters = args.get("filters") or []
        if isinstance(filters, list):
            return [f if isinstance(f, dict) else {} for f in filters]
        return []

    def tool_filter_operator_valid(self, tool_name: str) -> bool:
        valid = {
            "Equal", "NotEqual", "GreaterThan", "GreaterThanOrEqual",
            "LessThan", "LessThanOrEqual", "Like", "NotLike",
            "StartWith", "EndWith", "IsNull", "IsNotNull", "InList", "NotInList",
        }
        filters = self._get_filters(tool_name)
        return all(f.get("Operator") in valid for f in filters if f.get("Operator"))

    def tool_filter_has_operator(self, tool_name: str, operator: str) -> bool:
        return any(f.get("Operator") == operator for f in self._get_filters(tool_name))

    def tool_filter_value_contains(self, tool_name: str, values: list[str] | str) -> bool:
        if isinstance(values, str):
            values = [values]
        filters = self._get_filters(tool_name)
        all_values = " ".join(str(f.get("Value", "")) for f in filters)
        return any(v in all_values for v in values)

    def tool_filter_count_gte(self, tool_name: str, n: int) -> bool:
        return len(self._get_filters(tool_name)) >= n

    def tool_filter_logic_at(self, tool_name: str, index: int, logic: str) -> bool:
        filters = self._get_filters(tool_name)
        if index >= len(filters):
            return False
        return filters[index].get("Logic", "").lower() == logic.lower()

    def tool_filter_last_no_logic(self, tool_name: str) -> bool:
        filters = self._get_filters(tool_name)
        if not filters:
            return True
        last = filters[-1]
        logic = last.get("Logic")
        return logic is None or logic == "" or logic == "and"  # 最后一条 Logic 无实际意义，允许留空或 and

    def tool_filter_has_paren(self, tool_name: str, paren_key: str) -> bool:
        """paren_key: 'LeftParen' 或 'RightParen'"""
        return any(f.get(paren_key, "") == "(" or f.get(paren_key, "") == ")"
                   for f in self._get_filters(tool_name))

    def intent_is(self, expected: str) -> bool:
        return (self.intent or "").lower() == expected.lower()

    def answer_contains(self, text: str) -> bool:
        return text in self.answer

    def answer_contains_any(self, texts: list[str]) -> bool:
        return any(t in self.answer for t in texts)

    def answer_matches_pattern(self, pattern: str) -> bool:
        return bool(re.search(pattern, self.answer))

    def answer_contains_markdown_table(self) -> bool:
        lines = self.answer.split("\n")
        table_lines = [l for l in lines if "|" in l and l.strip().startswith("|")]
        return len(table_lines) >= 2

    def answer_min_length(self, n: int) -> bool:
        return len(self.answer.strip()) >= n


@dataclass
class CaseResult:
    case: EvalCase
    model: str
    run: RunResult
    scores: list[tuple[str, bool, str]]  # (check_name, passed, description)

    @property
    def passed(self) -> int:
        return sum(1 for _, ok, _ in self.scores if ok)

    @property
    def total(self) -> int:
        return len(self.scores)

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total if self.total else 0.0
