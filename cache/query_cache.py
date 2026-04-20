"""
ERP 查询结果缓存 - 对应 src/cache/queryCache.ts
TTL 内命中缓存时直接返回，跳过 ERP 接口请求
"""
import os
import json
import hashlib
import time
from dataclasses import dataclass
from logger import logger

# ===================== 配置 =====================

CACHE_TTL_S = int(os.getenv("QUERY_CACHE_TTL_MS", str(5 * 60 * 1000))) / 1000  # 转为秒，默认 5 分钟
MAX_CACHE_SIZE = int(os.getenv("QUERY_CACHE_MAX_SIZE", "200"))


# ===================== 类型 =====================

@dataclass
class CacheEntry:
    value: str
    expires_at: float
    created_at: float


# ===================== 缓存存储 =====================

_cache: dict[str, CacheEntry] = {}


# ===================== 工具函数 =====================

def build_cache_key(params: dict, user_id: str = "") -> str:
    """
    根据查询参数生成缓存 Key（SHA-256 哈希前 16 位）
    等价于 TypeScript 版的 buildCacheKey
    """
    normalized = {
        "userId":    user_id or "",
        "tableName": params.get("tableName", ""),
        "filters":   params.get("filters") or [],
        "pageSize":  params.get("pageSize", 20),
        "pageIndex": params.get("pageIndex", 1),
        "apiPath":   params.get("apiPath") or "",
        "extraBody": params.get("extraBody") or {},
    }
    raw = json.dumps(normalized, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _evict() -> None:
    """清理过期条目（写入时触发）"""
    now = time.time()
    expired_keys = [k for k, v in _cache.items() if v.expires_at <= now]
    for k in expired_keys:
        del _cache[k]

    if len(_cache) > MAX_CACHE_SIZE:
        # 简单 LRU：删除最早创建的条目
        sorted_keys = sorted(_cache.keys(), key=lambda k: _cache[k].created_at)
        to_remove = sorted_keys[:len(_cache) - MAX_CACHE_SIZE]
        for k in to_remove:
            del _cache[k]
        logger.info("QueryCache", f"LRU 淘汰 {len(to_remove)} 条旧缓存")


# ===================== 公开 API =====================

def get_cache(key: str) -> str | None:
    """从缓存中获取查询结果，未命中或已过期返回 None"""
    entry = _cache.get(key)
    if not entry:
        return None
    if time.time() > entry.expires_at:
        del _cache[key]
        return None
    return entry.value


def set_cache(key: str, value: str) -> None:
    """写入查询结果到缓存"""
    _evict()
    now = time.time()
    _cache[key] = CacheEntry(
        value=value,
        expires_at=now + CACHE_TTL_S,
        created_at=now,
    )
    logger.info("QueryCache", f"缓存写入 | key={key[:8]}... | TTL={int(CACHE_TTL_S)}s | 当前缓存数={len(_cache)}")


def invalidate_cache(key: str) -> None:
    """手动清除指定 key 的缓存"""
    _cache.pop(key, None)


def clear_all_cache() -> None:
    """清空所有缓存"""
    size = len(_cache)
    _cache.clear()
    logger.info("QueryCache", f"已清空全部缓存 | 共 {size} 条")


def get_cache_stats() -> dict:
    """获取缓存统计信息"""
    return {
        "size": len(_cache),
        "maxSize": MAX_CACHE_SIZE,
        "ttlMs": int(CACHE_TTL_S * 1000),
    }
