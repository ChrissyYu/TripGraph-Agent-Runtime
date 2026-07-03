# Phase 10B：README Showcase + Demo Script Hardening

> 将 GitHub 展示页与默认 demo 命令对齐，不扩展业务 scope。

---

## 1. README 重写原则

- **标题**：`TripGraph Agent Runtime` — 体现 Agent 系统，不是旅行 App
- **定位**：Agent Runtime / Tool Infrastructure；旅行规划仅为验证场景
- **结构**：展示页（背景 → 能力 → 架构 → Quick Start → 命令表 → 指标 → 边界 → Roadmap）
- **禁止**：Phase 开发日志、pytest 通过数、`docs/system_engineering/*` 具体链接、环境变量大全

---

## 2. Demo Commands

| 用途 | 命令 |
|------|------|
| Quick demo（3 cases，无 API key） | `python scripts/eval_graph_demo.py --max-cases 3` |
| Full graph demo eval | `python scripts/eval_graph_demo.py` |
| Tool routing regression | `python scripts/eval_tool_routing.py --compare-baseline` |
| MCP smoke | `python scripts/smoke_mcp_tools.py` |
| Qwen smoke（manual） | `QWEN_API_KEY=... LLM_PROVIDER=qwen python scripts/smoke_qwen_llm.py` |
| Qwen + MCP smoke（manual） | `python scripts/smoke_qwen_mcp_tools.py` |

`--max-cases N` 触发 **compact stdout**：每 case 输出 id / query / execution_success / actual_tools / providers / final_section_coverage，不 dump 完整 JSON。

---

## 3. What Is Real vs Mock

| 类别 | 内容 |
|------|------|
| Real infra | Graph runtime, Qwen client, MCP protocol, tool policy, fallback, tracing, eval + regression guard |
| Mock / local | builtin weather/map/budget, local mcp_weather/map/budget server, default RuleBased LLM |
| Manual only | Qwen + MCP smoke — 非默认 CI |

指标验证 **infra behavior**，不验证真实旅行质量。

---

## 4. 当前边界

- 不改 `graph/runtime/core/graph.py`
- 不改 Planner / ToolPolicyEngine / Executor 业务逻辑
- 不接真实 weather/map/budget API
- README 不链接本目录下其他 phase 文档（traceability 保留在 `docs/`）
