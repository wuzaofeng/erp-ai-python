"""
知识库文档管理路由
"""
from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse

from vector.knowledge_base import index_file, delete_file_index, list_indexed_files, get_knowledge_stats, search_knowledge
from vector.client import get_collection
from vector.document_processor import SUPPORTED_SUFFIXES, MAX_FILE_SIZE
from logger import logger

router = APIRouter(prefix="/api/ai/knowledge", tags=["knowledge"])

_DOCS_DIR = Path(os.getenv("KNOWLEDGE_DOCS_DIR", "docs/knowledge"))

_OPERATE_PATTERN = re.compile(
    r"(操作步骤|第[一二三四五六七八九十\d]+步|如何操作|操作流程|步骤\s*[：:]|操作说明)", re.MULTILINE
)
_MARKDOWN_PATTERN = re.compile(
    r"(^#{1,6}\s|\*\*[^*]+\*\*|\|.+\|.+\||\n[-*]\s|\n\d+\.\s)", re.MULTILINE
)


def _classify_chunk(text: str) -> dict:
    """判断 chunk 的 type（view/operate）和 format（markdown/text）"""
    chunk_type = "operate" if _OPERATE_PATTERN.search(text) else "view"
    fmt = "markdown" if _MARKDOWN_PATTERN.search(text) else "text"
    return {"type": chunk_type, "format": fmt}


@router.post("/upload")
async def upload_knowledge_file(file: UploadFile = File(...)):
    """上传文档并建立向量索引"""
    suffix = Path(file.filename).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件格式：{suffix}，支持：{', '.join(SUPPORTED_SUFFIXES)}",
        )

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="文件大小超过 20MB 限制")

    _DOCS_DIR.mkdir(parents=True, exist_ok=True)
    save_path = _DOCS_DIR / file.filename

    save_path.write_bytes(content)
    logger.info("Knowledge", f"文件已保存：{file.filename} | {len(content)} 字节")

    try:
        chunks_added = index_file(save_path)
    except Exception as e:
        save_path.unlink(missing_ok=True)
        logger.error("Knowledge", f"索引失败：{file.filename} | {e}")
        raise HTTPException(status_code=500, detail=f"文件处理失败：{str(e)}")

    return {
        "filename": file.filename,
        "chunks_added": chunks_added,
        "status": "success",
    }


@router.get("/list")
def list_files():
    """列出已上传的文档"""
    files = list_indexed_files()
    # 将 mtime 转为可读时间字符串
    for f in files:
        if f["indexed_at"]:
            import datetime
            f["indexed_at"] = datetime.datetime.fromtimestamp(f["indexed_at"]).strftime("%Y-%m-%d %H:%M")
    return {"files": files, "total": len(files)}


@router.delete("/{filename}")
def delete_file(filename: str):
    """删除文档及其向量索引"""
    file_path = _DOCS_DIR / filename
    deleted_chunks = delete_file_index(filename)

    if file_path.exists():
        file_path.unlink()
        logger.info("Knowledge", f"文件已删除：{filename}")

    return {
        "filename": filename,
        "deleted_chunks": deleted_chunks,
        "status": "success",
    }


@router.get("/search")
def search_knowledge_endpoint(q: str, n: int = 5):
    """测试召回：输入问题，返回最相关的文档段落及相似度分数"""
    if not q.strip():
        raise HTTPException(status_code=400, detail="查询内容不能为空")
    results = search_knowledge(q.strip(), n=min(n, 10))
    return {"query": q, "results": results, "total": len(results)}


@router.get("/chunks/{filename}")
def get_file_chunks(filename: str):
    """获取某文件的所有知识块内容，含 type/format 分类"""
    col = get_collection("knowledge_base")
    result = col.get(include=["documents", "metadatas"])
    chunks = []
    for doc, meta in zip(result["documents"], result["metadatas"]):
        if meta.get("source") != filename:
            continue
        classification = _classify_chunk(doc)
        chunks.append({
            "index": meta["chunk_index"],
            "text": doc,
            "type": classification["type"],    # "view" | "operate"
            "format": classification["format"], # "markdown" | "text"
        })
    chunks.sort(key=lambda x: x["index"])
    return {"filename": filename, "chunks": chunks, "total": len(chunks)}


@router.get("/stats")
def knowledge_stats():
    """知识库统计"""
    return get_knowledge_stats()
