# UnitTestRules — 单元测试规范

> 目标：**行覆盖率 ≥ 90%**，每个功能点至少 3 个测试场景。

---

## 1. 测试框架

```bash
# 引入依赖
pip install pytest pytest-asyncio pytest-cov pytest-mock

# 运行测试
pytest tests/ -v --cov=. --cov-report=term-missing
```

| 工具 | 用途 |
|------|------|
| `pytest` | 测试运行器 |
| `pytest-asyncio` | 异步测试支持（本项目大量 async 函数） |
| `pytest-cov` | 覆盖率报告 |
| `pytest-mock` | Mock 工具（替代 unittest.mock） |

---

## 2. 测试目录结构

```
tests/
├── conftest.py              # 共享 fixtures
├── test_ai_service.py       # 核心 AI 服务测试
├── test_erp_client.py       # ERP 客户端测试
├── test_tools/              # 工具测试
│   ├── test_query_erp.py
│   ├── test_global_search.py
│   └── test_field_layout.py
├── test_security/           # 安全模块测试
│   └── test_input_guard.py
├── test_memory/             # 记忆/缓存测试
│   ├── test_conversation.py
│   └── test_query_cache.py
└── test_routes/             # API 路由测试
    └── test_ai_chat.py
```

---

## 3. 测试用例三要素（强制）

每个功能点至少覆盖：

| 场景 | 说明 | 示例 |
|------|------|------|
| **正常路径** | 给定合法输入，期望正确输出 | `test_chat_with_valid_message_returns_200` |
| **边界条件** | 空值、最大值、分页边界 | `test_empty_message_rejected` |
| **异常路径** | ERP 不可达、模型 429、超长输入 | `test_erp_401_returns_auth_error` |

---

## 4. 测试命名

```python
# 格式：test_<被测函数>_<场景>_<期望结果>
def test_validate_input_sql_injection_returns_high_risk(): ...
def test_call_common_query_empty_table_returns_empty_list(): ...
def test_chat_route_missing_user_id_returns_400(): ...
```

---

## 5. 异步测试模板

```python
import pytest
from unittest.mock import AsyncMock, patch

@pytest.mark.asyncio
async def test_chat_with_ai_normal_flow():
    """正常对话流程：用户提问 → AI 调用工具 → 返回答案"""
    mock_llm = AsyncMock()
    mock_llm.ainvoke.return_value = AIMessage(content="查询结果如下...")

    with patch("ai_service.create_model", return_value=mock_llm):
        chunks = []
        async for chunk in chat_with_ai(
            request={"message": "查询订单"},
            openrouter_key="test-key",
        ):
            chunks.append(chunk)

    assert len(chunks) > 0
    assert any("查询结果" in c for c in chunks)
```

---

## 6. Mock 规范

```python
# ✅ 正确的 Mock 姿势：Mock 外部依赖，不 Mock 内部逻辑

# Mock HTTP 调用（ERP 接口）
with patch("erp_client.httpx.AsyncClient.post") as mock_post:
    mock_post.return_value.json.return_value = {"data": [...]}
    result = await call_common_query({...})

# Mock LLM 调用
with patch("langchain_openai.ChatOpenAI.ainvoke") as mock_llm:
    mock_llm.return_value = AIMessage(content="答案")
    ...

# ❌ 不要 Mock 自己的工具函数内部逻辑
# ❌ 不要 Mock 标准库基础函数（json.loads, os.getenv 等）
```

---

## 7. Fixture 规范

```python
# tests/conftest.py

@pytest.fixture
def sample_query_request():
    """标准查询请求 fixture"""
    return {
        "message": "查询最近一周的采购订单",
        "conversationId": None,
    }

@pytest.fixture
def mock_erp_response():
    """模拟 ERP 正常返回"""
    return {
        "data": [
            {"OrderNo": "PO-001", "Amount": 1000},
            {"OrderNo": "PO-002", "Amount": 2000},
        ],
        "total": 2,
    }
```

---

## 8. 覆盖率检查清单

PR 提交前必须：

- [ ] `pytest tests/ --cov=. --cov-report=term-missing` 通过
- [ ] 新增代码行覆盖率 ≥ 90%
- [ ] 所有测试用例有清晰的 docstring 说明测试意图
- [ ] 无跳过的测试（`@pytest.mark.skip`）除非有明确的 TODO 注释
