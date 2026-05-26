"""
维度 2：多轮追问强制重查
验证模型在追问"过滤/换条件"时是否重新调用工具，不从历史数据中二次过滤
"""
from eval.types import EvalCase, CheckResult

CASES: list[EvalCase] = [
    EvalCase(
        id="T2-1",
        dimension="多轮追问重查",
        name="追问过滤不从历史数据截取",
        turns=[
            {"role": "user", "content": "查在职员工列表"},
            {"role": "assistant", "content": "__mock__"},  # 第1轮回答占位，Runner 会替换为真实回答
            {"role": "user", "content": "再帮我过滤姓李的"},
        ],
        checks=[
            CheckResult(
                name="第2轮调用了工具",
                fn=lambda r: r.tool_called_in_turn("query_erp_list", turn=1),
            ),
            CheckResult(
                name="filters 包含姓李的条件",
                fn=lambda r: r.tool_filter_value_contains("query_erp_list", "李"),
            ),
        ],
        multi_turn=True,
    ),
    EvalCase(
        id="T2-2",
        dimension="多轮追问重查",
        name="换条件重查采购订单",
        turns=[
            {"role": "user", "content": "查采购订单"},
            {"role": "assistant", "content": "__mock__"},
            {"role": "user", "content": "只看未审批的"},
        ],
        checks=[
            CheckResult(
                name="第2轮调用了工具",
                fn=lambda r: r.tool_called_in_turn("query_erp_list", turn=1),
            ),
            CheckResult(
                name="filters 包含审批相关条件",
                fn=lambda r: r.tool_filter_value_contains("query_erp_list", ["未审批", "待审批", "0", "false"]),
            ),
        ],
        multi_turn=True,
    ),
    EvalCase(
        id="T2-3",
        dimension="多轮追问重查",
        name="追问更多数据",
        turns=[
            {"role": "user", "content": "查库存列表"},
            {"role": "assistant", "content": "__mock__"},
            {"role": "user", "content": "再查下一页"},
        ],
        checks=[
            CheckResult(
                name="第2轮调用了工具",
                fn=lambda r: r.tool_called_in_turn("query_erp_list", turn=1),
            ),
            CheckResult(
                name="pageIndex 大于 1",
                fn=lambda r: r.tool_arg_gt("query_erp_list", "pageIndex", 1),
            ),
        ],
        multi_turn=True,
    ),
]
