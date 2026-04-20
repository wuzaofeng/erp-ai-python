"""
预设技能注册表 - 对应 src/config/skills.ts
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SkillConfig:
    key: str
    name: str
    description: str
    rule: str
    match_pages: list[str] = field(default_factory=list)


# ===================== 预设技能注册表 =====================

SKILL_REGISTRY: list[SkillConfig] = [
    SkillConfig(
        key="employee-simple",
        name="员工简洁视图",
        description="查询员工时只展示编号、姓名、工号三列，隐藏其余字段",
        match_pages=["/hr/employee", "/bdm024"],
        rule=(
            "只展示以下字段，其余字段一律隐藏：\n"
            "- fEmpCode（员工编号）\n"
            "- fEmpName（员工名称）\n"
            "- fJobNo（员工工号）\n\n"
            "表格列顺序：员工编号 → 员工名称 → 员工工号"
        ),
    ),
    SkillConfig(
        key="po-alert-amount",
        name="采购大额订单预警",
        description="金额超过 10 万的采购订单用 ⚠️ 标注，并置顶显示",
        match_pages=["/purchase/order", "/pom001"],
        rule=(
            "展示采购订单时：\n"
            "1. 金额（Amount）超过 100000 元的行，在订单号前添加 ⚠️ 标记\n"
            "2. 带 ⚠️ 的行排在表格最前面（降序排列）\n"
            "3. 金额列加粗显示，格式：**¥xxx,xxx.00**\n"
            "4. 在表格下方注明：⚠️ 表示金额超过 10 万元，请重点关注"
        ),
    ),
    SkillConfig(
        key="so-status-filter",
        name="销售订单状态视图",
        description="默认只显示进行中的销售订单（过滤已完成和已取消）",
        match_pages=["/sales/order", "/som001"],
        rule=(
            "查询销售订单时：\n"
            '1. 优先筛选状态（Status）不为"已完成"和"已取消"的订单\n'
            "2. 展示字段：订单号、客户名称、金额、状态、创建日期\n"
            "3. 按金额从大到小排序\n"
            "4. 在表格标题前注明：📋 当前仅显示进行中订单"
        ),
    ),
    SkillConfig(
        key="stock-low-alert",
        name="低库存预警",
        description="库存数量低于 10 的物料用 🔴 标注，零库存用 ❌ 标注",
        match_pages=["/warehouse/stock", "/stm001"],
        rule=(
            "展示库存查询结果时：\n"
            "1. Qty（库存量）= 0：在物料名前添加 ❌ 标记，表示零库存\n"
            "2. Qty（库存量）> 0 且 < 10：在物料名前添加 🔴 标记，表示库存偏低\n"
            "3. Qty（库存量）>= 10：正常显示，无标记\n"
            "4. 表格按库存量从低到高排序\n"
            "5. 表格下方注明：❌ 零库存 | 🔴 库存低于 10，建议及时补货"
        ),
    ),
    SkillConfig(
        key="ap-overdue-alert",
        name="应付账款逾期预警",
        description="到期日已过的应付账款用 🔴 标注，7天内到期用 ⚠️ 标注",
        match_pages=["/finance/ap", "/fam001"],
        rule=(
            "展示应付账款时：\n"
            "1. DueDate（到期日）早于今天：在供应商名前添加 🔴 标记（已逾期）\n"
            "2. DueDate（到期日）在今天到 7 天内：添加 ⚠️ 标记（即将到期）\n"
            "3. 其他：正常显示\n"
            "4. 排序：🔴 逾期 → ⚠️ 即将到期 → 正常，同级按到期日升序\n"
            "5. 表格下方注明：🔴 已逾期 | ⚠️ 7天内到期，请安排付款"
        ),
    ),
    SkillConfig(
        key="ar-overdue-alert",
        name="应收账款逾期预警",
        description="到期日已过的应收账款用 🔴 标注，7天内到期用 ⚠️ 标注",
        match_pages=["/finance/ar", "/fam002"],
        rule=(
            "展示应收账款时：\n"
            "1. DueDate（到期日）早于今天：在客户名前添加 🔴 标记（已逾期未收）\n"
            "2. DueDate（到期日）在今天到 7 天内：添加 ⚠️ 标记（即将到期）\n"
            "3. 其他：正常显示\n"
            "4. 排序：🔴 逾期 → ⚠️ 即将到期 → 正常，同级按金额降序\n"
            "5. 表格下方注明：🔴 已逾期未收 | ⚠️ 7天内到期，请跟进催款"
        ),
    ),
    SkillConfig(
        key="product-active-only",
        name="仅显示启用产品",
        description="产品查询时只返回状态为启用的产品，过滤停用品",
        match_pages=["/product", "/bdm017"],
        rule=(
            "查询产品时：\n"
            '1. 只展示 Status（状态）为"启用"或"正常"的产品\n'
            "2. 展示字段：产品编号、产品名称、规格、单位、状态\n"
            "3. 停用产品一律不显示\n"
            "4. 在表格标题前注明：✅ 当前仅显示启用状态产品"
        ),
    ),
]


# ===================== 工具函数 =====================

def get_skill_by_key(key: str) -> Optional[SkillConfig]:
    """通过 key 查找技能配置"""
    return next((s for s in SKILL_REGISTRY if s.key == key), None)


def get_skill_by_page(page_context: str) -> Optional[SkillConfig]:
    """通过页面路由自动匹配技能"""
    if not page_context:
        return None
    page_lower = page_context.lower()
    return next(
        (s for s in SKILL_REGISTRY if any(p.lower() in page_lower for p in s.match_pages)),
        None
    )


def list_skills() -> list[dict]:
    """获取所有技能的简要信息（用于前端展示）"""
    return [
        {
            "key": s.key,
            "name": s.name,
            "description": s.description,
            "matchPages": s.match_pages,
        }
        for s in SKILL_REGISTRY
    ]
