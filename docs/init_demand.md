# 项目规划文档：Agent Ulysses

**项目名称**：Agent Ulysses
**副标题**：A Runtime System for Long-Horizon Code Agents
**项目定位**：面向长周期代码智能体的运行时系统——不是又一个 LangChain 包装器

**核心理念**：
Agent Ulysses 是一个 **Agent 运行时基础设施层**。它不解决"如何更好地调 LLM"（那是模型厂商的事），也不解决"如何搭建 RAG"（那是应用层的事）。它解决的是：**如何在概率性的 LLM 外面包一层确定性的工程基础设施，让 Agent 高效、可控、可观测、可调试**。

本项目借鉴了 Claude Code 的上下文工程与 Hook 系统、OpenClaw 的 Lane Queue 并发模型、OpenAI Codex 的三层护栏设计，以及 Behavior Tree + ReAct 的混合规划思想，目标是构建一个**自研的、模块化的、确定性与概率性分离的** Agent 运行时系统。

---

## 设计原则

| 原则 | 说明 |
|------|------|
| **模块化组装 > 整体耦合** | 每个模块有明确的 Go interface 契约，可独立开发、测试、替换。模块间只依赖接口不依赖实现 |
| **可运行为先 > 完美设计** | 第一阶段（6 周内）必须产出可运行的最小闭环，后续在可运行基础上迭代 |
| **确定性 > 概率性** | 先实现确定性的基础设施（Hook、Guardrails、Lane Queue），再叠加复杂 AI 能力（PreAct、Entropy-Guided） |
| **自研核心 > 胶水代码** | 拒绝 LangChain/LangGraph 等包装器依赖，核心运行时完全自研 |
| **不碰"烂大街"方向** | 不做 RAG Pipeline、不做向量数据库、不做 Prompt 模板库、不做模型微调——这些无法展示工程能力 |

---

## 1. 整体架构

```
                       ┌──────────────────────────────┐
                       │     Context Engineering       │
                       │  (上下文组装·压缩·路由·缓存)    │
                       └──────────────┬───────────────┘
                                      │
   ┌──────────┐  ┌──────────┐  ┌─────┴─────┐  ┌──────────┐
   │  Skill   │  │  极简    │  │  Protocol │  │   Hook   │
   │  System  │  │  Memory  │  │  MCP+A2A  │  │ Pipeline │
   └──────────┘  └──────────┘  └─────┬─────┘  └──────────┘
                                      │
                             ┌────────┴────────┐
                             │  Agent Runtime  │
                             │  Lane Queue     │
                             │  Tool Registry  │
                             │  Permission Gate│
                             └────────┬────────┘
                                      │
             ┌────────────────────────┼────────────────────────┐
             │                        │                        │
   ┌─────────┴──────┐  ┌─────────────┴────────┐  ┌───────────┴──────┐
   │  Planning      │  │  Execution Patterns  │  │    Sandbox      │
   │  DAG+ReAcTree  │  │ReAct/PreAct/EntropyG│  │ Local/Worktree  │
   └────────────────┘  └──────────────────────┘  └──────────────────┘
                                      │
                             ┌────────┴────────┐
                             │  Three-Tier     │
                             │  Guardrails     │
                             │ (Input/Tool/Out)│
                             └─────────────────┘
```

**架构核心理念**：上下文工程是整个系统的中心。LLM 推理只是管道中的一个环节——真正决定 Agent 质量的是上下文如何组装、压缩、缓存和路由。这是从 Claude Code 源码分析中得出的最关键洞察。

---

## 2. 核心模块详解

### 2.1 Context Engineering Engine（上下文工程引擎）🔥 核心差异化

**这是整个项目最重要的模块。不是 LLM 的附属品，而是 LLM 的管理者。**

Claude Code 的核心洞察：大约 98% 的代码在管理上下文流动，只有约 2% 是 AI 决策逻辑。上下文工程的本质是**确定性代码管理概率性模型**。

| 子模块 | 核心职责 | 关键技术 |
|--------|---------|----------|
| **ContextAssembler** | 组装发给 LLM 的上下文 | System Prompt 骨架（缓存友好）、RULES.md 注入、Skill 按需注入、分区排序（内置工具前缀稳定，保证 85%+ 缓存命中） |
| **ContextCompressor** | 上下文超窗口时自动压缩 | 4 级管线：Snip（截断）→ Microcompact（剥离元数据）→ ContextCollapse（合并）→ LLM Summary（付费，仅最后手段）。前 3 级免费 |
| **BudgetManager** | Token 预算硬限制 | 80% 预警自动压缩、95% 强制截断（确定性代码执行，不是"建议"）、Per-SubAgent 子预算分配 |
| **PromptCacheOptimizer** | 最大化 LLM Prompt Cache 命中 | 稳定前缀策略、增量更新重建、缓存命中率监控 |

### 2.2 Deterministic Hook Pipeline（确定性拦截层）🔥 安全性基石

**来源：Claude Code。Hook 是 Agent 与执行之间的一道防火墙，不是回调函数。**

```
事件生命周期：
SessionStart → UserPromptSubmit → [Turn 循环]
  ┌─────────────────────────────────────────┐
  │  PreToolUse → [Hook 链] → Tool.Execute → PostToolUse  │
  │      ↑              ↓ 阻止(exit 2)        ↑           │
  │   修改参数       PermissionGate         失败处理       │
  └─────────────────────────────────────────┘

Hook 处理器类型：
├── Command:  执行本地脚本，通过 exit code 决策
├── Inline:   正则匹配 + JSON Schema 校验 + 白名单检查
└── HTTP:     POST 到外部审计服务

合并规则（关键设计）：
  Deny(阻止) > Ask(询问用户) > Allow(允许)
  1 个 Deny 覆盖 100 个 Allow——不论有多少 Hook 放行
```

### 2.3 Lane Queue（并发队列模型）

**来源：OpenClaw。解决多源并发竞态问题的最优雅方案。**

```
┌──────────────────────────────────┐
│ Session A → [t1][t2][t3]  串行   │  每个 Session 内严格串行
│ Session B → [t4][t5]      串行   │  保证因果关系
│ Cron      → [j1]          并行   │  不同 Lane 可以并行
│ SubAgent  → [s1][s2]      并行   │  全局 maxConcurrent=4
└──────────────────────────────────┘

原则：并行是 opt-in，不是默认行为
```

### 2.4 DAG + ReAcTree 混合规划器

**DAG 和 ReAcTree 各司其职，不互相替代。**

| 层次 | 负责 | 特点 |
|------|------|------|
| **DAG** | 宏观任务分解 | 定义子任务依赖关系、识别可并行的子任务、定义数据流（A.output → C.input）。节点数 ≤ 10 |
| **ReAcTree** | 微观执行控制 | 嵌入在每个 DAG 节点内部。节点类型：Sequence（顺序）、Fallback（降级）、Retry(N)（重试）、Timeout(T)（超时）、Condition（条件分支） |

**为什么混合？**
- 纯 DAG 无法表达条件分支和重试——这是 Agent 的刚需
- 纯 ReAct 无法表达宏观结构和并行——会在单线程中线性执行
- LangGraph 的失败教训：用图表达所有控制流导致图膨胀到不可维护
- 正确做法：DAG 管"做什么"（≤10 个节点），ReAcTree 管"怎么做"（每节点内深度 ≤5）

### 2.5 Execution Patterns（可插拔执行模式）

所有模式实现统一接口，可在运行时切换。MVP 只实现 ReAct，后续模式渐进叠加。

| 模式 | 描述 | 状态 | 核心创新 |
|------|------|------|---------|
| **ReAct** | Think → Act → Observe | Phase 1 实现，基线 | 成熟方案，保证能跑通 |
| **PreAct** | Think → **Predict** → Act → Observe → **Compare(预测vs实际)** | Phase 4 实现 | Compare 是确定性字符串比较，不调 LLM。差异 > 阈值触发反思 |
| **Entropy-Guided** | 计算 tool_entropy(step)，高熵步骤才多候选探索 | Phase 5 实现 | tool_entropy 是**确定性函数**（基于工具名/参数复杂度/历史成功率），不调 LLM。K=4 超过 K=8 性能，节省 38-42% Token |

### 2.6 Three-Tier Guardrails（三级并行护栏）

**来源：OpenAI Codex。三级全部并行执行，任一触发→立即中断。**

```
输入护栏              工具级护栏            输出护栏
├── Schema 校验       ├── 参数 Schema 校验   ├── 格式校验
├── 注入检测           ├── PreToolUse Hook    ├── 内容安全检查
├── 预算检查           ├── 死循环检测          └── 预算剩余检查
└── 权限检查           └── 权限矩阵

三层并发执行，总延迟 = max(各层延迟)，不是 sum(各层延迟)
全部是确定性逻辑，不调 LLM
```

### 2.7 SubAgent System（子智能体系统）

**来源：Claude Code 的 Agent-as-Tool-Call 模式。**

```
父 Agent 视角：
  Agent 就是 ToolRegistry 中的一个普通 Tool
  调用 Agent("code-review", prompt="审查 src/handler.go")
  得到 text 结果——与调用 Read/Write 没有任何区别

子 Agent 内部：
  独立的 ContextEngine（不继承父对话历史）
  过滤后的 Tool Set（只能看到被授权的工具）
  独立的 Token Budget（防止一个子任务耗尽全局预算）
  独立的 Sidechain Transcript（JSONL，便于独立调试）
```

### 2.8 Workspace Sandbox（工作区沙箱）

```
Level 1: 本地文件限制（默认）
  - 只允许 cwd 子目录写入
  - Shell 命令白名单
  - 网络域名白名单

Level 2: Git Worktree（按需启用，秒级创建）
  - 完整仓库副本 + 独立分支
  - 执行完自动清理
  - 多 SubAgent 可并行操作不同 Worktree

Level 3: Container（后期按需加入）
  - 完全进程/网络隔离
```

### 2.9 Skill System（技能系统）

**来源：OpenClaw + Claude Code。**

Skills 是 Agent 获取领域知识的方式——纯 Markdown 文件 + YAML frontmatter，不是可执行代码：

```
.skills/
├── code-review/SKILL.md
├── react-best-practices/SKILL.md
└── database-migration/SKILL.md

SKILL.md 结构：
---
name: code-review
description: 代码审查技能
triggers: ["review", "审查"]
tools: [Read, Grep, Bash]
---
# 代码审查清单
...
```

关键设计：
- Agent 可自写 Skills——执行任务后总结经验写入 SKILL.md
- 纯文本，安全——不会引入代码执行风险
- 热加载——文件变更后自动生效
- Git 可追踪——放在仓库中版本控制

### 2.10 Trace System（追踪系统）

最小可用设计（JSONL 格式，不依赖 OpenTelemetry 全家桶）：

```
├── Session Span: session_id, model, start_time
│   ├── Turn Span: turn_number, user_input
│   │   ├── Thought: content, timestamp
│   │   ├── ToolCall: tool_name, params, start, end, status
│   │   ├── ToolResult: output_truncated, token_usage
│   │   ├── GuardrailEvent: tier, result, action
│   │   └── BudgetSnapshot: remaining, percentage
│   └── SubAgent Span（嵌套）
```

---

## 3. 架构边界（不做什么）

明确声明本项目不涉及以下方向，避免沦为烂大街的"调包侠"项目：

| 不做的方向 | 原因 |
|-----------|------|
| **RAG Pipeline** | LangChain 5 行代码搞定，不具备工程深度 |
| **向量数据库** | Pinecone/ChromaDB/Milvus 集成是面试减分项 |
| **Prompt 模板库** | 写长 Prompt 不是工程能力 |
| **模型微调/RLHF** | 与 Agent 运行时无关，是模型厂商的事 |
| **LangGraph/LangChain 包装** | 展示不了自研能力 |
| **AutoGen GroupChat** | 已进入 maintenance mode |

**Agent 获取信息首选方式是调用 Read/Grep 工具直接读取文件和代码，不是语义搜索。记忆就是 SQLite 一张表 + FTS5 全文索引，不需要 Embedding 模型。**

---

## 4. 技术选型

| 层级 | 选型 | 理由 |
|------|------|------|
| 核心运行时 | Go 1.23+ | 编译为单一二进制；天然并发；字节 Eino 已用 Go 验证此路线 |
| LLM 协议 | OpenAI 兼容 HTTP API | DeepSeek/Qwen/豆包全都兼容 |
| 存储 | SQLite (mattn/go-sqlite3) | 嵌入式，零部署，FTS5 全文搜索 |
| CLI | cobra + bubbletea | cobra 是 Go CLI 标准，bubbletea 做终端交互 |
| 配置 | YAML + 环境变量覆盖 | 简单标准 |

---

## 5. 按阶段实现路径

### Phase 1：最小闭环（第 1-6 周）✅ 可运行

**目标：能完成简单编程任务的 ReAct Agent。此时什么高级功能都没有，但能跑通。**

```
Week 1-2: 项目脚手架 + Tool 系统
  - Go module 初始化 + CLI 入口
  - Tool 接口定义 + ToolRegistry
  - 5 个基础工具：Read / Write / Bash / Grep / Glob
  - 每个工具有 isConcurrencySafe / isReadOnly 标记

Week 3-4: Agent Loop (ReAct)
  - 消息历史管理（System + User + Assistant + Tool 角色）
  - LLM Client 抽象（OpenAI 兼容协议）
  - ReAct 循环：组装上下文→LLM 推理→解析 Tool Call→执行→追加结果→循环
  - max_turns 硬限制

Week 5-6: Lane Queue + Agent 生命周期
  - 单 Session 串行队列，多 Session 并行
  - Agent 生命周期状态机
  - JSON 文件 Session 持久化
```

### Phase 2：确定性基础设施（第 7-10 周）🛡️ 安全可控

**目标：在概率性 Agent 外面套上确定性骨架。Agent 不一定更聪明，但绝对更可控。**

```
Week 7-8: Hook Pipeline
  - PreToolUse / PostToolUse Hook 事件总线
  - Command + Inline 处理器
  - Deny > Ask > Allow 合并规则

Week 9-10: Three-Tier Guardrails + Budget
  - 输入/工具/输出三级并行护栏
  - Token Budget 硬限制
  - 基础死循环检测（连续 3 次相同 tool call → 中断）
```

### Phase 3：上下文工程（第 11-14 周）🧠 核心差异化

**目标：Agent 能处理远超上下文窗口的复杂任务，上下文自动压缩不丢失信息。**

```
Week 11-12: ContextAssembler + Skill System
  - System Prompt 骨架 + 动态注入
  - Skill 系统：SKILL.md 解析 + 按需注入
  - 分区排序（Cache 友好）

Week 13-14: ContextCompressor + BudgetManager
  - Level 1-3 免费压缩管线
  - Level 4 LLM 摘要（仅最后手段）
  - 预算告警 80%/95% 自动动作
```

### Phase 4：高级执行模式（第 15-18 周）🚀 能力跃升

**目标：成功率显著高于纯 ReAct，但不是靠更好的 Prompt，而是靠更好的控制结构。**

```
Week 15-16: SubAgent + PreAct
  - Agent-as-Tool-Call 模式
  - 上下文隔离 + 工具过滤
  - PreAct: Think→Predict→Act→Compare（确定性 Compare）

Week 17-18: DAG + ReAcTree 混合规划
  - DAG 节点定义/验证/调度
  - ReAcTree 节点：Sequence / Fallback / Retry(N) / Timeout(T)
  - DAG 节点内嵌 ReAcTree 子树
```

### Phase 5：优化与隔离（第 19-21 周）⚡ 效率提升

```
Week 19-20: Entropy-Guided Search
  - tool_entropy 确定性函数
  - 高熵多候选探索 vs 低熵直接执行

Week 20-21: Workspace Sandbox
  - Level 1 本地文件限制 + Level 2 Git Worktree
```

### Phase 6：收尾（第 22-24 周）📦 交付

```
Week 22: MCP Client 协议适配
Week 23: Trace JSONL 输出 + HTML 可视化报告 + 10 个标准化测试用例
Week 24: 中英文文档 + Docker 一键部署 + Demo 视频录制
```

---

## 6. 风险控制

**每个 Phase 结束都有可运行的产物，不存在"到第 20 周才看到效果"的情况。**

| 技术 | 复杂度 | 不确定度 | 降级方案 |
|------|--------|---------|---------|
| ReAct Loop | 低 | 低 | 不需要降级 |
| Hook Pipeline | 中 | 零（纯工程） | 降为仅 PreToolUse |
| Guardrails | 中 | 零（纯工程） | 降为仅 Tool 级 |
| ContextEngine | 高 | 低（可参考 CC） | 降为简单模板 + 截断 |
| PreAct | 中 | 中（阈值调优） | 降回 ReAct |
| DAG+ReAcTree | 高 | 中（混合新方案） | 降为纯 DAG 或纯 ReAct |
| Entropy-Guided | 中 | 中（阈值调优） | 降为固定 K=2 探索 |

**最差情况：仅完成 Phase 1-3（ReAct + Hook + Guardrails + ContextEngine），已经是一个优于大多数 Agent 框架的完整系统——因为它们都没有确定性基础设施层。**

---

## 7. 面试展示定位

**一句话定位：**
> "Agent Ulysses 是一个 Agent 运行时系统。它解决的核心问题是：如何在 LLM 外面包一层确定性的工程基础设施，让 Agent 可控、可观测、可调试。它不是又一个 LangChain 包装器。"

**核心对比（面试时主动展示）：**

| 对比维度 | LangChain Agent | LangGraph Agent | Agent Ulysses |
|----------|----------------|-----------------|---------------|
| 核心思路 | 调 LLM + Chain | 状态图编排 | 确定性运行时 |
| 上下文管理 | 手动截断 | Checkpoint | 4 级自动压缩管线 |
| 安全模型 | 靠 Prompt | 靠开发者 | Hook 管线 + 三级并行护栏 |
| 并发模型 | 无 | 图调度 | Lane Queue（串行默认、并行 opt-in） |
| 执行隔离 | 无 | 无 | 本地 + Worktree + 容器三级 |
| 防死循环 | 靠 LLM 自觉 | max_steps | 3 层检测（工具→推理→规划） |
| 代码量（核心） | 依赖 LangChain | 依赖 LangGraph | 自研 ~5000 行 Go |
