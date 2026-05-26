# GitBranchRules — 分支与提交规范

---

## 分支命名

```
<type>/<描述>
```

| type | 用途 | 示例 |
|------|------|------|
| `feature/` | 新功能开发 | `feature/ai-chat-multi-round` |
| `bugfix/` | Bug 修复 | `bugfix/sse-stream-truncate` |
| `refactor/` | 重构（不改变功能） | `refactor/erp-client-httpx` |
| `chore/` | 工程化/配置/依赖 | `chore/add-ruff-lint` |
| `docs/` | 文档变更 | `docs/api-readme-update` |

**描述部分**：小写英文，用 `-` 连接，简洁明了，3-5 个单词。

---

## Commit 规范

### 格式

```
<type>(<scope>): <简短描述>

[可选详细说明]
```

| type | 示例 |
|------|------|
| `feat` | `feat(ai): 支持多轮对话上下文` |
| `fix` | `fix(erp): 修复 CommonQuery 401 错误返回格式` |
| `refactor` | `refactor(tools): 抽取通用过滤条件构建器` |
| `chore` | `chore(deps): 升级 langchain 到 0.3.x` |
| `test` | `test(eval): 新增意图路由评测用例` |
| `docs` | `docs: 更新 CLAUDE.md 架构说明` |

### scope 对照

| scope | 模块 |
|-------|------|
| `ai` | ai_service.py, routes/ai.py |
| `erp` | erp_client.py |
| `tools` | tools/ 目录 |
| `config` | config/ 目录 |
| `rag` | rag/ 目录 |
| `memory` | memory/ 目录 |
| `security` | security/ 目录 |
| `cache` | cache/ 目录 |
| `eval` | eval/ 目录 |
| `planner` | planner/ + orchestrator/ |
| `deps` | 依赖变更 |

---

## PR 规范

### 标题
同 commit 格式，但 type 可以是更业务化的措辞。

### 描述模板
```markdown
## 做了什么
-

## 测试
- [ ] 本地 uvicorn 启动正常
- [ ] eval 回归通过
- [ ] 手动测试关键路径

## 影响范围
-
```

---

## Git 操作禁忌

- ❌ 不 `push --force` 到 main/master
- ❌ 不直接在 main 上开发
- ❌ 不提交大文件（>5MB），用 `.gitignore` 排除
- ❌ 不提交 `.env`、密钥、token
