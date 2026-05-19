# AI-Agent 架构改造 — Orchestrate 执行命令

基于 `docs/AI-Agent-架构改造规划.md` 生成，ECC mode: plugin，Lang: python

---

## Steps overview

| # | 标题 | Tags | Chain |
|---|---|---|---|
| 1 | Phase 0.5 — Agent Run Trace | impl | `everything-claude-code:tdd-guide,everything-claude-code:python-reviewer` |
| 2 | Phase 0.75 — 安全与可信 | impl, security | `everything-claude-code:tdd-guide,everything-claude-code:python-reviewer,everything-claude-code:security-reviewer` |
| 3 | Phase 0.8 — 元认知层 | impl | `everything-claude-code:tdd-guide,everything-claude-code:python-reviewer` |
| 4 | Phase 1 — IntentRouter | impl | `everything-claude-code:tdd-guide,everything-claude-code:python-reviewer` |
| 5 | Phase 2 — TaskPlanner | design, impl | `everything-claude-code:planner,everything-claude-code:tdd-guide,everything-claude-code:python-reviewer` |
| 6 | Phase 3 — 多Agent拆分与协调器 | impl, refactor | `everything-claude-code:architect,everything-claude-code:tdd-guide,everything-claude-code:python-reviewer` |
| 7 | Phase 4 — 收尾：测试与文档 | test, docs | `everything-claude-code:tdd-guide,everything-claude-code:e2e-runner,everything-claude-code:doc-updater` |

---

## Step 1 — Phase 0.5: Agent Run Trace

**Intent**: 创建 `trace/agent_trace.py`，实现 TraceStep/AgentRunTrace 数据类与 AgentTraceService，集成到协调器每一步，通过 SSE 推送轨迹摘要到前端。

```bash
/everything-claude-code:orchestrate custom "everything-claude-code:tdd-guide,everything-claude-code:python-reviewer" "[Plan: docs/AI-Agent-架构改造规划.md#step-1] 在 erp-ai-python 项目中实现 Agent Run Trace 服务：创建 trace/agent_trace.py，包含 StepType 枚举、TraceStep/AgentRunTrace dataclass、AgentTraceService（start_trace/log_route/log_agent/log_tool/log_retry/log_reflection/end_trace/get_trace/get_summary）；集成到 routes/ai.py SSE 流，每次响应末尾推送 trace_summary 事件；Acceptance: 每次请求生成唯一 run_id；每步骤均有记录且可通过 get_trace 查询；SSE 末尾包含 trace_summary 字段"
```

---

## Step 2 — Phase 0.75: 安全与可信

**Intent**: 安装 `slowapi`，创建 `security/input_guard.py`（提示注入检测）、`security/human_in_loop.py`（写操作审批流）、`security/rate_limiter.py`（限流中间件），并集成到 `routes/ai.py`。

```bash
/everything-claude-code:orchestrate custom "everything-claude-code:tdd-guide,everything-claude-code:python-reviewer,everything-claude-code:security-reviewer" "[Plan: docs/AI-Agent-架构改造规划.md#step-2] 在 erp-ai-python 中实现安全模块：1) security/input_guard.py 基于 INJECTION_PATTERNS 正则检测提示注入，check() 返回 GuardResult，validate() 在 risk_level==high 时抛出；2) security/human_in_loop.py 实现 PendingApproval 和 HumanInLoop，危险关键词或影响行数>10 触发审批；3) security/rate_limiter.py 使用 slowapi 60/minute 限流；4) 集成到 routes/ai.py；Acceptance: 注入输入被拦截返回 400；危险操作返回 approval_id；超频返回 429"
```

---

## Step 3 — Phase 0.8: 元认知层

**Intent**: 创建 `metacognition/meta_cognition.py`，实现 QueryAdjustment/ReflectionResult 数据类、MetaCognition 服务，包含金额单位检查规则、日期格式规则及 LLM 反思兜底，集成到 QueryAgent 重试逻辑。

```bash
/everything-claude-code:orchestrate custom "everything-claude-code:tdd-guide,everything-claude-code:python-reviewer" "[Plan: docs/AI-Agent-架构改造规划.md#step-3] 在 erp-ai-python 中实现元认知模块：创建 metacognition/meta_cognition.py，包含 QueryAdjustment/ReflectionResult dataclass、MetaCognition.reflect_on_failure()（先规则匹配，再 LLM 兜底）、AmountUnitRule（元转分检测）、日期格式规则；集成到 ai_service.py 查询失败重试路径，失败时调用 reflect 并记录到 AgentTrace；Acceptance: 金额单位错误自动修正并重试；LLM 反思返回有效 ReflectionResult；trace 包含 reflection 步骤记录"
```

---

## Step 4 — Phase 1: IntentRouter

**Intent**: 创建 `router/intent_router.py`，实现 RoutingResult Pydantic 模型与 IntentRouter.route() 方法，将用户消息分类为 simple/complex/write 三种意图，编写单元测试覆盖边界情况。

```bash
/everything-claude-code:orchestrate custom "everything-claude-code:tdd-guide,everything-claude-code:python-reviewer" "[Plan: docs/AI-Agent-架构改造规划.md#step-4] 在 erp-ai-python 中实现意图路由：创建 router/intent_router.py，RoutingResult(intent: Literal[simple/complex/write], confidence, suggested_agent, reasoning, params)，IntentRouter 使用 openrouter gpt-4o-mini 异步分类，解析 LLM JSON 返回，confidence<0.5 时降级为 complex；集成到 routes/ai.py，simple 意图直接返回不走工具；Acceptance: 问候语路由到 simple；ERP 查询路由到 complex；写操作路由到 write；confidence 字段在 0-1 范围内"
```

---

## Step 5 — Phase 2: TaskPlanner

**Intent**: 设计并实现 `planner/task_planner.py`，支持将复杂查询拆分为有序子任务列表，实现循环依赖检测与计划验证，为 AgentOrchestrator 提供执行计划。

```bash
/everything-claude-code:orchestrate custom "everything-claude-code:planner,everything-claude-code:tdd-guide,everything-claude-code:python-reviewer" "[Plan: docs/AI-Agent-架构改造规划.md#step-5] 设计并实现 erp-ai-python planner/task_planner.py：TaskPlanner 接收用户消息和可用 agent 列表，输出有序 Task 列表（每个 Task 含 agent_name/input/depends_on）；实现循环依赖检测（拓扑排序）；TaskPlanner.create_plan() 为异步方法调用 LLM；Acceptance: 复杂查询生成 2+ 步骤计划；循环依赖输入抛出 ValueError；计划中 agent_name 均属于合法注册 Agent 集合"
```

---

## Step 6 — Phase 3: 多Agent拆分与协调器

**Intent**: 创建 `agents/base.py`（BaseAgent 抽象基类）、`agents/query_agent.py`、`agents/analysis_agent.py`，以及 `orchestrator/agent_orchestrator.py`（整合 Trace/Router/Planner/Agent 的完整执行链），保留 `ai_service.py` 为向后兼容回退路径。

```bash
/everything-claude-code:orchestrate custom "everything-claude-code:architect,everything-claude-code:tdd-guide,everything-claude-code:python-reviewer" "[Plan: docs/AI-Agent-架构改造规划.md#step-6] 在 erp-ai-python 实现多 Agent 拆分：1) agents/base.py: AgentConfig(Pydantic) + BaseAgent(ABC) execute()->AsyncGenerator；2) agents/query_agent.py: 继承 BaseAgent，复用现有 tools/；3) agents/analysis_agent.py: 继承 BaseAgent，接收 query_result 上下文；4) orchestrator/agent_orchestrator.py: 整合 Trace/Router/Planner，confidence>0.8 走多 Agent，否则 fallback 到 ai_service.py；5) routes/ai.py 新增 orchestrator 分支；Acceptance: 向后兼容 100%；复杂查询经 orchestrator 返回结果与旧接口一致；trace 完整记录各 Agent 步骤"
```

---

## Step 7 — Phase 4: 收尾 — 测试与文档

**Intent**: 执行完整性能测试与回归测试，确认所有验收标准通过，更新 CLAUDE.md 与 docs/ 目录反映新架构，补充各模块 API 说明。

```bash
/everything-claude-code:orchestrate custom "everything-claude-code:tdd-guide,everything-claude-code:e2e-runner,everything-claude-code:doc-updater" "[Plan: docs/AI-Agent-架构改造规划.md#step-7] 对 erp-ai-python 多 Agent 架构进行收尾验收：1) tdd-guide 补全 trace/security/metacognition/router/planner/agents 各模块单元测试，覆盖率≥80%；2) e2e-runner 验证 POST /api/ai/chat SSE 全链路：简单问答→direct；ERP查询→orchestrator；危险操作→human_in_loop；3) doc-updater 更新 CLAUDE.md 架构说明、docs/ 新增模块说明；Acceptance: 全部验收标准通过（见规划第六节）；CLAUDE.md 反映新目录结构；回归测试无破坏性变更"
```

---

## Batch execution（按顺序整体执行）

> 步骤间存在依赖：Step 1 Trace 服务 → Step 6 协调器；Step 2 安全模块 → Step 6 routes 集成。建议按序执行。

```bash
/everything-claude-code:orchestrate custom "everything-claude-code:tdd-guide,everything-claude-code:python-reviewer" "[Plan: docs/AI-Agent-架构改造规划.md#step-1] 在 erp-ai-python 项目中实现 Agent Run Trace 服务：创建 trace/agent_trace.py，包含 StepType 枚举、TraceStep/AgentRunTrace dataclass、AgentTraceService（start_trace/log_route/log_agent/log_tool/log_retry/log_reflection/end_trace/get_trace/get_summary）；集成到 routes/ai.py SSE 流，每次响应末尾推送 trace_summary 事件；Acceptance: 每次请求生成唯一 run_id；每步骤均有记录且可通过 get_trace 查询；SSE 末尾包含 trace_summary 字段"

/everything-claude-code:orchestrate custom "everything-claude-code:tdd-guide,everything-claude-code:python-reviewer,everything-claude-code:security-reviewer" "[Plan: docs/AI-Agent-架构改造规划.md#step-2] 在 erp-ai-python 中实现安全模块：1) security/input_guard.py 基于 INJECTION_PATTERNS 正则检测提示注入，check() 返回 GuardResult，validate() 在 risk_level==high 时抛出；2) security/human_in_loop.py 实现 PendingApproval 和 HumanInLoop，危险关键词或影响行数>10 触发审批；3) security/rate_limiter.py 使用 slowapi 60/minute 限流；4) 集成到 routes/ai.py；Acceptance: 注入输入被拦截返回 400；危险操作返回 approval_id；超频返回 429"

/everything-claude-code:orchestrate custom "everything-claude-code:tdd-guide,everything-claude-code:python-reviewer" "[Plan: docs/AI-Agent-架构改造规划.md#step-3] 在 erp-ai-python 中实现元认知模块：创建 metacognition/meta_cognition.py，包含 QueryAdjustment/ReflectionResult dataclass、MetaCognition.reflect_on_failure()（先规则匹配，再 LLM 兜底）、AmountUnitRule（元转分检测）、日期格式规则；集成到 ai_service.py 查询失败重试路径，失败时调用 reflect 并记录到 AgentTrace；Acceptance: 金额单位错误自动修正并重试；LLM 反思返回有效 ReflectionResult；trace 包含 reflection 步骤记录"

/everything-claude-code:orchestrate custom "everything-claude-code:tdd-guide,everything-claude-code:python-reviewer" "[Plan: docs/AI-Agent-架构改造规划.md#step-4] 在 erp-ai-python 中实现意图路由：创建 router/intent_router.py，RoutingResult(intent: Literal[simple/complex/write], confidence, suggested_agent, reasoning, params)，IntentRouter 使用 openrouter gpt-4o-mini 异步分类，解析 LLM JSON 返回，confidence<0.5 时降级为 complex；集成到 routes/ai.py，simple 意图直接返回不走工具；Acceptance: 问候语路由到 simple；ERP 查询路由到 complex；写操作路由到 write；confidence 字段在 0-1 范围内"

/everything-claude-code:orchestrate custom "everything-claude-code:planner,everything-claude-code:tdd-guide,everything-claude-code:python-reviewer" "[Plan: docs/AI-Agent-架构改造规划.md#step-5] 设计并实现 erp-ai-python planner/task_planner.py：TaskPlanner 接收用户消息和可用 agent 列表，输出有序 Task 列表（每个 Task 含 agent_name/input/depends_on）；实现循环依赖检测（拓扑排序）；TaskPlanner.create_plan() 为异步方法调用 LLM；Acceptance: 复杂查询生成 2+ 步骤计划；循环依赖输入抛出 ValueError；计划中 agent_name 均属于合法注册 Agent 集合"

/everything-claude-code:orchestrate custom "everything-claude-code:architect,everything-claude-code:tdd-guide,everything-claude-code:python-reviewer" "[Plan: docs/AI-Agent-架构改造规划.md#step-6] 在 erp-ai-python 实现多 Agent 拆分：1) agents/base.py: AgentConfig(Pydantic) + BaseAgent(ABC) execute()->AsyncGenerator；2) agents/query_agent.py: 继承 BaseAgent，复用现有 tools/；3) agents/analysis_agent.py: 继承 BaseAgent，接收 query_result 上下文；4) orchestrator/agent_orchestrator.py: 整合 Trace/Router/Planner，confidence>0.8 走多 Agent，否则 fallback 到 ai_service.py；5) routes/ai.py 新增 orchestrator 分支；Acceptance: 向后兼容 100%；复杂查询经 orchestrator 返回结果与旧接口一致；trace 完整记录各 Agent 步骤"

/everything-claude-code:orchestrate custom "everything-claude-code:tdd-guide,everything-claude-code:e2e-runner,everything-claude-code:doc-updater" "[Plan: docs/AI-Agent-架构改造规划.md#step-7] 对 erp-ai-python 多 Agent 架构进行收尾验收：1) tdd-guide 补全 trace/security/metacognition/router/planner/agents 各模块单元测试，覆盖率≥80%；2) e2e-runner 验证 POST /api/ai/chat SSE 全链路：简单问答→direct；ERP查询→orchestrator；危险操作→human_in_loop；3) doc-updater 更新 CLAUDE.md 架构说明、docs/ 新增模块说明；Acceptance: 全部验收标准通过（见规划第六节）；CLAUDE.md 反映新目录结构；回归测试无破坏性变更"
```
