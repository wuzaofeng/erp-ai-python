# 写操作分级确认框架 Spec

> 日期：2026-05-28
> 状态：草稿（暂缓实现，待写操作工具开发时启用）

## 1. 背景与目标

ERP AI 助手即将支持写操作（新增单据、审批、修改状态等）。写操作一旦执行无法撤销，必须在架构层面建立分级确认机制，防止 AI 幻觉或误操作造成业务损失。

---

## 2. 操作分级定义

| 级别 | 类型 | 示例 | 执行策略 |
|------|------|------|---------|
| **L0 - 只读** | 查询、导出、统计 | `query_erp_list`、`get_table_fields` | 直接执行，无需任何确认 |
| **L1 - 低风险写** | 可撤销或低影响写操作 | 保存草稿、修改个人偏好、备注更新 | 执行后通知用户（操作已完成，如需撤销请...） |
| **L2 - 高风险写** | 不可撤销或高影响写操作 | 提交审批、新增订单、删除记录、修改金额 | **暂停等待用户确认**，用户点击"确认"才执行 |

---

## 3. 影响范围

| 层级 | 文件 | 改动类型 |
|------|------|---------|
| 工具定义 | `tools/__init__.py` / 新增 `tools/write_ops.py` | 每个工具声明 `risk_level: L0/L1/L2` |
| Agent 执行 | `ai_service.py` | 拦截 L2 工具调用，发送确认事件并暂停 |
| SSE 协议 | `ai_service.py` + `routes/ai.py` | 新增 `\x00CONFIRM_REQUIRED:` 事件 |
| 前端 Hook | `useAIChat.js` | 解析 `confirm_required` 事件，暂停流，等待用户响应 |
| 前端 AI 面板 | `AIAssistantModal.jsx` | 新增确认弹窗 UI 组件 |
| Trace | `trace/agent_trace.py` | 新增 `write` StepType，记录确认结果 |
| 记忆写入 | `memory/conversation_memory.py` | 写操作前校验 `verified` 状态 |
| 确认接口 | `routes/ai.py` | 新增 `POST /api/ai/confirm` |

---

## 4. SSE 新增协议事件

**后端 → 前端（等待确认）**：
```
\x00CONFIRM_REQUIRED:{"confirm_id":"cfm_xxx","tool":"create_po_order","risk_level":"L2","summary":"新增采购订单：供应商 广州零零科技，金额 ¥12,000，物料 5 种","params":{...},"timeout_ms":30000}
```

**前端 → 后端（用户决策）**：
```http
POST /api/ai/confirm
{
  "confirm_id": "cfm_xxx",
  "run_id": "run_xxx",
  "decision": "approve" | "reject",
  "user_id": "xxx"
}
```

---

## 5. 后端核心实现

### 5.1 工具 risk_level 声明（tools/base.py 新增）

```python
from enum import Enum

class RiskLevel(str, Enum):
    L0 = "L0"  # 只读
    L1 = "L1"  # 低风险写
    L2 = "L2"  # 高风险写（需确认）

# 工具定义时声明（示例）
class CreatePOTool(BaseTool):
    risk_level: RiskLevel = RiskLevel.L2

    def describe_action(self, args: dict) -> str:
        """返回给用户看的操作摘要（中文）"""
        return f"新增采购订单：供应商={args.get('supplier')}，金额=¥{args.get('amount')}"
```

### 5.2 ai_service.py 拦截逻辑（在工具 ainvoke 前插入）

```python
# 模块级全局 pending dict（每个进程独立）
_confirm_pending: dict[str, asyncio.Event] = {}
_confirm_results: dict[str, str] = {}

# 工具执行前检查 risk_level
risk = getattr(target_tool, 'risk_level', RiskLevel.L0)
if risk == RiskLevel.L2:
    import uuid
    confirm_id = f"cfm_{uuid.uuid4().hex[:8]}"
    _confirm_pending[confirm_id] = asyncio.Event()

    yield f"\x00CONFIRM_REQUIRED:{json.dumps({
        'confirm_id': confirm_id,
        'run_id': run_id,
        'tool': tool_name,
        'risk_level': 'L2',
        'summary': target_tool.describe_action(tool_args),
        'params': tool_args,
        'timeout_ms': 30000,
    }, ensure_ascii=False)}"

    try:
        await asyncio.wait_for(_confirm_pending[confirm_id].wait(), timeout=30)
    except asyncio.TimeoutError:
        _confirm_pending.pop(confirm_id, None)
        _confirm_results.pop(confirm_id, None)
        yield "⏱️ 确认超时，操作已自动取消。"
        trace_service.log_write(run_id, tool_name, tool_args, "timeout")
        return

    decision = _confirm_results.pop(confirm_id, "reject")
    _confirm_pending.pop(confirm_id, None)

    if decision == "reject":
        yield "❌ 操作已取消，未执行任何写入。"
        trace_service.log_write(run_id, tool_name, tool_args, "rejected")
        return

    trace_service.log_write(run_id, tool_name, tool_args, "approved")
    # 继续向下执行 ainvoke
```

### 5.3 新增确认接口（routes/ai.py）

```python
class ConfirmBody(BaseModel):
    confirm_id: str
    run_id: str
    decision: str  # "approve" | "reject"
    user_id: str

@router.post("/api/ai/confirm")
async def confirm_action(body: ConfirmBody):
    from ai_service import _confirm_pending, _confirm_results
    if body.confirm_id not in _confirm_pending:
        raise HTTPException(status_code=404, detail="确认请求不存在或已超时")
    _confirm_results[body.confirm_id] = body.decision
    _confirm_pending[body.confirm_id].set()
    return {"code": 0, "message": "已收到决策"}
```

---

## 6. 前端实现

### 6.1 useAIChat.js — parseSSEEvent 增加

```javascript
if (obj.object === 'confirm_required') {
  return { confirmRequired: obj.data };
}
```

```javascript
// sendMessage 循环中
if (parsed.confirmRequired) {
  onConfirmRequired?.(parsed.confirmRequired);
  continue;
}
```

### 6.2 AIAssistantModal.jsx — 确认弹窗

```jsx
const [pendingConfirm, setPendingConfirm] = useState(null);

// useAIChat 增加 onConfirmRequired
onConfirmRequired: (data) => setPendingConfirm(data),

// 处理用户决策
const handleConfirm = async (decision) => {
  const { confirm_id, run_id } = pendingConfirm;
  setPendingConfirm(null);
  await fetch('/gw/api/ai/confirm', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-User-Id': userId },
    body: JSON.stringify({ confirm_id, run_id, decision, user_id: userId }),
  });
};

// 弹窗 UI
{pendingConfirm && (
  <Modal
    title="⚠️ 高风险写操作确认"
    open={!!pendingConfirm}
    onOk={() => handleConfirm('approve')}
    onCancel={() => handleConfirm('reject')}
    okText="确认执行"
    okButtonProps={{ danger: true }}
    cancelText="取消"
    maskClosable={false}
  >
    <p>{pendingConfirm.summary}</p>
    <p style={{ color: '#ff4d4f', fontSize: 13 }}>此操作执行后不可撤销，请确认。</p>
  </Modal>
)}
```

---

## 7. Trace 扩展

```python
# trace/agent_trace.py — StepType 新增
class StepType(str, Enum):
    ...
    WRITE = "write"

# 新增方法
def log_write(self, run_id, tool_name, params, decision, result=None):
    trace.add_step(
        StepType.WRITE, tool_name,
        input_data=params,
        output_data={"decision": decision, "result": result},
        metadata={"risk_level": "L2", "audit_trail": True},
    )
```

TraceModal.jsx 中 `STEP_ICON` 新增 `write: '✍️'`，decision=approved 显示绿色，rejected/timeout 显示红色。

---

## 8. 记忆污染防护与写操作结合

- **写操作执行前**：检查本次对话是否存在 `verified=False` 的 assistant 历史消息。若存在，在 system prompt 中追加警告，禁止依赖该历史做写操作的参数推断
- **写操作完成后（用户已确认）**：标记该轮 assistant 消息 `verified=True`，作为后续可信历史

---

## 9. 数据流

```
用户："帮我新增一张采购订单"
  → ai_service.py Agent Loop
    → LLM 决定调用 create_po_order (L2)
    → 拦截：生成 confirm_id，yield CONFIRM_REQUIRED 事件，await Event
  ← 前端 parseSSEEvent → onConfirmRequired → 弹窗显示
  用户点击"确认执行"
  → POST /api/ai/confirm {decision: "approve"}
    → _confirm_results[cfm_xxx] = "approve"
    → Event.set() 唤醒 coroutine
    → 继续执行 ainvoke
    → trace_service.log_write("approved")
    → yield 成功消息
  ← AI："采购订单已创建成功，单号 PO-2026-xxx"
```

---

## 10. 测试要点

- [ ] L0 工具（query_erp_list）：无任何拦截，直接执行
- [ ] L2 工具：前端弹窗出现，确认后工具正常执行
- [ ] L2 工具：用户点取消，工具不执行，trace 记录 rejected
- [ ] 超时 30s 未操作：自动取消，trace 记录 timeout
- [ ] 并发两个 run 同时等待确认：confirm_id 互不干扰
- [ ] Trace 面板：write 步骤正确显示 decision 及颜色
