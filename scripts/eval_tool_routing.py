"""Evaluate tool routing policy against labeled dataset (Phase 9C/9D)."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config.env_loader import bootstrap_environment
from config.settings import Settings, get_settings
from eval.tool_eval.baseline import save_tool_routing_baseline
from eval.tool_eval.evaluator import ToolRoutingEvaluator
from eval.tool_eval.loader import load_tool_routing_dataset
from eval.tool_eval.regression_guard import ToolRoutingRegressionGuard
from eval.tool_eval.report import write_tool_routing_report
from tools.adapters.mcp import MCPToolProvider
from tools.registry import ToolRegistry

DEFAULT_BASELINE = REPO_ROOT / "eval" / "baselines" / "tool_routing_baseline.json"


class FakeMCPClient:
    async def list_tools(self):
        return [
            {
                "name": "mcp_weather",
                "description": "MCP weather",
                "input_schema": {"type": "object", "properties": {"city": {"type": "string"}}},
            },
            {
                "name": "mcp_map",
                "description": "MCP map",
                "input_schema": {"type": "object", "properties": {"destination": {"type": "string"}}},
            },
            {
                "name": "mcp_budget",
                "description": "MCP budget",
                "input_schema": {
                    "type": "object",
                    "properties": {"city": {"type": "string"}, "days": {"type": "integer"}},
                },
            },
        ]

    async def call_tool(self, tool_name: str, args: dict):
        return {"tool": tool_name, "args": args, "source": "eval_mock_mcp"}


async def _build_registry(*, with_mcp: bool) -> ToolRegistry:
    registry = ToolRegistry.default()
    if with_mcp:
        provider = MCPToolProvider(FakeMCPClient(), tool_prefix="mcp_")
        await provider.register_all(registry)
    return registry


def _print_regression_summary(summary) -> None:
    print("\nRegression Summary")
    print("-" * 40)
    print(f"  regression_detected: {summary.regression_detected}")
    print(f"  degraded: {summary.degraded}")
    print(f"  summary: {summary.summary}")
    if summary.metric_deltas:
        print("  metric_deltas:")
        for key, value in summary.metric_deltas.items():
            print(f"    {key}: {value:+.4f}")
    if summary.failed_thresholds:
        print(f"  failed_thresholds: {summary.failed_thresholds}")
    if summary.warnings:
        print(f"  warnings: {summary.warnings}")


async def _run_eval(args: argparse.Namespace) -> int:
    bootstrap_environment()
    settings = get_settings()
    get_settings.cache_clear()

    cases, dataset_hash, source_paths = load_tool_routing_dataset(
        args.dataset,
        include_multi=not args.no_multi,
        multi_path=args.multi_dataset,
    )
    registry = await _build_registry(with_mcp=not args.no_mcp)
    evaluator = ToolRoutingEvaluator(
        registry,
        mcp_enabled=not args.no_mcp,
        mcp_tool_prefix=settings.mcp_tool_prefix,
    )
    report = evaluator.evaluate_cases(
        cases,
        dataset_hash=dataset_hash,
        dataset_path=",".join(source_paths),
    )

    baseline_path = Path(args.baseline)
    regression_summary = None
    if args.compare_baseline or args.fail_on_regression:
        guard = ToolRoutingRegressionGuard()
        regression_summary = guard.compare(
            report,
            baseline_path=str(baseline_path),
        )
        report = report.model_copy(
            update={
                "baseline_path": str(baseline_path),
                "regression_summary": regression_summary,
            },
        )

    output_path = write_tool_routing_report(
        report,
        output_dir=args.output_dir,
        regression_summary=regression_summary,
    )

    if args.save_baseline:
        saved = save_tool_routing_baseline(
            report,
            dataset_path=report.dataset_path,
            dataset_hash=report.dataset_hash,
            policy_strategy=report.policy_strategy,
            baseline_path=baseline_path,
        )
        print(f"Baseline saved to: {saved}")

    summary = report.model_dump_summary()
    print("Tool Routing Evaluation Summary")
    print("-" * 40)
    for key, value in summary.items():
        print(f"  {key}: {value}")
    if report.best_cases:
        print(f"  best_cases: {report.best_cases}")
    if report.worst_cases:
        print(f"  worst_cases: {report.worst_cases}")
    print(f"\nReport written to: {output_path}")
    print(f"Latest report: {Path(args.output_dir) / 'latest_report.json'}")
    print(f"Registered tools: {registry.list_names()}")

    if regression_summary is not None:
        _print_regression_summary(regression_summary)

    if args.fail_on_regression and regression_summary and regression_summary.regression_detected:
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run tool routing policy evaluation")
    parser.add_argument(
        "--dataset",
        default=str(REPO_ROOT / "eval" / "datasets" / "tool_routing.jsonl"),
        help="Path to tool_routing.jsonl",
    )
    parser.add_argument(
        "--multi-dataset",
        default=str(REPO_ROOT / "eval" / "datasets" / "tool_routing_multi.jsonl"),
        help="Path to multi-tool routing dataset",
    )
    parser.add_argument("--no-mcp", action="store_true", help="Evaluate without MCP tools registered")
    parser.add_argument("--no-multi", action="store_true", help="Skip multi-tool dataset")
    parser.add_argument("--output-dir", default=str(REPO_ROOT / "data" / "eval" / "tool_routing"))
    parser.add_argument("--save-baseline", action="store_true", help="Save current report as baseline")
    parser.add_argument("--compare-baseline", action="store_true", help="Compare against saved baseline")
    parser.add_argument(
        "--baseline",
        default=str(DEFAULT_BASELINE),
        help="Baseline JSON path",
    )
    parser.add_argument(
        "--fail-on-regression",
        action="store_true",
        help="Exit with code 1 if regression_detected=true",
    )
    args = parser.parse_args()
    return asyncio.run(_run_eval(args))


if __name__ == "__main__":
    raise SystemExit(main())
