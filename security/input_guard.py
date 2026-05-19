import re
from dataclasses import dataclass, field
from typing import Literal


INJECTION_PATTERNS = [
    r"ignore\s+(previous|all|above)\s+instructions?",
    r"disregard\s+.{0,20}instructions?",
    r"you\s+are\s+now\s+",
    r"forget\s+.{0,20}instructions?",
    r"system\s+prompt",
    r"ignore\s+.{0,10}rules?",
    r"忽略(之前|上面|所有)?(的)?指令",
    r"你现在是",
    r"系统提示",
    r"扮演.{0,10}(角色|助手|AI)",
    r"越(狱|权)",
]

_COMPILED = [re.compile(p, re.IGNORECASE) for p in INJECTION_PATTERNS]

MAX_INPUT_LENGTH = 10000


@dataclass
class GuardResult:
    safe: bool
    risk_level: Literal["low", "medium", "high"]
    detected_threats: list[str] = field(default_factory=list)
    sanitized_input: str = ""


class InputGuard:
    def check(self, text: str) -> GuardResult:
        threats: list[str] = []

        for pattern, compiled in zip(INJECTION_PATTERNS, _COMPILED):
            if compiled.search(text):
                threats.append(f"injection: {pattern[:40]}")

        if len(text) > MAX_INPUT_LENGTH:
            threats.append(f"input_too_long: {len(text)} chars")

        if threats:
            has_injection = any(t.startswith("injection") for t in threats)
            risk_level: Literal["low", "medium", "high"] = "high" if has_injection else "medium"
        else:
            risk_level = "low"

        return GuardResult(
            safe=len(threats) == 0,
            risk_level=risk_level,
            detected_threats=threats,
            sanitized_input=text.strip()[:MAX_INPUT_LENGTH],
        )

    def validate(self, text: str) -> None:
        result = self.check(text)
        if result.risk_level == "high":
            raise ValueError(f"输入安全检查未通过: {', '.join(result.detected_threats)}")


input_guard = InputGuard()
