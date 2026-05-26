"""
维度 5：意图识别准确率
验证 IntentRouter 对各类输入的分类是否正确
"""
from eval.types import EvalCase, CheckResult

CASES: list[EvalCase] = [
    EvalCase(
        id="T5-1",
        dimension="意图识别",
        name="问候 → simple",
        turns=[{"role": "user", "content": "你好，你能做什么"}],
        checks=[
            CheckResult(
                name="意图为 simple",
                fn=lambda r: r.intent_is("simple"),
            ),
            CheckResult(
                name="未调用工具",
                fn=lambda r: not r.tool_called("query_erp_list"),
            ),
        ],
        check_intent=True,
    ),
    EvalCase(
        id="T5-2",
        dimension="意图识别",
        name="明确查询 → complex",
        turns=[{"role": "user", "content": "帮我查一下当前库存情况"}],
        checks=[
            CheckResult(
                name="意图为 complex",
                fn=lambda r: r.intent_is("complex"),
            ),
            CheckResult(
                name="调用了工具",
                fn=lambda r: r.tool_called("query_erp_list"),
            ),
        ],
        check_intent=True,
    ),
    EvalCase(
        id="T5-3",
        dimension="意图识别",
        name="隐式追问 → complex",
        turns=[
            {"role": "user", "content": "查在职员工"},
            {"role": "assistant", "content": "__mock__"},
            {"role": "user", "content": "再过滤一下部门是研发的"},
        ],
        checks=[
            CheckResult(
                name="第2轮意图为 complex",
                fn=lambda r: r.intent_is("complex"),
            ),
            CheckResult(
                name="第2轮调用了工具",
                fn=lambda r: r.tool_called_in_turn("query_erp_list", turn=1),
            ),
        ],
        check_intent=True,
        multi_turn=True,
    ),
    EvalCase(
        id="T5-4",
        dimension="意图识别",
        name="写操作 → write",
        turns=[{"role": "user", "content": "帮我新增一个供应商"}],
        checks=[
            CheckResult(
                name="意图为 write",
                fn=lambda r: r.intent_is("write"),
            ),
        ],
        check_intent=True,
    ),
    EvalCase(
        id="T5-5",
        dimension="意图识别",
        name="无关请求 → simple 且礼貌拒绝",
        turns=[{"role": "user", "content": "帮我写一首诗"}],
        checks=[
            CheckResult(
                name="未调用 ERP 工具",
                fn=lambda r: not r.tool_called("query_erp_list"),
            ),
            CheckResult(
                name="回答中说明无法处理",
                fn=lambda r: r.answer_contains_any(["ERP", "无法", "不支持", "只能"]),
            ),
        ],
        check_intent=True,
    ),
]
