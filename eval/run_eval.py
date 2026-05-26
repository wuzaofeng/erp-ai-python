"""
ERP AI 模型评测主入口

用法:
    python -m eval.run_eval --models deepseek/deepseek-chat,anthropic/claude-3.5-haiku
    python -m eval.run_eval --models openai/gpt-4o-mini --dimensions T1,T2
    python -m eval.run_eval --list-cases
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

# 添加项目根目录到 sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from eval.types import EvalCase, CaseResult
from eval.runner import EvalRunner
from eval.reporter import print_report, save_json_report
from eval.cases.t1_tool_calling import CASES as T1
from eval.cases.t2_multi_turn import CASES as T2
from eval.cases.t3_filters import CASES as T3
from eval.cases.t4_instruction import CASES as T4
from eval.cases.t5_intent import CASES as T5

ALL_CASES: list[EvalCase] = T1 + T2 + T3 + T4 + T5

DEFAULT_MODELS = [
    # DeepSeek
    "deepseek/deepseek-chat",
    "deepseek/deepseek-r1-0528",
    # OpenAI
    "openai/gpt-4o-mini",
    "openai/gpt-4o",
    # Anthropic
    "anthropic/claude-3.5-haiku",
    "anthropic/claude-3.5-sonnet",
    # Google
    "google/gemini-2.0-flash-001",
    "google/gemini-2.5-flash-preview-05-20",
    # Qwen / 阿里
    "qwen/qwen-plus",
    "qwen/qwen-turbo",
]


async def run_model(model: str, cases: list[EvalCase], api_key: str) -> list[CaseResult]:
    runner = EvalRunner(api_key=api_key, model=model)
    results: list[CaseResult] = []

    for case in cases:
        print(f"  [{model}] 运行 {case.id}: {case.name} ... ", end="", flush=True)
        run = await runner.run_case(case)

        scores = []
        for check in case.checks:
            try:
                passed = check.fn(run)
            except Exception as e:
                passed = False
                print(f"\n    ⚠️ 检查异常 {check.name}: {e}")
            scores.append((check.name, passed, check.description))

        cr = CaseResult(case=case, model=model, run=run, scores=scores)
        status = "✓" if cr.pass_rate == 1.0 else f"{cr.passed}/{cr.total}"
        print(status)
        results.append(cr)

    return results


async def main():
    parser = argparse.ArgumentParser(description="ERP AI 模型评测")
    parser.add_argument("--models", default=",".join(DEFAULT_MODELS),
                        help="逗号分隔的模型列表")
    parser.add_argument("--dimensions", default="",
                        help="只运行指定维度，如 T1,T3（留空=全部）")
    parser.add_argument("--list-cases", action="store_true",
                        help="列出所有测试用例后退出")
    parser.add_argument("--output", default="eval/report.json",
                        help="JSON 报告输出路径")
    parser.add_argument("--concurrency", type=int, default=1,
                        help="模型并发数（同时跑多个模型）")
    args = parser.parse_args()

    if args.list_cases:
        print(f"\n共 {len(ALL_CASES)} 个测试用例：\n")
        for c in ALL_CASES:
            print(f"  {c.id:<8} [{c.dimension}] {c.name}")
        return

    api_key = os.getenv("EVAL_API_KEY") or os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        # 尝试从 SQLite 取第一个用户的 key（开发便利）
        try:
            from key_service import get_all_keys
            keys = get_all_keys()
            if keys:
                api_key = list(keys.values())[0]
        except Exception:
            pass
    if not api_key:
        print("❌ 未找到 API Key，请设置 EVAL_API_KEY 环境变量")
        sys.exit(1)

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    dim_filter = [d.strip().upper() for d in args.dimensions.split(",") if d.strip()]
    cases = ALL_CASES
    if dim_filter:
        cases = [c for c in cases if any(c.id.upper().startswith(d) for d in dim_filter)]
    if not cases:
        print("❌ 没有匹配的测试用例")
        sys.exit(1)

    print(f"\n🚀 开始评测 | 模型数={len(models)} | 用例数={len(cases)}\n")

    all_results: dict[str, list[CaseResult]] = {}

    if args.concurrency > 1:
        tasks = [run_model(m, cases, api_key) for m in models]
        results_list = await asyncio.gather(*tasks)
        for model, res in zip(models, results_list):
            all_results[model] = res
    else:
        for model in models:
            print(f"\n▶ 模型: {model}")
            all_results[model] = await run_model(model, cases, api_key)

    print_report(all_results)
    save_json_report(all_results, args.output)


if __name__ == "__main__":
    asyncio.run(main())
