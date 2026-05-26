# CodingStandardRules — Python 编码规范

> 本项目为 FastAPI + LangChain 的 AI ERP 服务，Python 3.11+，注释用中文。

---

## 1. 命名规范

| 类别 | 风格 | 示例 |
|------|------|------|
| 模块/文件名 | `snake_case` | `erp_client.py`, `ai_service.py` |
| 函数/方法 | `snake_case` | `call_common_query()`, `build_system_prompt()` |
| 私有函数 | `_snake_case` | `_to_erp_api_filters()`, `_decrypt()` |
| 类名 | `PascalCase` | `InputGuard`, `FieldLayoutCache` |
| Pydantic 模型 | `PascalCase` | `ChatRequestBody`, `FilterItem` |
| 变量 | `snake_case` | `erp_cookie`, `raw_tool_result` |
| 模块级常量 | `UPPER_SNAKE_CASE` | `MAX_TOOL_ROUNDS`, `ERP_BASE_URL` |
| 布尔变量 | `is_`/`has_`/`should_` 前缀 | `tools_were_called`, `is_streaming` |

### 特殊说明

- **Pydantic 字段名用 PascalCase**：为对齐 ERP 后端 JSON 协议（如 `FieldName`, `Operator`），这是有意设计，不要被 linter "纠正"
- **ERP 接口参数用 `dict`**：动态结构无固定 schema，不需要强行定义 Pydantic 模型

---

## 2. 类型注解

### 强制要求

```python
# ✅ 公共 API 函数必须完整注解
async def chat_with_ai(
    request: dict,
    openrouter_key: str,
    erp_cookie: str = "",
    user_id: str = "",
) -> AsyncGenerator[str, None]:
    ...

# ✅ 使用 Python 3.10+ 现代语法
def get_user_key(user_id: str) -> str | None: ...
accumulated_answer: list[str] = []
tool_map: dict[str, Any] = {}

# ✅ Pydantic 模型用 Field 加约束
class CommonQueryInput(BaseModel):
    table_name: str = Field(description="ERP 表名")
    page_size: int = Field(default=20, ge=1, le=100)
```

### 允许的例外
- 内部辅助函数如果上下文足够清晰，可省略
- `*args`, `**kwargs` 无法精确注解时注明 `# type: ignore[no-untyped-def]`

---

## 3. 导入规范

```python
# ==== 顺序：标准库 → 第三方 → 项目内部 ====

# 标准库
import os, json, time
from abc import ABC, abstractmethod
from typing import AsyncGenerator, Optional

# 第三方
from fastapi import FastAPI, HTTPException
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

# 项目内部（绝对导入，从项目根出发）
from logger import logger, start_timer
from config.prompt_config import build_system_prompt
from erp_client import call_common_query
```

### 关键规则
- **使用绝对导入**，不用相对导入（`from .xxx`）
- 只在**避免循环依赖**时才用函数内 `import`
- 不使用 `import *`

---

## 4. 文件结构

```python
"""
模块用途简述 — 对应原 TypeScript 文件 src/xxx.ts
"""

# ===================== 导入 =====================
...

# ===================== 常量 =====================
MAX_TOOL_ROUNDS = int(os.getenv("MAX_TOOL_ROUNDS", "3"))

# ===================== 数据模型 =====================
class XxxInput(BaseModel): ...

# ===================== 核心逻辑 =====================
def main_function(): ...

# ===================== 辅助函数 =====================
def _helper(): ...
```

### 规则
- 文件头用三引号 `"""..."""` docstring，不要用 koro1FileHeader 自动头
- 用 `# ====` 分隔线（约 20 个 `=`）划分段落
- 注释用中文，代码用英文

---

## 5. 日志规范

```python
from logger import logger, start_timer

# 级别方法
logger.info("模块名", "简短描述")
logger.success("模块名", "操作成功描述")
logger.warn("模块名", "警告描述")
logger.error("模块名", f"错误描述 | 详情={detail}")
logger.ai("模块名", "AI 调用描述")       # 洋红色
logger.erp("模块名", "ERP 调用描述")      # 蓝色

# 计时
t = start_timer()
# ... 操作 ...
logger.info("Done", f"耗时={t()}ms")
```

### 规则
- 第一个参数是模块/功能标识（如 `"CommonQuery"`, `"LangChain"`），不是文件名
- 敏感数据（API key、用户密码）**禁止**写入日志
- 错误日志必须包含足够的上下文信息用于排查

---

## 6. 错误处理

```python
# ✅ 分层策略
# 工具/客户端层 — 返回 error JSON 字符串
return json.dumps({"error": "错误描述（中文）"})

# 路由层 — 抛出 HTTPException
raise HTTPException(status_code=400, detail="用户 ID 缺失")

# AI Service 层 — 通过 SSE 流推送错误
yield f"data: {json.dumps({'error': '...'})}\n\n"

# ✅ 精确捕获优先
try:
    response = await client.post(url, json=body)
except httpx.HTTPStatusError as e:       # 先精确
    ...
except Exception as e:                   # 后宽泛
    ...

# ✅ 降级有兜底
except Exception as e:
    logger.error("Module", f"操作失败 | {e}")
    return fallback_value                 # 必须返回可用值
```

### 禁止
- ❌ 裸 `except:` 不带异常类型
- ❌ `except Exception: pass` （除非有明确理由且加注释说明）
- ❌ 异常不记录日志直接吞掉

---

## 7. 代码风格

- **缩进**：4 空格（不用 Tab）
- **行宽**：120 字符
- **文件编码**：UTF-8
- **行尾**：LF
- **空行**：函数间 2 空行，类方法间 1 空行，逻辑段落间 1 空行
- **字符串**：优先用双引号 `"`，f-string 用于拼接

---

## 8. 禁止事项

- ❌ 注释掉的代码（删掉，需要时可从 git 找回）
- ❌ `print()` 调试（用 `logger` 替代）
- ❌ 硬编码的魔法数字（提取为命名常量）
- ❌ 超过 100 行的函数（拆分）
- ❌ 超过 500 行的文件（拆分模块）
