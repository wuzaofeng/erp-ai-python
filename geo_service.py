"""
IP 地理位置服务 — 通过 ip-api.com 反查城市，用于天气等场景自动定位
免费接口，无需 API Key，精度到城市级
"""
import time
import httpx
from logger import logger

_CACHE: dict[str, tuple[str, float]] = {}  # ip -> (city, expire_ts)
_TTL = 3600  # 1 小时
_TIMEOUT = 3.0


async def get_city_by_ip(ip: str) -> str:
    """
    根据 IP 返回中文城市名，查询失败或内网 IP 返回空字符串
    """
    if not ip or ip in ("127.0.0.1", "::1", "localhost"):
        return ""

    # 内网地址直接跳过
    if ip.startswith(("10.", "192.168.", "172.")):
        return ""

    now = time.time()
    if ip in _CACHE:
        city, expire_ts = _CACHE[ip]
        if now < expire_ts:
            return city

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                f"http://ip-api.com/json/{ip}",
                params={"lang": "zh-CN", "fields": "status,city,regionName"},
            )
        data = resp.json()
        if data.get("status") == "success":
            city = data.get("city") or data.get("regionName") or ""
            _CACHE[ip] = (city, now + _TTL)
            logger.info("GeoService", f"IP={ip} → 城市={city}")
            return city
    except Exception as e:
        logger.warn("GeoService", f"IP 定位失败 | IP={ip} | {e}")

    _CACHE[ip] = ("", now + _TTL)
    return ""
