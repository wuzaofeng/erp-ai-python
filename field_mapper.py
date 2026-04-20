'''
Author: zack.wu zack.wu@zuru.com
Date: 2026-04-20 12:26:57
LastEditors: zack.wu zack.wu@zuru.com
LastEditTime: 2026-04-20 12:27:04
FilePath: \erp-ai-nodejsc:\WorkSpace\erp-ai-python\field_mapper.py
Description: 这是默认设置,请设置`customMade`, 打开koroFileHeader查看配置 进行设置: https://github.com/OBKoro1/koro1FileHeader/wiki/%E9%85%8D%E7%BD%AE
'''
"""
字段中文映射工具 - 对应 src/utils/fieldMapper.ts
从 tableCatalog 解析字段中文映射
注：此文件放在根目录以避免 utils/__init__.py 中的 Windows 路径 \\u 转义问题
"""
import re
from config.table_catalog import ERP_TABLE_CATALOG


def get_field_labels(table_name: str) -> dict[str, str]:
    """
    从 tableCatalog 中提取指定表的字段中文映射
    例：get_field_labels('BDM007_VendorKindQuery.BDM007_VendorKindQuery')
    → { 'fKindCode': '分类代码', 'fKindName': '分类名称', ... }
    """
    lines = [line.strip() for line in ERP_TABLE_CATALOG.split("\n")]
    target_line = next((line for line in lines if table_name in line), None)
    if not target_line:
        return {}

    columns = [c.strip() for c in target_line.split("|")]
    if len(columns) < 4:
        return {}

    field_desc_col = columns[3]  # 第4列是"常用字段说明"

    # 提取所有 "字段名(中文说明)" 格式
    field_labels: dict[str, str] = {}
    for match in re.finditer(r"(\w+)\(([^)]+)\)", field_desc_col):
        field_labels[match.group(1)] = match.group(2)

    return field_labels
