"""
联网搜索工具 — 调用 Tavily Search API 获取实时外部信息
适用场景：天气、汇率、行业资讯、政策法规等公开信息查询
"""
import os
import json
from pydantic import BaseModel, Field
from langchain_core.tools import StructuredTool

from logger import logger

TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")

WEB_SEARCH_DESCRIPTION = (
    "搜索互联网上的公开信息，适用于查询天气、汇率、行业资讯、政策法规等外部实时数据。"
    "不适用于查询公司内部 ERP 业务数据（订单/库存/采购等），内部数据请使用 query_erp_list。"
)


class WebSearchInput(BaseModel):
    query: str = Field(description="搜索关键词，尽量用中文描述，如'上海今天天气'、'美元兑人民币汇率'")


def _do_search(query: str) -> str:
    if not TAVILY_API_KEY:
        return json.dumps({"error": "未配置 TAVILY_API_KEY，联网搜索不可用"}, ensure_ascii=False)
    try:
        from tavily import TavilyClient
        client = TavilyClient(api_key=TAVILY_API_KEY)
        resp = client.search(query, max_results=5, search_depth="basic")
        results = [
            {"title": r.get("title", ""), "url": r.get("url", ""), "content": r.get("content", "")}
            for r in resp.get("results", [])
        ]
        return json.dumps({"results": results}, ensure_ascii=False)
    except ImportError:
        return json.dumps({"error": "tavily-python 未安装，请执行 pip install tavily-python"}, ensure_ascii=False)
    except Exception as e:
        logger.error("WebSearch", f"搜索失败 | query={query} | {e}")
        return json.dumps({"error": f"搜索失败：{e}"}, ensure_ascii=False)


def create_web_search_tool(run_id: str = "") -> StructuredTool:
    def handler(query: str) -> str:
        t = logger.start_timer() if hasattr(logger, "start_timer") else None
        from logger import start_timer
        _t = start_timer()
        result = _do_search(query)
        duration = _t()
        logger.info("WebSearch", f"搜索完成 | query={query} | 耗时={duration}ms")
        if run_id:
            try:
                from trace.agent_trace import trace_service
                parsed = json.loads(result)
                trace_service.log_knowledge_search(
                    run_id, query,
                    hits=parsed.get("results", []),
                    duration_ms=duration,
                )
            except Exception:
                pass
        return result

    return StructuredTool.from_function(
        func=handler,
        name="web_search",
        description=WEB_SEARCH_DESCRIPTION,
        args_schema=WebSearchInput,
    )
