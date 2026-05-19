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

from ai_service import chat_with_ai, test_openrouter_key
from key_service import save_user_key, get_user_key, has_user_key, delete_user_key, validate_key_format
from logger import logger, start_timer
from config.skills import list_skills, get_skill_by_key, create_skill, update_skill, delete_skill
from memory.conversation_memory import clear_history, get_memory_stats
from memory.user_preference import clear_preference, get_preference
from cache.query_cache import get_cache_stats, clear_all_cache

router = APIRouter(prefix="/api/ai")

DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "openai/gpt-4o-mini")
ERP_DATA_PREFIX = "\x00ERP_DATA:"
ACTION_DATA_PREFIX = "\x00ACTION_DATA:"

# ===================== 请求体 Schema =====================

class ChatRequestBody(BaseModel):
    message: str = Field(min_length=1, max_length=500, description="消息内容")
    pageContext: Optional[str] = None
    model: Optional[str] = None
    skillKey: Optional[str] = None
    skill: Optional[str] = Field(default=None, max_length=2000)
    history: Optional[list[dict]] = None  # 服务端 Memory 已替代，保留兼容


class SaveKeyRequest(BaseModel):
    openrouterKey: str
    userId: str


# ===================== POST /api/ai/chat =====================

@router.post("/chat")
async def chat_endpoint(
    body: ChatRequestBody,
    request: Request,
    x_user_id: Optional[str] = Header(default=None, alias="x-user-id"),
):
    """主对话接口，支持流式输出（Server-Sent Events）"""
    if not x_user_id:
        raise HTTPException(status_code=400, detail="缺少用户 ID（X-User-Id header）")

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
        }

        try:
            async for chunk in chat_with_ai(
                request=request_dict,
                openrouter_key=openrouter_key,
                erp_cookie=erp_cookie,
                erp_authorization=erp_authorization,
                user_id=user_id,
            ):
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
    clear_all_cache()
    return {"success": True, "message": "ERP 查询缓存已清空"}
