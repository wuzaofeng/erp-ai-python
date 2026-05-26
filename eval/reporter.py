"""
评测报告生成器
输出终端彩色表格 + JSON 详细报告
"""
from __future__ import annotations

import json
from datetime import datetime
from eval.types import CaseResult


def _color(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m"

def _green(t): return _color(t, "92")
def _red(t):   return _color(t, "91")
def _yellow(t): return _color(t, "93")
def _bold(t):  return _color(t, "1")
def _cyan(t):  return _color(t, "96")


def print_report(all_results: dict[str, list[CaseResult]]):
    """
    all_results: {model_name: [CaseResult, ...]}
    """
    models = list(all_results.keys())
    all_cases = list(all_results[models[0]]) if models else []

    print("\n" + "=" * 80)
    print(_bold("  ERP AI 模型评测报告"))
    print(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)

    # ---- 维度汇总表 ----
    dimensions = sorted({r.case.dimension for r in all_cases})
    print(_bold("\n📊 各维度得分汇总（%）\n"))

    header = f"{'维度':<14}" + "".join(f"{m[:18]:<20}" for m in models)
    print(_cyan(header))
    print("-" * (14 + 20 * len(models)))

    for dim in dimensions:
        row = f"{dim:<14}"
        for model in models:
            cases = [r for r in all_results[model] if r.case.dimension == dim]
            if not cases:
                row += f"{'N/A':<20}"
                continue
            total_passed = sum(r.passed for r in cases)
            total_checks = sum(r.total for r in cases)
            pct = total_passed / total_checks * 100 if total_checks else 0
            cell = f"{pct:.0f}% ({total_passed}/{total_checks})"
            colored = _green(cell) if pct >= 80 else (_yellow(cell) if pct >= 60 else _red(cell))
            row += f"{colored:<29}"  # 29 = 20 + ANSI escape padding
        print(row)

    # ---- 总分行 ----
    print("-" * (14 + 20 * len(models)))
    total_row = f"{'总分':<14}"
    for model in models:
        cases = all_results[model]
        total_passed = sum(r.passed for r in cases)
        total_checks = sum(r.total for r in cases)
        pct = total_passed / total_checks * 100 if total_checks else 0
        cell = f"{pct:.0f}% ({total_passed}/{total_checks})"
        colored = _green(cell) if pct >= 80 else (_yellow(cell) if pct >= 60 else _red(cell))
        total_row += f"{colored:<29}"
    print(_bold(total_row))

    # ---- 用例明细 ----
    print(_bold("\n📋 用例明细\n"))
    for model in models:
        print(_bold(f"  模型: {model}"))
        for cr in all_results[model]:
            status = _green("✓") if cr.pass_rate == 1.0 else (_yellow("~") if cr.pass_rate > 0 else _red("✗"))
            print(f"    {status} [{cr.case.id}] {cr.case.name} — {cr.passed}/{cr.total}")
            for check_name, passed, desc in cr.scores:
                icon = _green("  ✓") if passed else _red("  ✗")
                suffix = f" ({desc})" if desc else ""
                print(f"      {icon} {check_name}{suffix}")
        print()

    # ---- 错误汇总 ----
    errors = [
        (model, cr) for model, results in all_results.items()
        for cr in results if cr.run.error
    ]
    if errors:
        print(_bold("⚠️  执行错误\n"))
        for model, cr in errors:
            print(_red(f"  [{model}] {cr.case.id}: {cr.run.error}"))
        print()

    print("=" * 80)


def save_json_report(all_results: dict[str, list[CaseResult]], path: str):
    """保存详细 JSON 报告"""
    data = {
        "generated_at": datetime.now().isoformat(),
        "models": {},
    }
    for model, results in all_results.items():
        data["models"][model] = []
        for cr in results:
            data["models"][model].append({
                "case_id": cr.case.id,
                "dimension": cr.case.dimension,
                "name": cr.case.name,
                "passed": cr.passed,
                "total": cr.total,
                "pass_rate": round(cr.pass_rate, 3),
                "intent": cr.run.intent,
                "answer_preview": cr.run.answer[:200] if cr.run.answer else "",
                "tool_calls": [
                    {"tool": tc.tool_name, "turn": tc.turn_index, "args_keys": list(tc.args.keys())}
                    for tc in cr.run.tool_calls
                ],
                "checks": [
                    {"name": n, "passed": ok, "desc": d}
                    for n, ok, d in cr.scores
                ],
                "error": cr.run.error,
            })

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"\n📄 详细报告已保存: {path}")
