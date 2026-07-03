"""Render runtime flow diagrams to PNG (offline, matplotlib)."""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

OUT = Path(__file__).resolve().parents[1] / "docs" / "diagrams"
OUT.mkdir(parents=True, exist_ok=True)

# Use a font that supports Chinese on macOS
plt.rcParams["font.sans-serif"] = ["PingFang SC", "Heiti SC", "Arial Unicode MS", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


def _box(ax, x, y, w, h, text, fc="#E8F4FD", ec="#2563EB", fontsize=8):
    patch = FancyBboxPatch(
        (x, y),
        w,
        h,
        boxstyle="round,pad=0.02,rounding_size=0.08",
        linewidth=1.2,
        edgecolor=ec,
        facecolor=fc,
    )
    ax.add_patch(patch)
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fontsize, wrap=True)
    return x + w / 2, y, x + w / 2, y + h


def _arrow(ax, x1, y1, x2, y2, color="#334155", style="-|>", dashed=False):
    ax.add_patch(
        FancyArrowPatch(
            (x1, y1),
            (x2, y2),
            arrowstyle=style,
            mutation_scale=12,
            linewidth=1.2,
            color=color,
            linestyle="--" if dashed else "-",
        ),
    )


def render_overview() -> Path:
    fig, ax = plt.subplots(figsize=(20, 14))
    ax.set_xlim(0, 20)
    ax.set_ylim(0, 14)
    ax.axis("off")
    ax.set_title("TripPlan Multi-Agent — 完整 Runtime Flow 总览", fontsize=16, fontweight="bold", pad=16)

    # Section labels
    sections = [
        (0.3, 12.2, "① 请求入口", "#FEF3C7"),
        (0.3, 9.8, "② 启动装配", "#DCFCE7"),
        (0.3, 6.8, "③ Macro Graph", "#E0E7FF"),
        (11.0, 6.8, "④ Plan 子图", "#F3E8FF"),
        (0.3, 3.2, "⑤ Tool 层", "#FFE4E6"),
        (11.0, 3.2, "⑥ Observer 旁路", "#F1F5F9"),
    ]
    for x, y, label, color in sections:
        ax.add_patch(
            FancyBboxPatch(
                (x, y),
                8.8 if x < 10 else 8.5,
                2.0 if "Macro" in label or "子图" in label else 1.6,
                boxstyle="round,pad=0.02",
                linewidth=0.8,
                edgecolor="#94A3B8",
                facecolor=color,
                alpha=0.35,
            ),
        )
        ax.text(x + 0.15, y + 1.75 if y > 6 else y + 1.35, label, fontsize=10, fontweight="bold", va="top")

    # ① Entry
    nodes_e = [
        (1.0, 11.0, 2.2, 0.55, "Client / SSE"),
        (3.5, 11.0, 2.8, 0.55, "RequestID\n(trace_id)"),
        (6.6, 11.0, 2.8, 0.55, "FastAPI\n/graph/execute"),
        (1.0, 10.2, 2.2, 0.55, "GraphService"),
    ]
    centers_e = []
    for x, y, w, h, t in nodes_e:
        cx, _, _, top = _box(ax, x, y, w, h, t)
        centers_e.append((cx, top))
    for i in range(len(centers_e) - 1):
        _arrow(ax, centers_e[i][0], centers_e[i][1] - 0.05, centers_e[i + 1][0], centers_e[i + 1][1] + 0.55)

    # ② Bootstrap
    boot = [
        (1.0, 10.0, 2.0, 0.5, "Container"),
        (3.2, 10.0, 2.2, 0.5, "bootstrap"),
        (5.6, 10.0, 2.0, 0.5, "ToolRegistry"),
        (7.8, 10.0, 2.2, 0.5, "ToolExecutor"),
        (1.0, 9.2, 2.4, 0.5, "Planner+LLM"),
        (3.6, 9.2, 2.6, 0.5, "GraphRunner"),
        (6.4, 9.2, 2.0, 0.5, "Observer"),
        (8.6, 9.2, 2.0, 0.5, "Recorder"),
    ]
    for x, y, w, h, t in boot:
        _box(ax, x, y, w, h, t, fc="#DCFCE7", ec="#16A34A", fontsize=7)

    # ③ Macro graph - horizontal flow
    macro_y = 7.5
    macro = [
        "memory_load",
        "planner",
        "compile_plan",
        "router",
        "execution",
        "memory_persist",
        "critic",
        "replanner",
        "finalize",
    ]
    mx = 0.8
    macro_centers = []
    for name in macro:
        w = 1.55 if name != "memory_persist" else 1.75
        cx, _, _, top = _box(ax, mx, macro_y, w, 0.55, name, fc="#E0E7FF", ec="#4F46E5", fontsize=7)
        macro_centers.append((cx, top, mx + w))
        mx += w + 0.15
    for i in range(len(macro_centers) - 1):
        _arrow(ax, macro_centers[i][2], macro_y + 0.28, macro_centers[i + 1][0] - macro_centers[i][2] + macro_centers[i][0], macro_y + 0.28)

    # Conditional notes
    ax.text(12.5, 8.35, "critic → replanner [need_replan]", fontsize=8, color="#B45309")
    ax.text(12.5, 8.05, "critic → finalize [done]", fontsize=8, color="#15803D")
    ax.text(12.5, 7.75, "replanner → router (循环)", fontsize=8, color="#B45309")

    # ④ Subgraph
    sub_y = 7.0
    sub = ["plan_entry", "step_1", "join_0", "step_2", "join_1", "step_N"]
    sx = 11.2
    for name in sub:
        w = 1.35
        _box(ax, sx, sub_y, w, 0.5, name, fc="#F3E8FF", ec="#7C3AED", fontsize=7)
        if sx > 11.2:
            _arrow(ax, sx - 0.15, sub_y + 0.25, sx, sub_y + 0.25)
        sx += w + 0.12
    ax.text(11.2, 6.55, "PlanGraphCompiler 编译子图", fontsize=8, color="#6D28D9")

    # ⑤ Tools
    tools = [
        (1.0, 3.6, 2.2, 0.5, "ToolRouter"),
        (3.5, 3.6, 2.2, 0.5, "StepResolver"),
        (6.0, 3.6, 2.2, 0.5, "ToolExecutor"),
        (8.5, 3.6, 2.8, 0.5, "weather/map/budget"),
    ]
    tcx = []
    for x, y, w, h, t in tools:
        cx, _, _, top = _box(ax, x, y, w, h, t, fc="#FFE4E6", ec="#E11D48", fontsize=7)
        tcx.append((cx, top, x + w))
    for i in range(len(tcx) - 1):
        _arrow(ax, tcx[i][2], 3.85, tcx[i + 1][0] - tcx[i][2] + tcx[i][0], 3.85)

    # ⑥ Observer
    obs = [
        (11.2, 3.6, 2.5, 0.5, "MetricsCollector"),
        (14.0, 3.6, 2.2, 0.5, "MetricsStore"),
        (11.2, 2.8, 2.5, 0.5, "AsyncWriteQueue"),
        (14.0, 2.8, 2.2, 0.5, "SQLite"),
        (16.5, 3.2, 2.5, 0.5, "JSON Log"),
    ]
    for x, y, w, h, t in obs:
        _box(ax, x, y, w, h, t, fc="#F1F5F9", ec="#64748B", fontsize=7)

    # Cross links (dashed)
    _arrow(ax, 6.0, 7.5, 2.2, 4.15, dashed=True, color="#64748B")
    _arrow(ax, 7.5, 7.5, 7.1, 4.15, dashed=True, color="#64748B")
    ax.text(4.5, 5.6, "execution → tools", fontsize=8, color="#64748B", rotation=0)
    ax.text(9.0, 5.3, "on_graph_event / on_tool_record", fontsize=8, color="#64748B")
    _arrow(ax, 9.5, 7.5, 12.5, 4.15, dashed=True, color="#64748B")
    _arrow(ax, 9.5, 7.5, 12.5, 3.05, dashed=True, color="#64748B")

    # Main vertical flow hint
    _arrow(ax, 4.5, 10.2, 4.5, 8.1, color="#2563EB")
    ax.text(4.7, 9.1, "GraphRuntimeRunner", fontsize=8, color="#2563EB")

    out = OUT / "runtime_flow_overview.png"
    fig.savefig(out, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return out


def render_sequence() -> Path:
    fig, ax = plt.subplots(figsize=(18, 12))
    ax.set_xlim(0, 18)
    ax.set_ylim(0, 12)
    ax.axis("off")
    ax.set_title("Query 进入系统后的详细流动（时序图）", fontsize=16, fontweight="bold", pad=16)

    participants = [
        (1.5, "用户"),
        (3.5, "FastAPI"),
        (5.5, "GraphRuntime\nRunner"),
        (7.5, "Graph\nEngine"),
        (9.5, "Planner\nAgent"),
        (11.5, "Plan\nExecutor"),
        (13.5, "Tool\nExecutor"),
        (15.5, "Metrics\nObserver"),
        (17.0, "SQLite"),
    ]
    y_top = 11.0
    y_bot = 1.0
    x_map = {}

    for x, name in participants:
        x_map[name.split("\n")[0]] = x
        ax.plot([x, x], [y_bot, y_top], color="#CBD5E1", linewidth=1.5, linestyle="--")
        _box(ax, x - 0.55, y_top - 0.15, 1.1, 0.7, name, fc="#E0E7FF", ec="#4F46E5", fontsize=7)
        ax.text(x, y_bot - 0.25, name.replace("\n", ""), ha="center", fontsize=7, color="#64748B")

    def msg(y, x1, x2, text, color="#1E293B", dashed=False):
        style = "<|-"
        if x1 > x2:
            style = "-|>"
        _arrow(ax, x1, y, x2, y, color=color, style=style, dashed=dashed)
        ax.text((x1 + x2) / 2, y + 0.12, text, ha="center", fontsize=7, color=color)

    y = 10.2
    msg(y, 1.5, 3.5, "POST query + session_id")
    y -= 0.55
    msg(y, 3.5, 3.5, "RequestID → trace_id", color="#64748B")
    y -= 0.55
    msg(y, 3.5, 5.5, "GraphService.execute()")
    y -= 0.55
    msg(y, 5.5, 5.5, "AgentState + begin_execution()", color="#64748B")
    ax.text(6.8, y, "execution_id 生成", fontsize=7, color="#B45309")

    y -= 0.65
    msg(y, 5.5, 7.5, "astream(state)")
    y -= 0.55
    msg(y, 7.5, 7.5, "memory_load", color="#64748B")
    y -= 0.55
    msg(y, 7.5, 9.5, "planner_node → create_plan()")
    y -= 0.55
    msg(y, 9.5, 7.5, "Plan (weather→map→budget)", color="#15803D")
    y -= 0.55
    msg(y, 7.5, 7.5, "compile_plan + router_node", color="#64748B")
    y -= 0.55
    msg(y, 7.5, 11.5, "execution_node → 子图 step_1..N")
    y -= 0.55
    msg(y, 11.5, 13.5, "weather / map / budget")
    y -= 0.55
    msg(y, 13.5, 11.5, "tool outputs", color="#15803D")
    y -= 0.55
    msg(y, 11.5, 7.5, "execution_trace 更新", color="#15803D")

    y -= 0.65
    msg(y, 7.5, 7.5, "memory_persist + critic_node", color="#64748B")
    y -= 0.55
    ax.add_patch(
        FancyBboxPatch(
            (2.5, y - 0.35),
            12.5,
            0.7,
            boxstyle="round,pad=0.02",
            linewidth=1,
            edgecolor="#F59E0B",
            facecolor="#FFFBEB",
            linestyle="--",
        ),
    )
    ax.text(8.75, y, "alt: need_replan? → replanner → router → execution (循环)", ha="center", fontsize=8, color="#B45309")
    y -= 0.75
    msg(y, 7.5, 7.5, "finalize → should_stop=true", color="#15803D")

    y -= 0.75
    ax.text(1.0, y + 0.35, "loop 每个 graph/tool 事件", fontsize=8, fontweight="bold", color="#64748B")
    y -= 0.15
    msg(y, 7.5, 15.5, "on_graph_event", dashed=True, color="#64748B")
    y -= 0.45
    msg(y, 7.5, 17.0, "ExecutionRecorder", dashed=True, color="#64748B")
    y -= 0.45
    msg(y, 13.5, 15.5, "on_tool_record", dashed=True, color="#64748B")
    y -= 0.45
    msg(y, 13.5, 17.0, "tool_calls 写入", dashed=True, color="#64748B")

    y -= 0.65
    msg(y, 7.5, 5.5, "final AgentState", color="#15803D")
    y -= 0.55
    msg(y, 5.5, 3.5, "GraphExecuteResponse", color="#15803D")
    y -= 0.55
    msg(y, 3.5, 1.5, "JSON 或 SSE (start→graph_node→done)", color="#15803D")

    out = OUT / "query_flow_sequence.png"
    fig.savefig(out, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return out


if __name__ == "__main__":
    p1 = render_overview()
    p2 = render_sequence()
    print(p1)
    print(p2)
