# Phase 10A：Graph-level Demo Eval

> 轻量 Graph 全链路 Demo 评估，验证 Agent Infra 行为闭环，而非真实旅行质量 benchmark。

---

## 1. 目标

Phase 9 已完成 Tool Routing 离线评估（`eval_tool_routing.py`），但仅覆盖 **ToolPolicyEngine 单步决策**，不验证完整 Graph 执行链路：

```
User Query
  → GraphRuntime
  → Planner / PlanValidator
  → ToolPolicyEngine
  → ToolExecutor
  → builtin 或 MCP mock tools
  → final_synthesis
```

Phase 10A 引入 **Graph-level Demo Eval**，在 deterministic / RuleBased 路径下验证上述闭环是否正常工作。

**评估对象：** Agent Infra 行为（计划、工具调用、provider 选择、final_result 结构）

**不评估：** 真实天气/路线/预算质量、LLM 创造性、第三方 MCP 可靠性

---

## 2. 为什么 Tool Routing Eval 之后还需要 Graph-level Eval

| 维度 | Tool Routing Eval (`eval_tool_routing.py`) | Graph Demo Eval (`eval_graph_demo.py`) |
|------|-------------------------------------------|----------------------------------------|
| 评估层级 | ToolPolicyEngine 单步 | 完整 GraphRuntime 链路 |
| Planner | 不涉及 | RuleBased / 未来 LLM planner |
| PlanValidator | 不涉及 | 验证 plan 合法性 |
| ToolExecutor | 不涉及 | 实际执行 mock/builtin tools |
| final_synthesis | 不涉及 | 检查分节标题覆盖 |
| Replan / Fallback | 模拟 fallback 场景 | 从 execution_trace / policy trace 提取 |

Tool routing eval 保证 **路由策略正确**；Graph demo eval 保证 **端到端 infra 可运行**。

---

## 3. 目录结构

```
eval/graph_eval/
  models.py      # GraphDemoEvalCase / Result / Report
  loader.py      # JSONL 数据集加载
  scorer.py      # recall / coverage 指标
  evaluator.py   # GraphDemoEvaluator + mock MCP
  report.py      # JSON 报告输出

eval/datasets/graph_demo_eval.jsonl   # ≥12 labeled cases
scripts/eval_graph_demo.py            # CLI 入口
data/eval/graph_demo/                 # 运行产物（gitignore）
```

---

## 4. Dataset Schema

每条 case（JSONL 一行）：

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | str | 唯一标识 |
| `query` | str | 用户查询 |
| `expected_tool_families` | list[str] | 期望工具族：weather / map / budget |
| `expected_tools` | list[str] optional | 期望具体工具名 |
| `expected_providers` | list[str] optional | builtin / mcp |
| `expected_final_sections` | list[str] | final_synthesis 分节标题 |
| `policy_strategy` | str optional | builtin_first / mcp_first / planner_hint_first 等 |
| `mcp_enabled` | bool | 是否注册 mock MCP tools |
| `allow_replan` | bool | 是否启用 critic replan |
| `difficulty` | str | easy / medium / hard |
| `notes` | str optional | 说明 |

### final_synthesis 真实分节标题

与 `plan/final_synthesis.py` 一致：

- `天气信息：`
- `行程路线：`
- `预算估算：`
- `总结：`（via `_build_summary`）
- `目标：`（plan goal 前缀）

Dataset 中 `expected_final_sections` 使用短名（如 `"天气信息"`），scorer 会匹配带冒号标题。

---

## 5. Metrics

### Per-case

| 指标 | 说明 |
|------|------|
| `execution_success` | final_result 非空且无失败 tool step |
| `plan_validity` | PlanValidator 通过 |
| `final_result_present` | final_result 非空 |
| `tool_family_recall` | \|expected families ∩ actual\| / \|expected\| |
| `tool_family_precision` | \|expected families ∩ actual\| / \|actual\| |
| `tool_selection_recall` | \|expected tools ∩ actual\| / \|expected\|（expected 为空则 skip） |
| `tool_selection_precision` | \|expected tools ∩ actual\| / \|actual\| |
| `provider_recall` | \|expected providers ∩ actual providers\| / \|expected providers\|（按 unique provider 集合） |
| `provider_precision` | \|expected providers ∩ actual providers\| / \|actual providers\| |
| `final_section_coverage` | expected sections 在 final_result 中的覆盖率 |
| `fallback_used` | execution_trace / tool_policy_trace 是否出现 fallback |
| `replan_used` / `replan_count` | replan_history 长度 |
| `latency_ms` | 单 case 耗时 |

### Aggregate

- `execution_success_rate`
- `avg_tool_family_recall` / `avg_tool_family_precision`
- `avg_tool_selection_recall` / `avg_tool_selection_precision`
- `avg_provider_recall` / `avg_provider_precision`
- `avg_final_section_coverage`
- `fallback_rate` / `replan_rate`
- `avg_latency_ms`
- `failed_cases`
- `low_tool_selection_recall_cases` / `low_provider_recall_cases`（含 `mismatch_reason`）

---

## 5.1 Metric Interpretation / Diagnostics

Graph Demo Eval 关注 **完整链路是否跑通** 与 **family / final_result 覆盖**，而非最小工具调用集。

### 主指标（优先看）

1. **`execution_success_rate`** — Graph 是否成功产出 final_result，且无失败 tool step
2. **`avg_tool_family_recall`** — 期望工具族（weather / map / budget）是否被实际调用覆盖
3. **`avg_final_section_coverage`** — final_synthesis 分节是否与预期对齐

### Exact tool / provider recall（辅助）

- **`tool_selection_recall` / `provider_recall`** 仅在 case 标注了 `expected_tools` / `expected_providers` 时计入 aggregate；为空则 skip（null），**不当作 0 分**
- **并非所有 case 都应强制 exact provider**。单工具 MCP wording（如「使用 MCP 查询天气」）在 RuleBased 非 trip 路径下不会强制 `mcp_*`，这类 case 只评 **family coverage**
- **严格 MCP provider 验证** 由 trip+budget+MCP case 覆盖（如 `graph-demo-mcp-trip-001`），其保留 `expected_tools=["mcp_weather", ...]` 与 `expected_providers=["mcp"]`

### RuleBased planner 与 MCP 偏好

- MCP 偏好（`_prefer_mcp_tools`）主要在 **trip+budget** 类 query 中稳定生效（`_build_trip_weather_map_budget_plan`）
- 单工具 MCP wording 走 `_build_default_plan()` → `_pick_tool(..., prefer_mcp=False)` → builtin hints → `planner_hint_first` 尊重 hints

### Recall vs Precision

| 公式 | 含义 |
|------|------|
| recall = \|expected ∩ actual\| / \|expected\| | expected 是否被覆盖 |
| precision = \|expected ∩ actual\| / \|actual\| | actual 中有多少是 expected |

**多调工具降低 precision，不降低 recall。**

例：`expected_tools=["weather"]`，`actual_tools=["weather","map","budget"]`：

- recall = 1.0
- precision = 1/3

因此 **precision 较低是合理的**（RuleBased default plan 常多调三步），不应作为 Graph Demo Eval 的主要 pass/fail 门槛。

---

## 6. CLI 使用

```bash
# 默认：deterministic + RuleBased，不需要 QWEN_API_KEY
python scripts/eval_graph_demo.py

# 指定 dataset / 限制 case 数
python scripts/eval_graph_demo.py --dataset eval/datasets/graph_demo_eval.jsonl
python scripts/eval_graph_demo.py --max-cases 3

# 全局 override（可选）
python scripts/eval_graph_demo.py --mcp-enabled
python scripts/eval_graph_demo.py --policy-strategy mcp_first

# CI gate
python scripts/eval_graph_demo.py --fail-on-error

# 预留（Phase 10A 不启用）
python scripts/eval_graph_demo.py --real-llm
# → 提示使用 smoke_qwen_mcp_tools.py 做 manual smoke
```

报告输出：

- `data/eval/graph_demo/graph_demo_report_<timestamp>.json`
- `data/eval/graph_demo/latest_report.json`

运行产物已加入 `.gitignore`，请勿提交。

---

## 7. 默认 Eval 路径

- `EVAL_MODE=deterministic_eval`
- `LLM_PROVIDER=rule_based`
- 不依赖 `QWEN_API_KEY`
- MCP cases 使用 in-process `FakeMCPClient`（与 `eval_tool_routing.py` 同类 mock）
- `mcp_first` 等策略在 graph eval 中通过 eval-only policy engine 注入，**不修改** `graph/runtime/core/graph.py`

---

## 8. 当前限制

1. **RuleBased planner 行为**：非 trip+budget query 走 `_build_default_plan`，不会设置 `prefer_mcp`；单工具 MCP wording case 已对齐为 **family-only** expectation（见 §5.1）
2. **Recall vs Precision**：多调工具主要降低 **precision**，不应降低 **recall**；recall 低通常表示 expected tool/provider 未被实际覆盖
3. **Fallback / Replan**：dataset 含 allow_replan case，但 RuleBased critic 不保证触发 replan
4. **Real LLM**：`--real-llm` 仅预留提示，默认 path 不使用 Qwen
5. **Persistence**：eval 强制 `persistence_enabled=False`
6. **规模**：12 case demo，非大规模 benchmark

---

## 9. 后续方向

- Real weather MCP smoke hardening（manual，`smoke_qwen_mcp_tools.py`）
- README demo 脚本与 Graph eval 指标对齐
- 可选：Graph eval baseline + regression gate（类比 Phase 9D tool routing）
- 可选：更多 fallback / replan 注入场景（仍保持 mock tools）

---

## 10. 与 Phase 9 的关系

Phase 10A **不破坏** Phase 9A–9D 行为：

- 不改 `graph/runtime/core/graph.py`
- 不改 Qwen API 主逻辑
- 不接真实 weather/map/budget API
- Tool routing eval / baseline / regression guard 保持独立

Graph demo eval 是 Phase 9 tool routing 之上的 **端到端 infra 验证层**。
