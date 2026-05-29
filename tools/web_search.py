"""
联网搜索工具 — 调用 Perplexity Sonar (via OpenRouter) 获取实时外部信息
适用场景：天气、汇率、行业资讯、政策法规等公开信息查询
"""
import json
from pydantic import BaseModel, Field
from langchain_core.tools import StructuredTool

from logger import logger, start_timer

WEB_SEARCH_DESCRIPTION = (
    "搜索互联网上的任何公开信息。"
    "凡是答案不在公司 ERP 内部系统中的问题，一律调用此工具，不受话题类型限制。"
    "不适用于查询公司内部 ERP 业务数据（订单/库存/采购等），内部数据请使用 query_erp_list。"
)


class WebSearchInput(BaseModel):
    query: str = Field(description="搜索关键词，尽量用中文描述，如'深圳今天天气'、'美元兑人民币汇率'")


def _extract_citations(data: dict, answer: str) -> list[str]:
    """从 OpenRouter/Perplexity 响应中提取引用链接，多路径兜底"""
    # 路径1：顶层 citations（Perplexity 原生格式）
    cites = data.get("citations") or []
    if cites:
        return [c if isinstance(c, str) else c.get("url", str(c)) for c in cites]

    # 路径2：choices[0].message.citations（部分 OpenRouter 版本）
    try:
        cites = data["choices"][0]["message"].get("citations") or []
        if cites:
            return [c if isinstance(c, str) else c.get("url", str(c)) for c in cites]
    except (KeyError, IndexError, TypeError):
        pass

    # 路径3：从回答文本中提取裸 URL（兜底）
    import re
    urls = re.findall(r'https?://[^\s\)\]\>\"\']+', answer)
    seen: dict[str, bool] = {}
    return [u for u in urls if not seen.get(u) and not seen.update({u: True})]  # type: ignore[func-returns-value]


async def _do_search_async(query: str, openrouter_key: str) -> str:
    """调用 Perplexity Sonar（via OpenRouter）执行联网搜索，返回 JSON 字符串"""
    if not openrouter_key:
        return json.dumps({"error": "未配置 OpenRouter API Key，联网搜索不可用"}, ensure_ascii=False)
    try:
        import httpx
        payload = {
            "model": "perplexity/sonar-pro",
            "messages": [{"role": "user", "content": query}],
        }
        headers = {
            "Authorization": f"Bearer {openrouter_key}",
            "HTTP-Referer": "http://localhost:8000",
            "X-Title": "ERP AI Assistant",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                json=payload,
                headers=headers,
            )
        resp.raise_for_status()
        data = resp.json()
        answer = data["choices"][0]["message"]["content"]
        citations = _extract_citations(data, answer)
        logger.info("WebSearch", f"citations={len(citations)} 条 | keys={list(data.keys())}")
        return json.dumps({"answer": answer, "citations": citations}, ensure_ascii=False)
    except Exception as e:
        logger.error("WebSearch", f"Perplexity 搜索失败 | query={query} | {e}")
        return json.dumps({"error": f"搜索失败：{e}"}, ensure_ascii=False)


def create_web_search_tool(run_id: str = "", openrouter_key: str = "") -> StructuredTool:
    async def handler(query: str) -> str:
        _t = start_timer()
        result = await _do_search_async(query, openrouter_key)
        duration = _t()
        logger.info("WebSearch", f"Perplexity 搜索完成 | query={query} | 耗时={duration}ms")
        # trace 由 ai_service.py 的 log_tool 统一记录，此处不重复打
        return result

    return StructuredTool.from_function(
        coroutine=handler,
        name="web_search",
        description=WEB_SEARCH_DESCRIPTION,
        args_schema=WebSearchInput,
    )
