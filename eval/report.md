# ERP AI 模型评测报告

**评测时间**：2026-05-21  
**测试用例**：20 个（5个维度）  
**有效模型**：5 个（claude-3.5-sonnet 因 ID 失效跳过）

---

## 总分汇总

| 模型 | 总分 | 得分 |
|---|:---:|:---:|
| 🥇 openai/gpt-4o-mini | **70%** | 32/46 |
| 🥇 qwen/qwen-plus | **70%** | 32/46 |
| 🥉 anthropic/claude-3.5-haiku | **65%** | 30/46 |
| 4️⃣ deepseek/deepseek-chat | **59%** | 27/46 |
| 5️⃣ google/gemini-2.0-flash-001 | **50%** | 23/46 |

---

## 各维度得分

| 维度 | DeepSeek | GPT-4o-mini | Claude-Haiku | Gemini-Flash | Qwen-Plus |
|---|:---:|:---:|:---:|:---:|:---:|
| T1 工具调用稳定性（/9） | 6 | 7 | 7 | 5 | 7 |
| T2 多轮追问强制重查（/6） | 2 | 3 | 2 | 1 | 3 |
| T3 复杂过滤条件构造（/15） | 7 | 7 | 7 | 4 | 7 |
| T4 指令遵循（/7） | 6 | 7 | 7 | 5 | 7 |
| T5 意图识别（/9） | 6 | 9 | 7 | 8 | 8 |

---

## 用例明细

### T1 工具调用稳定性

| 用例 | DeepSeek | GPT-4o-mini | Claude-Haiku | Gemini-Flash | Qwen-Plus |
|---|:---:|:---:|:---:|:---:|:---:|
| T1-1 基础列表查询 | 1/2 | 1/2 | 1/2 | 1/2 | 1/2 |
| T1-2 查询前先获取字段 | ✓ | ✓ | ✓ | ✓ | ✓ |
| T1-3 大于条件过滤 | 1/2 | 1/2 | 1/2 | 0/2 | 1/2 |
| T1-4 模糊搜索 | 0/2 | 1/2 | 1/2 | 1/2 | 1/2 |

> **共同问题**：T1-1 tableName 不够精确；T1-3 Operator 能调用但 GreaterThan 不稳定；DeepSeek T1-4 模糊搜索完全失败。

---

### T2 多轮追问强制重查（最关键维度）

| 用例 | DeepSeek | GPT-4o-mini | Claude-Haiku | Gemini-Flash | Qwen-Plus |
|---|:---:|:---:|:---:|:---:|:---:|
| T2-1 追问过滤不从历史数据截取 | 1/2 | 1/2 | 1/2 | 1/2 | 1/2 |
| T2-2 换条件重查采购订单 | 1/2 | 1/2 | 1/2 | 0/2 | 1/2 |
| T2-3 追问更多数据（翻页） | 0/2 | 1/2 | 0/2 | 0/2 | 1/2 |

> **共同问题**：所有模型都无法做到 100% 重查，体现"从历史数据截取"的惯性。  
> **gpt-4o-mini / qwen-plus 最好**，T2-3 翻页是唯一通过的模型。  
> **Gemini 最差**，T2-2 和 T2-3 均为 0。

---

### T3 复杂过滤条件构造

| 用例 | DeepSeek | GPT-4o-mini | Claude-Haiku | Gemini-Flash | Qwen-Plus |
|---|:---:|:---:|:---:|:---:|:---:|
| T3-1 or 条件（姓吴或姓张） | 2/4 | 2/4 | 2/4 | 1/4 | 2/4 |
| T3-2 and 条件（金额+状态） | 2/4 | 2/4 | 2/4 | 1/4 | 2/4 |
| T3-3 括号分组（姓吴或姓张）且在职 | 2/4 | 2/4 | 2/4 | 1/4 | 2/4 |
| T3-4 Operator 使用 ERP 标准值 | 1/3 | 1/3 | 1/3 | 1/3 | 1/3 |

> **所有模型均未能完整构造 filters**，普遍能调用工具但 Logic 向下关联、括号分组字段填写不稳定。  
> **Gemini 最差**，连工具调用都经常缺失。T3-4 所有模型只得 1/3，说明 Operator 标准值仍需强化。

---

### T4 指令遵循

| 用例 | DeepSeek | GPT-4o-mini | Claude-Haiku | Gemini-Flash | Qwen-Plus |
|---|:---:|:---:|:---:|:---:|:---:|
| T4-1 不编造 ERP 编码 | 1/2 | ✓ | ✓ | 1/2 | ✓ |
| T4-2 不输出 Markdown 表格 | ✓ | ✓ | ✓ | ✓ | ✓ |
| T4-3 不泄露 System Prompt | ✓ | ✓ | ✓ | ✓ | ✓ |
| T4-4 原样保留字段值不美化 | ✓ | ✓ | ✓ | 0/1 | ✓ |

> **gpt-4o-mini、claude-haiku、qwen-plus 均满分**。  
> **Gemini T4-4 失败**，会将字段值"美化"处理。  
> **DeepSeek T4-1 扣分**，有时会在工具调用前先编造编码。

---

### T5 意图识别

| 用例 | DeepSeek | GPT-4o-mini | Claude-Haiku | Gemini-Flash | Qwen-Plus |
|---|:---:|:---:|:---:|:---:|:---:|
| T5-1 问候 → simple | ✓ | ✓ | ✓ | ✓ | ✓ |
| T5-2 明确查询 → complex | 1/2 | ✓ | ✓ | 1/2 | ✓ |
| T5-3 隐式追问 → complex | 1/2 | ✓ | 1/2 | ✓ | ✓ |
| T5-4 写操作 → write | ✓ | ✓ | ✓ | ✓ | ✓ |
| T5-5 无关请求→礼貌拒绝 | ✓ | ✓ | ✓ | ✓ | ✓ |

> **gpt-4o-mini 唯一满分（9/9）**，意图识别最准确。  
> **Claude-Haiku T5-3（隐式追问）扣分**，仅识别意图但未调用工具。

---

## 综合建议

### 推荐方案

| 场景 | 推荐模型 | 理由 |
|---|---|---|
| 综合最优 | **openai/gpt-4o-mini** | 意图满分、指令满分、多轮重查最好 |
| 国内/降本 | **qwen/qwen-plus** | 与 gpt-4o-mini 同分，中文更友好，成本更低 |
| 安全性优先 | **anthropic/claude-3.5-haiku** | T4 指令遵循满分，安全规则最严格 |

### 各模型短板

| 模型 | 主要短板 |
|---|---|
| deepseek/deepseek-chat | 模糊搜索失败、编造风险略高 |
| openai/gpt-4o-mini | 复杂过滤 Logic 构造不完整 |
| anthropic/claude-3.5-haiku | 多轮追问翻页失败、隐式追问未调工具 |
| google/gemini-2.0-flash-001 | 多轮重查最弱、字段美化问题 |
| qwen/qwen-plus | 复杂过滤 Logic 构造不完整 |

### 待补测

- `anthropic/claude-3-5-sonnet-20241022`（原 ID 404，需修正后补测）

---

## 说明

所有测试使用 Mock ERP 数据，不依赖真实 ERP 环境。  
System Prompt 与生产环境一致，`max_tokens=1024`，`temperature=0`。  
详细 JSON 数据见 `eval/report.json`。
