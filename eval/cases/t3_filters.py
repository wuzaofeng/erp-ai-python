"""
维度 3：复杂过滤条件构造
验证 and/or 逻辑、括号分组、Logic 向下关联、最后一条无 Logic
"""
from eval.types import EvalCase, CheckResult

CASES: list[EvalCase] = [
    EvalCase(
        id="T3-1",
        dimension="复杂过滤构造",
        name="or 条件（姓吴或姓张）",
        turns=[{"role": "user", "content": "查姓吴或者姓张的员工"}],
        checks=[
            CheckResult(
                name="调用了工具",
                fn=lambda r: r.tool_called("query_erp_list"),
            ),
            CheckResult(
                name="filters 有2个或以上条件",
                fn=lambda r: r.tool_filter_count_gte("query_erp_list", 2),
            ),
            CheckResult(
                name="第1条 Logic=or",
                fn=lambda r: r.tool_filter_logic_at("query_erp_list", 0, "or"),
            ),
            CheckResult(
                name="最后一条无 Logic 字段",
                fn=lambda r: r.tool_filter_last_no_logic("query_erp_list"),
            ),
        ],
    ),
    EvalCase(
        id="T3-2",
        dimension="复杂过滤构造",
        name="and 条件（金额+状态）",
        turns=[{"role": "user", "content": "查金额大于5万且状态为已审批的采购订单"}],
        checks=[
            CheckResult(
                name="调用了工具",
                fn=lambda r: r.tool_called("query_erp_list"),
            ),
            CheckResult(
                name="filters 有2个或以上条件",
                fn=lambda r: r.tool_filter_count_gte("query_erp_list", 2),
            ),
            CheckResult(
                name="第1条 Logic=and",
                fn=lambda r: r.tool_filter_logic_at("query_erp_list", 0, "and"),
            ),
            CheckResult(
                name="最后一条无 Logic 字段",
                fn=lambda r: r.tool_filter_last_no_logic("query_erp_list"),
            ),
        ],
    ),
    EvalCase(
        id="T3-3",
        dimension="复杂过滤构造",
        name="括号分组 (姓吴或姓张)且在职",
        turns=[{"role": "user", "content": "查(姓吴或姓张)且在职的员工"}],
        checks=[
            CheckResult(
                name="调用了工具",
                fn=lambda r: r.tool_called("query_erp_list"),
            ),
            CheckResult(
                name="有 LeftParen 括号",
                fn=lambda r: r.tool_filter_has_paren("query_erp_list", "LeftParen"),
            ),
            CheckResult(
                name="有 RightParen 括号",
                fn=lambda r: r.tool_filter_has_paren("query_erp_list", "RightParen"),
            ),
            CheckResult(
                name="最后一条无 Logic 字段",
                fn=lambda r: r.tool_filter_last_no_logic("query_erp_list"),
            ),
        ],
    ),
    EvalCase(
        id="T3-4",
        dimension="复杂过滤构造",
        name="Operator 使用 ERP 标准值",
        turns=[{"role": "user", "content": "查名称包含'电子'且编码以PO开头的采购订单"}],
        checks=[
            CheckResult(
                name="使用 Like 操作符",
                fn=lambda r: r.tool_filter_has_operator("query_erp_list", "Like"),
            ),
            CheckResult(
                name="使用 StartWith 操作符（非 StartsWith）",
                fn=lambda r: r.tool_filter_has_operator("query_erp_list", "StartWith"),
            ),
            CheckResult(
                name="不使用非法操作符 StartsWith",
                fn=lambda r: not r.tool_filter_has_operator("query_erp_list", "StartsWith"),
            ),
        ],
    ),
]
