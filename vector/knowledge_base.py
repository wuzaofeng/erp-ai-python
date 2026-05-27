"""
RAG 业务知识库
将业务文档切块后存入 Chroma，供 AI 在回答时召回相关段落。

文档放置目录：docs/knowledge/
支持格式：.txt  .md

使用方式：
  python -m vector.knowledge_base          # 扫描 docs/knowledge/ 建立索引
  from vector.knowledge_base import search_knowledge
  results = search_knowledge("采购订单审批流程")
"""
import os
import re
from pathlib import Path
from typing import Optional

from vector.client import get_collection
from logger import logger

_COLLECTION_NAME = "knowledge_base"
_DOCS_DIR = Path(os.getenv("KNOWLEDGE_DOCS_DIR", "docs/knowledge"))
_CHUNK_SIZE = 500       # 每块最大字符数
_CHUNK_OVERLAP = 50     # 块与块之间的重叠字符数
_SCORE_THRESHOLD = 0.15  # 相似度阈值（text-embedding-3-small 中文相似度普遍偏低，实测最高约 0.28）


# ===================== 文档切块 =====================

def _chunk_text(text: str, source: str) -> list[dict]:
    """将长文本切成重叠的小块"""
    # 优先按段落切（空行分隔）
    paragraphs = [p.strip() for p in re.split(r'\n\s*\n', text) if p.strip()]

    chunks = []
    current = ""
    chunk_index = 0

    for para in paragraphs:
        if len(current) + len(para) <= _CHUNK_SIZE:
            current = (current + "\n\n" + para).strip()
        else:
            if current:
                chunks.append({
                    "text": current,
                    "source": source,
                    "chunk_index": chunk_index,
                })
                chunk_index += 1
                # 保留末尾重叠部分
                current = current[-_CHUNK_OVERLAP:] + "\n\n" + para if _CHUNK_OVERLAP else para
            else:
                # 单段落超长，强制按字符切
                for i in range(0, len(para), _CHUNK_SIZE - _CHUNK_OVERLAP):
                    chunks.append({
                        "text": para[i:i + _CHUNK_SIZE],
                        "source": source,
                        "chunk_index": chunk_index,
                    })
                    chunk_index += 1
                current = ""

    if current:
        chunks.append({"text": current, "source": source, "chunk_index": chunk_index})

    return chunks


# ===================== 公开 API =====================

def build_knowledge_index(force: bool = False) -> int:
    """
    扫描 docs/knowledge/ 目录，将所有文档切块存入 Chroma。
    force=True 时先清空再重建。
    返回新增的块数。
    """
    if not _DOCS_DIR.exists():
        _DOCS_DIR.mkdir(parents=True, exist_ok=True)
        logger.info("KnowledgeBase", f"已创建文档目录：{_DOCS_DIR}，请将业务文档放入此目录后重新运行")
        return 0

    col = get_collection(_COLLECTION_NAME)

    if force:
        existing = col.get()
        if existing["ids"]:
            col.delete(ids=existing["ids"])
        logger.info("KnowledgeBase", "强制重建：已清空旧索引")

    existing_ids = set(col.get()["ids"])
    all_chunks = []

    for path in _DOCS_DIR.rglob("*"):
        if path.suffix not in (".txt", ".md"):
            continue
        try:
            text = path.read_text(encoding="utf-8").strip()
        except Exception as e:
            logger.warn("KnowledgeBase", f"读取文件失败：{path} | {e}")
            continue

        if not text:
            continue

        chunks = _chunk_text(text, source=path.name)
        for chunk in chunks:
            chunk_id = f"{path.stem}_{chunk['chunk_index']}"
            if chunk_id not in existing_ids:
                all_chunks.append((chunk_id, chunk))

    if not all_chunks:
        logger.info("KnowledgeBase", f"无新增文档块，当前共 {len(existing_ids)} 块")
        return 0

    col.add(
        ids=[c[0] for c in all_chunks],
        documents=[c[1]["text"] for c in all_chunks],
        metadatas=[{"source": c[1]["source"], "chunk_index": c[1]["chunk_index"]} for c in all_chunks],
    )

    logger.info("KnowledgeBase", f"知识库已更新：新增 {len(all_chunks)} 块，总计 {len(existing_ids) + len(all_chunks)} 块")
    return len(all_chunks)


def search_knowledge(query: str, n: int = 3) -> list[dict]:
    """
    语义搜索与 query 最相关的文档段落。
    返回：[{"text": str, "source": str, "score": float}, ...]
    score > 0.5 才认为相关
    """
    col = get_collection(_COLLECTION_NAME)
    count = col.count()
    if count == 0:
        return []

    results = col.query(
        query_texts=[query],
        n_results=min(n, count),
        include=["documents", "metadatas", "distances"],
    )

    output = []
    for i in range(len(results["ids"][0])):
        score = round(1 - results["distances"][0][i], 4)
        if score < _SCORE_THRESHOLD:
            continue
        output.append({
            "text": results["documents"][0][i],
            "source": results["metadatas"][0][i].get("source", ""),
            "score": score,
        })

    return output


def build_knowledge_prompt(query: str) -> str:
    """
    给定用户问题，返回可注入 System Prompt 的知识段落文本。
    若无相关文档则返回空字符串。
    """
    results = search_knowledge(query, n=3)
    if not results:
        return ""

    lines = ["【相关业务知识】"]
    for r in results:
        lines.append(f"（来源：{r['source']}）")
        lines.append(r["text"])
        lines.append("")

    return "\n".join(lines)


def get_knowledge_stats() -> dict:
    col = get_collection(_COLLECTION_NAME)
    return {"collection": _COLLECTION_NAME, "count": col.count(), "docs_dir": str(_DOCS_DIR)}


def index_file(file_path: Path) -> int:
    """将单个文件提取、清洗、分块后存入 Chroma，返回新增块数"""
    from vector.document_processor import extract_text, clean_text

    raw = extract_text(file_path)
    text = clean_text(raw)
    if not text:
        return 0

    col = get_collection(_COLLECTION_NAME)
    existing_ids = set(col.get()["ids"])

    # 先删除该文件旧的块（支持重新上传覆盖）
    old_ids = [i for i in existing_ids if i.startswith(file_path.stem + "_")]
    if old_ids:
        col.delete(ids=old_ids)
        logger.info("KnowledgeBase", f"已删除旧索引块：{len(old_ids)} 块 | 文件={file_path.name}")

    chunks = _chunk_text(text, source=file_path.name)
    if not chunks:
        return 0

    col.add(
        ids=[f"{file_path.stem}_{c['chunk_index']}" for c in chunks],
        documents=[c["text"] for c in chunks],
        metadatas=[{"source": c["source"], "chunk_index": c["chunk_index"]} for c in chunks],
    )
    logger.info("KnowledgeBase", f"文件已索引：{file_path.name} | 新增 {len(chunks)} 块")
    return len(chunks)


def delete_file_index(filename: str) -> int:
    """从 Chroma 中删除某文件的所有块，返回删除块数"""
    stem = Path(filename).stem
    col = get_collection(_COLLECTION_NAME)
    all_ids = col.get()["ids"]
    target_ids = [i for i in all_ids if i.startswith(stem + "_")]
    if target_ids:
        col.delete(ids=target_ids)
        logger.info("KnowledgeBase", f"已删除索引：{filename} | {len(target_ids)} 块")
    return len(target_ids)


def list_indexed_files() -> list[dict]:
    """列出已建索引的所有文件及块数"""
    col = get_collection(_COLLECTION_NAME)
    result = col.get(include=["metadatas"])
    if not result["ids"]:
        return []

    file_chunks: dict[str, int] = {}
    for meta in result["metadatas"]:
        src = meta.get("source", "unknown")
        file_chunks[src] = file_chunks.get(src, 0) + 1

    # 补充磁盘文件的上传时间
    output = []
    for filename, count in sorted(file_chunks.items()):
        file_path = _DOCS_DIR / filename
        indexed_at = (
            file_path.stat().st_mtime if file_path.exists() else None
        )
        output.append({
            "filename": filename,
            "chunk_count": count,
            "indexed_at": indexed_at,
            "exists_on_disk": file_path.exists(),
        })
    return output


if __name__ == "__main__":
    count = build_knowledge_index(force=True)
    print(f"索引完成，新增 {count} 块")
    stats = get_knowledge_stats()
    print(f"当前知识库：{stats}")
