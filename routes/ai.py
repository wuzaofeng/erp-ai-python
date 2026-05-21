"""
AI 路由 - 对应 src/routes/ai.ts
使用 FastAPI 替代 Express Router
"""
from __future__ import annotations

import json
import os
from typing import Optional

from fastapi import APIRouter, Request, Header, Query, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel, Field

from ai_service import test_openrouter_key
from key_service import save_user_key, get_user_key, has_user_key, delete_user_key, validate_key_format
from logger import logger, start_timer
from security.input_guard import input_guard
from security.human_in_loop import human_in_loop
from security.rate_limiter import limiter
from config.skills import list_skills, get_skill_by_key, create_skill, update_skill, delete_skill
from memory.conversation_memory import clear_history, get_memory_stats
from memory.user_preference import clear_preference, get_preference
from cache.query_cache import get_cache_stats, clear_all_cache

router = APIRouter(prefix="/api/ai")

DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "openai/gpt-4o-mini")
ERP_DATA_PREFIX = "\x00ERP_DATA:"
ACTION_DATA_PREFIX = "\x00ACTION_DATA:"
TRACE_SUMMARY_PREFIX = "\x00TRACE_SUMMARY:"

# ===================== 请求体 Schema =====================

class ChatRequestBody(BaseModel):
    message: str = Field(min_length=1, max_length=500, description="消息内容")
    pageContext: Optional[str] = None
    model: Optional[str] = None
    skillKey: Optional[str] = None
    skill: Optional[str] = Field(default=None, max_length=2000)
    history: Optional[list[dict]] = None  # 服务端 Memory 已替代，保留兼容
    navIndex: Optional[str] = Field(default=None, max_length=5000, description="前端菜单导航索引")
    conversationId: Optional[str] = Field(default=None, max_length=64, description="前端会话 ID，用于串联同一会话的多条 trace")
    isRefresh: bool = False


class SaveKeyRequest(BaseModel):
    openrouterKey: str
    userId: str


# ===================== POST /api/ai/chat =====================

@router.post("/chat")
@limiter.limit("60/minute")
async def chat_endpoint(
    body: ChatRequestBody,
    request: Request,
    x_user_id: Optional[str] = Header(default=None, alias="x-user-id"),
):
    """主对话接口，支持流式输出（Server-Sent Events）"""
    if not x_user_id:
        raise HTTPException(status_code=400, detail="缺少用户 ID（X-User-Id header）")

    guard_result = input_guard.check(body.message)
    if guard_result.risk_level == "high":
        logger.warn("Security", f"用户 {x_user_id} 输入被拦截 | 威胁: {guard_result.detected_threats}")
        raise HTTPException(status_code=400, detail={
            "error": "输入内容包含不安全内容，已被拦截",
            "code": "INPUT_BLOCKED",
        })

    user_id = x_user_id
    erp_cookie = request.headers.get("cookie", "")
    erp_authorization = request.headers.get("authorization", "")

    if not erp_cookie:
        logger.warn("Chat", f"用户 {user_id} 请求未携带 Cookie，ERP 查询可能鉴权失败")
    if not erp_authorization:
        logger.warn("Chat", f"用户 {user_id} 请求未携带 Authorization，ERP 查询可能鉴权失败")

    openrouter_key = get_user_key(user_id)
    if not openrouter_key:
        logger.warn("Chat", f"用户 {user_id} 未配置 API Key")
        return JSONResponse(
            status_code=400,
            content={
                "error": "AI Key 未配置",
                "hint": "请先在个人设置中配置 OpenRouter API Key",
                "code": "KEY_NOT_CONFIGURED",
            },
        )

    model_name = body.model or DEFAULT_MODEL
    msg_preview = body.message[:60] + "..." if len(body.message) > 60 else body.message
    logger.info("Chat", f"用户={user_id} | 页面={body.pageContext or '-'} | 消息=\"{msg_preview}\"")

    elapsed = start_timer()

    async def event_stream():
        """SSE 事件流生成器"""
        def sse_chunk(content: str) -> str:
            return "data: " + json.dumps({
                "id": "erp-ai",
                "object": "chat.completion.chunk",
                "model": model_name,
                "choices": [{"index": 0, "delta": {"content": content}, "finish_reason": None}],
            }, ensure_ascii=False) + "\n\n"

        def sse_raw_data(data: dict) -> str:
            return "data: " + json.dumps({
                "id": "erp-ai",
                "object": "erp.data",
                "model": model_name,
                "data": data,
            }, ensure_ascii=False) + "\n\n"

        def sse_action(actions: list) -> str:
            return "data: " + json.dumps({
                "id": "erp-ai",
                "object": "chat.action",
                "actions": actions,
            }, ensure_ascii=False) + "\n\n"

        request_dict = {
            "message": body.message,
            "pageContext": body.pageContext,
            "model": body.model,
            "skillKey": body.skillKey,
            "skill": body.skill,
            "navIndex": body.navIndex,
            "conversation_id": body.conversationId or "",
            "is_refresh": body.isRefresh,
        }

        # ---- AgentOrchestrator：统一入口，内部处理 simple/complex/write 分流 ----
        from orchestrator.agent_orchestrator import AgentOrchestrator
        orchestrator = AgentOrchestrator(
            api_key=openrouter_key,
            erp_config={
                "cookie": erp_cookie,
                "authorization": erp_authorization,
                "user_id": user_id,
                "pageContext": body.pageContext,
            },
        )

        try:
            async for chunk in orchestrator.execute(request_dict):
                if chunk.startswith(ERP_DATA_PREFIX):
                    try:
                        raw_json = chunk[len(ERP_DATA_PREFIX):]
                        parsed = json.loads(raw_json)
                        yield sse_raw_data(parsed)
                        logger.info(
                            "Chat",
                            f"已推送 erp.data | rows={len(parsed.get('rows', []))} | total={parsed.get('total', '-')}",
                        )
                    except json.JSONDecodeError:
                        logger.warn("Chat", "erp.data 事件 JSON 解析失败，已跳过")
                    continue
                if chunk.startswith(ACTION_DATA_PREFIX):
                    try:
                        raw_json = chunk[len(ACTION_DATA_PREFIX):]
                        parsed = json.loads(raw_json)
                        actions = parsed.get("actions", [])
                        yield sse_action(actions)
                        logger.info("Chat", f"已推送 chat.action | actions={len(actions)}")
                    except json.JSONDecodeError:
                        logger.warn("Chat", "chat.action 事件 JSON 解析失败，已跳过")
                    continue
                if chunk.startswith(TRACE_SUMMARY_PREFIX):
                    try:
                        raw_json = chunk[len(TRACE_SUMMARY_PREFIX):]
                        summary = json.loads(raw_json)
                        yield "data: " + json.dumps({
                            "id": "erp-ai",
                            "object": "agent.trace",
                            "trace": summary,
                        }, ensure_ascii=False) + "\n\n"
                        logger.info("Chat", f"已推送 agent.trace | steps={summary.get('step_count')} | status={summary.get('status')}")
                    except json.JSONDecodeError:
                        logger.warn("Chat", "agent.trace 事件 JSON 解析失败，已跳过")
                    continue
                yield sse_chunk(chunk)

            yield "data: [DONE]\n\n"
            logger.success("Chat", f"完成 | 用户={user_id} | 耗时={elapsed()}ms")

        except Exception as error:
            msg = str(error)
            logger.error("Chat", f"失败 | 用户={user_id} | {msg}")
            yield "data: " + json.dumps(
                {"error": {"message": msg, "type": "server_error"}},
                ensure_ascii=False,
            ) + "\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream; charset=utf-8",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ===================== POST /api/ai/save-key =====================

@router.post("/save-key")
async def save_key_endpoint(body: SaveKeyRequest):
    if not body.userId:
        raise HTTPException(status_code=400, detail="缺少用户 ID")
    if not body.openrouterKey:
        raise HTTPException(status_code=400, detail="OpenRouter Key 不能为空")

    if not validate_key_format(body.openrouterKey):
        raise HTTPException(
            status_code=400,
            detail={
                "error": "Key 格式不正确",
                "hint": "OpenRouter Key 格式为 sk-or-v1-xxxxxxxxxx，请从 https://openrouter.ai/keys 获取",
            },
        )

    test_result = await test_openrouter_key(body.openrouterKey)
    if not test_result["valid"]:
        raise HTTPException(status_code=400, detail=test_result["message"])

    save_user_key(body.userId, body.openrouterKey)
    return {"success": True, "message": "Key 已保存，可以开始使用 AI 功能"}


# ===================== GET /api/ai/key-status =====================

@router.get("/key-status")
def key_status_endpoint(userId: str = Query(...)):
    configured = has_user_key(userId)
    return {
        "configured": configured,
        "hint": "Key 已配置，可以正常使用" if configured else "请在个人设置中配置 OpenRouter API Key",
    }


# ===================== DELETE /api/ai/key =====================

@router.delete("/key")
def delete_key_endpoint(userId: str = Query(...)):
    delete_user_key(userId)
    return {"success": True, "message": "Key 已删除"}


# ===================== Skills CRUD =====================

class SkillBody(BaseModel):
    key: str
    name: str
    description: str = ""
    rule: str
    pages: list[str] = []
    priority: int = 0


class SkillUpdateBody(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    rule: Optional[str] = None
    pages: Optional[list[str]] = None
    priority: Optional[int] = None
    enabled: Optional[bool] = None


@router.get("/skills")
def list_skills_endpoint():
    return {"skills": list_skills()}


@router.get("/skills/{skill_key}")
def get_skill_endpoint(skill_key: str):
    skill = get_skill_by_key(skill_key)
    if not skill:
        raise HTTPException(status_code=404, detail=f"技能 \"{skill_key}\" 不存在")
    return {"skill": {"key": skill.key, "name": skill.name, "description": skill.description, "rule": skill.rule}}


@router.post("/skills")
def create_skill_endpoint(body: SkillBody):
    skill_id = create_skill(
        key=body.key, name=body.name, description=body.description,
        rule=body.rule, pages=body.pages, priority=body.priority,
    )
    return {"success": True, "id": skill_id}


@router.put("/skills/{skill_id}")
def update_skill_endpoint(skill_id: int, body: SkillUpdateBody):
    updates = body.dict(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="没有可更新的字段")
    update_skill(skill_id, **updates)
    return {"success": True}


@router.delete("/skills/{skill_id}")
def delete_skill_endpoint(skill_id: int):
    delete_skill(skill_id)
    return {"success": True}


# ===================== DELETE /api/ai/memory =====================

@router.delete("/memory")
def clear_memory_endpoint(userId: str = Query(...)):
    clear_history(userId)
    return {"success": True, "message": "对话历史已清除，下次对话将重新开始"}


# ===================== DELETE /api/ai/preference =====================

@router.delete("/preference")
def clear_preference_endpoint(userId: str = Query(...)):
    clear_preference(userId)
    return {"success": True, "message": "查询偏好已重置"}


# ===================== GET /api/ai/preference =====================

@router.get("/preference")
def get_preference_endpoint(userId: str = Query(...)):
    pref = get_preference(userId)
    return {"preference": pref}


# ===================== GET /api/ai/stats =====================

@router.get("/stats")
def stats_endpoint():
    from datetime import datetime
    return {
        "memory": get_memory_stats(),
        "queryCache": get_cache_stats(),
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


# ===================== DELETE /api/ai/cache =====================

@router.delete("/cache")
def clear_cache_endpoint():
    """清空 ERP 查询结果内存缓存（LRU）"""
    stats = get_cache_stats()
    size = stats.get("size", 0)
    clear_all_cache()
    return {"ok": True, "deleted": size, "message": f"已清空 {size} 条查询结果缓存"}


@router.delete("/catalog/layout-cache/sqlite")
def clear_layout_sqlite_cache():
    """清空 erp_form_layout_cache SQLite 持久化缓存（保留 catalog 条目，同步清进程内存）"""
    from db import get_conn
    from tools.table_fields import _field_cache
    conn = get_conn()
    with conn:
        result = conn.execute("DELETE FROM erp_form_layout_cache")
        deleted = result.rowcount
    conn.close()
    _field_cache.clear()
    return {"ok": True, "deleted": deleted, "message": f"已清空 {deleted} 条字段布局 SQLite 缓存"}


@router.delete("/catalog/layout-cache/memory")
def clear_layout_memory_cache():
    """清空字段布局进程内存缓存（不影响 SQLite）"""
    from tools.table_fields import _field_cache
    deleted = len(_field_cache)
    _field_cache.clear()
    return {"ok": True, "deleted": deleted, "message": f"已清空 {deleted} 条字段布局内存缓存"}


@router.get("/cache/stats")
def get_all_cache_stats():
    """返回各层缓存当前数量"""
    from db import get_conn
    from tools.table_fields import _field_cache
    conn = get_conn()
    sqlite_count = conn.execute("SELECT COUNT(*) FROM erp_form_layout_cache").fetchone()[0]
    conn.close()
    query_stats = get_cache_stats()
    return {
        "ok": True,
        "layoutSqlite": sqlite_count,
        "layoutMemory": len(_field_cache),
        "queryMemory": query_stats.get("size", 0),
    }


# ===================== Human-in-Loop 审批 =====================

class ApprovalDecisionBody(BaseModel):
    approvalId: str
    decision: str  # "approve" | "reject"
    userId: str


@router.post("/approve")
def handle_approval_endpoint(body: ApprovalDecisionBody):
    try:
        approved = human_in_loop.process(body.approvalId, body.decision, body.userId)
        return {"success": True, "approved": approved}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ===================== GET /api/ai/traces =====================

@router.get("/traces")
def list_traces_endpoint(
    userId: str = Query(...),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    """查询指定用户的历史 Agent Trace 列表（不含 steps 详情）"""
    from db import get_conn
    conn = get_conn()
    rows = conn.execute(
        """
        SELECT run_id, user_message, status, step_count, duration_ms, created_at
        FROM agent_traces
        WHERE user_id = ?
        ORDER BY created_at DESC
        LIMIT ? OFFSET ?
        """,
        (userId, limit, offset),
    ).fetchall()
    total = conn.execute(
        "SELECT COUNT(*) FROM agent_traces WHERE user_id = ?", (userId,)
    ).fetchone()[0]
    conn.close()
    return {
        "total": total,
        "traces": [dict(r) for r in rows],
    }


@router.get("/traces/{run_id}")
def get_trace_endpoint(run_id: str):
    """查询单条 Trace 完整 steps 详情"""
    from db import get_conn
    import json as _json
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM agent_traces WHERE run_id = ?", (run_id,)
    ).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail=f"Trace {run_id} 不存在")
    data = dict(row)
    try:
        data["steps"] = _json.loads(data["steps"])
    except Exception:
        data["steps"] = []
    return data


# ===================== Human-in-Loop 审批 =====================

@router.get("/approvals")
def list_approvals_endpoint(
    x_user_id: Optional[str] = Header(default=None, alias="x-user-id"),
):
    if not x_user_id:
        raise HTTPException(status_code=400, detail="缺少用户 ID")
    pending = human_in_loop.get_pending(x_user_id)
    return {
        "approvals": [
            {
                "approvalId": a.approval_id,
                "action": a.action,
                "details": a.details,
                "createdAt": a.created_at.isoformat(),
            }
            for a in pending
        ]
    }


# ===================== ERP 表目录管理 =====================

class CatalogCreateBody(BaseModel):
    form_code:   str = Field(..., min_length=1)
    module_name: str = Field(default="")
    api_path:    str = Field(default="")
    extra_body:  str = Field(default="")
    enabled:     int = Field(default=1)

class CatalogUpdateBody(BaseModel):
    module_name: Optional[str] = None
    api_path:    Optional[str] = None
    extra_body:  Optional[str] = None
    enabled:     Optional[int] = None


def _catalog_row_to_dict(row) -> dict:
    d = dict(row)
    # 拼上 layout cache 信息
    return d


@router.get("/catalog")
def list_catalog():
    from db import get_conn
    conn = get_conn()
    rows = conn.execute("""
        SELECT c.form_code, c.module_name, c.api_path, c.extra_body, c.enabled, c.created_at,
               l.table_name, l.form_desc, l.fields_json, l.sub_tables_json, l.cached_at
        FROM erp_form_catalog c
        LEFT JOIN erp_form_layout_cache l ON c.form_code = l.form_code
        ORDER BY c.form_code
    """).fetchall()
    conn.close()
    return {"catalog": [dict(r) for r in rows]}


@router.post("/catalog")
def create_catalog(body: CatalogCreateBody):
    import time
    from db import get_conn
    conn = get_conn()
    existing = conn.execute(
        "SELECT 1 FROM erp_form_catalog WHERE form_code = ?", (body.form_code,)
    ).fetchone()
    if existing:
        conn.close()
        raise HTTPException(status_code=409, detail=f"{body.form_code} 已存在")
    with conn:
        conn.execute(
            """INSERT INTO erp_form_catalog
               (form_code, module_name, api_path, extra_body, enabled, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (body.form_code, body.module_name, body.api_path, body.extra_body, body.enabled, time.time()),
        )
    conn.close()
    return {"ok": True, "form_code": body.form_code}


@router.put("/catalog/{form_code}")
def update_catalog(form_code: str, body: CatalogUpdateBody):
    from db import get_conn
    conn = get_conn()
    row = conn.execute(
        "SELECT 1 FROM erp_form_catalog WHERE form_code = ?", (form_code,)
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail=f"{form_code} 不存在")
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if updates:
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        with conn:
            conn.execute(
                f"UPDATE erp_form_catalog SET {set_clause} WHERE form_code = ?",
                (*updates.values(), form_code),
            )
    conn.close()
    return {"ok": True}


@router.delete("/catalog/{form_code}")
def delete_catalog(form_code: str):
    from db import get_conn
    conn = get_conn()
    with conn:
        conn.execute("DELETE FROM erp_form_catalog WHERE form_code = ?", (form_code,))
        conn.execute("DELETE FROM erp_form_layout_cache WHERE form_code = ?", (form_code,))
    conn.close()
    return {"ok": True}


@router.post("/catalog/{form_code}/sync")
async def sync_catalog(
    form_code: str,
    request: Request,
    x_user_id: Optional[str] = Header(default=None, alias="x-user-id"),
):
    """调用 getProgGridLayout 刷新单条表的字段布局缓存"""
    import time, json as _json
    from db import get_conn
    from erp_client import _build_erp_headers, ERP_BASE_URL, _HTTP_CLIENT_KWARGS
    import httpx

    row = None
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM erp_form_catalog WHERE form_code = ?", (form_code,)
    ).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail=f"{form_code} 不存在")

    erp_cookie = request.headers.get("x-erp-cookie", "")
    erp_auth   = request.headers.get("x-erp-authorization", request.headers.get("authorization", ""))
    user_id    = x_user_id or ""

    url  = f"{ERP_BASE_URL}/gw/api/ERP/FunRights/getProgGridLayout"
    body = {"sUserCode": user_id, "FormCode": form_code, "FrontJSFileName": "view.jsx"}
    headers = _build_erp_headers(erp_cookie, erp_auth)

    try:
        async with httpx.AsyncClient(**_HTTP_CLIENT_KWARGS) as client:
            resp = await client.post(url, json=body, headers=headers)
        data = resp.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"调用 ERP 接口失败: {e}")

    if not data.get("success"):
        raise HTTPException(status_code=502, detail=data.get("msg") or "ERP 返回失败")

    response   = data.get("response") or {}
    form_desc  = response.get("fFormDesc", "")
    main_cfg   = response.get("mainTableConfig") or {}
    inter_code = main_cfg.get("fInterCode", "")
    table_name = f"{form_code}.{inter_code}" if inter_code else form_code
    columns    = main_cfg.get("columns") or []

    # f28=强制隐藏 / f26=在编辑页是否可见（缺失时视为True）
    fields = [
        {"field": c.get("f4", ""), "label": c.get("f5", ""),
         "hidden": bool(c.get("f28", False)) or c.get("f26") is False}
        for c in columns if c.get("f4")
    ]

    # 细表摘要
    sub_tables = [
        {
            "inter_code": s.get("fInterCode", ""),
            "desc": (s.get("fInterDesc") or [""])[0],
            "table_name": f"{form_code}.{s.get('fInterCode', '')}",
            "fields": [
                {"field": c.get("f4", ""), "label": c.get("f5", "")}
                for c in (s.get("columns") or []) if c.get("f4")
            ],
        }
        for s in (response.get("subTableConfig") or [])
    ]

    now = time.time()
    conn = get_conn()
    with conn:
        conn.execute("""
            INSERT OR REPLACE INTO erp_form_layout_cache
                (form_code, table_name, form_desc, fields_json, sub_tables_json, cached_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (form_code, table_name, form_desc, _json.dumps(fields, ensure_ascii=False),
              _json.dumps(sub_tables, ensure_ascii=False), now))
    conn.close()

    return {
        "ok": True,
        "form_code":  form_code,
        "table_name": table_name,
        "form_desc":  form_desc,
        "field_count": len(fields),
        "sub_table_count": len(sub_tables),
    }


@router.post("/catalog/sync-all")
async def sync_all_catalog(
    request: Request,
    x_user_id: Optional[str] = Header(default=None, alias="x-user-id"),
):
    """批量 Sync 所有启用的表，逐条调用 getProgGridLayout"""
    import time, json as _json, asyncio
    from db import get_conn
    from erp_client import _build_erp_headers, ERP_BASE_URL, _HTTP_CLIENT_KWARGS
    import httpx

    erp_cookie = request.headers.get("x-erp-cookie", "")
    erp_auth   = request.headers.get("x-erp-authorization", request.headers.get("authorization", ""))
    user_id    = x_user_id or ""

    conn = get_conn()
    form_codes = [r["form_code"] for r in conn.execute(
        "SELECT form_code FROM erp_form_catalog WHERE enabled = 1 ORDER BY form_code"
    ).fetchall()]
    conn.close()

    headers = _build_erp_headers(erp_cookie, erp_auth)
    results = {"success": [], "failed": []}

    async def _sync_one(fc: str):
        url  = f"{ERP_BASE_URL}/gw/api/ERP/FunRights/getProgGridLayout"
        body = {"sUserCode": user_id, "FormCode": fc, "FrontJSFileName": "view.jsx"}
        try:
            async with httpx.AsyncClient(**_HTTP_CLIENT_KWARGS) as client:
                resp = await client.post(url, json=body, headers=headers)
            data = resp.json()
            if not data.get("success"):
                results["failed"].append({"form_code": fc, "reason": data.get("msg", "ERP 返回失败")})
                return

            response   = data.get("response") or {}
            form_desc  = response.get("fFormDesc", "")
            main_cfg   = response.get("mainTableConfig") or {}
            inter_code = main_cfg.get("fInterCode", "")
            table_name = f"{fc}.{inter_code}" if inter_code else fc
            columns    = main_cfg.get("columns") or []
            fields = [
                {"field": c.get("f4", ""), "label": c.get("f5", ""),
                 "hidden": bool(c.get("f28", False)) or c.get("f26") is False}
                for c in columns if c.get("f4")
            ]
            sub_tables = [
                {
                    "inter_code": s.get("fInterCode", ""),
                    "desc": (s.get("fInterDesc") or [""])[0],
                    "table_name": f"{fc}.{s.get('fInterCode', '')}",
                    "fields": [
                        {"field": c.get("f4", ""), "label": c.get("f5", "")}
                        for c in (s.get("columns") or []) if c.get("f4")
                    ],
                }
                for s in (response.get("subTableConfig") or [])
            ]
            now = time.time()
            conn2 = get_conn()
            with conn2:
                conn2.execute("""
                    INSERT OR REPLACE INTO erp_form_layout_cache
                        (form_code, table_name, form_desc, fields_json, sub_tables_json, cached_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (fc, table_name, form_desc,
                      _json.dumps(fields, ensure_ascii=False),
                      _json.dumps(sub_tables, ensure_ascii=False), now))
            conn2.close()
            results["success"].append({"form_code": fc, "table_name": table_name, "field_count": len(fields)})

        except Exception as e:
            results["failed"].append({"form_code": fc, "reason": str(e)})

    # 并发但限制 5 个并行，避免对 ERP 造成压力
    semaphore = asyncio.Semaphore(5)
    async def _guarded(fc):
        async with semaphore:
            await _sync_one(fc)

    await asyncio.gather(*[_guarded(fc) for fc in form_codes])

    return {
        "ok": True,
        "total": len(form_codes),
        "success_count": len(results["success"]),
        "failed_count": len(results["failed"]),
        "failed": results["failed"],
    }
