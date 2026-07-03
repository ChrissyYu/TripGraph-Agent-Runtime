# Phase 9A: Qwen LLM Integration

## Why Qwen

TripPlan Multi-Agent 默认使用 `RuleBasedLLMClient`，便于确定性测试与零成本开发。Phase 9A 接入阿里云百炼（DashScope）OpenAI-compatible Chat Completions API，使 **Planner / ExecutionCritic / Replanner** 等核心 LLM caller 可在配置 API Key 后使用真实 Qwen 模型，同时保持工具层仍为 builtin/mock/MCP wrapper。

## Modules Using Real LLM

| Caller | 用途 | 默认 Qwen 模型（env） |
|--------|------|----------------------|
| Planner | `create_plan` | `QWEN_PLANNER_MODEL` |
| ExecutionCritic | `evaluate` | `QWEN_CRITIC_MODEL` |
| Replanner | `replan_*` | `QWEN_REPLANNER_MODEL` |
| ContextCompressor (P1) | summarizer | `QWEN_SUMMARIZER_MODEL` |
| ToolSelectionRouter (P1) | llm strategy | `QWEN_ROUTER_MODEL` |

Graph Runtime、ToolExecutor、Persistence、Evaluation 核心逻辑未改动。

## Configuration

复制 `.env.example` 为 `.env`，**只需填写 `QWEN_API_KEY` 并设置 provider** 即可启用：

```bash
LLM_PROVIDER=qwen
EVAL_MODE=auto
QWEN_API_KEY=your_qwen_api_key_here
```

可选覆盖：

```bash
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_PLANNER_MODEL=qwen3.7-plus
QWEN_CRITIC_MODEL=qwen3.7-plus
QWEN_REPLANNER_MODEL=qwen3.7-plus
QWEN_TEMPERATURE=0
QWEN_MAX_TOKENS=2048
QWEN_TIMEOUT_SEC=120
```

`qwen3.7-plus` 真实 smoke 建议将 `QWEN_TIMEOUT_SEC` 设为 **120–180** 秒。Planner 首次调用若超时，`AdaptiveLLMClient` 会 fallback 到 RuleBased；Phase 9A.3 起 RuleBased 对「X 日游 + 预算 + 城市」类 query 会稳定生成 weather → map → budget 三步计划。

可选 smoke 参数：

```bash
SMOKE_MAX_REPLAN_ATTEMPTS=1
```

无 `QWEN_API_KEY` 时系统自动 fallback 到 `RuleBasedLLMClient`。

## Smoke Test

```bash
python scripts/smoke_qwen_llm.py
```

脚本会读取 `.env`，执行一条完整 Graph Execute，并打印 provider/model、plan steps、tool calls、`planner_fallback_used` / `planner_error_type`、final_result coverage 与 execution_id。

若 Planner Qwen 超时 fallback，输出会包含 `planner_error_type=timeout` 及提高 `QWEN_TIMEOUT_SEC` 的建议。

## Evaluation Modes

| `EVAL_MODE` | 行为 |
|-------------|------|
| `deterministic_eval`（默认） | 强制 `RuleBasedLLMClient`，用于 CI / 回归 |
| `auto` | 跟随 `LLM_PROVIDER`（smoke / 生产推荐） |
| `real_llm_eval` | 使用 `LLM_PROVIDER=qwen` 跑真实 LLM eval |

回归测试 fixture 显式使用 RuleBased，不受 `.env` 中 Qwen 配置影响。

真实 LLM smoke 数据集：`eval/datasets/real_llm/qwen_smoke.jsonl`（3 条 case）。

```bash
# 需 EVAL_MODE=real_llm_eval + LLM_PROVIDER=qwen + QWEN_API_KEY
```

## Observability

`InstrumentedLLMClient` 记录 `provider=qwen`、`model=<model_name>`、`caller=planner|critic|planner_replan|summarizer|tool_router`，以及 latency 与 token usage。

## JSON Parsing & Fallback

Planner / Critic / Replanner prompt 要求 **strict JSON**（无 Markdown）。解析层支持从 ` ```json ... ``` ` 提取 JSON；解析失败会 retry 一次，仍失败则 fallback `RuleBased` 并写 warning log。

API 调用失败（timeout / HTTP error）时 `AdaptiveLLMClient` 同样 fallback RuleBased。

## Cost & Stability Notes

- 真实 LLM 输出非确定性，勿用于默认 regression gate。
- 建议 `QWEN_TEMPERATURE=0` 降低波动。
- Token 成本可在 `METRICS_ENABLED=true` 时通过 Profile 端点查看估算值。
- 设置合理 `QWEN_TIMEOUT_SEC`（smoke 建议 120–180）与 `QWEN_MAX_RETRIES` 避免长时间阻塞。
- RuleBased fallback 对旅行规划 query 覆盖 weather/map/budget，保证 smoke 在 timeout 后仍可展示完整三节结果。

## Architecture

```
app/bootstrap.py
  └── create_runtime_llm()
        └── AdaptiveLLMClient (provider routing)
              └── InstrumentedLLMClient (metrics)
                    └── PlannerAgent / ExecutionCritic / PlanExecutor summarizer
```

实现文件：`core/llm/qwen_client.py`、`core/llm/factory.py`、`core/llm/json_utils.py`。
