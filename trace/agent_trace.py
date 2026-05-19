from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional
from enum import Enum
import uuid


class StepType(str, Enum):
    ROUTE = "route"
    AGENT = "agent"
    TOOL = "tool"
    ANALYSIS = "analysis"
    RETRY = "retry"
    REFLECTION = "reflection"
    COMPLETE = "complete"


@dataclass
class TraceStep:
    step_id: int
    timestamp: str
    type: StepType
    name: str
    input_data: Optional[Any] = None
    output_data: Optional[Any] = None
    metadata: dict = field(default_factory=dict)
    confidence: Optional[float] = None
    error: Optional[str] = None


@dataclass
class AgentRunTrace:
    run_id: str
    user_message: str
    intent: str
    start_time: str
    end_time: Optional[str] = None
    steps: list[TraceStep] = field(default_factory=list)
    total_tokens: int = 0
    status: str = "running"  # running, completed, failed

    def add_step(self, step_type: StepType, name: str, **kwargs) -> None:
        self.steps.append(TraceStep(
            step_id=len(self.steps) + 1,
            timestamp=datetime.now().isoformat(),
            type=step_type,
            name=name,
            **kwargs,
        ))


class AgentTraceService:
    def __init__(self):
        self._traces: dict[str, AgentRunTrace] = {}

    def start_trace(self, user_message: str, intent: str = "pending") -> str:
        run_id = f"run_{uuid.uuid4().hex[:12]}"
        self._traces[run_id] = AgentRunTrace(
            run_id=run_id,
            user_message=user_message,
            intent=intent,
            start_time=datetime.now().isoformat(),
        )
        return run_id

    def log_tool(self, run_id: str, tool_name: str, params: dict, result: Any) -> None:
        trace = self._traces.get(run_id)
        if not trace:
            return
        row_count = len(result) if isinstance(result, list) else 0
        trace.add_step(
            StepType.TOOL,
            tool_name,
            input_data=params,
            output_data=result if row_count == 0 else f"[{row_count} rows]",
            metadata={"row_count": row_count},
        )

    def log_retry(self, run_id: str, reason: str, attempt: int) -> None:
        trace = self._traces.get(run_id)
        if not trace:
            return
        trace.add_step(StepType.RETRY, f"Retry #{attempt}", input_data=reason)

    def log_reflection(self, run_id: str, reason: str, adjustment: dict) -> None:
        trace = self._traces.get(run_id)
        if not trace:
            return
        trace.add_step(
            StepType.REFLECTION,
            "MetaCognition",
            input_data={"reason": reason},
            output_data=adjustment,
        )

    def end_trace(self, run_id: str, status: str = "completed", error: Optional[str] = None) -> None:
        trace = self._traces.get(run_id)
        if not trace:
            return
        trace.end_time = datetime.now().isoformat()
        trace.status = status
        if error:
            trace.add_step(StepType.COMPLETE, "Error", error=error)

    def get_trace(self, run_id: str) -> Optional[AgentRunTrace]:
        return self._traces.get(run_id)

    def get_summary(self, run_id: str) -> dict:
        trace = self._traces.get(run_id)
        if not trace:
            return {"step_count": 0, "status": "unknown"}
        duration_ms = None
        if trace.end_time:
            duration_ms = round(
                (datetime.fromisoformat(trace.end_time) - datetime.fromisoformat(trace.start_time))
                .total_seconds() * 1000
            )
        return {
            "run_id": trace.run_id,
            "step_count": len(trace.steps),
            "status": trace.status,
            "steps": [
                {"id": s.step_id, "type": s.type, "name": s.name}
                for s in trace.steps
            ],
            "duration_ms": duration_ms,
        }


# 全局单例，供 ai_service 导入使用
trace_service = AgentTraceService()
