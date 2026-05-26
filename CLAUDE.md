# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Coding Rules（编码规范）

所有代码改动必须遵循 `.claude/rules/` 目录下的规范文件：

| 规则文件 | 内容 |
|---------|------|
| [WorkflowRules.md](.claude/rules/WorkflowRules.md) | 工作流规范：先出 Spec 再写代码 |
| [GitBranchRules.md](.claude/rules/GitBranchRules.md) | 分支命名与 Commit 规范 |
| [CodingStandardRules.md](.claude/rules/CodingStandardRules.md) | Python 编码规范（命名、类型注解、日志等） |
| [UnitTestRules.md](.claude/rules/UnitTestRules.md) | 单元测试规范（覆盖率 ≥ 90%） |
| [SecurityRules.md](.claude/rules/SecurityRules.md) | 安全编码规范（输入校验、Key 保护等） |
| [DesignSpecRules.md](.claude/rules/DesignSpecRules.md) | 设计规范（Spec 模板） |

## Running the Service

```bash
# Start with auto-reload (development)
uvicorn main:app --host 0.0.0.0 --port 3001 --reload

# Or directly
python main.py
```

Copy `.env.example` to `.env` and fill in required values before running.

## Key Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `ERP_BASE_URL` | — | ERP backend URL (e.g. `http://10.35.110.70:9090`) |
| `DEFAULT_MODEL` | — | OpenRouter model ID (e.g. `anthropic/claude-3.5-sonnet`) |
| `ENCRYPTION_SECRET` | — | AES-256-GCM key for encrypting user API keys |
| `MAX_TOOL_ROUNDS` | `3` | Max LangChain agent tool-call iterations per query |
| `RAG_THRESHOLD` | `30` | Row count above which RAG compression activates |
| `RAG_MAX_ROWS` | `20` | Max rows kept after RAG compression |
| `QUERY_CACHE_TTL_MS` | `300000` | Query cache TTL (5 min) |
| `MAX_HISTORY_MESSAGES` | `20` | Conversation history pairs per user |

## Architecture

This is a FastAPI service that acts as an AI-powered ERP query assistant. It is a Python port of a Node.js/TypeScript project (`erp-ai-node`); comments throughout reference the TypeScript originals.

### Request Flow

```
POST /api/ai/chat
  → routes/ai.py          # validates X-User-Id header, resolves OpenRouter key
  → ai_service.py         # builds system prompt, runs LangChain agent loop
    → tools/              # LangChain StructuredTools call erp_client.py
    → rag/context_builder.py  # compresses results if > RAG_THRESHOLD rows
    → cache/query_cache.py    # SHA-256 keyed LRU cache with TTL
  → SSE stream back to client (includes AI text + ERP data table metadata)
```

### Module Responsibilities

- **`ai_service.py`** — LangChain agent loop, system prompt construction, model invocation, SSE streaming, model fallback on 429
- **`erp_client.py`** — HTTP calls to ERP backend: `CommonQuery`, global search, field-layout endpoints
- **`tools/`** — Three LangChain StructuredTools: `query_erp_list` (paginated table query), `get_table_fields` (field layout), `search_erp_global` (cross-table search)
- **`config/prompt_config.py`** — Assembles system prompt from table catalog + skills + behavior/security rules
- **`config/table_catalog.py`** — Auto-generated registry of 60+ ERP tables with field names and query parameters; regenerate from the Node.js template when tables change
- **`config/skills.py`** — Named query presets (employee view, PO alert amounts, SO status filters, etc.) injected into the system prompt
- **`memory/conversation_memory.py`** — In-memory per-user message history (TTL 2 hrs)
- **`rag/context_builder.py`** — Scores each ERP row for relevance and keeps top `RAG_MAX_ROWS`
- **`cache/query_cache.py`** — Normalizes ERP query params → SHA-256 key → LRU cache
- **`key_service.py`** — AES-256-GCM encrypt/decrypt for user OpenRouter API keys
- **`app_types.py`** — All Pydantic models (`ChatRequest`, `ErpFilter`, `CommonQueryRequest`, etc.); `types.py` re-exports these to avoid shadowing Python's `types` module

### Auth Model

- **ERP auth**: client passes cookie/Authorization headers per-request; service forwards them to ERP
- **LLM auth**: per-user OpenRouter API keys stored encrypted in memory; retrieved via `X-User-Id` header
- No database; all state (keys, history, cache, preferences) is in-memory and lost on restart
