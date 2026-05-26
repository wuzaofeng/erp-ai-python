"""批量导入 ERP 表目录：从 config/table_catalog.py 的静态配置写入 erp_form_catalog 表"""
import re
import time
from config.table_catalog import ERP_TABLE_CATALOG, FORM_CODE_CONFIG

# 解析 Markdown 表格中的 module_name、table_name、special 列
_catalog_map: dict[str, dict] = {}
for line in ERP_TABLE_CATALOG.splitlines():
    line = line.strip()
    if not line.startswith("|") or "|---" in line or "业务模块" in line:
        continue
    parts = [p.strip() for p in line.split("|")]
    parts = [p for p in parts if p]
    if len(parts) < 2:
        continue
    module_name = parts[0]
    table_name  = parts[1]
    special     = parts[3] if len(parts) >= 4 else ""

    api_path   = ""
    extra_body = ""
    m = re.search(r"apiPath=([^\]\s,]+)", special)
    if m:
        api_path = m.group(1)
    m = re.search(r"extraBody=(\{.+?\})", special)
    if m:
        extra_body = m.group(1)

    _catalog_map[table_name] = {
        "module_name": module_name,
        "api_path": api_path,
        "extra_body": extra_body,
    }

# 以 FORM_CODE_CONFIG 为主键，补充 module_name 等信息
from db import get_conn
conn = get_conn()
now = time.time()
inserted = 0
skipped  = 0
with conn:
    for table_key, cfg in FORM_CODE_CONFIG.items():
        form_code = cfg["formCode"]
        meta = _catalog_map.get(table_key, {})
        module_name = meta.get("module_name", "")
        api_path    = meta.get("api_path", "")
        extra_body  = meta.get("extra_body", "")

        existing = conn.execute(
            "SELECT 1 FROM erp_form_catalog WHERE form_code = ?", (form_code,)
        ).fetchone()
        if existing:
            skipped += 1
            continue
        conn.execute(
            """INSERT INTO erp_form_catalog
               (form_code, module_name, api_path, extra_body, enabled, created_at)
               VALUES (?, ?, ?, ?, 1, ?)""",
            (form_code, module_name, api_path, extra_body, now),
        )
        inserted += 1

conn.close()
print(f"导入完成：新增 {inserted} 条，跳过（已存在）{skipped} 条，共 {inserted + skipped} 条")
