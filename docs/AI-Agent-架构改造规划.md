# ERP AI Python 多Agent架构改造规划

> 基于 Datawhale Hello-Agents 课程
> 更新时间：2026-05-19

---

## 一、项目现状评估

### 1.1 已有能力

| 能力 | 状态 | 位置 |
|------|------|------|
| 单Agent Loop | ✅ | ai_service.py |
| 工具注册表 | ✅ | tools/ |
| Prompt配置 | ✅ | config/prompt_config.py |
| 对话记忆 | ✅ | memory/conversation_memory.py |
| 用户偏好 | ✅ | memory/user_preference.py |
| RAG压缩 | ✅ | rag/context_builder.py |
| 字段校验 | ✅ | ai_service.py:269 |
| 知识库RAG | ✅ | vector/knowledge_base.py |
| SSE流式 | ✅ | routes/ai.py |

### 1.2 缺失能力

| 能力 | 状态 | 优先级 |
|------|------|--------|
| **Agent Run Trace** | ✅ 已实现 | 🔴 必须 |
| **多Agent协作** | ✅ 已实现 | 🔴 必须 |
| **安全增强** | ✅ 已实现 | 🔴 必须 |
| **元认知层** | ✅ 已实现 | 🔴 必须 |
| **任务规划** | ✅ 已实现 | 🔴 必须 |

### 1.3 项目评分

| 设计模式 | 完成度 |
|---------|--------|
| 清晰指令 | 95% |
| 结构化输出 | 85% |
| 单一职责Agent | 25% |
| Agent Run Trace | 0% |
| 安全与可信 | 35% |
| **综合评分** | **56%** |

---

## 二、目标架构

### 2.1 渐进式三层架构

```
┌─────────────────────────────────────────────────────────────┐
│                    入口层（Entry）                          │
│  InputGuard → IntentRouter → TaskPlanner                    │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                  核心Agent层（Core）                         │
│  ┌─────────┐  ┌─────────────┐  ┌──────────┐  ┌─────────┐  │
│  │ Query   │  │ Analysis    │  │Knowledge │  │ Action  │  │
│  │ Agent   │  │ Agent       │  │ Agent    │  │ Agent   │  │
│  └─────────┘  └─────────────┘  └──────────┘  └─────────┘  │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                    输出层（Output）                          │
│  AgentTrace → HumanInLoop → ResponseBuilder                 │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 目录结构

```
erp-ai-python/
├── agents/                      # ⭐ 新增：Agent定义
│   ├── __init__.py
│   ├── base.py                 # 抽象基类
│   ├── query_agent.py          # 查询专家
│   ├── analysis_agent.py       # 分析专家
│   ├── knowledge_agent.py      # 知识专家（RAG）
│   └── action_agent.py          # 执行专家
│
├── router/                      # ⭐ 新增：意图分流
│   ├── __init__.py
│   └── intent_router.py
│
├── planner/                     # ⭐ 新增：任务规划
│   ├── __init__.py
│   └── task_planner.py
│
├── orchestrator/                 # ⭐ 新增：协调器
│   ├── __init__.py
│   └── agent_orchestrator.py
│
├── trace/                       # ⭐ 新增：追踪服务
│   ├── __init__.py
│   └── agent_trace.py
│
├── security/                     # ⭐ 新增：安全模块
│   ├── __init__.py
│   ├── input_guard.py          # 输入验证
│   ├── human_in_loop.py        # 人机协作
│   └── rate_limiter.py         # 限流
│
├── metacognition/                # ⭐ 新增：元认知
│   ├── __init__.py
│   └── meta_cognition.py
│
├── tools/                        # 现有
├── config/                       # 现有
├── memory/                       # 现有
├── rag/                          # 现有
├── vector/                       # 现有
├── routes/                       # 现有（需修改）
│   └── ai.py
├── ai_service.py                 # 现有（保留，向后兼容）
└── main.py                       # 现有
```

---

## 三、所需依赖

### 已有依赖

```txt
fastapi>=0.115.0
langchain>=0.3.0
langchain-openai>=0.2.0
pydantic>=2.7.0
chromadb>=0.5.0
...
```

### 需要新增的依赖

```bash
pip install slowapi httpx
```

| 库 | 版本 | Phase | 用途 |
|---|------|-------|------|
| `slowapi` | ^0.1.x | 0.75 | FastAPI 限流 |
| `opentelemetry-api` | ^1.x | 0.5 | 可选：追踪 |
| `opentelemetry-sdk` | ^1.x | 0.5 | 可选：追踪 |

### 依赖结论

**Phase 0.75 之前仅需 1-2 个库**，其余按规划自实现。

---

## 四、核心接口设计

### 4.1 Agent Run Trace 服务

```python
# trace/agent_trace.py

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
            **kwargs
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

    def log_agent(self, run_id: str, agent_name: str, input_data: str, output_data: Any) -> None:
        trace = self._traces.get(run_id)
        if not trace:
            return
        trace.add_step(
            StepType.AGENT,
            agent_name,
            input_data=input_data,
            output_data=output_data,
        )

    def log_tool(self, run_id: str, tool_name: str, params: dict, result: Any) -> None:
        trace = self._traces.get(run_id)
        if not trace:
            return
        row_count = len(result) if isinstance(result, list) else 0
        trace.add_step(
            StepType.TOOL,
            tool_name,
            input_data=params,
            output_data=result,
            metadata={"row_count": row_count},
        )

    def log_retry(self, run_id: str, reason: str, attempt: int) -> None:
        trace = self._traces.get(run_id)
        if not trace:
            return
        trace.add_step(
            StepType.RETRY,
            f"Retry #{attempt}",
            input_data=reason,
        )

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
        return {
            "step_count": len(trace.steps),
            "status": trace.status,
            "current_step": trace.steps[-1].name if trace.steps else None,
            "duration_ms": (
                datetime.fromisoformat(trace.end_time) - datetime.fromisoformat(trace.start_time)
            ).total_seconds() * 1000 if trace.end_time else None,
        }
```

### 4.2 IntentRouter（意图分流）

```python
# router/intent_router.py

from typing import Literal
from pydantic import BaseModel
from langchain_openai import ChatOpenAI
from config.prompt_config import build_system_prompt


class RoutingResult(BaseModel):
    intent: Literal["simple", "complex", "write"]
    confidence: float
    suggested_agent: str | None = None
    reasoning: str
    params: dict | None = None


class IntentRouter:
    def __init__(self, api_key: str):
        self.llm = ChatOpenAI(
            api_key=api_key,
            model="openai/gpt-4o-mini",
            base_url="https://openrouter.ai/api/v1",
        )

    async def route(self, message: str, history: list | None = None) -> RoutingResult:
        prompt = f"""
判断用户意图类型：

意图类型：
- simple: 简单问答、问候、无需查询数据的请求
- complex: 需要查询ERP数据、分析的请求
- write: 需要写操作（新增/修改/删除）的请求

用户消息：{message}

请返回JSON格式：
{{"intent": "类型", "confidence": 0.0-1.0, "reasoning": "判断理由"}}
"""
        response = await self.llm.ainvoke([{"role": "user", "content": prompt}])
        # 解析并返回 RoutingResult
        ...
```

### 4.3 安全模块

#### 4.3.1 输入守卫

```python
# security/input_guard.py

from dataclasses import dataclass
from typing import Literal


INJECTION_PATTERNS = [
    r"ignore previous instructions",
    r"disregard.*instructions",
    r"you are now",
    r"system prompt",
    r"忽略之前的指令",
    r"你是谁",
    r"系统提示",
]


@dataclass
class GuardResult:
    safe: bool
    risk_level: Literal["low", "medium", "high"]
    detected_threats: list[str]
    sanitized_input: str


class InputGuard:
    def check(self, text: str) -> GuardResult:
        threats = []
        for pattern in INJECTION_PATTERNS:
            import re
            if re.search(pattern, text, re.IGNORECASE):
                threats.append(f"injection_pattern: {pattern}")

        # 长度检查
        if len(text) > 10000:
            threats.append("input_too_long")

        risk_level = "low"
        if "injection_pattern" in str(threats):
            risk_level = "high"
        elif threats:
            risk_level = "medium"

        return GuardResult(
            safe=len(threats) == 0,
            risk_level=risk_level,
            detected_threats=threats,
            sanitized_input=text.strip(),
        )

    def validate(self, text: str) -> None:
        result = self.check(text)
        if result.risk_level == "high":
            raise ValueError(f"输入安全检查失败: {', '.join(result.detected_threats)}")
```

#### 4.3.2 人机协作

```python
# security/human_in_loop.py

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
import uuid


DANGEROUS_KEYWORDS = ["删除", "删除所有", "批量删除", "清空", "drop", "truncate"]


@dataclass
class PendingApproval:
    approval_id: str
    user_id: str
    action: str
    details: dict
    created_at: datetime
    status: Literal["pending", "approved", "rejected"]


class HumanInLoop:
    def __init__(self):
        self._pending: dict[str, PendingApproval] = {}

    def needs_approval(self, action: str, details: dict) -> bool:
        # 危险关键词检查
        is_dangerous = any(kw in action for kw in DANGEROUS_KEYWORDS)
        # 影响行数检查
        too_many_rows = (details.get("affected_rows") or 0) > 10
        return is_dangerous or too_many_rows

    def request_approval(self, user_id: str, action: str, details: dict) -> PendingApproval:
        approval_id = f"apr_{uuid.uuid4().hex[:8]}"
        approval = PendingApproval(
            approval_id=approval_id,
            user_id=user_id,
            action=action,
            details=details,
            created_at=datetime.now(),
            status="pending",
        )
        self._pending[approval_id] = approval
        return approval

    def process(self, approval_id: str, decision: str, user_id: str) -> bool:
        approval = self._pending.get(approval_id)
        if not approval:
            raise ValueError("审批不存在")
        if approval.user_id != user_id:
            raise ValueError("无权限审批")
        approval.status = "approved" if decision == "approve" else "rejected"
        return decision == "approve"
```

#### 4.3.3 限流

```python
# security/rate_limiter.py

from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

limiter = Limiter(key_func=get_remote_address)

# 使用示例
@router.post("/chat")
@limiter.limit("60/minute")
async def chat(request: Request, ...):
    ...
```

### 4.4 元认知层

```python
# metacognition/meta_cognition.py

from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class QueryAdjustment:
    adjustment_type: str  # field_name, amount_unit, date_format
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


class MetaCognition:
    """元认知服务 - 查询失败后的反思"""

    def __init__(self, llm=None):
        self.llm = llm
        self.rules: list["ReflectionRule"] = []

    async def reflect_on_failure(
        self,
        query: dict,
        result: dict,
        table_meta: dict,
    ) -> ReflectionResult:
        # 1. 硬编码规则检查
        for rule in self.rules:
            if rule.can_handle(query, result, table_meta):
                adjustment = await rule.apply(query, result, table_meta)
                return ReflectionResult(
                    success=True,
                    adjustment=adjustment,
                    confidence=rule.confidence,
                )

        # 2. LLM 兜底
        if self.llm:
            return await self.llm_reflection(query, result, table_meta)

        return ReflectionResult(success=False, reason="无法自动修复")

    async def llm_reflection(self, query: dict, result: dict, meta: dict) -> ReflectionResult:
        prompt = f"""
场景：ERP订单查询失败
原始查询: {query}
查询结果: {result}
表结构: {meta}

请分析失败原因并给出调整建议。
返回JSON格式：{{"reason": "...", "adjustment": {{...}}, "confidence": 0.0}}
"""
        response = await self.llm.ainvoke([{"role": "user", "content": prompt}])
        # 解析返回
        ...


# 金额单位检查规则
class AmountUnitRule:
    name = "金额单位检查"
    confidence = 0.9

    def can_handle(self, query, result, meta) -> bool:
        return (
            result.get("rows") is None
            and any("amount" in str(f).lower() for f in query.get("filters", []))
        )

    async def apply(self, query, result, meta) -> QueryAdjustment:
        # 检查字段单位
        for field in meta.get("fields", []):
            if "amount" in field["name"].lower():
                if field.get("unit") == "fen":
                    # 用户输入的是元，数据库存的是分
                    original = query["filters"][0]["value"]
                    return QueryAdjustment(
                        adjustment_type="amount_unit",
                        field=field["name"],
                        original=original,
                        adjusted=original * 100,
                        confidence=0.9,
                    )
        raise ValueError("非金额单位问题")
```

### 4.5 BaseAgent 抽象基类

```python
# agents/base.py

from abc import ABC, abstractmethod
from typing import AsyncGenerator
from pydantic import BaseModel


class AgentConfig(BaseModel):
    name: str
    role: str
    responsibilities: list[str]
    constraints: list[str]
    tools: list[str]
    max_rounds: int = 3


class BaseAgent(ABC):
    def __init__(self, config: AgentConfig, api_key: str):
        self.config = config
        self.api_key = api_key

    @abstractmethod
    async def execute(
        self,
        message: str,
        context: str | None = None,
    ) -> AsyncGenerator[str, None]:
        """执行Agent，返回流式输出"""
        pass

    def build_system_prompt(self) -> str:
        parts = [
            f"# 角色：{self.config.role}",
            "\n## 职责：",
            *[f"- {r}" for r in self.config.responsibilities],
            "\n## 约束：",
            *[f"- {c}" for c in self.config.constraints],
        ]
        return "\n".join(parts)
```

### 4.6 Agent 协调器

```python
# orchestrator/agent_orchestrator.py

from trace.agent_trace import AgentTraceService
from router.intent_router import IntentRouter, RoutingResult
from planner.task_planner import TaskPlanner
from agents.query_agent import QueryAgent
from agents.analysis_agent import AnalysisAgent


class AgentOrchestrator:
    def __init__(self, api_key: str, erp_config: dict):
        self.trace = AgentTraceService()
        self.router = IntentRouter(api_key)
        self.planner = TaskPlanner(api_key)
        # 初始化 Agent
        self.query_agent = QueryAgent(api_key, erp_config)
        self.analysis_agent = AnalysisAgent(api_key)

    async def execute(self, request: dict) -> AsyncGenerator[str, None]:
        run_id = self.trace.start_trace(request["message"])

        try:
            # 1. 意图分流
            route = await self.router.route(request["message"])
            self.trace.log_route(run_id, route.model_dump())

            # 2. 简单查询直接返回
            if route.intent == "simple":
                yield "你好！有什么可以帮你的？"
                self.trace.end_trace(run_id, "completed")
                return

            # 3. 复杂查询：Planner 规划
            if route.intent == "complex":
                plan = await self.planner.create_plan(
                    request["message"],
                    ["query", "analysis"],
                )
                self.trace.log_agent(run_id, "TaskPlanner", request["message"], plan)

                # 执行计划
                query_result = ""
                async for chunk in self.query_agent.execute(request["message"]):
                    self.trace.log_tool(run_id, "QueryAgent", request["message"], chunk)
                    yield chunk
                    query_result += chunk

                # 分析结果
                async for chunk in self.analysis_agent.execute(
                    request["message"],
                    query_result,
                ):
                    self.trace.log_agent(run_id, "AnalysisAgent", query_result, chunk)
                    yield chunk

            self.trace.end_trace(run_id, "completed")

        except Exception as e:
            self.trace.end_trace(run_id, "failed", str(e))
            yield f"发生错误：{str(e)}"
```

---

## 五、实施计划

### Phase 0: 当前状态（已完成）
- [x] 单Agent Loop
- [x] 工具注册表
- [x] Prompt配置
- [x] 对话记忆
- [x] RAG压缩
- [x] 字段校验（ai_service.py:269）
- [x] SSE流式输出

### Phase 0.5: Agent Run Trace ⭐
- [ ] 创建 `trace/agent_trace.py`
- [ ] 定义 TraceStep/AgentRunTrace 数据类
- [ ] 实现步骤记录 API
- [ ] 集成到协调器每一步
- [ ] 前端 SSE 推送轨迹摘要

### Phase 0.75: 安全与可信 🔴 ✅
- [x] 安装 `slowapi`
- [x] 创建 `security/input_guard.py`
- [x] 实现提示注入检测
- [x] 创建 `security/human_in_loop.py`
- [x] 实现审批流程（POST /api/ai/approve、GET /api/ai/approvals）
- [x] 创建 `security/rate_limiter.py`
- [x] FastAPI 限流中间件

### Phase 0.8: 元认知层 ⭐ ✅
- [x] 创建 `metacognition/meta_cognition.py`
- [x] 实现金额单位检查规则
- [x] 实现日期格式检查规则
- [x] 集成到 ai_service（空结果自动触发）
- [x] 实现 LLM 反思兜底
- [x] 更新 AgentTrace 支持 reflection/retry

### Phase 1: IntentRouter 🔴 ✅
- [x] 创建 `router/intent_router.py`
- [x] 实现意图分类（simple/complex/write）
- [x] 简单查询分支优化（跳过 Agent Loop 快速回答）
- [x] 单元测试

### Phase 2: TaskPlanner ✅
- [x] 创建 `planner/task_planner.py`
- [x] 实现任务拆分（LLM + 关键词降级）
- [x] 实现计划验证（循环依赖检测 DFS）

### Phase 3: 多Agent拆分 ✅
- [x] 创建 `agents/base.py`
- [x] 创建 `agents/query_agent.py`
- [x] 创建 `agents/analysis_agent.py`
- [x] 创建 `orchestrator/agent_orchestrator.py`（含向后兼容降级）

### Phase 4: 收尾 ✅
- [x] 回归测试（模块导入 + 单元断言）
- [x] 文档状态更新

---

## 六、验收标准

### Agent Run Trace 验收
- [ ] 每次请求都有唯一 trace_id
- [ ] 每一步（分流/Agent/工具/重试）都有记录
- [ ] 轨迹可查询、可展示

### 安全验收
- [ ] 输入验证拦截恶意提示注入
- [ ] 危险写操作自动触发审批
- [ ] 请求限流生效

### 功能验收
- [ ] 简单查询响应速度提升
- [ ] 复杂查询结果与单Agent一致
- [ ] 向后兼容100%

### 元认知层验收
- [ ] 查询失败时自动反思
- [ ] 字段校验已有 ✅
- [ ] LLM反思给出有效建议

---

## 七、向后兼容方案

保留 `ai_service.py` 作为默认处理器，新流程逐步替换：

```python
# routes/ai.py

async def chat_with_ai(request: dict, ...):
    route = await intent_router.route(request["message"])

    if route.intent == "simple":
        # 新流程：直接回答
        return simple_response(request["message"])
    elif route.confidence > 0.8:
        # 新流程：多Agent
        async for chunk in orchestrator.execute(request):
            yield chunk
    else:
        # 向后兼容：单Agent
        async for chunk in ai_service.chat_with_ai(request, ...):
            yield chunk
```

---

## 八、风险与对策

| 风险 | 影响 | 对策 |
|------|------|------|
| Router判断不准 | 简单查询走复杂流程 | 置信度阈值，低了走单Agent |
| 多Agent上下文丢失 | 分析结果不准确 | 明确Agent间传递格式 |
| 向后兼容破坏 | 现有功能异常 | 完整回归测试 |
| Token增加 | 成本上升 | 简单查询走精简Prompt |
| 提示注入无成熟库 | 需自建规则库 | 逐步积累关键词/正则 |
