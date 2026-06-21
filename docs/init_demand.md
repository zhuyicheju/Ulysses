# 项目规划文档：Agent Ulysses

**项目名称**：Agent Ulysses
**副标题**：A Runtime System for Long-Horizon Code Agents
**项目定位**：长周期代码智能体的运行时系统

**核心理念**：
Agent Ulysses 是一个 **Agent 运行时基础设施层**。它解决的是：**如何在概率性的 LLM 外面包一层确定性的工程基础设施，让 Agent 高效、可控、可观测、可调试**。目标是构建一个**自研的、模块化的、确定性与概率性分离的** Agent 运行时系统。

---

## 设计原则

| 原则 | 说明 |
|------|------|
| **模块化组装 > 整体耦合** | 每个模块有明确的 Go interface 契约，可独立开发、测试、替换。模块间只依赖接口不依赖实现 |
| **可运行为先 > 完美设计** | 第一阶段必须产出可运行的最小闭环，后续在可运行基础上迭代 |
| **确定性 > 概率性** | 先实现确定性的基础设施（Hook、Guardrails、Lane Queue），再叠加复杂 AI 能力（PreAct、Entropy-Guided） |
| **自研核心 > 胶水代码** | 拒绝 LangChain/LangGraph 等包装器依赖，核心运行时完全自研 |
| **不碰低含金量方向** | 不做 RAG Pipeline、不做向量数据库、不做 Prompt 模板库、不做模型微调——这些无法展示工程能力 |

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

### 2.1 Context Engineering Engine（上下文工程引擎）

Claude Code 的核心洞察：大约 98% 的代码在管理上下文流动，只有约 2% 是 AI 决策逻辑。上下文工程的本质是**确定性代码管理概率性模型**。

| 子模块 | 核心职责 | 关键技术 |
|--------|---------|----------|
| **ContextAssembler** | 组装发给 LLM 的上下文 | System Prompt 骨架（缓存友好）、RULES.md 注入、Skill 按需注入、分区排序（内置工具前缀稳定，保证 85%+ 缓存命中） |
| **ContextCompressor** | 上下文超窗口时自动压缩 | 4 级管线：Snip（截断）→ Microcompact（剥离元数据）→ ContextCollapse（合并）→ LLM Summary（付费，仅最后手段）。前 3 级免费 |
| **BudgetManager** | Token 预算硬限制 | 80% 预警自动压缩、95% 强制截断（确定性代码执行，不是"建议"）、Per-SubAgent 子预算分配 |
| **PromptCacheOptimizer** | 最大化 LLM Prompt Cache 命中 | 稳定前缀策略、增量更新重建、缓存命中率监控 |

### 2.2 Deterministic Hook Pipeline（确定性拦截层）

**来源：Claude Code。Hook 是 Agent 与执行之间的一道防火墙，不是回调函数。**

```
事件生命周期：
SessionStart → UserPromptSubmit → [Turn 循环]
  ┌─────────────────────────────────────────┐
  │  PreToolUse → [Hook 链] → Tool.Execute → PostToolUse  │
  │      ↑              ↓ 阻止(exit 2)        ↑           │
  │   修改参数       PermissionGate         失败处理       │
  └─────────────────────────────────────────┘
```

### 2.4 DAG + ReAcTree 混合规划器

**DAG 和 ReAcTree 各司其职，不互相替代。**

| 层次 | 负责 | 特点 |
|------|------|------|
| **DAG** | 宏观任务分解 | 定义子任务依赖关系、识别可并行的子任务、定义数据流（A.output → C.input）。节点数 ≤ 10 |
| **ReAcTree** | 微观执行控制 | 嵌入在每个 DAG 节点内部。 |

**为什么混合？**
- 纯 DAG 无法表达条件分支和重试——这是 Agent 的刚需
- 纯 ReAct 无法表达宏观结构和并行——会在单线程中线性执行
- LangGraph 的失败教训：用图表达所有控制流导致图膨胀到不可维护
- 采用游戏状态树思想

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
```

### 2.7 SubAgent System（子智能体系统）

**来源：Claude Code 的 Agent-as-Tool-Call 模式。**

```
父 Agent 视角：
  Agent 就是 ToolRegistry 中的一个普通 Tool

子 Agent 内部：
  独立的 ContextEngine
  过滤后的 Tool Set
  独立的 Token Budget
  独立的 Sidechain Transcript
```

### 2.8 Workspace Sandbox（工作区沙箱）

### 2.9 Skill System（技能系统）

**来源：OpenClaw + Claude Code。**

Skills 是 Agent 获取领域知识的方式——纯 Markdown 文件 + YAML frontmatter

### 2.10 Trace System（追踪系统）

在现代企业需求中**尤为重要**，借鉴OpenTelemetry的实现思想

---

## 3. 架构边界

明确声明本项目不涉及以下方向：

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
| 核心运行时 | Go 1.23+ | 编译为单一二进制；天然并发 |
| LLM 协议 | AI框架内容采用python, OpenAI 兼容 HTTP API | 兼容GPT、DEEPSEEK、CLAUDE格式 |
| 存储 | SQLite  | 嵌入式，零部署，FTS5 全文搜索 |
| CLI | cobra + bubbletea | cobra 是 Go CLI 标准，bubbletea 做终端交互 |
| 配置 | YAML + 环境变量覆盖 | 简单标准 |

Go 启动 Python 子进程，使用 Stdio 交换 JSON-RPC 消息
## 6. 风险控制

| 技术 | 复杂度 | 不确定度 | 降级方案 |
|------|--------|---------|---------|
| ReAct Loop | 低 | 低 | 不需要降级 |
| Hook Pipeline | 中 | 零（纯工程） | 降为仅 PreToolUse |
| Guardrails | 中 | 零（纯工程） | 降为仅 Tool 级 |
| ContextEngine | 高 | 低（可参考 CC） | 降为简单模板 + 截断 |
| PreAct | 中 | 中（阈值调优） | 降回 ReAct |
| DAG+ReAcTree | 高 | 中（混合新方案） | 降为纯 DAG 或纯 ReAct |
| Entropy-Guided | 中 | 中（阈值调优） | 降为固定 K=2 探索 |