"""
维度 1：工具调用稳定性
验证模型是否会调用工具、tableName/filters 参数是否合理
"""
from eval.types import EvalCase, CheckResult


CASES: list[EvalCase] = [
    EvalCase(
        id="T1-1",
        dimension="工具调用稳定性",
        name="基础列表查询",
        turns=[{"role": "user", "content": "帮我查前20条供应商"}],
        checks=[
            CheckResult(
                name="调用了工具",
                fn=lambda r: r.tool_called("query_erp_list"),
            ),
            CheckResult(
                name="tableName 包含 Vendor 或 供应商",
                fn=lambda r: r.tool_arg_contains("query_erp_list", "tableName", ["Vendor", "vendor"]),
            ),
        ],
    ),
    EvalCase(
        id="T1-2",
        dimension="工具调用稳定性",
        name="查询前先获取字段",
        turns=[{"role": "user", "content": "查姓李的员工信息"}],
        checks=[
            CheckResult(
                name="调用了 get_table_fields",
                fn=lambda r: r.tool_called("get_table_fields"),
            ),
            CheckResult(
                name="调用了 query_erp_list",
                fn=lambda r: r.tool_called("query_erp_list"),
            ),
            CheckResult(
                name="filters.Operator 使用标准值",
                fn=lambda r: r.tool_filter_operator_valid("query_erp_list"),
            ),
        ],
    ),
    EvalCase(
        id="T1-3",
        dimension="工具调用稳定性",
        name="大于条件过滤",
        turns=[{"role": "user", "content": "查采购订单金额大于10万的记录"}],
        checks=[
            CheckResult(
                name="调用了工具",
                fn=lambda r: r.tool_called("query_erp_list"),
            ),
            CheckResult(
                name="Operator 为 GreaterThan",
                fn=lambda r: r.tool_filter_has_operator("query_erp_list", "GreaterThan"),
            ),
        ],
    ),
    EvalCase(
        id="T1-4",
        dimension="工具调用稳定性",
        name="模糊搜索",
        turns=[{"role": "user", "content": "搜索名称包含'苹果'的客户"}],
        checks=[
            CheckResult(
                name="调用了工具",
                fn=lambda r: r.tool_called("query_erp_list"),
            ),
            CheckResult(
                name="Operator 为 Like",
                fn=lambda r: r.tool_filter_has_operator("query_erp_list", "Like"),
            ),
        ],
    ),
]
