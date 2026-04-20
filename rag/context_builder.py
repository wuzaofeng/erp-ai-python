"""
RAG（检索增强生成）数据上下文构建器 - 对应 src/rag/contextBuilder.ts
大数据集只传相关行给 AI，减少 token 消耗
"""
import os
import re
import json
from dataclasses import dataclass
from logger import logger

# ===================== 配置 =====================

RAG_THRESHOLD = int(os.getenv("RAG_THRESHOLD", "30"))
MAX_RELEVANT_ROWS = int(os.getenv("RAG_MAX_ROWS", "20"))


# ===================== 类型 =====================

@dataclass
class RawErpData:
    rows: list[dict]
    total: int
    page_index: int
    page_size: int


@dataclass
class BuiltContext:
    context_text: str
    is_rag: bool
    sent_row_count: int


# ===================== 工具函数 =====================

_STOP_WORDS = {"查询", "查找", "显示", "列出", "一下", "所有", "全部", "什么", "哪些", "这些", "帮我", "帮忙"}


def _extract_keywords(user_message: str) -> list[str]:
    """从用户问题中提取关键词（中文词2字以上 + 英文单词）"""
    chinese_words = re.findall(r"[\u4e00-\u9fa5]{2,}", user_message)
    english_words = re.findall(r"[a-zA-Z][a-zA-Z0-9]*", user_message)
    return [
        w.lower()
        for w in chinese_words + english_words
        if w not in _STOP_WORDS
    ]


def _score_row(row: dict, keywords: list[str]) -> int:
    """计算一行数据与关键词的相关度得分"""
    if not keywords:
        return 0
    row_text = " ".join(
        str(v).lower()
        for v in row.values()
        if v is not None
    )
    return sum(1 for kw in keywords if kw in row_text)


def _build_summary(data: RawErpData) -> str:
    """生成数据集的统计摘要"""
    rows = data.rows
    total = data.total
    page_index = data.page_index
    page_size = data.page_size

    if not rows:
        return f"查询结果为空（共 {total} 条）。"

    fields = list(rows[0].keys())

    # 对数值字段做简单统计（只取前 5 个字段）
    num_stats = []
    for field_name in fields[:5]:
        nums = []
        for row in rows:
            try:
                nums.append(float(row.get(field_name, "")))
            except (ValueError, TypeError):
                pass
        if nums:
            mn, mx, sm = min(nums), max(nums), sum(nums)
            if mn != mx:
                num_stats.append(f"{field_name}(范围:{mn:.2f}~{mx:.2f}, 总计:{sm:.2f})")

    lines = [
        "⚠️ 以下是 ERP 系统返回的【真实数据摘要】，字段值必须严格引用，禁止编造：",
        f"- 查询总记录数：{total} 条（本页第 {page_index} 页，每页 {page_size} 条，本页共 {len(rows)} 条）",
        f"- 包含字段：{', '.join(fields[:15])}" + (f" 等共 {len(fields)} 个字段" if len(fields) > 15 else ""),
    ]
    if num_stats:
        lines.append(f"- 数值统计：{'；'.join(num_stats)}")
    return "\n".join(lines)


# ===================== 主函数 =====================

def build_context(
    data: RawErpData,
    user_message: str,
    field_labels: dict[str, str] | None = None,
) -> BuiltContext:
    """
    构建传给 AI 的 RAG 上下文
    - 小数据集（≤ RAG_THRESHOLD）：直接全量传递
    - 大数据集：摘要 + 相关度最高的 MAX_RELEVANT_ROWS 条
    """
    rows = data.rows
    disclaimer = (
        "⚠️ 以下是 ERP 系统返回的【真实数据】，你必须严格按照此数据作答，"
        "禁止使用任何训练知识替换或补充下列字段值：\n"
    )

    # 小数据集：直接全量传递
    if len(rows) <= RAG_THRESHOLD:
        result_json = json.dumps(
            {"total": data.total, "pageIndex": data.page_index, "pageSize": data.page_size, "rows": rows},
            ensure_ascii=False, indent=2
        )
        logger.info("RAG", f"小数据集全量传递 | rows={len(rows)} | threshold={RAG_THRESHOLD}")
        return BuiltContext(
            context_text=disclaimer + result_json,
            is_rag=False,
            sent_row_count=len(rows),
        )

    # 大数据集：RAG 分片
    logger.info("RAG", f"大数据集触发RAG分片 | rows={len(rows)} | 提取关键词中...")
    keywords = _extract_keywords(user_message)
    logger.info("RAG", f"关键词: [{', '.join(keywords)}]")

    scored = sorted(
        enumerate(rows),
        key=lambda x: (-_score_row(x[1], keywords), x[0])
    )
    relevant_rows = [row for _, row in scored[:MAX_RELEVANT_ROWS]]

    summary = _build_summary(data)

    label_note = ""
    if field_labels:
        label_pairs = ", ".join(
            f"{k}={v}" for k, v in list(field_labels.items())[:20]
        )
        label_note = f"\n字段中文对应：{label_pairs}"

    relevant_json = json.dumps(
        {
            "total": data.total,
            "pageIndex": data.page_index,
            "pageSize": data.page_size,
            "shownRows": len(relevant_rows),
            "rows": relevant_rows,
        },
        ensure_ascii=False, indent=2
    )

    context_text = "\n".join(filter(None, [
        summary,
        label_note,
        f"\n以下是与你问题最相关的 {len(relevant_rows)} 条数据（从 {len(rows)} 条中智能筛选）：",
        disclaimer,
        relevant_json,
        f"\n注意：以上仅为最相关数据，完整 {len(rows)} 条数据已通过 erp.data 事件发送给前端。",
    ]))

    logger.info(
        "RAG",
        f"RAG分片完成 | 总行={len(rows)} | 传给AI={len(relevant_rows)} | 关键词={len(keywords)}个"
    )

    return BuiltContext(
        context_text=context_text,
        is_rag=True,
        sent_row_count=len(relevant_rows),
    )
