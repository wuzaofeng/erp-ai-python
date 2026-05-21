"""
ERP 客户端模块 - 对应 src/erpClient.ts
负责调用 ERP CommonQuery、全局搜索、字段布局接口
"""
import os
import json
from typing import Optional
import httpx
from logger import logger, start_timer

# ===================== 字段布局缓存 =====================
# key: f"{user_id}:{form_code}", TTL: 10 分钟（600 秒）

from dataclasses import dataclass, field
import time

@dataclass
class FieldLayoutCache:
    field_labels: dict[str, str]
    hidden_fields: list[dict]
    expires_at: float

_field_layout_cache: dict[str, FieldLayoutCache] = {}
FIELD_LAYOUT_TTL_S = 10 * 60  # 10 分钟

# ===================== 操作符映射 =====================

OPERATOR_MAP: dict[str, str] = {
    # 兼容旧版简写，统一转为 ERP 标准值
    "=":           "Equal",
    "!=":          "NotEqual",
    ">":           "GreaterThan",
    ">=":          "GreaterThanOrEqual",
    "<":           "LessThan",
    "<=":          "LessThanOrEqual",
    "contains":    "Like",
    "notContains": "NotLike",
    "startsWith":  "StartWith",
    "endsWith":    "EndWith",
    "isNull":      "IsNull",
    "isNotNull":   "IsNotNull",
    "inList":      "InList",
    "notInList":   "NotInList",
    # ERP 标准值直传（AI 直接传标准值时原样保留）
    "Equal":              "Equal",
    "NotEqual":           "NotEqual",
    "GreaterThan":        "GreaterThan",
    "GreaterThanOrEqual": "GreaterThanOrEqual",
    "LessThan":           "LessThan",
    "LessThanOrEqual":    "LessThanOrEqual",
    "Like":               "Like",
    "NotLike":            "NotLike",
    "StartWith":          "StartWith",
    "EndWith":            "EndWith",
    "IsNull":             "IsNull",
    "IsNotNull":          "IsNotNull",
    "InList":             "InList",
    "NotInList":          "NotInList",
}


def _to_erp_api_filters(filters: list[dict]) -> list[dict]:
    """将 AI 工具调用格式的 ErpFilter 转为 ERP 接口实际格式 ErpApiFilter"""
    result = []
    last = len(filters) - 1
    for i, f in enumerate(filters):
        item: dict = {
            "fFeild":          f["FieldName"],
            "fComparOperator": OPERATOR_MAP.get(f["Operator"], f["Operator"]),
            "fValue":          f.get("Value", ""),
            "fLeftKuoHao":     f.get("LeftParen", ""),
            "fRightKuoHao":    f.get("RightParen", ""),
        }
        if i < last:
            item["fConnectRelate"] = f.get("Logic", "and")
        result.append(item)
    return result


ERP_BASE_URL = os.getenv("ERP_BASE_URL", "http://localhost:5000")

# 允许内网自签名证书（等价于 rejectUnauthorized: false）
_HTTP_CLIENT_KWARGS = {
    "verify": False,
    "follow_redirects": False,
    "timeout": 15.0,
}

def _build_erp_headers(erp_cookie: str = "", erp_auth: str = "") -> dict:
    """构造 ERP 请求头"""
    headers = {
        "Accept":          "application/json, text/plain, */*",
        "Content-Type":    "application/json",
        "Language":        os.getenv("ERP_LANGUAGE",   "zh-CN"),
        "Accept-Language": os.getenv("ERP_LANGUAGE",   "zh-CN"),
        "Time-Zone":       os.getenv("ERP_TIMEZONE",   "Asia/Shanghai"),
        "Utc-Offset":      os.getenv("ERP_UTC_OFFSET", "-480"),
    }
    if erp_cookie:
        headers["Cookie"] = erp_cookie
    if erp_auth:
        headers["Authorization"] = erp_auth
    return headers


def _build_common_query_body(args: dict) -> dict:
    """根据 AI 工具参数组装 CommonQuery 请求体"""
    raw_filters = args.get("filters")
    pagination: dict = {
        "PageIndex":  args.get("pageIndex", 1),
        "PageSize":   args.get("pageSize", 20),
        "IsPageable": True,
        "lstFldFliter": [],
    }
    if raw_filters is not None:
        pagination["lstAdvFilterRow"] = _to_erp_api_filters(raw_filters)
    default_body = {
        "TableName": args["tableName"],
        "Pagination": pagination,
        "IsChild": False,
        "Action":  "GridBrowse",
        "formData": {},
        "flag":    "clickSearchBtn",
    }
    extra_body = args.get("extraBody")
    if extra_body:
        return {**default_body, **extra_body}
    return default_body


# ===================== CommonQuery =====================

async def call_common_query(args: dict, erp_cookie: str, erp_authorization: str = "") -> str:
    """
    调用 ERP 通用查询接口 CommonQuery
    返回查询结果的 JSON 字符串（直接返回给 AI）
    """
    body = _build_common_query_body(args)
    elapsed = start_timer()

    api_segment = (args.get("apiPath") or "FormCommon").strip() or "FormCommon"
    url = f"{ERP_BASE_URL}/gw/api/ERP/{api_segment}/CommonQuery"

    logger.erp("CommonQuery", f"→ 请求 | 表={args['tableName']} | 路径={api_segment} | 页码={args.get('pageIndex', 1)} | 每页={args.get('pageSize', 20)}")
    filters = args.get("filters") or []
    if filters:
        conds = " AND ".join(f"{f['FieldName']} {f['Operator']} {f['Value']}" for f in filters)
        logger.erp("CommonQuery", f"  过滤条件: {conds}")
    logger.erp("CommonQuery", f"  URL: POST {url}")
    logger.erp("CommonQuery", f"  请求体:\n{json.dumps(body, ensure_ascii=False, indent=2)}")

    headers = _build_erp_headers(erp_cookie, erp_authorization)

    try:
        async with httpx.AsyncClient(**_HTTP_CLIENT_KWARGS) as client:
            response = await client.post(url, json=body, headers=headers)

        data = response.json()

        if data.get("success") is False:
            logger.error("CommonQuery", f"← ERP 业务失败: {data.get('msg')}")
            return json.dumps({"error": data.get("msg") or "ERP 查询失败"})

        origin_response = data.get("response")
        raw_rows: list = []
        if origin_response and isinstance(origin_response.get("Data"), list):
            if origin_response["Data"] and isinstance(origin_response["Data"][0], list):
                raw_rows = origin_response["Data"][0]
            elif origin_response["Data"] and isinstance(origin_response["Data"][0], dict):
                raw_rows = origin_response["Data"]

        # 清洗：去除 null / None 字段
        rows = [
            {k: v for k, v in row.items() if v is not None}
            for row in raw_rows
        ]

        pagination = (origin_response or {}).get("Pagination") or {}
        result = {
            "total":     pagination.get("TotalCount") or (origin_response or {}).get("TotalCount") or len(rows),
            "pageIndex": pagination.get("PageIndex") or args.get("pageIndex", 1),
            "pageSize":  pagination.get("PageSize") or args.get("pageSize", 20),
            "rows":      rows,
        }

        logger.erp("CommonQuery", f"← 响应 {response.status_code} | 总记录={result['total']} | 本次返回={len(rows)}条")

        disclaimer = (
            "⚠️ 以下是 ERP 系统返回的【真实数据】，你必须严格按照此数据作答，"
            "禁止使用任何训练知识替换或补充下列字段值：\n"
        )
        return disclaimer + json.dumps(result, ensure_ascii=False, indent=2)

    except httpx.HTTPStatusError as e:
        status = e.response.status_code
        logger.error("CommonQuery", f"← 失败 {status} | {e} | 耗时={elapsed()}ms")
        if status == 401:
            return json.dumps({"error": "登录已过期，请重新登录 ERP 系统"})
        if status == 403:
            return json.dumps({"error": "您没有权限查询该数据"})
        return json.dumps({"error": f"ERP 接口请求失败: {e}", "status": status})
    except Exception as e:
        logger.error("CommonQuery", f"← 未知错误: {e} | 耗时={elapsed()}ms")
        return json.dumps({"error": "未知错误，请稍后重试"})


# ===================== 全局单据搜索 =====================

async def call_global_search(
    keyword: str,
    erp_cookie: str,
    erp_auth: str = "",
    operator: str = "Equal",
) -> str:
    """调用 ERP ADM100_ZuruQuery/CommonQuery 接口，按单据号全局搜索"""
    url = f"{ERP_BASE_URL}/gw/api/ERP/ADM100_ZuruQuery/CommonQuery"
    body = {
        "TableName": "ADM100_ZuruQuery.ADM100_ZuruQuery",
        "Pagination": {
            "PageIndex": 1,
            "PageSize": 50,
            "IsPageable": False,
            "lstFldFliter": [],
            "lstAdvFilterRow": [
                {"fComparOperator": operator, "fFeild": "fDanNo", "fValue": keyword}
            ],
        },
        "IsChild": False,
        "Action": "GridBrowse",
    }

    elapsed = start_timer()
    logger.erp("GlobalSearch", f"→ 请求 | 关键词={keyword} | URL: POST {url}")
    headers = _build_erp_headers(erp_cookie, erp_auth)

    try:
        async with httpx.AsyncClient(**_HTTP_CLIENT_KWARGS) as client:
            response = await client.post(url, json=body, headers=headers)

        data = response.json()
        if data.get("success") is False:
            logger.error("GlobalSearch", f"← ERP 业务失败: {data.get('msg')}")
            return json.dumps({"error": data.get("msg") or "ERP 全局搜索失败"})

        origin_response = data.get("response")
        raw_rows: list = []
        if origin_response and isinstance(origin_response.get("Data"), list):
            if origin_response["Data"] and isinstance(origin_response["Data"][0], list):
                raw_rows = origin_response["Data"][0]
            elif origin_response["Data"] and isinstance(origin_response["Data"][0], dict):
                raw_rows = origin_response["Data"]

        rows = [
            {k: v for k, v in row.items() if v is not None}
            for row in raw_rows
        ]

        result = {
            "total":     (origin_response or {}).get("Pagination", {}).get("TotalCount") or len(rows),
            "pageIndex": 1,
            "pageSize":  len(rows),
            "rows":      rows,
        }

        logger.erp("GlobalSearch", f"← 响应 {response.status_code} | 命中={len(rows)}条 | 耗时={elapsed()}ms")

        disclaimer = "⚠️ 以下是 ERP 全局单据搜索的【真实结果】，严格按此作答，禁止编造：\n"
        return disclaimer + json.dumps(result, ensure_ascii=False, indent=2)

    except httpx.HTTPStatusError as e:
        status = e.response.status_code
        logger.error("GlobalSearch", f"← 失败 {status} | {e} | 耗时={elapsed()}ms")
        if status == 401:
            return json.dumps({"error": "登录已过期，请重新登录 ERP 系统"})
        if status == 403:
            return json.dumps({"error": "您没有权限使用全局搜索"})
        return json.dumps({"error": f"全局搜索请求失败: {e}", "status": status})
    except Exception as e:
        logger.error("GlobalSearch", f"← 未知错误: {e}")
        return json.dumps({"error": "未知错误，请稍后重试"})


# ===================== 字段布局动态获取 =====================

from dataclasses import dataclass

@dataclass
class FieldLayout:
    field_labels: dict[str, str]
    hidden_fields: list[dict]


def _derive_form_code(table_name: str) -> str:
    """从 tableName 派生 FormCode（取第一个 . 之前的部分）"""
    return table_name.split(".")[0]


def _parse_grid_columns(data: dict) -> Optional[FieldLayout]:
    """解析 getProgGridLayout 响应，提取字段布局"""
    if not data or not isinstance(data, dict):
        return None

    resp = data.get("response")
    cols = (resp or {}).get("mainTableConfig", {}).get("columns")

    if not isinstance(cols, list) or not cols:
        logger.warn("FieldLayout", "响应结构不符预期，mainTableConfig.columns 未找到")
        return None

    # 默认列对象（当列字段缺失时使用）
    DEFAULT_COLUMN = {
        "f28": False,   # fIfForceHide 默认不强制隐藏
        "f35": True,    # fIfVisible 默认可见
    }

    field_labels: dict[str, str] = {}
    hidden_fields: list[dict] = []

    for col in cols:
        merged = {**DEFAULT_COLUMN, **col}
        field_code: Optional[str] = merged.get("f4")   # fFieldCode
        field_desc: Optional[str] = merged.get("f5")   # fFieldDesc
        force_hide: bool = bool(merged.get("f28", False))

        if not field_code:
            continue
        if field_desc == "至":
            continue

        label = field_desc or field_code
        field_labels[field_code] = label

        if force_hide:
            hidden_fields.append({"field": field_code, "label": label})

    logger.ai(
        "FieldLayout",
        f"列解析完成 | 总列={len(cols)} | 隐藏={len(hidden_fields)} | 有标题={len(field_labels)}"
    )
    return FieldLayout(field_labels=field_labels, hidden_fields=hidden_fields)


FIELD_LAYOUT_DB_TTL_S = 24 * 60 * 60  # SQLite cache 保留 24 小时


async def get_field_layout(
    table_name: str,
    user_id: str,
    erp_cookie: str,
    erp_auth: str,
) -> Optional[FieldLayout]:
    """
    获取字段布局。优先读 SQLite erp_form_layout_cache（TTL 24h），
    过期或缺失时调用 getProgGridLayout 并回写 cache。
    """
    import json as _json
    from db import get_conn

    form_code = _derive_form_code(table_name)
    now = time.time()

    # ---- 1. 读 SQLite cache ----
    conn = get_conn()
    db_row = conn.execute(
        "SELECT fields_json, cached_at FROM erp_form_layout_cache WHERE form_code = ?",
        (form_code,),
    ).fetchone()
    conn.close()

    if db_row and (now - db_row["cached_at"]) < FIELD_LAYOUT_DB_TTL_S:
        try:
            fields = _json.loads(db_row["fields_json"])
            field_labels = {f["field"]: f["label"] for f in fields if f.get("field")}
            hidden_fields = [f for f in fields if f.get("hidden")]
            logger.ai("FieldLayout", f"SQLite cache 命中 | form={form_code} | 字段={len(field_labels)}")
            return FieldLayout(field_labels=field_labels, hidden_fields=hidden_fields)
        except Exception:
            pass

    # ---- 2. cache 缺失/过期，调 ERP 接口 ----
    logger.ai("FieldLayout", f"SQLite cache 未命中，调用 ERP | form={form_code}")
    url = f"{ERP_BASE_URL}/gw/api/ERP/FunRights/getProgGridLayout"
    body = {"sUserCode": user_id, "FormCode": form_code, "FrontJSFileName": "view.jsx"}
    headers = _build_erp_headers(erp_cookie, erp_auth)

    t = start_timer()
    try:
        async with httpx.AsyncClient(verify=False, follow_redirects=False, timeout=8.0) as client:
            response = await client.post(url, json=body, headers=headers)

        logger.erp("FieldLayout", f"← 响应 {response.status_code} | form={form_code} | 耗时={t()}ms")
        data = response.json()

        if not data.get("success"):
            logger.warn("FieldLayout", f"ERP 返回失败 | form={form_code} | msg={data.get('msg')}")
            return None

        resp_data  = data.get("response") or {}
        form_desc  = resp_data.get("fFormDesc", "")
        main_cfg   = resp_data.get("mainTableConfig") or {}
        inter_code = main_cfg.get("fInterCode", "")
        db_table_name = f"{form_code}.{inter_code}" if inter_code else form_code
        columns    = main_cfg.get("columns") or []

        fields = [
            {"field": c.get("f4", ""), "label": c.get("f5", ""),
             "hidden": bool(c.get("f28", False)) or c.get("f26") is False}
            for c in columns if c.get("f4")
        ]
        sub_tables = [
            {
                "inter_code": s.get("fInterCode", ""),
                "desc": (s.get("fInterDesc") or [""])[0],
                "table_name": f"{form_code}.{s.get('fInterCode', '')}",
                "fields": [
                    {"field": c.get("f4", ""), "label": c.get("f5", "")}
                    for c in (s.get("columns") or []) if c.get("f4")
                ],
            }
            for s in (resp_data.get("subTableConfig") or [])
        ]

        # 回写 SQLite cache
        conn = get_conn()
        with conn:
            conn.execute("""
                INSERT OR REPLACE INTO erp_form_layout_cache
                    (form_code, table_name, form_desc, fields_json, sub_tables_json, cached_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (form_code, db_table_name, form_desc,
                  _json.dumps(fields, ensure_ascii=False),
                  _json.dumps(sub_tables, ensure_ascii=False),
                  now))
        conn.close()

        field_labels = {f["field"]: f["label"] for f in fields if f.get("field")}
        hidden_fields = [f for f in fields if f.get("hidden")]
        logger.ai("FieldLayout", f"已解析并缓存 | form={form_code} | 字段={len(field_labels)} | 隐藏={len(hidden_fields)}")
        return FieldLayout(field_labels=field_labels, hidden_fields=hidden_fields)

    except Exception as err:
        status = getattr(getattr(err, "response", None), "status_code", "N/A")
        logger.warn("FieldLayout", f"获取字段布局失败 | form={form_code} | status={status} | {err}")
        return None
