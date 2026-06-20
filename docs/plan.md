# Agent Ulysses 实现路径阶段规划

## 概述

本文档对 Agent Ulysses 项目进行阶段化的实现路径规划。每个阶段包含多个小任务，确保解耦与模块化优先，保证基础实现跑通，保证每一个任务实现后项目都可运行。

**项目定位**：长周期代码智能体的运行时系统。核心理念：**确定性工程基础设施包裹概率性的 LLM 调用**——上下文工程为中心，Hook Pipeline 为防火墙，执行模式为可插拔策略。

**技术选型**：Go 1.23+（核心运行时）、Python（AI 框架，通过 JSON-RPC over stdio 通信）、SQLite（存储）、Cobra + Bubbletea（CLI）、YAML + 环境变量覆盖（配置）。

**贯穿始终的工程原则**：
1. **每个模块暴露 Go interface**：内部包只依赖接口，不依赖具体实现
2. **无包级全局状态**：所有依赖通过构造函数注入（config、logger、clients）
3. **上下文感知**：所有 I/O 操作接受 `context.Context`，尊重取消信号
4. **确定性与概率性分离**：hooks、guardrails、compressors、entropy 是确定性 Go 代码；仅 LLM 调用是概率性的
5. **错误即返回值**：库代码中禁止 `panic`，错误通过返回值传播

---

## 阶段总览

```
Phase 1: 项目骨架           → go build && ./ulysses version
Phase 2: LLM 连接层         → ./ulysses chat "你好"
Phase 3: Agent 运行时核心    → 首个 ReAct agent loop 跑通
Phase 4: 上下文工程引擎      → 上下文组装、压缩、预算管理
Phase 5: Hook 拦截管线      → 确定性的工具拦截防火墙
Phase 6: 三级护栏系统       → 并行安全护栏
Phase 7: 规划系统           → DAG + ReAcTree 混合规划器
Phase 8: SubAgent 子系统    → Agent-as-Tool 模式
Phase 9: 高级执行模式       → PreAct + Entropy-Guided
Phase 10: 生态系统          → Skills、Sandbox、Trace、Python 桥接
```

---

## Phase 1：项目骨架

**目标**：可编译的二进制文件，具备 CLI、配置加载、结构化日志。依赖仅限 Go 标准库 + cobra。

### Task 1.1：初始化 Go module 与目录结构

- 创建 `go.mod`（module: `github.com/zhuyicheju/ulysses`）
- 创建目录树：
  ```
  cmd/ulysses/          # 入口 main
  internal/
    config/             # 配置加载
    logger/             # 结构化日志
    agent/              # agent 接口（空壳）
    tool/               # tool 接口（空壳）
    llm/                # LLM 客户端接口（空壳）
  pkg/                  # 共享类型/错误
  ```
- 创建 `main.go`，打印 "Ulysses starting..." 后退出
- **可运行检查点**：`go run ./cmd/ulysses/` 打印消息

### Task 1.2：配置系统

- 在 `internal/config/` 中定义 `Config` 结构体（YAML 标签）
- 从 `ulysses.yaml` 加载，环境变量覆盖（`ULYSSES_` 前缀）
- 默认配置包含：LLM endpoint、model name、log level、token budget
- 单元测试覆盖环境变量优先级逻辑
- **可运行检查点**：`go test ./internal/config/...` 通过；`./ulysses config` 打印配置

### Task 1.3：CLI 入口（cobra）

- 添加 `cobra` 依赖
- 根命令，子命令：`version`、`config`、`run`
- `version` 打印构建信息（git commit、build time，通过 ldflags 注入）
- `config` 打印加载后的配置（YAML 格式）
- `run` 为占位命令，打印 "agent loop not yet implemented"
- 在 cobra 的 `PersistentPreRun` 中注入配置加载
- **可运行检查点**：`./ulysses version`、`./ulysses config`、`./ulysses run` 均正常

### Task 1.4：结构化日志

- 在 `internal/logger/` 中定义 `Logger` interface
- 使用 `slog`（Go 1.21+ 标准库）实现
- 机器输出 JSON 格式，TTY 输出文本格式
- 日志级别由配置控制
- 将 logger 注入到 cobra 命令中
- **可运行检查点**：所有 CLI 命令产生结构化日志输出

### Task 1.5：Makefile 与构建系统

- `make build` — 跨平台构建（linux、darwin、windows）
- `make test` — 运行所有测试并开启 race detector
- `make lint` — golangci-lint
- `make run` — 构建并使用默认配置运行
- **可运行检查点**：`make build && make test` 绿灯

---

## Phase 2：LLM 连接层

**目标**：向 LLM 发送 prompt 并接收响应，为所有 AI 交互提供基础。

### Task 2.1：LLM Client 接口

- 在 `internal/llm/` 中定义 `Client` interface：
  - `Chat(ctx, messages) -> (response, usage, error)`
  - `ChatStream(ctx, messages) -> (<-chan StreamEvent, error)`
- 定义共享类型：`Message`、`StreamEvent`、`Usage`
- **可运行检查点**：接口编译通过

### Task 2.2：OpenAI 兼容 HTTP 客户端

- 为 OpenAI 兼容 API 实现 `Client` 接口
- 支持：OpenAI、DeepSeek、Claude（通过 OpenAI 兼容端点）
- 配置驱动：base URL、API key、model name
- HTTP 指数退避重试（429、5xx）
- 使用 `httptest` mock server 编写单元测试
- **可运行检查点**：测试通过；设置环境变量后可调用真实 API

### Task 2.3：CLI chat 命令

- 添加 `ulysses chat "prompt"` 子命令
- 加载 LLM 配置，创建客户端，发送单条消息
- 响应输出到 stdout，token 用量输出到 stderr
- 优雅处理错误（不使用 panic）
- **可运行检查点**：`./ulysses chat "你好"` 打印 LLM 响应

---

## Phase 3：Agent 运行时核心

**目标**：第一个可工作的 ReAct agent loop。Agent 能够思考、调用工具、观察结果、给出响应。

### Task 3.1：Tool 接口与注册中心

- 在 `internal/tool/` 中定义 `Tool` interface：
  - `Name() string`
  - `Description() string`
  - `Parameters() JSONSchema`
  - `Execute(ctx, params) -> (result, error)`
- 定义 `Registry` interface：`Register(Tool)`、`List() []ToolDef`、`Execute(ctx, name, params)`
- 实现内存 `Registry`
- 单元测试覆盖注册与执行
- **可运行检查点**：测试通过；工具注册中心独立可用

### Task 3.2：内置 Echo 工具

- 实现 `EchoTool` — 将输入作为输出返回
- 注册到 agent 的工具注册中心
- 工具序列化为 LLM function-calling 格式
- **可运行检查点**：Echo 工具可通过注册中心调用

### Task 3.3：Agent 循环接口与 ReAct 执行器

- 在 `internal/agent/` 中定义 `Agent` interface：
  - `Run(ctx, task string) -> (<-chan AgentEvent, error)`
- 定义 `AgentEvent`：`{Type: "think"|"act"|"observe"|"done", Data: ...}`
- 实现 ReAct 循环：
  1. 将 task + 工具列表发送给 LLM
  2. 解析响应：文本 → 流式输出为 "think"，tool_call → 执行 → "observe"
  3. 将观察结果反馈给 LLM（循环）
  4. LLM 仅返回文本（无 tool_call）或达到最大迭代次数时停止
- **可运行检查点**：Agent 可 think→act→observe 循环；`./ulysses run "重复我说的话: hello"` 工作

### Task 3.4：工具结果格式化

- 为 LLM 消费格式化工具结果（截断、结构化输出）
- 处理工具错误：错误结果也是 LLM 的有效输入
- **可运行检查点**：Agent 正确处理工具错误并重试

### Task 3.5：CLI run 命令接入

- 将 `ulysses run "task"` 接入完整 agent loop
- 流式输出：展示思考过程、工具调用和最终回答
- 可配置最大迭代次数和超时时间
- **可运行检查点**：端到端 agent demo（使用 echo 工具）

---

## Phase 4：上下文工程引擎

**目标**：正确的上下文组装、压缩和 token 预算管理——架构的核心。

### Task 4.1：ContextAssembler（上下文组装器）

- 在 `internal/context/` 中定义 `Assembler` interface：
  - `Assemble(ctx, params) -> (Context, error)`
- 实现：system prompt 骨架 + RULES 注入 + skill 注入 + 分区排序
- 稳定前缀策略：system prompt 放在最前面（最大化 LLM 缓存命中——目标 85%+）
- 从 `./ulysses-rules.md` 或类似文件读取 RULES
- **可运行检查点**：组装器生成正确排序的上下文；测试验证分区排序

### Task 4.2：Token 计数器

- 实现近似 token 计数（英文按 char/4，或集成 `tiktoken-go`）
- 统计消息、工具定义、工具结果的 token 数
- **可运行检查点**：token 计数与实际误差在 10% 以内（对照已知样例验证）

### Task 4.3：BudgetManager（预算管理器）

- 定义硬 token 预算（从配置读取，默认 200K）
- 80% 阈值 → 自动触发压缩
- 95% 阈值 → 强制截断（确定性代码执行，不是"建议"）
- 与 ContextAssembler 集成
- **可运行检查点**：预算管理器在正确阈值触发；使用 mock 上下文测试

### Task 4.4：ContextCompressor 第 1、2 级

- Level 1 "Snip"：按字符数截断旧消息
- Level 2 "Microcompact"：从工具结果中剥离空白/元数据，保留语义内容
- 前两级免费（不调用 LLM）
- **可运行检查点**：压缩器显著减少上下文大小；测试验证内容保留

### Task 4.5：ContextCompressor 第 3、4 级

- Level 3 "ContextCollapse"：将连续观察合并为摘要（纯 Go，不调 LLM）
- Level 4 "LLM Summary"：调用 LLM 进行摘要（付费，最后手段）
- 集成：4 级管线，预算满足时提前退出
- **可运行检查点**：完整 4 级管线可用；仅在 1-3 级耗尽时才调用 LLM 摘要

### Task 4.6：PromptCacheOptimizer（缓存优化器）

- 追踪缓存断点：什么变化触发了缓存未命中？
- 增量更新：前缀稳定时只重建后缀
- 记录缓存命中率估算
- **可运行检查点**：缓存优化器报告指标；稳定前缀被识别

---

## Phase 5：确定性 Hook 拦截管线

**目标**：Hook 管线作为 agent 决策与工具执行之间的防火墙。

### Task 5.1：Hook 接口与管线引擎

- 在 `internal/hook/` 中定义 `Hook` interface：
  - `Name() string`
  - `Priority() int`（执行顺序）
  - `PreToolUse(ctx, tool, params) -> (modifiedParams, error | abort)`
  - `PostToolUse(ctx, tool, params, result) -> (modifiedResult, error)`
- 实现管线引擎：注册 hooks、按优先级执行
- 中止语义：任何 hook 返回 `exit code 2` 时停止链路并阻止执行
- **可运行检查点**：管线引擎按顺序执行 hooks；中止传播正确

### Task 5.2：PreToolUse 拦截器

- 实现内置 hooks：
  - `PermissionGate`：对照 allowlist/denylist 检查工具/参数
  - `ParameterValidator`：对照工具的 JSON Schema 验证参数
  - `RateLimiter`：强制执行工具调用速率限制
- **可运行检查点**：权限门控阻止未授权工具；验证器捕获错误参数

### Task 5.3：PostToolUse 拦截器

- 实现内置 hooks：
  - `ResultTrimmer`：截断过大的工具结果
  - `ErrorNormalizer`：为 LLM 消费规范化错误格式
  - `AuditLogger`：记录所有工具调用及结果
- **可运行检查点**：结果在到达 agent loop 前被修剪和规范化

### Task 5.4：Hook 与 Agent Runtime 集成

- 将 hook 管线接入 ReAct 执行器
- 每次工具调用前运行 PreToolUse
- 每次工具调用后运行 PostToolUse
- Hook 失败对 agent 可见（不作为静默错误）
- **可运行检查点**：完整 agent loop 配合 hook 管线；权限拒绝作为观察结果呈现

---

## Phase 6：三级护栏系统

**目标**：三级并行运行的安全护栏——任一触发 → 立即中断。

### Task 6.1：Guard 接口与并行执行器

- 在 `internal/guard/` 中定义 `Guard` interface：
  - `Name() string`
  - `Level() string`（"input" | "tool" | "output"）
  - `Check(ctx, data) -> (passed bool, reason string)`
- 实现并行执行器：同级别所有 guard 并发运行
- 任一 guard 失败 → 中断传播
- **可运行检查点**：并行执行正常工作；单个失败触发中断

### Task 6.2：输入护栏

- 实现输入 guard：
  - `PromptInjectionGuard`：检测 jailbreak/注入模式（正则 + 启发式）
  - `ContentPolicyGuard`：阻止禁止话题
- **可运行检查点**：检测到 prompt 注入尝试

### Task 6.3：工具级护栏

- 实现工具 guard：
  - `DangerousCommandGuard`：阻止 `rm -rf /`、`curl | sh` 等危险命令
  - `FileAccessGuard`：限制文件访问到允许的路径
  - `NetworkGuard`：限制网络访问（域名白名单）
- **可运行检查点**：危险命令在执行前被阻止

### Task 6.4：输出护栏

- 实现输出 guard：
  - `SecretLeakGuard`：检测输出中的 API key、token（正则）
  - `ContentFilterGuard`：过滤有害/不当输出
  - `HallucinationGuard`：检测虚构的文件路径、命令
- **可运行检查点**：检测到并屏蔽输出中的密钥

---

## Phase 7：规划系统——DAG + ReAcTree

**目标**：多步骤任务分解——DAG 负责宏观规划，ReAcTree 负责微观执行。

### Task 7.1：DAG 规划器接口与实现

- 在 `internal/plan/` 中定义 `Planner` interface：
  - `Decompose(ctx, task) -> (*DAG, error)`
- `DAG` 结构体：节点（≤10）、边（数据流：A.output → C.input）、并行组
- LLM 驱动分解：prompt LLM 将任务拆分为带依赖的子任务
- **可运行检查点**：从自然语言任务描述生成 DAG

### Task 7.2：DAG 执行器

- 拓扑排序 → 执行节点
- 独立节点并行执行（goroutine + 同步）
- 数据流：上游节点输出 → 下游节点输入
- 错误传播：节点失败 → 依赖节点跳过
- **可运行检查点**：通过 DAG 执行简单多步骤任务（如"创建文件，然后读取"）

### Task 7.3：ReAcTree 节点

- 每个 DAG 叶节点封装一个 ReAct 循环
- 树形表示：root = 任务，children = ReAct 步骤（think/act/observe）
- 状态保存：每步后 checkpoint，支持恢复
- **可运行检查点**：ReAcTree 记录带父子关系的执行历史

### Task 7.4：混合编排器

- DAG 规划器生成计划 → DAG 执行器运行节点 → 每个节点是一个 ReAcTree
- 节点失败时规划器可重新规划（自适应）
- 合并 ReAcTree 结果为最终响应
- **可运行检查点**：端到端执行"创建包含多个文件的项目"任务

---

## Phase 8：SubAgent 子系统

**目标**：Agent-as-Tool-Call 模式——子 agent 作为父 agent 工具注册中心的普通工具。

### Task 8.1：SubAgent 生成工具

- 将 subagent 定义为 `Tool` 接口的实现
- 工具参数：任务描述、工具白名单、token 预算、模型
- 启动 goroutine 运行独立 agent loop
- 将结果（或流）返回给父 agent
- **可运行检查点**：父 agent 可通过工具调用生成子 agent

### Task 8.2：子 agent 独立上下文

- 每个子 agent 拥有独立的 `ContextAssembler` 实例
- 过滤的工具集（仅白名单中的工具）
- 独立的 token 预算
- 独立的 sidechain transcript（用于调试）
- **可运行检查点**：受限工具集的子 agent 无法访问被阻止的工具

### Task 8.3：SubAgent 编排

- 并行生成子 agent（扇出）
- 多个子 agent 的结果聚合
- 超时与取消（context 传播）
- **可运行检查点**：父 agent 并行生成 3 个子 agent，聚合结果

---

## Phase 9：高级执行模式

**目标**：PreAct 和 Entropy-Guided 作为 ReAct 的可插拔替代模式。

### Task 9.1：执行模式接口

- 定义 `ExecutionPattern` interface：
  - `Execute(ctx, task, tools) -> (<-chan AgentEvent, error)`
- 模式注册中心：按名称注册模式，运行时切换
- **可运行检查点**：多种模式已注册；通过配置切换正常

### Task 9.2：PreAct 模式

- Think → **Predict**（预测工具输出） → Act → Observe → **Compare**
- Compare 是**确定性**字符串差异比较（不调 LLM！）
- 差异 > 阈值 → 触发反思（"为什么结果与预测不同？"）
- **可运行检查点**：PreAct 正确对比预测与实际结果；不匹配时触发反思

### Task 9.3：熵值计算

- `tool_entropy(step)` — 确定性函数（不调 LLM）
- 影响因素：工具名稀有度、参数复杂度（嵌套深度、字符串长度）、历史成功率
- 使用已知高/低熵场景编写单元测试
- **可运行检查点**：熵值分数具有区分度；高熵步骤被识别

### Task 9.4：Entropy-Guided 模式

- 仅高熵步骤生成 K=4 个候选探索
- 低熵步骤直接执行（单路径）
- K=4 达到比 K=8 更好的性能（依据设计文档节省 38-42% token）
- **可运行检查点**：相同任务 Entropy-Guided agent 比基线使用更少 token

---

## Phase 10：生态系统——Skills、Sandbox、Trace、Python 桥接

**目标**：使 agent 具备生产级能力的支撑系统。

### Task 10.1：Skill 系统

- Skills 是 Markdown 文件 + YAML frontmatter（与设计文档一致）
- 解析 frontmatter 元数据（name、description、triggers）
- Skill 注册中心：从 `./skills/` 目录加载
- 与 ContextAssembler 集成：触发时将相关 skill 注入上下文
- **可运行检查点**：Skill 从 `.md` 文件加载并注入到 agent 上下文

### Task 10.2：Workspace Sandbox

- `Sandbox` interface：`Execute(ctx, command) -> (result, error)`
- Local sandbox：在工作目录中执行，带路径白名单限制
- Worktree sandbox：git worktree 隔离（借鉴 Claude Code）
- **可运行检查点**：命令在 sandbox 中执行；路径逃逸被阻止

### Task 10.3：Trace 系统（借鉴 OpenTelemetry）

- Span/Trace 模型：TraceID → Span 树
- 导出器：stdout（开发）、OTLP（生产）
- 插桩 agent loop、工具调用、LLM 调用、hook 执行
- **可运行检查点**：stdout 可见 trace 输出；span 具有正确的父子关系

### Task 10.4：Python AI 框架桥接

- Go 侧：生成 Python 子进程，通过 JSON-RPC over stdio 通信
- Python 侧：最小化服务器，接收 JSON-RPC，调用 OpenAI/Anthropic SDK，返回结果
- 协议定义：消息类型、错误码、流式支持
- 优雅关闭：信号处理、进程清理
- **可运行检查点**：Go → Python → LLM → Python → Go 往返通信正常

### Task 10.5：文档与示例

- `docs/architecture.md` — 架构概览
- `docs/getting-started.md` — 快速入门指南
- `examples/` — 示例配置和 skill 文件
- 所有公开接口编写 Go doc 注释
- **可运行检查点**：新开发者仅凭文档即可搭建并运行

---

## 验证策略

**每个 Task 完成后**：
1. `go build ./...` — 必须编译通过
2. `go test ./...` — 所有测试通过
3. 新功能的手动冒烟测试

**每个 Phase 完成后**：
1. 带 race detector 的全量测试：`go test -race ./...`
2. 端到端演示：`./ulysses run "一个覆盖本阶段新功能的综合性任务"`
3. 所有公开接口的模块化 code review

---

## 阶段依赖关系图

```
Phase 1 (项目骨架)
  └→ Phase 2 (LLM连接层)
       └→ Phase 3 (Agent运行时核心)
            ├→ Phase 4 (上下文工程)
            │    └→ Phase 7 (规划系统) ──┐
            ├→ Phase 5 (Hook管线)        │
            │    └→ Phase 6 (护栏系统)    │
            └→ Phase 8 (SubAgent) ───────┤
                                         │
            Phase 9 (高级执行模式) ───────┘
                 └→ Phase 10 (生态系统)
```

Phase 3 完成后，Phase 4-8 可并行开发（它们依赖不同的接口，彼此独立）。Phase 9 依赖 Phase 3（模式扩展 agent loop）。Phase 10 大部分独立，但应放在最后作为打磨。

---

## 风险降级策略

依据 `init_demand.md` 的风险控制表，每个模块均预设降级路径：

| 技术 | 复杂度 | 降级方案 |
|------|--------|---------|
| ReAct Loop | 低 | 不需要降级 |
| Hook Pipeline | 中 | 降为仅 PreToolUse |
| Guardrails | 中 | 降为仅 Tool 级 |
| ContextEngine | 高 | 降为简单模板 + 截断 |
| PreAct | 中 | 降回 ReAct |
| DAG+ReAcTree | 高 | 降为纯 DAG 或纯 ReAct |
| Entropy-Guided | 中 | 降为固定 K=2 探索 |
