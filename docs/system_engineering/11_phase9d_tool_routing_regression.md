# Phase 9D：Tool Routing Regression Gate + Reliability-aware Policy

> 将 Phase 9C 的 tool routing eval 从「离线报告」升级为可保存 baseline、可对比、可检测 regression，并实现 `reliability_aware` v1 与少量 multi-tool eval。

---

## 1. 目标

Phase 9C 已具备：

- `ToolPolicyEngine` + MCP↔builtin fallback
- `eval/tool_eval/` + `tool_routing.jsonl`
- `scripts/eval_tool_routing.py` 输出 accuracy / provider / fallback 指标

Phase 9D 在此基础上增加：

1. **Baseline + Regression Guard** — 保存/对比 tool routing 指标，检测退化
2. **CLI 扩展** — `--save-baseline` / `--compare-baseline` / `--fail-on-regression`
3. **reliability_aware v1** — 基于 stats 文件选择 builtin / MCP
4. **Multi-tool eval v1** — 少量多步 routing case，输出 recall / precision

**不在本阶段范围：**

- 不改 `graph/runtime/core/graph.py`
- 不改 Qwen API 主逻辑
- 不接真实 API / 第三方 MCP
- Qwen + MCP smoke 不进入默认 CI
- 不引入复杂 DB 表

---

## 2. 为什么 Phase 9C eval 需要 Regression Gate

Phase 9C 的 `eval_tool_routing.py` 能输出单次报告，但无法回答：

- 这次 routing 改动是否让 accuracy 下降了？
- fallback 率是否异常上升？
- 能否在 CI / 本地脚本中 **fail fast**？

Phase 9D 引入 baseline 对比，使 tool routing 指标可回归、可门禁。

---

## 3. Baseline / Compare 流程

### 保存 baseline

```bash
python scripts/eval_tool_routing.py --save-baseline
# → eval/baselines/tool_routing_baseline.json
```

baseline 字段包括：`dataset_path`、`dataset_hash`、`policy_strategy`、accuracy 系列指标、`created_at` 等。

### 对比 baseline

```bash
python scripts/eval_tool_routing.py --compare-baseline
python scripts/eval_tool_routing.py --compare-baseline --fail-on-regression
python scripts/eval_tool_routing.py --baseline eval/baselines/tool_routing_baseline.json --compare-baseline
```

输出 `regression_summary`（写入 report + `latest_report.json`）。

### Baseline vs Report（版本化策略）

| 类型 | 路径 | 是否建议提交 |
|------|------|--------------|
| **Baseline** | `eval/baselines/tool_routing_baseline.json` | ✓ 是 — regression 对比基准，应版本化 |
| **Reliability stats** | `data/eval/tool_routing/tool_reliability_stats.json` | ✓ 是 — `reliability_aware` 示例 stats |
| **Latest report** | `data/eval/tool_routing/latest_report.json` | ✗ 否 — 本地运行产物 |
| **Timestamp report** | `data/eval/tool_routing/tool_routing_report_*.json` | ✗ 否 — 历史 report，默认不提交 |

Baseline 含 `baseline_schema_version`（当前 `v1`）、`dataset_hash` 与 aggregate 指标；每次 eval 的 timestamp report 是运行记录，**不要**把 report history 当作 baseline。

### 报告输出

- 时间戳报告：`data/eval/tool_routing/tool_routing_report_*.json`
- 最近一次：`data/eval/tool_routing/latest_report.json`

---

## 4. Regression Thresholds

默认阈值（`ToolRoutingRegressionThresholds`）：

| 指标 | 默认 tolerance | 触发 |
|------|----------------|------|
| `tool_selection_accuracy` 下降 | 0.05 | `regression_detected=true` |
| `provider_accuracy` 下降 | 0.05 | `regression_detected=true` |
| `family_accuracy` 下降 | 0.02 | `regression_detected=true` |
| `fallback_rate` 上升 | 0.10 | `degraded=true`（不单独触发 regression） |

规则说明：

- **accuracy / provider / family 下降超过阈值** → `regression_detected=true`
- **fallback_rate 上升超过阈值** → `degraded=true`；**不会**单独令 `regression_detected=true`（除非 accuracy 类指标同时下降）
- **`--fail-on-regression`** 仅在 `regression_detected=true` 时 exit code 非 0
- **`degraded` 当前不会单独触发 fail**；后续可选支持 `--fail-on-degraded`（见 §9）
- baseline 缺失 → 友好提示，不崩溃

---

## 5. reliability_aware Policy v1

### Stats 文件

默认路径：`data/eval/tool_routing/tool_reliability_stats.json`

```json
{
  "weather": {
    "builtin": {"success_rate": 0.98, "avg_latency_ms": 20, "fallback_rate": 0.01},
    "mcp": {"success_rate": 0.90, "avg_latency_ms": 80, "fallback_rate": 0.10}
  }
}
```

### Score 公式

```
score = success_rate * success_weight
      - normalized_latency * latency_weight
      - fallback_rate * fallback_weight
```

默认权重：`success=0.7`, `latency=0.2`, `fallback=0.1`  
latency 归一化：`min(max(avg_latency_ms / 1000, 0), 1)`

### 行为

- 同 family 下比较 builtin vs MCP score，选高分 provider
- stats 缺失 → fallback 到 `builtin_first`，`reason` 含 `stats_missing`
- `decision.reason` 含 score summary
- `fallback_candidates` 包含另一 provider 工具

### 配置

```env
TOOL_POLICY_RELIABILITY_STATS_PATH=./data/eval/tool_routing/tool_reliability_stats.json
TOOL_POLICY_SUCCESS_WEIGHT=0.7
TOOL_POLICY_LATENCY_WEIGHT=0.2
TOOL_POLICY_FALLBACK_WEIGHT=0.1
TOOL_POLICY_STRATEGY=reliability_aware
```

**注意：** `EVAL_MODE=deterministic_eval` 时 runtime 仍将 `reliability_aware` 降为 `builtin_first`（CI 稳定）；eval case 可显式指定 `policy_strategy=reliability_aware` 测试 engine。

---

## 6. Multi-tool Eval v1

数据集：`eval/datasets/tool_routing_multi.jsonl`（与 single-tool 数据集合并加载）

对 `tasks` 列表逐步调用 `ToolPolicyEngine`，输出：

- `tool_recall` / `tool_precision`
- `family_recall` / `provider_recall`
- 聚合 `multi_tool_metrics`

第一版 **不要求 Graph Execute**，**不要求 Qwen**。

---

## 7. 当前限制

1. regression gate 仅覆盖 tool routing 离线 eval，不覆盖完整 Graph / Qwen 质量
2. multi-tool case 数量少，主要验证 recall/precision  plumbing
3. `cost_aware` 仍为 stub
4. reliability stats 为静态 JSON，非实时采集
5. baseline 不含 per-case 明细 diff（仅 aggregate 指标）
6. Qwen + MCP smoke 仍为 manual

---

## 8. Validation Summary

| 检查项 | 结果 |
|--------|------|
| pytest | **222 passed** |
| `eval_tool_routing.py`（默认） | 与 Phase 9C 兼容 |
| `--save-baseline` | 生成 `eval/baselines/tool_routing_baseline.json` |
| `--compare-baseline` | 输出 regression summary |
| `latest_report.json` | 正常生成 |

---

## 9. 后续方向

- CI job 接入 `--compare-baseline --fail-on-regression`
- 可选 CLI：`--fail-on-degraded`（fallback_rate 超阈值时也非 0 exit）
- 从 `tool_policy_trace` / metrics 自动刷新 reliability stats
- per-case baseline diff
- GET `/api/v1/eval/tool-routing` API
- multi-tool Graph-level eval

---

## 10. Success Criteria 对照

| # | 条件 | 状态 |
|---|------|------|
| 1 | 默认 `eval_tool_routing.py` 与 Phase 9C 兼容 | ✓ |
| 2 | `--save-baseline` 可生成 baseline | ✓ |
| 3 | `--compare-baseline` 可输出 regression summary | ✓ |
| 4 | `--fail-on-regression` regression 时非 0 exit | ✓ |
| 5 | `reliability_aware` 根据 stats 选择 provider | ✓ |
| 6 | stats 缺失 fallback `builtin_first` | ✓ |
| 7 | multi-tool eval 输出 recall / precision | ✓ |
| 8 | `latest_report.json` 正常生成 | ✓ |
| 9 | 全部旧测试继续通过 | ✓（222 passed） |
| 10 | 文档完整 | ✓ |
