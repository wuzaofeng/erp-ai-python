"""临时脚本：从 TypeScript tableCatalog.ts 提取数据生成 Python 配置文件"""
import sys
# 确保先移除当前目录（防止 types.py 与标准库冲突）
sys.path = [p for p in sys.path if 'erp-ai-python' not in p]

import json
import os

TS_FILE = r"C:\WorkSpace\erp-ai-nodejs\src\config\tableCatalog.ts"
OUT_FILE = r"C:\WorkSpace\erp-ai-python\config\table_catalog.py"

with open(TS_FILE, "r", encoding="utf-8") as f:
    content = f.read()

# ---- 提取 ERP_TABLE_CATALOG（backtick 字符串）----
BT = "\x60"  # backtick
i1 = content.index("ERP_TABLE_CATALOG = " + BT) + len("ERP_TABLE_CATALOG = " + BT)
i2 = content.index(BT + ";", i1)
catalog_str = content[i1:i2]
print(f"catalog_str length: {len(catalog_str)}")

# ---- 提取 FORM_CODE_CONFIG（跳过类型注解，找 '= {'）----
fc_start = content.index("export const FORM_CODE_CONFIG")
eq_brace = content.index("= {", fc_start)   # 找赋值的 = {
brace_start = eq_brace + 2  # 跳过 '= '，指向 '{'

depth = 0
pos = brace_start
for ch in content[brace_start:]:
    if ch == "{":
        depth += 1
    elif ch == "}":
        depth -= 1
    pos += 1
    if depth == 0:
        break

config_js = content[brace_start:pos]
config_dict = json.loads(config_js)
print(f"form_codes: {len(config_dict)}")

# ---- 生成 Python 文件 ----
os.makedirs(os.path.dirname(OUT_FILE), exist_ok=True)

with open(OUT_FILE, "w", encoding="utf-8") as f:
    f.write("# ERP 数据表目录配置 - 对应 src/config/tableCatalog.ts\n")
    f.write("# 如需更新，请在原 Node.js 项目运行 npm run generate-catalog，然后重新执行此脚本\n\n")
    f.write("# ===================== ERP 数据表目录（注入 System Prompt）=====================\n\n")
    f.write("ERP_TABLE_CATALOG = " + repr(catalog_str) + "\n\n")
    f.write("# ===================== FormCode 映射配置 =====================\n")
    f.write("# 用于 getFieldLayout 查找正确的 formCode 和 frontJSFileName\n\n")
    f.write("FORM_CODE_CONFIG: dict = " + repr(config_dict) + "\n")

print(f"OK -> {OUT_FILE}")
