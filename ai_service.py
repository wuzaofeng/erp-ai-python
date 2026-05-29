"""
AI 对话核心服务 - 对应 src/aiService.ts

核心功能：
  1. 服务端 Memory：从 conversationMemory 读取历史
  2. 用户偏好：从 userPreference 读取偏好注入 System Prompt
  3. Agent Loop：最多 MAX_TOOL_ROUNDS 轮工具调用（支持跨表联查）
  4. RAG 数据压缩：大数据集只传相关行给 AI，减少 token 消耗
  5. 模型降级：429/503 时自动切备用模型
"""
import os
import json
from typing import AsyncGenerator, Any, Optional

from langchain_openai import ChatOpenAI
from langchain_core.messages import (
    SystemMessage,
    HumanMessage,
    AIMessage,
    ToolMessage,
    BaseMessage,
)

from logger import logger, start_timer
from config.prompt_config import build_system_prompt
from config.skills import get_skill_by_key, get_skill_by_page
from tools import create_all_tools
from field_mapper import get_field_labels
from erp_client import get_field_layout
from rag.context_builder import build_context, RawErpData
from memory.conversation_memory import get_history, append_user_message, append_assistant_message
from memory.user_preference import get_preference_prompt, update_preference, QueryInfo
from memory.session_state import save_query_state, get_query_state, LastQueryState
from vector.knowledge_base import build_knowledge_prompt
from trace.agent_trace import trace_service, StepType
from metacognition.meta_cognition import meta_cognition

DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "openai/gpt-4o-mini")
MAX_TOOL_ROUNDS = int(os.getenv("MAX_TOOL_ROUNDS", "3"))

MODEL_FALLBACKS = [
    "deepseek/deepseek-chat",
    "openai/gpt-4o-mini",
    "openai/gpt-4o",
    "anthropic/claude-3-5-sonnet-20241022",
]


# ===================== 工具函数 =====================

def extract_text(content: Any) -> str:
    """从 LangChain message content 中提取纯文本"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
        return "".join(parts)
    return ""


def create_model(api_key: str, model_name: str, temperature: float = 0.1) -> ChatOpenAI:
    """创建 ChatOpenAI 实例（指向 OpenRouter）"""
    return ChatOpenAI(
        api_key=api_key,
        model=model_name,
        temperature=temperature,
        base_url="https://openrouter.ai/api/v1",
        default_headers={
            "HTTP-Referer": os.getenv("OPENROUTER_REFERER", "http://localhost:8000"),
            "X-Title": "ERP AI Assistant",
        },
    )


async def invoke_with_fallback(
    api_key: str,
    model_name: str,
    tools: list,
    messages: list[BaseMessage],
) -> tuple[AIMessage, str, str | None]:
    """带降级的 invoke，返回 (response, used_model, fallback_error)"""
    models_to_try = list(dict.fromkeys([model_name] + MODEL_FALLBACKS))
    last_error_msg: str | None = None

    for i, try_model in enumerate(models_to_try):
        try:
            if try_model != model_name:
                logger.warn("LangChain", f"模型降级重试 → {try_model}")
            model = create_model(api_key, try_model, 0.1)
            model_with_tools = model.bind_tools(tools)
            response = await model_with_tools.ainvoke(messages)
            return response, try_model, last_error_msg  # type: ignore[return-value]
        except Exception as err:
            status = getattr(err, "status_code", None) or getattr(err, "status", None)
            msg = str(err)
            logger.error("LangChain", f"调用失败 [{try_model}] | status={status} | {msg}")
            if status in (429, 404, 403) and i < len(models_to_try) - 1:
                reason = "429 限流" if status == 429 else ("403 区域限制" if status == 403 else "404 模型不可用")
                last_error_msg = f"{try_model} {reason}: {msg}"
                logger.warn("LangChain", f"{reason}，尝试下一个备用模型...")
                continue
            raise

    raise RuntimeError("所有备用模型均不可用，请稍后重试")


def parse_tool_result(tool_result: str) -> Optional[RawErpData]:
    """从工具返回的字符串中解析原始 ERP 数据"""
    json_start = tool_result.find("{")
    if json_start < 0:
        return None
    try:
        parsed = json.loads(tool_result[json_start:])
        if parsed.get("rows") and isinstance(parsed["rows"], list):
            return RawErpData(
                rows=parsed["rows"],
                total=parsed.get("total", len(parsed["rows"])),
                page_index=parsed.get("pageIndex", 1),
                page_size=parsed.get("pageSize", len(parsed["rows"])),
            )
    except (json.JSONDecodeError, KeyError):
        pass
    return None


# ===================== 主函数 =====================

async def chat_with_ai(
    request: dict,
    openrouter_key: str,
    erp_cookie: str = "",
    erp_authorization: str = "",
    user_id: str = "",
    _run_id: str = "",
) -> AsyncGenerator[str, None]:
    """
    核心：AI 对话 + Agent Loop，返回 AsyncGenerator 用于流式输出

    SSE 输出：
      - \\x00ERP_DATA:<json>   → 推送 erp.data 事件
      - 普通文本              → 推送 chat.completion.chunk 事件
    """
    model_name = request.get("model") or DEFAULT_MODEL

    # ---- 0. 开启 Trace（外部传入 run_id 时复用，避免 orchestrator fallback 重复开 trace）----
    conv_id = request.get("conversation_id", "")
    if _run_id:
        run_id = _run_id
    else:
        run_id = trace_service.start_trace(request["message"], conversation_id=conv_id)

    # ---- 1. 解析技能规则 ----
    resolved_skill: Optional[str] = request.get("skill")
    if not resolved_skill and request.get("skillKey"):
        matched = get_skill_by_key(request["skillKey"])
        if matched:
            resolved_skill = matched.rule
            logger.ai("Skill", f"命中预设技能 [{request['skillKey']}]: {matched.name}")
        else:
            logger.warn("Skill", f"未找到 skillKey=\"{request['skillKey']}\"，忽略")
    if not resolved_skill and request.get("pageContext"):
        auto_matched = get_skill_by_page(request["pageContext"])
        if auto_matched:
            resolved_skill = auto_matched.rule
            logger.ai("Skill", f"按页面自动匹配技能 [{auto_matched.key}]: {auto_matched.name}")

    # ---- 2. 读取服务端 Memory、用户偏好、知识库 ----
    history_messages = get_history(user_id, conv_id)
    preference_prompt = get_preference_prompt(user_id)
    t_kb = start_timer()
    knowledge_prompt, knowledge_hits = build_knowledge_prompt(request["message"])
    trace_service.log_knowledge_search(run_id, request["message"], knowledge_hits, duration_ms=t_kb())
    logger.ai(
        "Memory",
        f"读取历史 | userId={user_id} | 历史轮数={len(history_messages) // 2} | 有偏好={bool(preference_prompt)}",
    )

    # ---- 3. 创建工具 ----
    erp_tools = create_all_tools(erp_cookie, erp_authorization, user_id, run_id,
                                  enable_web_search=request.get("enable_web_search", False),
                                  openrouter_key=openrouter_key)
    tool_map: dict[str, Any] = {t.name: t for t in erp_tools}

    # ---- 4. 构造初始消息 ----
    current_query_state = get_query_state(conv_id) if conv_id else None
    if current_query_state:
        logger.ai("SessionState", f"注入查询状态 | table={current_query_state.table_name} | pageSize={current_query_state.page_size} | pageIndex={current_query_state.page_index} | total={current_query_state.total}")
    else:
        logger.ai("SessionState", f"无活跃查询状态 | conv_id={conv_id}")
    system_prompt_text = build_system_prompt(
        request.get("pageContext"), resolved_skill, preference_prompt, knowledge_prompt,
        nav_index=request.get("navIndex"),
        query_state=current_query_state,
        enable_web_search=request.get("enable_web_search", False),
        user_city=request.get("user_city", ""),
    )
    trace_service.set_system_prompt(run_id, system_prompt_text)
    # 刷新时强制重复上次查询，不走翻页逻辑
    is_refresh = request.get("is_refresh", False)
    user_message_content = request["message"]
    if is_refresh and current_query_state:
        user_message_content = (
            f"【刷新指令】请重新执行上一次查询，参数保持完全不变："
            f"tableName={current_query_state.table_name}，"
            f"pageSize={current_query_state.page_size}，"
            f"pageIndex={current_query_state.page_index}，"
            f"filters 与上次相同。不得修改任何参数。"
        )
        logger.ai("SessionState", f"刷新模式：重复查询 pageIndex={current_query_state.page_index}")

    messages: list[BaseMessage] = [
        SystemMessage(content=system_prompt_text),
        *[
            HumanMessage(content=h.content) if h.role == "user"
            else AIMessage(content=h.content)
            for h in history_messages
        ],
        HumanMessage(content=user_message_content),
    ]

    append_user_message(user_id, request["message"], conv_id)

    # ---- 5. Agent Loop ----
    used_model = model_name
    tools_were_called = False
    query_erp_called = False   # 是否真正调用了 query_erp_list 或 search_erp_global
    web_search_called = False  # 是否调用了 web_search（联网搜索，不属于 ERP 查询，不触发强制提示）
    erp_data_pushed = False    # 是否有工具成功返回了 ERP 数据
    tool_errors: list[str] = []  # 收集工具错误信息
    accumulated_answer: list[str] = []
    called_tool_args: list[dict] = []

    for round_n in range(1, MAX_TOOL_ROUNDS + 1):
        t = start_timer()
        logger.ai(
            "LangChain",
            f"→ Agent Loop 第 {round_n}/{MAX_TOOL_ROUNDS} 轮 | 模型={used_model} | messages={len(messages)}",
        )

        prev_model = used_model
        ai_response, used_model, fallback_error = await invoke_with_fallback(
            openrouter_key, used_model, erp_tools, messages
        )

        tool_calls = ai_response.tool_calls or []
        llm_duration = t()
        logger.ai(
            "LangChain",
            f"← 第 {round_n} 轮响应 [{used_model}] | tool_calls={len(tool_calls)} | 耗时={llm_duration}ms",
        )

        if used_model != prev_model:
            fallback_hint = f"⚠️ 模型 {prev_model} 不可用，已自动切换至 {used_model}"
            yield fallback_hint + "\n"
            trace_service.log_retry(run_id, reason=f"{prev_model} → {used_model}", attempt=round_n, error=fallback_error)
        _usage = getattr(ai_response, "usage_metadata", None) or {}
        _tokens = {
            "input_tokens": _usage.get("input_tokens", 0),
            "output_tokens": _usage.get("output_tokens", 0),
            "total_tokens": _usage.get("total_tokens", 0),
        } if _usage else {}
        finish_reason = getattr(ai_response, "response_metadata", {}).get("finish_reason") or \
                        getattr(ai_response, "response_metadata", {}).get("stop_reason")
        trace_service.log_llm(
            run_id, round_n, used_model,
            reasoning=extract_text(ai_response.content),
            tool_calls=tool_calls,
            tokens=_tokens,
            duration_ms=llm_duration,
            messages=messages,
            finish_reason=finish_reason,
        )

        # ---- 无 tool calls → AI 直接回答 ----
        if not tool_calls:
            text = extract_text(ai_response.content)
            # 如果 AI 调用了 get_table_fields 但没有调用 query_erp_list，
            # 说明它可能在用字段元数据编造业务数据，强制要求重新查询
            if tools_were_called and not query_erp_called and not web_search_called and round_n < MAX_TOOL_ROUNDS:
                logger.warn(
                    "LangChain",
                    f"第 {round_n} 轮：AI 只调了 get_table_fields 就给出结论，强制要求调用 query_erp_list",
                )
                messages.append(ai_response)
                messages.append(HumanMessage(content=(
                    "【系统强制提示】你只查询了字段列表（get_table_fields），"
                    "但字段列表不包含任何业务数据，不能据此得出任何业务结论。"
                    "请立即调用 query_erp_list 工具查询真实数据，然后再回答用户问题。"
                )))
                continue
            if not tools_were_called:
                if text:
                    logger.ai("LangChain", f"第 {round_n} 轮直接回答 | 总字符={len(text)}")
                    accumulated_answer.append(text)
                    yield text
            break

        # ---- 有 tool calls → 执行工具 ----
        tools_were_called = True
        messages.append(ai_response)

        for tool_call in tool_calls:
            tool_name = tool_call.get("name") if isinstance(tool_call, dict) else getattr(tool_call, "name", None)
            tool_call_id = tool_call.get("id") if isinstance(tool_call, dict) else getattr(tool_call, "id", "no-id")
            tool_args = tool_call.get("args", {}) if isinstance(tool_call, dict) else getattr(tool_call, "args", {})

            if not tool_name:
                logger.warn("ToolCall", f"tool_call 缺少 name | id={tool_call_id}")
                messages.append(ToolMessage(
                    content=json.dumps({"error": "工具调用缺少 name，无法执行"}),
                    tool_call_id=tool_call_id,
                ))
                continue

            target_tool = tool_map.get(tool_name)
            if not target_tool:
                logger.warn("ToolCall", f"未找到工具 \"{tool_name}\"")
                messages.append(ToolMessage(
                    content=json.dumps({"error": f"工具 \"{tool_name}\" 不存在"}),
                    tool_call_id=tool_call_id,
                ))
                continue

            # ⭐ 预校验：query_erp_list 的 filter 字段名合法性
            if tool_name == "query_erp_list":
                filters = tool_args.get("filters", [])
                table_name_arg = tool_args.get("tableName", "")
                if filters and table_name_arg and user_id:
                    layout = await get_field_layout(
                        table_name=table_name_arg,
                        user_id=user_id,
                        erp_cookie=erp_cookie,
                        erp_auth=erp_authorization,
                    )
                    if layout and layout.field_labels:
                        valid_fields = list(layout.field_labels.keys())
                        invalid_filters = [
                            f for f in filters
                            if isinstance(f, dict) and f.get("FieldName") not in valid_fields
                        ]
                        if invalid_filters:
                            invalid_names = ", ".join(f.get("FieldName", "") for f in invalid_filters)
                            field_list_with_desc = ", ".join(
                                f"{code}（{layout.field_labels[code]}）" if layout.field_labels.get(code) else code
                                for code in valid_fields
                            )
                            err_msg = (
                                f"过滤条件中包含无效字段名：【{invalid_names}】\n"
                                f"表 \"{table_name_arg}\" 的真实可用字段及中文描述如下，"
                                f"请严格从以下字段名中选择正确字段名重新构造过滤条件：\n{field_list_with_desc}"
                            )
                            logger.warn("ToolCall", f"字段名校验失败 | 无效字段: {invalid_names}")
                            messages.append(ToolMessage(content=err_msg, tool_call_id=tool_call_id))
                            continue

            if tool_name == "web_search":
                yield f"🌐 正在联网搜索...\n"
            else:
                yield f"🔍 正在查询 ERP 数据（{tool_name}）...\n"
            t_tool = start_timer()

            try:
                invoke_result = await target_tool.ainvoke(tool_call)
                if isinstance(invoke_result, dict) and "content" in invoke_result:
                    c = invoke_result["content"]
                    raw_tool_result = c if isinstance(c, str) else json.dumps(c, ensure_ascii=False)
                elif hasattr(invoke_result, "content"):
                    # LangChain ToolMessage 对象
                    c = invoke_result.content
                    raw_tool_result = c if isinstance(c, str) else json.dumps(c, ensure_ascii=False)
                else:
                    raw_tool_result = str(invoke_result)
                tool_duration = t_tool()
                logger.ai("ToolCall", f"[{tool_name}] 完成 | 耗时={tool_duration}ms | 返回={len(raw_tool_result)}字节")
            except Exception as e:
                import traceback
                tool_duration = t_tool()
                tb = traceback.extract_tb(e.__traceback__)
                source = f"{tb[-1].filename}:{tb[-1].lineno} in {tb[-1].name}" if tb else type(e).__name__
                logger.error("ToolCall", f"[{tool_name}] 失败: {e} | 来源={source}")
                raw_tool_result = json.dumps({
                    "error": str(e),
                    "source": source,
                    "type": type(e).__name__,
                }, ensure_ascii=False)

            called_tool_args.append({"toolName": tool_name, "args": tool_args})
            # search_erp_tables 已在工具内部调用 log_table_search，此处跳过避免重复记录
            if tool_name == "web_search":
                try:
                    parsed = json.loads(raw_tool_result)
                    trace_service.log_web_search(
                        run_id, tool_args.get("query", ""),
                        answer=parsed.get("answer", parsed.get("error", "")),
                        citations=parsed.get("citations", []),
                        duration_ms=tool_duration,
                    )
                except Exception:
                    trace_service.log_tool(run_id, tool_name, tool_args, raw_tool_result, duration_ms=tool_duration)
            elif tool_name != "search_erp_tables":
                trace_service.log_tool(run_id, tool_name, tool_args, raw_tool_result, erp_cookie=erp_cookie, erp_auth=erp_authorization, duration_ms=tool_duration)
            if tool_name in ("query_erp_list", "search_erp_global"):
                query_erp_called = True
            if tool_name == "web_search":
                web_search_called = True

            # ---- trigger_actions 工具：直接转发给前端 ----
            if tool_name == "trigger_actions" and raw_tool_result.startswith("\x00ACTION_DATA:"):
                yield raw_tool_result
                messages.append(ToolMessage(
                    content=json.dumps({"status": "actions_pushed"}),
                    tool_call_id=tool_call_id,
                ))
                continue

            # ---- 元认知反思：空结果时自动检查并提示调整 ----
            if tool_name == "query_erp_list" and round_n < MAX_TOOL_ROUNDS:
                parsed_check = parse_tool_result(raw_tool_result)
                if not parsed_check or not parsed_check.rows:
                    table_meta_for_reflect: dict = {}
                    layout_for_reflect = await get_field_layout(
                        table_name=tool_args.get("tableName", ""),
                        user_id=user_id,
                        erp_cookie=erp_cookie,
                        erp_auth=erp_authorization,
                    ) if tool_args.get("tableName") and user_id else None
                    if layout_for_reflect:
                        table_meta_for_reflect = {
                            "fields": [
                                {"name": k, "label": v}
                                for k, v in (layout_for_reflect.field_labels or {}).items()
                            ]
                        }
                    reflection = await meta_cognition.reflect_on_failure(
                        query=tool_args,
                        result=json.loads(raw_tool_result) if raw_tool_result.startswith("{") else {},
                        table_meta=table_meta_for_reflect,
                    )
                    if reflection.success and reflection.adjustment:
                        adj = reflection.adjustment
                        hint = (
                            f"【元认知提示】查询返回空结果，检测到可能的参数问题：\n"
                            f"  类型：{adj.adjustment_type}\n"
                            f"  字段：{adj.field}\n"
                            f"  原始值：{adj.original} → 建议调整为：{adj.adjusted}\n"
                            f"  置信度：{adj.confidence:.0%}\n"
                            f"请根据以上建议调整查询参数后重新调用工具。"
                        )
                        trace_service.log_reflection(run_id, hint)
                        logger.ai("MetaCognition", f"反思完成 | 类型={adj.adjustment_type} | 置信度={adj.confidence:.0%}")
                        messages.append(ToolMessage(content=hint, tool_call_id=tool_call_id))
                        continue

            # ---- 保存会话查询状态（用于翻页上下文注入）----
            if tool_name == "query_erp_list":
                parsed_for_state = parse_tool_result(raw_tool_result)
                conv_id = request.get("conversation_id", "")
                if conv_id and parsed_for_state:
                    save_query_state(conv_id, LastQueryState(
                        table_name=tool_args.get("tableName", ""),
                        page_size=tool_args.get("pageSize", 20),
                        page_index=tool_args.get("pageIndex", 1) or 1,
                        filters=tool_args.get("filters", []),
                        total=parsed_for_state.total,
                    ))

            # ---- RAG 处理 ----
            parsed = parse_tool_result(raw_tool_result)
            if parsed and parsed.rows:
                table_name_for_rag = (
                    "ADM100_ZuruQuery.ADM100_ZuruQuery"
                    if tool_name == "search_erp_global"
                    else tool_args.get("tableName")
                )
                if table_name_for_rag:
                    dynamic_layout = await get_field_layout(
                        table_name=table_name_for_rag,
                        user_id=user_id,
                        erp_cookie=erp_cookie,
                        erp_auth=erp_authorization,
                    ) if user_id else None
                    field_labels = (
                        dynamic_layout.field_labels if dynamic_layout
                        else get_field_labels(table_name_for_rag)
                    )

                    erp_data_payload = {
                        "rows": parsed.rows,
                        "total": parsed.total,
                        "pageIndex": parsed.page_index,
                        "pageSize": parsed.page_size,
                        "tableName": table_name_for_rag,
                        "fieldLabels": field_labels,
                        "forceHiddenFields": [
                            h.get("field", "") for h in (dynamic_layout.hidden_fields if dynamic_layout else [])
                        ],
                    }
                    yield f"\x00ERP_DATA:{json.dumps(erp_data_payload, ensure_ascii=False)}"
                    erp_data_pushed = True
                    logger.ai("ToolCall", f"已推送 erp.data 事件 | rows={len(parsed.rows)} | total={parsed.total}")
                    trace_service.log_erp_data(
                        run_id,
                        table_name=table_name_for_rag,
                        rows=len(parsed.rows),
                        total=parsed.total,
                        page_index=parsed.page_index,
                        page_size=parsed.page_size,
                    )

                    t_rag = start_timer()
                    rag_context = build_context(parsed, request["message"], field_labels, model_id=model_name, system_used_tokens=_tokens.get("input_tokens", 0))
                    messages.append(ToolMessage(content=rag_context.context_text, tool_call_id=tool_call_id))
                    logger.ai(
                        "RAG",
                        f"上下文构建完成 | isRag={rag_context.is_rag} | 传给AI={rag_context.sent_row_count}行 / 共{len(parsed.rows)}行",
                    )
                    from rag.context_builder import _extract_keywords
                    trace_service.log_rag(
                        run_id,
                        is_rag=rag_context.is_rag,
                        total_rows=len(parsed.rows),
                        sent_rows=rag_context.sent_row_count,
                        keywords=_extract_keywords(request["message"]),
                        duration_ms=t_rag(),
                    )
                else:
                    messages.append(ToolMessage(content=raw_tool_result, tool_call_id=tool_call_id))
            else:
                # 检测工具是否返回了 error 字段，是则注入强制报错指令，防止 AI 用历史数据幻觉
                try:
                    _err_parsed = json.loads(raw_tool_result) if raw_tool_result.strip().startswith("{") else {}
                    _err_msg = _err_parsed.get("error") if isinstance(_err_parsed, dict) else None
                except Exception:
                    _err_msg = None
                if _err_msg:
                    tool_errors.append(f"{tool_name}: {_err_msg}")
                    messages.append(ToolMessage(content=raw_tool_result, tool_call_id=tool_call_id))
                    trace_service.log_reflection(
                        run_id,
                        f"工具 {tool_name} 返回错误",
                        {"tool": tool_name, "error": _err_msg, "action": "error_intercept"},
                    )
                else:
                    messages.append(ToolMessage(content=raw_tool_result, tool_call_id=tool_call_id))

    # ---- 6. 如果调用了工具：streaming 输出最终回答 ----
    if tools_were_called:
        # 工具全部失败且无任何成功数据 → 直接报错，跳过 LLM，避免幻觉
        if tool_errors and not erp_data_pushed:
            err_text = "查询失败：" + "；".join(tool_errors)
            accumulated_answer.append(err_text)
            yield err_text
            trace_service.log_agent(run_id, "FinalAnswer", input_data=None, output_data=err_text)
            trace_service.end_trace(run_id, "completed", user_id=user_id)
            yield f"\x00TRACE_SUMMARY:{json.dumps(trace_service.get_summary(run_id, slim=True), ensure_ascii=False)}"
            return

        if web_search_called and not erp_data_pushed:
            # 纯联网搜索场景：无前端表格，允许 LLM 完整展示搜索内容
            messages.append(HumanMessage(content=(
                "请根据上方 web_search 工具返回的内容（answer 字段）直接回答用户的问题。\n\n"
                "规则：\n"
                "1. 完整展示与问题相关的内容，不要压缩或省略关键信息\n"
                "2. 使用 Markdown 格式（列表、加粗、标题等）让内容清晰易读\n"
                "3. 回答末尾必须加一个【参考来源】部分：\n"
                "   - 若 citations 字段包含链接，逐条列出（Markdown 链接格式）\n"
                "   - 若 citations 为空，则写：> 来源：Perplexity Sonar 实时联网搜索\n"
                "4. 内容必须来自工具返回的真实数据，禁止添加未经搜索的内容\n"
            )))
        else:
            # ERP 查询场景：数据已推送前端原生表格，只需文字摘要
            messages.append(HumanMessage(content=(
                "原始数据表格已通过 erp.data 事件直接推送给前端展示，用户已经可以看到完整的数据表格。\n\n"
                "现在请你只做【文字分析摘要】，规则如下：\n"
                "1. 【禁止输出表格】不要用 Markdown 表格重复展示数据，前端已有原生表格\n"
                "2. 用 1~3 句话说明查询结果的关键信息（如总数、范围、特殊情况等）\n"
                "3. 如有需要，用 **加粗** 突出关键数字或结论\n"
                "4. 如有异常（空结果、条件过严等）给出建议\n"
                "5. 所有数字、编码、名称必须来自工具返回的真实数据，禁止编造\n"
            )))

        t2 = start_timer()
        logger.ai("LangChain", f"→ 最终流式输出 | 模型={used_model}")

        stream_model = create_model(openrouter_key, used_model, 0)
        stream = stream_model.bind_tools(erp_tools, tool_choice="none").astream(messages)  # type: ignore[arg-type]

        total_chars = 0
        has_content = False
        chunk_index = 0

        async for chunk in stream:
            chunk_index += 1
            text = extract_text(chunk.content)
            if text:
                has_content = True
                total_chars += len(text)
                accumulated_answer.append(text)
                yield text

        final_answer_ms = t2()
        logger.ai(
            "LangChain",
            f"← 流式输出完成 | chunk={chunk_index} | 总字符={total_chars} | 耗时={final_answer_ms}ms",
        )

        if not has_content:
            logger.warn("LangChain", "流式输出返回空内容")
            yield "（AI 未返回内容，请检查 ERP 查询结果或重新提问）"
    else:
        final_answer_ms = None

    # ---- 7. 收尾：保存 Memory + 更新 userPreference ----
    final_answer = "".join(accumulated_answer)
    if final_answer:
        # 无知识库命中 + 无工具调用 + 有实质回答 → 疑似使用训练知识
        suspected_hallucination = (
            not knowledge_hits
            and not tools_were_called
            and len(final_answer.strip()) > 20
        )
        trace_service.log_agent(
            run_id, "FinalAnswer",
            input_data=None,
            output_data=final_answer,
            metadata={"suspected_hallucination": suspected_hallucination} if suspected_hallucination else {},
            duration_ms=final_answer_ms,
        )
    # 有工具报错时不写 Memory，防止错误内容污染后续对话
    if final_answer and not tool_errors:
        append_assistant_message(user_id, final_answer, conv_id, verified=erp_data_pushed)
        logger.ai("Memory", f"AI 回复已保存到 Memory | userId={user_id} | 字符={len(final_answer)} | verified={erp_data_pushed}")
    elif final_answer and tool_errors:
        logger.warn("Memory", f"AI 回复因工具报错未写入 Memory | userId={user_id} | errors={tool_errors}")

    for call_info in called_tool_args:
        if call_info["toolName"] == "query_erp_list" and call_info["args"].get("tableName"):
            raw_filters = call_info["args"].get("filters")
            filters_as_dicts = (
                [f if isinstance(f, dict) else f.dict() for f in raw_filters]
                if raw_filters else None
            )
            update_preference(user_id, QueryInfo(
                tableName=call_info["args"]["tableName"],
                filters=filters_as_dicts,
                pageSize=call_info["args"].get("pageSize"),
            ))

    # ---- 8. 结束 Trace，推送 summary ----
    trace_service.end_trace(run_id, "completed", user_id=user_id)
    yield f"\x00TRACE_SUMMARY:{json.dumps(trace_service.get_summary(run_id, slim=True), ensure_ascii=False)}"


# ===================== Key 测试 =====================

async def test_openrouter_key(key: str, model_name: str = "deepseek/deepseek-chat") -> dict:
    """测试 OpenRouter Key 及指定模型是否可用"""
    try:
        model = ChatOpenAI(
            api_key=key,
            model=model_name,
            max_tokens=5,
            base_url="https://openrouter.ai/api/v1",
        )
        await model.ainvoke([HumanMessage(content="hi")])
        return {"valid": True, "message": f"连接成功，模型 {model_name} 可正常使用"}
    except Exception as error:
        status = getattr(error, "status_code", None) or getattr(error, "status", None)
        if status == 401:
            return {"valid": False, "message": "Key 无效，请检查是否填写正确"}
        if status == 402:
            return {"valid": False, "message": "OpenRouter 账户余额不足，请充值后使用"}
        return {"valid": False, "message": f"验证失败，请检查网络或 Key 是否正确【{error}】"}
