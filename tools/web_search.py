"""
联网搜索工具 — 调用 Perplexity Sonar (via OpenRouter) 获取实时外部信息
适用场景：天气、汇率、行业资讯、政策法规等公开信息查询
"""
import json
from pydantic import BaseModel, Field
from langchain_core.tools import StructuredTool

from logger import logger, start_timer

WEB_SEARCH_DESCRIPTION = (
    "搜索互联网上的任何公开信息，包括但不限于：天气预报、汇率、体育赛事比分/赛程、"
    "新闻资讯、行业动态、政策法规、公司背景、产品价格等实时或公开数据。"
    "只要信息来自互联网而非公司内部 ERP 系统，都应调用此工具。"
    "不适用于查询公司内部 ERP 业务数据（订单/库存/采购等），内部数据请使用 query_erp_list。"
)


class WebSearchInput(BaseModel):
    query: str = Field(description="搜索关键词，尽量用中文描述，如'深圳今天天气'、'美元兑人民币汇率'")


async def _do_search_async(query: str, openrouter_key: str) -> str:
    """调用 Perplexity Sonar（via OpenRouter）执行联网搜索，返回 JSON 字符串"""
    if not openrouter_key:
        return json.dumps({"error": "未配置 OpenRouter API Key，联网搜索不可用"}, ensure_ascii=False)
    try:
        import httpx
        payload = {
            "model": "perplexity/sonar",
            "messages": [{"role": "user", "content": query}],
        }
        headers = {
            "Authorization": f"Bearer {openrouter_key}",
            "HTTP-Referer": "http://localhost:8000",
            "X-Title": "ERP AI Assistant",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                json=payload,
                headers=headers,
            )
        resp.raise_for_status()
        data = resp.json()
        answer = data["choices"][0]["message"]["content"]
        citations = data.get("citations", [])
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
