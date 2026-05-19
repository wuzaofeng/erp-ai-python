"""
Chroma 向量数据库客户端封装
数据存储在 data/chroma/ 目录，与 SQLite 同级，无需额外服务。

嵌入模型优先级：
  1. 若设置了 OPENROUTER_API_KEY 或 OPENAI_API_KEY，使用 OpenAI-compatible embedding API
  2. 否则降级到 Chroma 内置的 ONNX 模型（需要从网络下载 80MB 模型文件）
"""
import os
from pathlib import Path
from typing import Optional

import chromadb
from chromadb import Collection
from chromadb.utils import embedding_functions

_CHROMA_PATH = Path(os.getenv("CHROMA_PATH", "data/chroma"))
_client: Optional[chromadb.PersistentClient] = None
_embed_fn = None


def _get_embedding_function():
    global _embed_fn
    if _embed_fn is not None:
        return _embed_fn

    # 优先使用 OpenRouter / OpenAI embedding API，无需本地下载模型
    api_key = os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY")
    if api_key:
        base_url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
        _embed_fn = embedding_functions.OpenAIEmbeddingFunction(
            api_key=api_key,
            api_base=base_url,
            model_name=os.getenv("EMBEDDING_MODEL", "openai/text-embedding-3-small"),
        )
    else:
        # 降级到本地 ONNX 模型（首次使用需要下载）
        _embed_fn = embedding_functions.DefaultEmbeddingFunction()

    return _embed_fn


def get_client() -> chromadb.PersistentClient:
    global _client
    if _client is None:
        _CHROMA_PATH.mkdir(parents=True, exist_ok=True)
        _client = chromadb.PersistentClient(path=str(_CHROMA_PATH))
    return _client


def get_collection(name: str, metadata: Optional[dict] = None) -> Collection:
    """获取或创建 Collection"""
    client = get_client()
    return client.get_or_create_collection(
        name=name,
        embedding_function=_get_embedding_function(),
        metadata=metadata or {"hnsw:space": "cosine"},
    )
