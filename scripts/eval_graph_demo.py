"""Run graph-level demo evaluation (Phase 10A)."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config.env_loader import bootstrap_environment
from config.settings import get_settings
from eval.graph_eval.evaluator import GraphDemoEvaluator, apply_deterministic_eval_env
from eval.graph_eval.loader import load_graph_demo_dataset
from eval.graph_eval.report import write_graph_demo_report


def _print_quick_demo(report, *, output_path: Path, latest_path: Path) -> None:
    print("TripGraph Graph Demo — Quick Run")
    print("=" * 60)
    for result in report.per_case_results:
        providers = sorted(set(result.actual_providers)) if result.actual_providers else []
        coverage = (
            f"{result.final_section_coverage:.2f}"
            if result.final_section_coverage is not None
            else "n/a"
        )
        print(f"id: {result.id}")
        print(f"  query: {result.query}")
        print(f"  execution_success: {result.execution_success}")
        print(f"  actual_tools: {result.actual_tools}")
        print(f"  actual_providers: {providers}")
        print(f"  final_section_coverage: {coverage}")
        print()

    agg = report.aggregate_metrics
    print("Aggregate")
    print("-" * 40)
    print(f"  cases: {agg.total_cases}")
    print(f"  execution_success_rate: {agg.execution_success_rate:.4f}")
    if agg.avg_tool_family_recall is not None:
        print(f"  tool_family_recall: {agg.avg_tool_family_recall:.4f}")
    if agg.avg_final_section_coverage is not None:
        print(f"  final_section_coverage: {agg.avg_final_section_coverage:.4f}")
    print(f"\nReport: {output_path}")
    print(f"Latest: {latest_path}")


def _print_summary(report) -> None:
    print("Graph Demo Evaluation Summary")
    print("-" * 40)
    summary = report.model_dump_summary()
    skip_keys = {"low_tool_selection_recall_cases", "low_provider_recall_cases"}
    for key, value in summary.items():
        if key in skip_keys:
            continue
        print(f"  {key}: {value}")

    if report.low_tool_selection_recall_cases:
        print("\nLow tool_selection_recall cases")
        print("-" * 40)
        for case in report.low_tool_selection_recall_cases:
            print(f"  id: {case.id}")
            print(f"  query: {case.query}")
            print(f"  expected_tools: {case.expected_tools}")
            print(f"  actual_tools: {case.actual_tools}")
            print(f"  tool_selection_recall: {case.tool_selection_recall}")
            print(f"  tool_selection_precision: {case.tool_selection_precision}")
            print(f"  mismatch_reason: {case.mismatch_reason}")
            print()

    if report.low_provider_recall_cases:
        print("Low provider_recall cases")
        print("-" * 40)
        for case in report.low_provider_recall_cases:
            print(f"  id: {case.id}")
            print(f"  query: {case.query}")
            print(f"  expected_providers: {case.expected_providers}")
            print(f"  actual_providers: {case.actual_providers}")
            print(f"  provider_recall: {case.provider_recall}")
            print(f"  provider_precision: {case.provider_precision}")
            print(f"  mismatch_reason: {case.mismatch_reason}")
            print()


async def _run_eval(args: argparse.Namespace) -> int:
    if args.real_llm:
        print(
            "Note: real_llm graph eval is not the default path in Phase 10A.\n"
            "Use scripts/smoke_qwen_mcp_tools.py for manual Qwen + MCP smoke instead.",
        )
        return 2

    bootstrap_environment()
    apply_deterministic_eval_env()
    get_settings.cache_clear()

    cases, dataset_hash, dataset_path = load_graph_demo_dataset(args.dataset)
    if args.max_cases is not None:
        cases = cases[: args.max_cases]

    default_mcp = True if args.mcp_enabled else None
    evaluator = GraphDemoEvaluator(
        default_mcp_enabled=default_mcp,
        default_policy_strategy=args.policy_strategy,
        eval_mode="deterministic_eval",
        llm_provider="rule_based",
    )
    report = await evaluator.evaluate_cases(
        cases,
        dataset_hash=dataset_hash,
        dataset_path=dataset_path,
    )
    output_path = write_graph_demo_report(report, output_dir=args.output_dir)
    latest_path = Path(args.output_dir) / "latest_report.json"
    if args.max_cases is not None:
        _print_quick_demo(report, output_path=output_path, latest_path=latest_path)
    else:
        _print_summary(report)
        print(f"\nReport written to: {output_path}")
        print(f"Latest report: {latest_path}")

    if args.fail_on_error:
        agg = report.aggregate_metrics
        if agg.execution_success_rate < 1.0 or report.failed_cases:
            return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run graph-level demo evaluation")
    parser.add_argument(
        "--dataset",
        default=str(REPO_ROOT / "eval" / "datasets" / "graph_demo_eval.jsonl"),
        help="Path to graph_demo_eval.jsonl",
    )
    parser.add_argument(
        "--output-dir",
        default=str(REPO_ROOT / "data" / "eval" / "graph_demo"),
        help="Directory for JSON reports",
    )
    parser.add_argument(
        "--mcp-enabled",
        action="store_true",
        help="Force MCP enabled for all cases (overrides per-case mcp_enabled=false)",
    )
    parser.add_argument(
        "--policy-strategy",
        default=None,
        help="Override TOOL_POLICY_STRATEGY for all cases",
    )
    parser.add_argument("--max-cases", type=int, default=None, help="Limit number of cases")
    parser.add_argument(
        "--fail-on-error",
        action="store_true",
        help="Exit 1 when execution_success_rate < 1.0 or failed_cases present",
    )
    parser.add_argument(
        "--real-llm",
        action="store_true",
        help="Reserved: real LLM graph eval (not supported as default path)",
    )
    args = parser.parse_args()
    return asyncio.run(_run_eval(args))


if __name__ == "__main__":
    raise SystemExit(main())
