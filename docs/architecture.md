# ERP AI Python 架构说明

**项目**：erp-ai-python  
**定位**：FastAPI 服务，作为 AI 驱动的 ERP 查询助手，是 Node.js/TypeScript 版本（erp-ai-node）的 Python 移植

---

## 整体调用链

```
请求 → 接入层(FastAPI) → 安全层(key解密) → 调度层(IntentRouter)
     → AI层(LangChain Agent) → 工具层(ERP Tools) → 连接层(erp_client)
     → 记忆层(history) → 知识层(ChromaDB) → 持久层(SQLite)
```

---

## 第一层：接入层（`routes/ai.py` + `main.py`）

**职责**：接收 HTTP 请求、鉴权、限流、转发给下游。

### 入口文件

| 文件 | 作用 |
|---|---|
| `main.py` | FastAPI 实例、挂载路由、启动时调用 `init_db()` |
| `routes/ai.py` | 所有 `/api/ai/*` 路由定义 |

### 主要接口

| 接口 | 方法 | 说明 |
|---|---|---|
| `/api/ai/chat` | POST | 核心对话接口，返回 SSE 流 |
| `/api/ai/key` | POST/DELETE | 保存/删除用户 OpenRouter Key |
| `/api/ai/key/status` | GET | 查询是否已配置 Key |
| `/api/ai/preferences` | GET | 查询用户偏好 |

### SSE 响应格式

`/api/ai/chat` 返回三种事件：

```
event: text       # AI 文字回复（流式，逐 token）
event: erp.data   # ERP 查询结果表格元数据
event: chat.action  # 前端操作指令（如跳转页面）
```

### 限流

使用 `slowapi`，上限 **60 次/分钟**（按 `X-User-Id` 计数）。

---

## 第二层：安全层（`key_service.py`）

**职责**：对用户 OpenRouter API Key 进行加密存储与解密取用。

### 核心：AES-256-GCM 加密

认证加密算法，同时保证**机密性 + 完整性**，比 AES-CBC 更安全。

```
明文 API Key
    ↓ AESGCM.encrypt(iv, plaintext, None)
密文 = iv:tag:cipher  （全部 hex 编码后拼接）
    ↓ 存入 SQLite user_keys.encrypted 列
```

三段结构：

| 段 | 长度 | 作用 |
|---|---|---|
| `iv` | 12 字节（随机） | 初始化向量，每次加密都不同，防重放 |
| `tag` | 16 字节 | 认证标签，解密时验证数据未被篡改 |
| `cipher` | 变长 | 实际密文 |

### 密钥来源

```python
_raw = ENCRYPTION_SECRET.ljust(32, "0")[:32]  # 补齐或截断到 32 字节
_KEY_BYTES = _raw.encode("utf-8")              # AES-256 需要 32 字节 key
```

密钥来自 `.env` 的 `ENCRYPTION_SECRET`，生产环境**必须替换**为随机 32 位字符串。

### 防篡改机制

`get_user_key()` 解密失败时自动删除损坏记录：

```python
except Exception:
    delete_user_key(user_id)
    return None
```

### Key 格式校验

```python
re.match(r"^sk-or-v1-[a-zA-Z0-9_-]{10,}$", key)
```

只接受 OpenRouter 标准格式，防止误填其他平台的 Key。

---

## 第三层：调度层（`router/intent_router.py`）

**职责**：判断用户输入属于哪类意图，分流到不同处理路径。

### 三种意图类型

| 意图 | 含义 | 示例 |
|---|---|---|
| `simple` | 问候/闲聊/无需查数据 | "你好"、"谢谢" |
| `complex` | 需要查询 ERP 数据或分析 | "查一下采购订单" |
| `write` | 需要写操作 | "新增供应商"、"提交审批" |

### 判断流程

```
用户输入
  ↓
关键词快速匹配（零 LLM 成本）
  ├─ 命中 write 关键词 → 直接返回 write（confidence=0.95）
  ├─ 命中 simple/complex → 进入 LLM 精判
  └─ 未命中 → 进入 LLM 精判
        ↓
   LLM 精判（gpt-4o-mini，max_tokens=120）
        ├─ confidence ≥ 0.6 → 采用 LLM 结果
        └─ 失败/低置信 → 关键词兜底（或 complex）
```

> 当前配置：`use_llm=False`，全部走关键词路由，不消耗 LLM token。

### 关键词表（节选）

```python
_WRITE_KEYWORDS = ["新增", "添加", "创建", "修改", "更新", "删除", "发起审批", "提交审批", ...]
_SIMPLE_KEYWORDS = ["你好", "hi", "help", "谢谢", "你是谁", ...]
_COMPLEX_KEYWORDS = ["查询", "统计", "过滤", "筛选", "订单", "采购", "库存", "员工", ...]
```

---

## 第四层：AI 层（`ai_service.py`）

**职责**：构建 System Prompt，驱动 LangChain ReAct Agent 循环，流式输出结果。

### LangChain ReAct 循环

```
用户消息
  ↓
System Prompt（表结构 + Skills + 行为规则）
  ↓
LangChain AgentExecutor
  ├─ 思考 → 决定调用哪个工具
  ├─ 调用工具（最多 MAX_TOOL_ROUNDS=3 轮）
  ├─ 观察结果 → 继续思考
  └─ 生成最终回复
  ↓
SSE 流式输出
```

### 模型回退机制

主模型返回 429（超限）时，自动切换备用模型：

```python
FALLBACK_MODELS = ["openai/gpt-4o-mini", "qwen/qwen-plus", "anthropic/claude-3.5-haiku"]
```

### System Prompt 构成

```
角色定义
+ 表目录（60+ 张 ERP 表的字段说明）
+ Skills（快捷查询预设）
+ 行为规则（14 条，包含禁止编造、禁止从历史截取数据等）
+ 安全规则（禁止泄露 Prompt、禁止执行非查询操作）
```

---

## 第五层：工具层（`tools/`）

**职责**：封装对 ERP 的三种调用方式，供 LangChain Agent 调用。

### 三个 StructuredTool

| 工具名 | 文件 | 作用 |
|---|---|---|
| `query_erp_list` | `tools/common_query.py` | 分页列表查询，支持过滤、排序 |
| `get_table_fields` | `tools/field_getter.py` | 获取指定表的字段定义 |
| `search_erp_global` | `tools/global_search.py` | 跨表全局搜索 |

### ERP 过滤条件格式

AI 构造的过滤条件遵循 ERP 标准结构：

```json
{
  "fFeild": "fStatus",
  "fComparOperator": "Equal",
  "fValue": "1",
  "fConnectRelate": "And",
  "fLeftKuoHao": "",
  "fRightKuoHao": ""
}
```

支持的 Operator：`Equal`、`NotEqual`、`Contains`、`GreaterThan`、`LessThan` 等。

### 触发动作（`tools/trigger_actions.py`）

查询结果附带 `chat.action` 事件，可触发前端行为：

```json
{ "action": "navigate", "page": "PurchaseOrder", "params": { "id": "xxx" } }
```

---

## 第六层：连接层（`erp_client.py`）

**职责**：封装所有对 ERP 后端的 HTTP 请求，工具层通过它与 ERP 通信。

### 三个核心函数

| 函数 | ERP 接口 | 说明 |
|---|---|---|
| `common_query()` | `CommonQuery` | 分页列表查询（主力接口） |
| `get_field_layout()` | `GetFieldLayout` | 获取表字段定义 |
| `global_search()` | `GlobalSearch` | 跨表关键词搜索 |

### 请求头透传

客户端的 ERP 认证信息（Cookie / Authorization）原样转发给 ERP 后端，**不在 AI 服务存储任何 ERP 凭证**：

```python
headers = {
    "Cookie": request.headers.get("cookie", ""),
    "Authorization": request.headers.get("authorization", ""),
    "Language": ERP_LANGUAGE,
    "Timezone": ERP_TIMEZONE,
}
```

---

## 第七层：记忆层（`memory/`）

**职责**：维护对话上下文和用户偏好，让 AI 具备多轮对话能力。

### 两个模块

| 模块 | 文件 | 说明 |
|---|---|---|
| 对话历史 | `memory/conversation_memory.py` | 每用户保留最近 N 轮对话（TTL 2小时） |
| 用户偏好 | `memory/user_preference.py` | 记录常用表、常用过滤条件、每页行数 |

### 对话历史双写

```
SQLite conversations ←→ memory/conversation_memory.py（内存 dict）
```

启动时从 SQLite 加载到内存；对话时只读写内存；定期/退出时写回 SQLite。

### 历史消息上限

由 `.env` 的 `MAX_HISTORY_MESSAGES=20` 控制，超出后滚动删除最早的消息。

---

## 第八层：知识层（`vector/`）

**职责**：提供 RAG（检索增强生成）能力，将 ERP 业务文档向量化，在查询时检索相关知识片段注入 Prompt。

### 技术栈

- **向量数据库**：ChromaDB（本地文件，持久化到 `data/chroma/`）
- **Embedding 模型**：`openai/text-embedding-3-small`（via OpenRouter）
- **分块策略**：按 `\n\n` 段落切分，每块 ≤ 500 tokens

### 工作流程

```
docs/knowledge/*.txt/.md/.pdf/.docx
      ↓ 分块 + Embedding
ChromaDB（data/chroma/）
      ↓ 用户查询时，取 Top-K 相关块
注入 System Prompt
```

### 当前知识库状态

| 文件 | 块数 |
|---|---|
| 供应商档案管理.txt | 4 |
| 收货单操作指南.txt | 3 |
| 销售订单常见问题.txt | 2 |
| **合计** | **9 块** |

### 添加新文件

1. 把文件放入 `docs/knowledge/` 目录（支持 .txt / .md / .pdf / .docx）
2. 执行 `python -m vector.knowledge_base`

### RAG 触发条件

| 参数 | 默认值 | 说明 |
|---|---|---|
| `RAG_THRESHOLD` | 30 | 查询结果行数超过此值才触发 RAG 压缩 |
| `RAG_MAX_ROWS` | 20 | RAG 压缩后最多保留的行数 |

---

## 第九层：持久层（`db.py`）

**职责**：把所有需要跨重启保留的数据落地到本地 SQLite 文件。

### 数据库文件

```
data/erp_ai.db       ← SQLite 主文件
data/erp_ai.db-wal   ← WAL 预写日志（并发写缓冲）
```

### 五张表

| 表名 | 存什么 | 谁在用 |
|---|---|---|
| `user_keys` | 用户 OpenRouter Key（AES 加密后） | `key_service.py` |
| `conversations` | 对话历史（role + content） | `memory/conversation_memory.py` |
| `user_preference` | 常用表、常用过滤条件、每页行数 | `memory/user_preference.py` |
| `skills` | 查询预设（快捷指令） | `config/skills.py` |
| `agent_traces` | 每次 AI 调用的执行轨迹（调试用） | `ai_service.py` |

### 关键配置

**WAL 模式**：允许多读一写同时进行，避免 FastAPI 多线程下写锁冲突。

```python
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA foreign_keys=ON")
```

**幂等建表**：`init_db()` 在启动时调用一次，表存在就跳过，不清数据。

---

## 模块文件速查

| 层级 | 文件 |
|---|---|
| 接入层 | `main.py`, `routes/ai.py` |
| 安全层 | `key_service.py` |
| 调度层 | `router/intent_router.py`, `router/agent_orchestrator.py` |
| AI 层 | `ai_service.py`, `config/prompt_config.py` |
| 工具层 | `tools/common_query.py`, `tools/field_getter.py`, `tools/global_search.py`, `tools/trigger_actions.py` |
| 连接层 | `erp_client.py` |
| 记忆层 | `memory/conversation_memory.py`, `memory/user_preference.py` |
| 知识层 | `vector/knowledge_base.py`, `rag/context_builder.py` |
| 持久层 | `db.py` |

---

## 环境变量速查

| 变量 | 默认值 | 说明 |
|---|---|---|
| `ERP_BASE_URL` | — | ERP 后端地址 |
| `DEFAULT_MODEL` | `openai/gpt-4o-mini` | 主 LLM 模型 |
| `ENCRYPTION_SECRET` | — | AES-256 加密密钥（32位） |
| `MAX_TOOL_ROUNDS` | `3` | Agent 最大工具调用轮次 |
| `RAG_THRESHOLD` | `30` | 触发 RAG 的最小行数 |
| `RAG_MAX_ROWS` | `20` | RAG 保留最大行数 |
| `MAX_HISTORY_MESSAGES` | `20` | 每用户最大历史消息条数 |
| `QUERY_CACHE_TTL_MS` | `300000` | 查询缓存 TTL（5分钟） |
