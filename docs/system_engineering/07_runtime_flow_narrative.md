# Runtime Flow 叙事 — Query 如何在系统中流动

> 给新人、面试官、自己复盘用 · 示例 query：`帮我规划上海3日游并计算预算`  
> 代码入口：`app/api/v1/graph.py` → `GraphService` → `GraphRuntimeRunner`

---

## Before reading the details

先记住三条线，再读 14 步细节：

| 线 | 路径 |
|----|------|
| **主执行流** | Query → Plan → Graph → Tool → Critic → Final Result |
| **旁路观测流** | Graph / Tool / LLM events → Persistence + Metrics + Logs |
| **评估流（离线）** | JSONL cases → GraphRuntimeRunner → Scorer → RegressionGuard |

主路径回答：**这次请求做了什么、结果是什么。**  
旁路回答：**能不能事后查、能不能量性能。**  
评估流回答：**换一批 case 质量是否退化。**

---

## 小白版类比

| 系统组件 | 类比 | 实际职责 |
|----------|------|----------|
| FastAPI | 前台 | 接 HTTP / SSE，转交 GraphService |
| GraphRuntimeRunner | 项目总控 | 创建 AgentState，驱动整张 Graph，汇总响应 |
| PlannerAgent | 任务规划师 | 把 query 拆成 Plan（几步、用什么 tool） |
| Graph Runtime | 流程调度系统 | 按节点顺序跑 memory → plan → execute → critic |
| PlanGraphCompiler | 施工图纸转换 | 把 Plan 编译成 step_1 / plan_join 子图 |
| ToolExecutor | 工具执行员 | 真正调用 weather / map / budget |
| ExecutionCritic | 质检员 | 看结果是否满足 goal，要不要返工 |
| ReplanningController | 返工负责人 | 改写 Plan，触发下一轮 execution |
| Persistence | 档案室 | SQLite 存 execution / tool / state |
| Observability | 监控室 | 延迟、成本、JSON log、Profile |

---

## 总览

```
HTTP → trace_id → GraphRuntimeRunner → Macro Graph → Plan 子图调 Tool
     → Observer 写 DB / Metrics → GraphExecuteResponse（或 SSE）
```

---

## 第 1 步：HTTP 请求进入 FastAPI

**目的：** 把用户的自然语言 query 接进系统。

```http
POST /api/v1/graph/execute
{"session_id": "demo", "query": "帮我规划上海3日游并计算预算"}
```

路由到 `app/api/v1/graph.py`。`stream: true` 时走 SSE，否则返回 JSON。

---

## 第 2 步：RequestIDMiddleware 设置 trace_id

**目的：** 给整次请求一个可追踪 ID，日志和 Metrics 能串起来。

`app/middleware/request_id.py` 读取或生成 `X-Request-ID`，写入 `current_trace_id`（ContextVar）。

---

## 第 3 步：GraphService 调用 GraphRuntimeRunner

**目的：** API 层只调 Service 门面，不碰 Graph 内部。

`GraphService` → `GraphRuntimeRunner.invoke()` 或 `.stream()`。

---

## 第 4 步：创建 AgentState 并开始执行录制

**目的：** 初始化本次执行的「全局状态」，并分配 execution_id。

1. 创建 **AgentState**（session_id、query、空 plan / trace）
2. **begin_execution()** → `execution_id`（Persistence / Metrics 开启时）
3. 构建 Macro Graph（`agent_workflow`）
4. 进入 `graph.astream()`

SSE 推送 `event: start`，含 `execution_id`。

---

## 第 5 步：memory_load 加载记忆

**目的：** 把该 session 的历史上下文载入，供后续 planner 参考。

从 CompositeMemory 读 short / long / episodic。首次执行通常为空，结构先就绪。

---

## 第 6 步：planner 生成 Plan

**目的：** 把模糊 query 变成可执行的任务列表。

PlannerAgent + LLM → JSON Plan，PlanValidator 校验，Resolver 解析 `city=上海`、`days=3`。

| Step | Task | Tool |
|------|------|------|
| 1 | 查询上海天气 | weather |
| 2 | 规划上海景点路线 | map |
| 3 | 计算3天旅行预算 | budget |

---

## 第 7 步：compile_plan 编译为子图

**目的：** 把「任务列表」变成 Graph 能跑的节点和边。

PlanGraphCompiler → `plan_entry → step_1 → plan_join_0 → step_2 → …`

---

## 第 8 步：router 绑定 Tool

**目的：** 确认每一步具体用哪个 tool、参数从哪来。

有 tool_hint 直接用；否则 ToolSelectionRouter 选择。

---

## 第 9 步：execution 调用 ToolExecutor

**目的：** 真正执行 Plan 里的每一步，拿到 tool 输出。

子图内：weather → map → budget；每次调用写入 `execution_trace`。

---

## 第 10 步：ToolTracer / Persistence / Metrics 旁路记录

**目的：** 主路径不被拖慢的前提下，留下可查询、可度量的记录。

Graph 事件 → Recorder + MetricsObserver  
Tool 调用 → ToolTracer 链式回调  
LLM 调用 → InstrumentedLLMClient

Feature flag 关闭时，旁路不装配，主链不变。

---

## 第 11 步：critic 判断是否需要 replan

**目的：** 验货——结果是否真的满足用户 goal。

ExecutionCritic → `ExecutionCritique`（score、need_replan）。

- Case 1：`need_replan=false` → finalize
- Case 2：缺 route plan → `need_replan=true` → replanner 循环

---

## 第 12 步：replanner 或 finalize

**目的：** 要么返工改 Plan，要么结束并输出最终答案。

- **finalize**：`should_stop=true`，合成 `final_result`
- **replanner**：改写 Plan → 回到 router → 再 execution（有次数上限）

---

## 第 13 步：memory_persist 收尾

**目的：** 把本次 episode 写入 episodic memory，供后续 session 使用。

finalize 后还有一次 memory_persist；`should_stop=true` 时 Graph 结束。

---

## 第 14 步：返回 GraphExecuteResponse

**目的：** 把 plan、trace、final_result、execution_id 等交给客户端。

- 同步：一次 JSON
- SSE：`start → graph_node → … → done`
- 事后：`GET /execution/{id}`、`GET /execution/{id}/profile`

---

## 附录：关键代码路径

| 环节 | 文件 |
|------|------|
| API | `app/api/v1/graph.py` |
| Runner | `graph/runtime/runner.py` |
| Macro Graph | `graph/runtime/workflow.py` |
| 节点 | `graph/runtime/nodes.py` |
| Plan 编译 | `graph/runtime/compiler/plan_compiler.py` |
| Tool | `tools/executor.py` |
| 旁路 | `persistence/recorder.py`、`observability/observer.py` |

---

## 附录：AgentState 变化摘要

| 字段 | 变化 |
|------|------|
| `plan` | null → 3 steps |
| `execution_trace` | [] → weather / map / budget |
| `execution_critique` | null → Critic 结果 |
| `final_result` | null → 多行文本 |
| 旁路 | execution_id、trace_id、SQLite、Metrics |
