# TripPlan Multi-Agent — 简历 / 面试项目描述

> 素材 + 正式版 · v0.8.0 · 150 tests passed

---

## 1. 项目一句话定位

自研 **Graph-native Multi-Agent Runtime** 基础设施：Plan→Graph 编译、Critic-Replanner 闭环、Observer 旁路持久化与可观测，附离线 Evaluation 与 Docker 部署；旅行规划为验证场景。

---

## 2. 完整版项目描述

TripPlan Multi-Agent 不是旅行聊天应用，而是 **Agent 执行基础设施**。按 Phase 1–8 分层建设：Tool 抽象与可靠执行 → Plan-driven Agent → 自研 Graph Runtime → Persistence / Observability / Evaluation / Deployment。

主路径 `GraphRuntimeRunner` 驱动 Macro Graph（memory → planner → compile → router → execution → critic → replan/finalize），`PlanGraphCompiler` 将 LLM Plan 编译为可执行子图。Persistence 与 Metrics 以 Observer 订阅 Graph / Tool 事件，异步写 SQLite，不侵入 Graph 核心。Evaluation 独立批量跑 JSONL 数据集并做 baseline 回归。Phase 8 完成 Service Layer、DI 容器、Docker 与 `/health/detailed`。**150 tests passed。**

技术栈：Python 3.11、FastAPI、Pydantic v2、自研 Graph、SQLite、Docker。

---

## 3. 简历 Bullet 素材版

可按岗位自由裁剪组合。

### Graph Runtime

- **Graph-native Runtime**：自研 Graph 引擎（并行、条件边、状态版本化），`GraphRuntimeRunner` 为主入口，150 tests
- **Plan→Graph 编译**：`PlanGraphCompiler` 将 Plan 编译为 step/join 子图，Demo 验证 weather→map→budget 全链路
- **Critic-Replanner 闭环**：Graph 条件边驱动 replan；Case 2 trace 验证 2 轮 replanner

### Tool System

- **Tool 运行时**：`ToolRegistry` + `ToolExecutor` + ReliabilityPolicy + `ToolSelectionRouter`
- **Tool 追踪**：ToolTracer 链式回调，同时喂 persistence 与 metrics

### Infra

- **SQLite 持久化**：五表模型 + AsyncWriteQueue + replay / session restore
- **可观测性**：Metrics Profile、JsonLogFormatter、trace_id 传播
- **离线评估**：EvaluationRunner + RegressionGuard，与 serving 解耦
- **部署**：Docker + ApplicationContainer + `/health/detailed`

---

## 4. 面试 30 秒版

> Graph-native 的 Multi-Agent Runtime，旅行规划做验证。Query 进来 → planner 出 Plan → 编译成子图 → 调 Tool → critic 不行就 replan。Persistence 和 Metrics 用 Observer 旁路写 SQLite，不侵入 Graph。还有离线 Eval 和 Docker，150 tests 全过。

---

## 5. 面试 3 分钟版

**背景（30s）：** Agent 基础设施，不是聊天机器人。Phase 1–8 分层演进，travel 只是验证场景。

**架构（60s）：** 主路径 `/graph/execute` → GraphRuntimeRunner。Plan 是语义层，Graph 是执行层，PlanGraphCompiler 连接两者。Tool 层 Registry + Executor + Router；Intelligence 层 Critic + Replanner 做自修复。

**横切（60s）：** Observer 非侵入写 SQLite 和 Metrics。Evaluation 独立跑 JSONL。Phase 8 Service Layer + Docker + health/detailed。

**亮点（30s）：** Plan→Graph 编译、Case 2 replan 循环真实跑通；Persistence 需 drain 才能即时查库；RuleBasedLLM 规划有限——Evaluation 的价值所在。

---

## 6. 技术关键词（ATS）

`Python` · `FastAPI` · `Graph Runtime` · `Multi-Agent` · `LLM Tool Calling` · `Plan-and-Execute` · `Observer Pattern` · `SQLite` · `Observability` · `Docker` · `pytest`

---

## 7. 相关文档

- [README](../../README.md)
- [System Architecture](../architecture/system_architecture.md)
- [Runtime Flow](../system_engineering/07_runtime_flow_narrative.md)

---

## 8. 正式简历版（推荐）

直接复制到简历「项目经历」下，4 条为宜：

- **Graph Runtime / Plan 编译**：设计并实现 Graph-native Multi-Agent Runtime（自研 Graph 引擎 + `GraphRuntimeRunner`），通过 `PlanGraphCompiler` 将 LLM 结构化 Plan 编译为可执行子图，支持 Critic-Replanner 自修复闭环；150 tests 通过
- **Tool Calling / 执行可靠性**：构建 ToolRegistry、ToolExecutor、ToolSelectionRouter 统一 Tool 调用与路由，ReliabilityPolicy 保障重试与超时，ToolTracer 链式 Observer 回调
- **Persistence / Observability**：Observer 非侵入接入 ExecutionRecorder 与 MetricsObserver，AsyncWriteQueue 异步写 SQLite，支持 execution replay、Profile 与 JSON structured logging（trace_id / execution_id）
- **Evaluation / Deployment / 质量保障**：离线 EvaluationRunner + RegressionGuard 批量评估与回归检测；Docker + Service Layer + `/health/detailed` 组件健康探测；全项目 150 pytest 覆盖 Phase 1–8

---

## 9. 简历压缩版（一行版）

用于项目名称下方或技能摘要：

> Graph-native Multi-Agent Runtime（Plan→Graph 编译 · Tool calling · Observer 旁路持久化/可观测 · 离线 Eval · Docker）· Python / FastAPI · 150 tests

或更短：

> 自研 Graph Runtime 的 Multi-Agent 基础设施：Plan 驱动 Tool 执行、Critic-Replanner 闭环、SQLite replay/Profile、离线 Eval 与 Docker 部署
