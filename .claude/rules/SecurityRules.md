# SecurityRules — 安全编码规范

> 安全问题是 **阻塞级**，不符合此规范的代码不得合入。

---

## 1. 输入校验（最高优先级）

### 入口防护

```python
from security.input_guard import InputGuard

guard = InputGuard()

# ✅ 所有用户输入必须过 InputGuard
@router.post("/api/ai/chat")
async def chat(request: ChatRequestBody, ...):
    result = guard.check(request.message)
    if result.risk_level == "high":
        raise HTTPException(status_code=400, detail="输入包含不安全内容")

# ✅ Pydantic 模型必须设置约束
class ChatRequestBody(BaseModel):
    message: str = Field(min_length=1, max_length=500)  # 长度限制
    conversation_id: str | None = Field(default=None, max_length=64)
```

### 必须拦截的模式

- SQL 注入关键字：`DROP`, `DELETE`, `INSERT`, `UPDATE`, `UNION`, `--`, `';`
- 路径穿越：`../`, `..\`
- 脚本注入：`<script>`, `javascript:`, `onerror=`
- Prompt 注入：试图覆盖系统提示词的内容

---

## 2. API Key 安全

```python
# ✅ 加密存储（AES-256-GCM）
from key_service import save_user_key, get_user_key

save_user_key(user_id, openrouter_key)      # 自动加密
key = get_user_key(user_id)                  # 自动解密

# ❌ 禁止的行为
# 不记录 Key 到日志
logger.info("Auth", f"用户={user_id} Key={openrouter_key}")  # 违规!

# 不返回 Key 给前端
return {"key": openrouter_key}  # 违规!

# 不硬编码 Key
OPENROUTER_KEY = "sk-or-v1-xxxx"  # 违规! 用环境变量
```

---

## 3. ERP 接口调用安全

```python
# ✅ 用户凭证透传，服务端不存储
headers = {}
if erp_cookie:
    headers["Cookie"] = erp_cookie
if erp_authorization:
    headers["Authorization"] = erp_authorization

# ✅ ERP 接口错误不泄露后端细节
except httpx.HTTPStatusError as e:
    # 不返回原始响应体
    return json.dumps({"error": "ERP 接口请求失败"})
    # 不返回堆栈信息
    # 不返回内网 IP/端口
```

---

## 4. 日志安全

```python
# ❌ 绝对不记录
logger.info("Auth", f"用户密码: {password}")
logger.info("KeyService", f"解密密钥: {ENCRYPTION_SECRET}")
logger.info("ERP", f"Cookie: {erp_cookie}")        # Cookie 含会话 token

# ✅ 安全写法
logger.info("Auth", f"用户 {user_id} 登录成功")     # 只记 user_id
logger.info("KeyService", "存储密钥成功")            # 不记密钥内容
logger.info("ERP", f"请求 Query | 表={table_name}")  # 不记 Cookie
```

---

## 5. 依赖安全

```bash
# 定期检查已知漏洞
pip-audit
# 或
safety check
```

- requirements.txt 中依赖版本用 `>=` 而非固定版本，允许安全补丁
- 新增第三方库前评估其维护状态和安全记录

---

## 6. 数据输出安全

```python
# ✅ 返回给前端的数据必须脱敏
def sanitize_erp_response(data: list[dict]) -> list[dict]:
    """移除不应暴露的字段"""
    SENSITIVE_FIELDS = {"Password", "Token", "SecretKey", "IdNumber"}
    return [
        {k: v for k, v in row.items() if k not in SENSITIVE_FIELDS}
        for row in data
    ]
```

---

## 7. 安全检查清单

PR 提交前自查：

- [ ] 所有用户输入点有 InputGuard 或 Pydantic 校验
- [ ] SQL/命令注入风险已排除（使用参数化查询，不拼接字符串）
- [ ] API Key、密码、Token 未出现在日志、返回值、URL 参数中
- [ ] ERP 错误响应不泄露后端架构信息（IP、端口、数据库表结构等）
- [ ] 新增依赖经过安全性评估
- [ ] 敏感数据在传输/存储中已加密
