# Phase 9C：Tool Routing Intelligence + MCP Evaluation

> 将系统从「能调用 MCP 工具」升级为「能解释、能 fallback、可评估」的工具路由层。

---

## 1. 目标

Phase 9B 完成了 Minimal MCP Tool Integration（本地 mock MCP server + `mcp_weather/map/budget`）。Phase 9C 在此基础上增加：

1. **Tool Policy Engine** — 在 builtin 与 MCP 工具之间做可解释选择
2. **Failure Fallback** — MCP 失败时自动回退 builtin（及反向）
3. **Observability** — `tool_policy_trace`、JSON log、metrics 计数
4. **Tool Routing Eval** — 离线评估 tool_selection / provider / fallback 指标

**不在本阶段范围：**

- 不改 `graph/runtime/core/graph.py`
- 不改 Qwen API 主逻辑
- 不接真实 weather/map/budget 或第三方 MCP server
- deterministic eval 仍默认 RuleBased LLM

---

## 2. 为什么 MCP 接入后还需要 Routing Policy

Phase 9B 之后系统同时存在两套工具：

| Family | Builtin | MCP |
|--------|---------|-----|
| weather | `weather` | `mcp_weather` |
| map | `map` | `mcp_map` |
| budget | `budget` | `mcp_budget` |

Planner 可能给出 `weather` 或 `mcp_weather`，环境可能只有 builtin 或 MCP 未启动。没有 policy 层时：

- 无法解释「为什么选了 builtin 而不是 MCP」
- MCP 调用失败时缺少结构化 fallback
- eval / metrics 无法衡量 provider 选择质量

---

## 3. Tool Policy Engine

目录：`tools/policy/`

| 文件 | 职责 |
|------|------|
| `models.py` | `ToolPolicyDecision`、`ToolFamily`、`ToolProvider`、family 映射 |
| `engine.py` | `ToolPolicyEngine.decide()` |
| `trace.py` | `ToolPolicyTracer` — 写入 observations / JSON log |
| `bootstrap.py` | `build_tool_policy_engine()` |

### 策略

| 策略 | 行为 |
|------|------|
| `planner_hint_first` | 默认尊重 Planner `tool_hint`；无 hint 时按 query/task 关键词推断 |
| `builtin_first` | 同 family 优先 builtin；fallback 到 `mcp_*` |
| `mcp_first` | 同 family 优先 MCP；fallback 到 builtin |
| `deterministic` | CI / deterministic_eval 用，等价 `builtin_first` |
| `cost_aware` / `reliability_aware` | v1 stub → 回落 `builtin_first` |

### ToolPolicyDecision 字段

- `original_tool_hint`、`selected_tool`、`selected_provider`、`tool_family`
- `policy_name`、`confidence`、`fallback_candidates`、`reason`
- `fallback_used`、`fallback_tool`、`failure_reason`（执行阶段填充）

---

## 4. 配置

`config/settings.py` / `.env.example`：

```env
TOOL_POLICY_ENABLED=true
TOOL_POLICY_STRATEGY=planner_hint_first
TOOL_POLICY_MCP_FALLBACK_ENABLED=true
TOOL_POLICY_TRACE_ENABLED=true
TOOL_POLICY_DEFAULT_PROVIDER=builtin
```

行为说明：

- `TOOL_POLICY_ENABLED=false` → 不创建 engine，router / executor 行为与 Phase 9B 一致
- `EVAL_MODE=deterministic_eval` 时 `mcp_first` 自动降为 `builtin_first`
- `MCP_ENABLED=false` 时 `mcp_first` 不崩溃，选 builtin 并记录 reason

---

## 5. 集成点

```
router_node
  → ToolPolicyEngine.decide(hint, task, query)
  → 更新 step.tool_hint = selected_tool
  → observations["tool_policy_trace"]
  → plan_state.global_context["tool_policy_decisions"]

PlanExecutor._execute_step
  → ToolExecutor（含 retry）
  → 失败且 TOOL_POLICY_MCP_FALLBACK_ENABLED
  → 遍历 fallback_candidates
  → execution_trace.recovery_action = mcp_to_builtin_fallback | builtin_to_mcp_fallback
```

**未修改：** `graph/runtime/core/graph.py`、Qwen client、PlanValidator 校验规则。

---

## 6. Fallback Chain

顺序：

1. `selected_tool` 在 `ToolExecutor` 内完成 retry（ReliabilityPolicy）
2. 全部失败后，若 policy fallback 开启，按 `fallback_candidates` 依次尝试
3. fallback 调用同样经过 `ToolExecutor` + `ToolTracer`
4. 双侧均失败 → 保留最终 error，不吞异常

---

## 7. Observability

### state.observations

- `tool_policy_trace` — 每步决策列表
- `tool_policy_counters` — `mcp_selected_count`、`fallback_count` 等

### JSON Log

`event=tool_policy_decision` / `tool_policy_fallback`（`tools.policy` module）

### Metrics（v1）

计数器经 `ToolPolicyTracer.counters` 暴露；完整 MetricsCollector 扩展留待后续。

---

## 8. Tool Routing Evaluation

```
eval/tool_eval/          — models, loader, evaluator, report
eval/datasets/tool_routing.jsonl   — 12+ labeled cases
scripts/eval_tool_routing.py
```

指标：

- `tool_selection_accuracy` — `selected_tool == expected_tool` 的比例；要求**精确工具名一致**（例如期望 `mcp_weather` 时必须命中 `mcp_weather`，不能只命中同 family 的 `weather`）
- `family_accuracy` — selected tool family == `expected_tool_family` 的比例（例如 `weather` 与 `mcp_weather` 同属 `weather` family）
- `provider_accuracy` — `selected_provider` == `expected_provider` 的比例（builtin / mcp 是否选对）
- `mcp_usage_rate` — `selected_provider` 为 `mcp` 的 case 占比
- `builtin_usage_rate` — `selected_provider` 为 `builtin` 的 case 占比
- `fallback_rate` — 执行阶段发生 fallback 的 case 占比（含 eval 中 `simulate_mcp_failure` 场景）
- `fallback_success_rate` — 发生 fallback 后成功切换到 fallback tool 的比例
- `average_confidence` — policy decision 的平均 confidence

```bash
python scripts/eval_tool_routing.py
# 报告 → data/eval/tool_routing/tool_routing_report_*.json
```

---

## 9. Manual Smoke

```bash
# Phase 9B MCP smoke（CI 外手动）
python scripts/smoke_mcp_tools.py

# Phase 9C Qwen + MCP + Policy（需 QWEN_API_KEY）
export QWEN_API_KEY=...
export MCP_ENABLED=true
python scripts/smoke_qwen_mcp_tools.py
```

---

## 10. 测试

| 文件 | 覆盖 |
|------|------|
| `tests/unit/test_tool_policy_engine.py` | 策略与 family 映射 |
| `tests/unit/test_tool_policy_trace.py` | 序列化、observations 写入 |
| `tests/unit/test_tool_routing_eval.py` | 数据集加载与指标 |
| `tests/integration/test_mcp_tool_policy_integration.py` | MCP 选择、failure fallback |

---

## 11. Validation Summary（验证结果）

Phase 9C 完成后的实测结果（文档对齐时复核）：

| 检查项 | 结果 |
|--------|------|
| pytest 全量 | **208 passed** |
| `scripts/smoke_mcp_tools.py` | **exit code 0** |
| `scripts/eval_tool_routing.py` | 见下表 |

**Tool routing eval 指标（`eval/datasets/tool_routing.jsonl`，12 cases）：**

| 指标 | 数值 |
|------|------|
| `tool_selection_accuracy` | **90.9%** |
| `provider_accuracy` | **91.7%** |

**结果解读（不夸大）：**

- **tool_selection_accuracy 90.9%** 表示绝大多数 case 精确选中了期望工具名；未命中的 case 多为 ambiguous / simulate_mcp_failure 等边界场景，不代表整体 Graph 执行已完全稳定。
- **provider_accuracy 91.7%** 表示绝大多数 case 正确选择了 builtin 或 MCP provider；仍有个别 case 在 policy 与 fallback 模拟下 provider 与期望不完全一致。
- 上述指标来自**离线 ToolPolicyEngine 评估**，只衡量路由决策质量；**不等价于**完整 Graph 任务成功率，也**不代表** Qwen Planner 的规划质量或「Qwen 已稳定使用 MCP」。

复核命令：

```bash
make test                              # 期望 208 passed
python scripts/smoke_mcp_tools.py      # 期望 exit 0
python scripts/eval_tool_routing.py    # 期望 tool_selection_accuracy ≈ 90.9%，provider_accuracy ≈ 91.7%
```

---

## 12. 当前限制

1. Policy 在 `router_node` 应用；replanner 新步骤需再次经过 router
2. 多工具并行 case 仅评估 primary expected tool
3. `cost_aware` / `reliability_aware` 为 stub
4. 真实 Qwen 输出仍有波动；smoke 为 manual
5. 无独立 DB 表存储 policy trace（observations + JSON log 为主）

---

## 13. 后续 Phase 9D 方向

- LLM-assisted tool routing（Qwen router 与 policy 协同）
- 基于历史 success rate 的 `reliability_aware` 策略
- 多工具 plan 的 joint routing optimization
- Tool routing eval 接入 CI regression gate
- GET `/api/v1/eval/tool-routing` API

---

## 14. Success Criteria 对照

| # | 条件 | 状态 |
|---|------|------|
| 1 | `TOOL_POLICY_ENABLED=false` 兼容旧行为 | ✓ |
| 2 | `mcp_first` 映射 weather→mcp_weather | ✓ |
| 3 | MCP unavailable → fallback builtin | ✓ |
| 4 | MCP 执行失败 → fallback + recovery_action | ✓ |
| 5 | `observations["tool_policy_trace"]` | ✓ |
| 6 | JSON log policy decision | ✓ |
| 7 | `eval_tool_routing.py` 输出指标 | ✓ |
| 8 | `smoke_mcp_tools.py` exit 0 | ✓（exit code 0） |
| 9 | `smoke_qwen_mcp_tools.py` manual | ✓ |
| 10 | 全量 tests 通过 | ✓（208 passed） |
