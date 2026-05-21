"""一次性迁移脚本：从 tableCatalog.ts 导入 erp_form_catalog"""
import json
import re
import time

TS_FILE = r"C:\WorkSpace\erp-ai-nodejs\src\config\tableCatalog.ts"

with open(TS_FILE, encoding="utf-8") as f:
    content = f.read()

# 提取 ERP_TABLE_CATALOG Markdown
BT = "\x60"
i1 = content.index("ERP_TABLE_CATALOG = " + BT) + len("ERP_TABLE_CATALOG = " + BT)
i2 = content.index(BT + ";", i1)
catalog_str = content[i1:i2]

# 解析 Markdown 表格
rows = []
for line in catalog_str.splitlines():
    line = line.strip()
    if not line.startswith("|") or "|---" in line or "业务模块" in line:
        continue
    parts = [p.strip() for p in line.split("|")]
    parts = [p for p in parts if p]
    if len(parts) < 2:
        continue
    module_name = parts[0]
    table_name  = parts[1]
    form_code   = table_name.split(".")[0] if "." in table_name else table_name

    api_path   = ""
    extra_body = ""
    if len(parts) >= 4:
        special = parts[3]
        m = re.search(r"apiPath=([^\]\s,]+)", special)
        if m:
            api_path = m.group(1)
        m = re.search(r"extraBody=(\{.+?\})", special)
        if m:
            extra_body = m.group(1)

    rows.append((form_code, module_name, api_path, extra_body))

print(f"解析到 {len(rows)} 条")

# 写入 SQLite
from db import get_conn
conn = get_conn()
now = time.time()
inserted = 0
skipped  = 0
with conn:
    for form_code, module_name, api_path, extra_body in rows:
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
print(f"导入完成：新增 {inserted} 条，跳过（已存在）{skipped} 条")
