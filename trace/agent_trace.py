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
    TABLE_SEARCH = "table_search"
    KNOWLEDGE = "knowledge"
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
    duration_ms: Optional[int] = None


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
    system_prompt: str = ""

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

    def start_trace(self, user_message: str, intent: str = "pending", conversation_id: str = "", system_prompt: str = "") -> str:
        run_id = f"run_{uuid.uuid4().hex[:12]}"
        trace = AgentRunTrace(
            run_id=run_id,
            user_message=user_message,
            intent=intent,
            start_time=datetime.now().isoformat(),
            system_prompt=system_prompt,
        )
        trace.conversation_id = conversation_id
        self._traces[run_id] = trace
        return run_id

    def log_llm(self, run_id: str, round_n: int, model: str, reasoning: str, tool_calls: list, tokens: dict,
                duration_ms: Optional[int] = None, messages: Optional[list] = None, finish_reason: Optional[str] = None) -> None:
        """记录每轮 LLM 调用：推理文本、使用模型、token 用量、输入消息摘要、finish_reason"""
        trace = self._traces.get(run_id)
        if not trace:
            return

        # 消息摘要：记录条数 + 每条 role/内容前80字（避免体积过大）
        messages_summary = None
        if messages:
            messages_summary = [
                {
                    "role": getattr(m, "type", type(m).__name__),
                    "preview": (m.content[:80] + "…" if isinstance(m.content, str) and len(m.content) > 80 else m.content)
                    if hasattr(m, "content") else str(m)[:80],
                }
                for m in messages
            ]

        trace.add_step(
            StepType.AGENT,
            f"LLM Round {round_n} [{model}]",
            input_data={
                "round": round_n,
                "model": model,
                "message_count": len(messages) if messages else None,
                "messages": messages_summary,
            },
            output_data={
                "reasoning": reasoning or None,
                "tool_calls": [
                    {"name": tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", ""),
                     "args": tc.get("args", {}) if isinstance(tc, dict) else getattr(tc, "args", {})}
                    for tc in tool_calls
                ] if tool_calls else [],
            },
            metadata={
                **({"tokens": tokens} if tokens else {}),
                **({"finish_reason": finish_reason} if finish_reason else {}),
            },
            duration_ms=duration_ms,
        )
        # 累加 token 到 trace
        if tokens:
            trace.total_tokens += tokens.get("total_tokens", 0)

    def set_system_prompt(self, run_id: str, system_prompt: str) -> None:
        trace = self._traces.get(run_id)
        if trace:
            trace.system_prompt = system_prompt

    def log_tool(self, run_id: str, tool_name: str, params: dict, result: Any, erp_cookie: str = "", erp_auth: str = "", duration_ms: Optional[int] = None) -> None:
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
        metadata: dict = {"row_count": row_count}
        if erp_cookie:
            metadata["erp_cookie"] = erp_cookie
        if erp_auth:
            metadata["erp_auth"] = erp_auth

        # 记录实际发给 ERP 的 HTTP 请求体，便于排查问题
        if tool_name == "query_erp_list":
            try:
                from erp_client import _build_common_query_body, ERP_BASE_URL
                from tools.common_query import _lookup_catalog_params
                table_name = params.get("tableName", "")
                catalog_api_path, catalog_extra_body, catalog_body_mode = _lookup_catalog_params(table_name)
                resolved_params = dict(params)
                resolved_params["apiPath"]   = catalog_api_path
                resolved_params["extraBody"] = catalog_extra_body or {}
                resolved_params["bodyMode"]  = catalog_body_mode
                erp_body = _build_common_query_body(resolved_params)
                api_path = (catalog_api_path or "").strip()
                if not api_path:
                    url = f"{ERP_BASE_URL}/gw/api/ERP/FormCommon/CommonQuery"
                elif "/" in api_path:
                    url = f"{ERP_BASE_URL}/gw/api/ERP/{api_path}"
                else:
                    url = f"{ERP_BASE_URL}/gw/api/ERP/{api_path}/CommonQuery"
                metadata["erp_request"] = {
                    "url": url,
                    "method": "POST",
                    "body": erp_body,
                }
            except Exception:
                pass
        elif tool_name == "get_table_fields":
            try:
                from erp_client import ERP_BASE_URL
                form_code = params.get("formCode", "")
                metadata["erp_request"] = {
                    "url": f"{ERP_BASE_URL}/gw/api/ERP/FunRights/getProgGridLayout",
                    "method": "POST",
                    "body": {"FormCode": form_code, "FrontJSFileName": "view.jsx"},
                }
            except Exception:
                pass

        trace.add_step(
            StepType.TOOL,
            tool_name,
            input_data=params,
            output_data=output_data,
            metadata=metadata,
            duration_ms=duration_ms,
        )

    def log_retry(self, run_id: str, reason: str, attempt: int, error: Optional[str] = None) -> None:
        trace = self._traces.get(run_id)
        if not trace:
            return
        parts = reason.split(" → ")
        trace.add_step(
            StepType.RETRY,
            f"ModelFallback #{attempt}",
            input_data={"from": parts[0] if len(parts) == 2 else reason},
            output_data={"to": parts[1] if len(parts) == 2 else None},
            metadata={"reason": "model_unavailable", "error": error},
        )

    def log_route(self, run_id: str, result: dict, duration_ms: Optional[int] = None) -> None:
        trace = self._traces.get(run_id)
        if not trace:
            return
        trace.add_step(
            StepType.ROUTE,
            "IntentRouter",
            input_data=result.get("reasoning"),
            output_data={"intent": result.get("intent"), "confidence": result.get("confidence")},
            confidence=result.get("confidence"),
            duration_ms=duration_ms,
        )

    def log_agent(self, run_id: str, agent_name: str, input_data: Any, output_data: Any, metadata: dict | None = None, duration_ms: Optional[int] = None) -> None:
        trace = self._traces.get(run_id)
        if not trace:
            return
        trace.add_step(StepType.AGENT, agent_name, input_data=input_data, output_data=output_data, metadata=metadata or {}, duration_ms=duration_ms)

    def log_knowledge_search(self, run_id: str, query: str, hits: list[dict], duration_ms: Optional[int] = None) -> None:
        trace = self._traces.get(run_id)
        if not trace:
            return
        trace.add_step(
            StepType.KNOWLEDGE,
            "KnowledgeSearch",
            input_data={"query": query},
            output_data={"hit_count": len(hits), "hits": hits},
            metadata={"matched": bool(hits)},
            duration_ms=duration_ms,
        )

    def log_table_search(self, run_id: str, keyword: str, matched_count: int, tables: list[dict], cache_hit: bool, duration_ms: Optional[int] = None) -> None:
        trace = self._traces.get(run_id)
        if not trace:
            return
        trace.add_step(
            StepType.TABLE_SEARCH,
            "SearchErpTables",
            input_data={"keyword": keyword},
            output_data={"matched": matched_count, "tables": tables},
            metadata={"cache_hit": cache_hit, "table_count": matched_count},
            duration_ms=duration_ms,
        )

    def log_rag(self, run_id: str, is_rag: bool, total_rows: int, sent_rows: int, keywords: list[str], duration_ms: Optional[int] = None) -> None:
        trace = self._traces.get(run_id)
        if not trace:
            return
        trace.add_step(
            StepType.ANALYSIS,
            "RAG",
            input_data={"total_rows": total_rows, "keywords": keywords},
            output_data={"is_rag": is_rag, "sent_rows": sent_rows},
            metadata={"compressed": is_rag, "drop_count": total_rows - sent_rows},
            duration_ms=duration_ms,
        )

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
                        (run_id, user_id, conversation_id, user_message, status, step_count, duration_ms, steps, system_prompt, total_tokens, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                        trace.system_prompt or "",
                        trace.total_tokens,
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
            "total_tokens": trace.total_tokens,
            "system_prompt": trace.system_prompt or "",
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
                    "duration_ms": s.duration_ms,
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
