import json
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

    def start_trace(self, user_message: str, intent: str = "pending", conversation_id: str = "") -> str:
        run_id = f"run_{uuid.uuid4().hex[:12]}"
        trace = AgentRunTrace(
            run_id=run_id,
            user_message=user_message,
            intent=intent,
            start_time=datetime.now().isoformat(),
        )
        trace.conversation_id = conversation_id
        self._traces[run_id] = trace
        return run_id

    def log_tool(self, run_id: str, tool_name: str, params: dict, result: Any) -> None:
        trace = self._traces.get(run_id)
        if not trace:
            return
        # result 是字符串，尝试从 JSON 中解析 rows 数量
        row_count = 0
        output_data = result
        if isinstance(result, str):
            try:
                parsed = json.loads(result)
                rows = parsed.get("rows") if isinstance(parsed, dict) else None
                if isinstance(rows, list):
                    row_count = len(rows)
                    # 大结果只记摘要，避免 trace 体积过大
                    output_data = {**parsed, "rows": f"[{row_count} rows, omitted]"} if row_count > 3 else parsed
            except (json.JSONDecodeError, AttributeError):
                pass
        elif isinstance(result, list):
            row_count = len(result)
        trace.add_step(
            StepType.TOOL,
            tool_name,
            input_data=params,
            output_data=output_data,
            metadata={"row_count": row_count},
        )

    def log_retry(self, run_id: str, reason: str, attempt: int) -> None:
        trace = self._traces.get(run_id)
        if not trace:
            return
        trace.add_step(StepType.RETRY, f"Retry #{attempt}", input_data=reason)

    def log_route(self, run_id: str, result: dict) -> None:
        trace = self._traces.get(run_id)
        if not trace:
            return
        trace.add_step(
            StepType.ROUTE,
            "IntentRouter",
            input_data=result.get("reasoning"),
            output_data={"intent": result.get("intent"), "confidence": result.get("confidence")},
            confidence=result.get("confidence"),
        )

    def log_agent(self, run_id: str, agent_name: str, input_data: Any, output_data: Any) -> None:
        trace = self._traces.get(run_id)
        if not trace:
            return
        trace.add_step(StepType.AGENT, agent_name, input_data=input_data, output_data=output_data)

    def log_reflection(self, run_id: str, reason: str, adjustment: Optional[dict] = None) -> None:
        trace = self._traces.get(run_id)
        if not trace:
            return
        trace.add_step(
            StepType.REFLECTION,
            "MetaCognition",
            input_data={"reason": reason},
            output_data=adjustment or {},
        )

    def end_trace(self, run_id: str, status: str = "completed", error: Optional[str] = None, user_id: str = "") -> None:
        trace = self._traces.get(run_id)
        if not trace:
            return
        trace.end_time = datetime.now().isoformat()
        trace.status = status
        if error:
            trace.add_step(StepType.COMPLETE, "Error", error=error)
        self._persist(trace, user_id)

    def _persist(self, trace: "AgentRunTrace", user_id: str) -> None:
        """将 trace 写入 SQLite，异常时静默忽略不影响主流程"""
        try:
            import time
            from db import get_conn
            summary = self.get_summary(trace.run_id)
            conn = get_conn()
            with conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO agent_traces
                        (run_id, user_id, conversation_id, user_message, status, step_count, duration_ms, steps, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        trace.run_id,
                        user_id,
                        getattr(trace, "conversation_id", ""),
                        trace.user_message,
                        trace.status,
                        summary["step_count"],
                        summary.get("duration_ms"),
                        json.dumps(summary["steps"], ensure_ascii=False),
                        time.time(),
                    ),
                )
            conn.close()
        except Exception:
            pass

    def get_trace(self, run_id: str) -> Optional[AgentRunTrace]:
        return self._traces.get(run_id)

    def get_summary(self, run_id: str, slim: bool = False) -> dict:
        """返回 trace 摘要。slim=True 时不含 steps（用于 SSE 推送，减小传输体积）"""
        trace = self._traces.get(run_id)
        if not trace:
            return {"step_count": 0, "status": "unknown"}
        duration_ms = None
        if trace.end_time:
            duration_ms = round(
                (datetime.fromisoformat(trace.end_time) - datetime.fromisoformat(trace.start_time))
                .total_seconds() * 1000
            )
        base = {
            "run_id": trace.run_id,
            "conversation_id": getattr(trace, "conversation_id", ""),
            "user_message": trace.user_message,
            "step_count": len(trace.steps),
            "status": trace.status,
            "duration_ms": duration_ms,
        }
        if slim:
            return base
        return {
            **base,
            "steps": [
                {
                    "id": s.step_id,
                    "type": s.type,
                    "name": s.name,
                    "timestamp": s.timestamp,
                    "input": s.input_data,
                    "output": s.output_data,
                    "metadata": s.metadata or {},
                    "error": s.error,
                }
                for s in trace.steps
            ],
        }


# 全局单例，供 ai_service 导入使用
trace_service = AgentTraceService()
