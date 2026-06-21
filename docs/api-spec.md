# Agent Ulysses: Go-Python JSON-RPC 2.0 API 规范

> **Version**: 1.0
> **Status**: Draft
> **读者**: Go 实现者 (`internal/rpc/`, `internal/process/`, `internal/llm/`) 和 Python 实现者 (`ulysses_ai/`)

---

## 目录

1. [架构概述](#1-架构概述)
2. [传输层](#2-传输层)
   - 2.1 进程启动
   - 2.2 JSONL 帧格式
   - 2.3 管道架构
   - 2.4 消息大小限制
3. [JSON-RPC 2.0 消息类型](#3-json-rpc-20-消息类型)
   - 3.1 请求
   - 3.2 响应（成功）
   - 3.3 响应（错误）
   - 3.4 通知
4. [方法规范](#5-方法规范)
   - 4.1 ping
   - 4.2 chat（Anthropic Messages API 格式）
   - 4.3 chat_stream（Anthropic SSE 事件映射）
   - 4.4 count_tokens
   - 4.5 shutdown
5. [流式协议细节](#6-流式协议细节)
   - 5.1 Anthropic SSE 事件映射
   - 5.2 事件序列
   - 5.3 id 与 request_id 的关系
   - 5.4 流中错误处理
   - 5.5 取消流
   - 5.6 流式通知汇总
6. [错误码注册表](#7-错误码注册表)

---

## 1. 架构概述

```
┌─────────────────────────────────────────────────────────┐
│  Go 进程 (父进程)                                        │
│                                                          │
│  ┌─────────────┐  ┌──────────────┐  ┌─────────────────┐ │
│  │ Process      │─▶│ RPC Client   │─▶│ LLM Client      │ │
│  │ Manager      │  │ (jsonrpc)    │  │ (typed wrapper) │ │
│  └──────┬───────┘  └──────┬───────┘  └────────┬────────┘ │
│         │                 │                    │          │
│         │      ┌──────────┴──────────┐        │          │
│         │      │  stdin (writes)     │        │          │
│         └──────│  stdout (reads)     │────────┘          │
│                │  stderr (logs only) │                    │
│                └──────────┬──────────┘                    │
│                           │                               │
│                     JSON-RPC 2.0                          │
│                     换行分隔 JSON                          │
└───────────────────────────┬───────────────────────────────┘
                            │
┌───────────────────────────┴───────────────────────────────┐
│  Python 进程 (子进程)                                      │
│                                                           │
│  ┌──────────────────────────────────────────────────┐     │
│  │  ulysses_ai/server.py — JSON-RPC 服务端循环       │     │
│  │  - 从 stdin 逐行读取                              │     │
│  │  - 按方法名分发到 handler                          │     │
│  │  - 将响应写入 stdout                              │     │
│  └──────────┬───────────────────────────────────────┘     │
│             │                                             │
│  ┌──────────┴───────────────────────────────────────┐     │
│  │  ulysses_ai/handlers/llm.py — LLM API 调用        │     │
│  │  - Anthropic SDK → Anthropic Messages API        │     │
│  │  - 异步 HTTP 调用                                 │     │
│  └──────────────────────────────────────────────────┘     │
│                                                           │
│  stderr → 仅 Python 日志（绝不包含 JSON-RPC）              │
└───────────────────────────────────────────────────────────┘
```

### 关键设计决策

- **Go 负责所有确定性基础设施**: agent loop、tool registry、planning、guardrails、hooks、进程生命周期。
- **Python 仅负责 LLM API 调用**: Python 进程对 agent、tool、planning 一无所知。JSON-RPC params/result 直接映射 Anthropic Messages API 请求/响应体，Python 做零翻译透传。
- **JSON-RPC 接口即契约**: 任一端可替换，只要遵循相同协议。
- **Go 始终是发起方**: 无 Go→Python 以外的双向通信。Python 从不主动发起请求。
- **Stderr 严格用于日志**: Python 绝不向 stderr 写入 JSON-RPC 消息。Go 绝不解析 stderr 中的 JSON-RPC。

---

## 2. 传输层

### 2.1 进程启动

**配置字段**（来自 `internal/config`）:

| 配置字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `python.path` | string | `"python3"` | Python 解释器路径 |
| `python.module_path` | string | `""` | 可选：添加到 `PYTHONPATH` |
| `llm.model` | string | `"claude-sonnet-4-6"` | 默认模型名 |
| `llm.base_url` | string | `""` | Anthropic API base URL（默认 https://api.anthropic.com） |
| `llm.api_key` | string | (环境变量: `ULYSSES_API_KEY`) | API key（绝不写入 YAML） |
| `llm.max_tokens` | int | `8192` | 默认最大输出 token 数 |
| `llm.temperature` | float | `0.7` | 默认温度 |
| `process.start_timeout` | duration | `"10s"` | 启动健康检查最大等待时间 |
| `process.stop_timeout` | duration | `"5s"` | 优雅关闭最大等待时间 |
| `process.max_restarts` | int | `5` | 放弃前最大连续重启次数 |
| `logging.level` | string | `"info"` | Go 和 Python 的日志级别 |

### 2.2 JSONL 帧格式

- 每条 JSON 消息必须恰好一行，以 `\n` (U+000A) 结尾。
- JSON 对象内字符串不得包含字面换行符。包含换行符的字符串必须转义为 `\n`。
- Go 写入 stdin。
- Python 从 stdin 读取。
- Python 写入 stdout。
- Go 从 stdout 读取。

### 2.3 管道架构

```
                   Go                              Python
              ┌──────────┐                   ┌──────────┐
   Go writes ─┤  stdin   ├───────────────────┤  stdin   │── reads
              ├──────────┤                   ├──────────┤
   Go reads  ─┤  stdout  │←──────────────────┤  stdout  │── writes
              ├──────────┤                   ├──────────┤
              │  stderr  │←──────────────────┤  stderr  │── writes
              └──────────┘                   └──────────┘
                      (仅日志)                      (仅日志)
```

### 2.4 消息大小限制

| 限制项 | 值 | 执行方式 |
|---|---|---|
| 单行最大长度 | 10 MiB | Go: bufio.Scanner 自定义缓冲区。Python: 可配置 readline 缓冲区 |
| 最大请求 ID | 2^53 - 1 | Go 使用 int64，JSON 安全 |
| ping 最小间隔 | 100ms | Go 侧对健康检查做速率限制 |

---

## 3. JSON-RPC 2.0 消息类型

所有消息符合 [JSON-RPC 2.0 规范](https://www.jsonrpc.org/specification)。

### 3.1 请求 (Request)

```json
{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "chat",
    "params": { ... }
}
```

- `jsonrpc`: 必须为 `"2.0"`。
- `id`: int64，Go 侧原子递增计数器。Python 在响应中原样回传此 ID。
- `method`: string，已注册方法名之一。
- `params`: JSON 对象或数组（本规范所有方法均使用对象参数）。

### 3.2 响应 (Response) —— 成功

```json
{
    "jsonrpc": "2.0",
    "id": 1,
    "result": { ... }
}
```

- `id` 与请求 `id` 匹配。
- `result` 为方法特定的返回值。可以是任意 JSON 值。

### 3.3 响应 (Response) —— 错误

```json
{
    "jsonrpc": "2.0",
    "id": 1,
    "error": {
        "code": -32603,
        "message": "Internal error",
        "data": {
            "type": "AuthenticationError",
            "detail": "Invalid API key"
        }
    }
}
```

- `code`: integer，参见[错误码注册表](#7-错误码注册表)。
- `message`: string，简短的人类可读描述。
- `data`: 可选对象，可包含额外错误详情。存在时应包含：
  - `type`: string，Python 异常类名。
  - `detail`: string，详细错误消息。
  - `traceback`: string，可选，仅 debug 模式。

### 3.4 通知 (Notification)

```json
{
    "jsonrpc": "2.0",
    "method": "stream/content_block_delta",
    "params": {
        "request_id": 3,
        "index": 0,
        "delta": { ... }
    }
}
```

- 无 `id` 字段。缺失 `id` 即区分通知与响应。
- 所有流式通知的 `params` 中**必须**包含 `request_id`（整数），值为发起流式请求时的 `id`。Go 侧按 `request_id` 路由到对应的 stream channel，支持多流并发。

---


## 5. 方法规范

### 5.1 `ping`

**用途**: 健康检查。验证 Python 进程存活且可响应。

**Params**:

```json
{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "ping",
    "params": {}
}
```

**Result**:

```json
{
    "jsonrpc": "2.0",
    "id": 1,
    "result": "pong"
}
```

**错误**: 永不返回错误。进程存活且 stdin/stdout 管道完好时始终返回 `"pong"`。

**实现说明**:
- Python handler: 立即返回 `"pong"`，无 I/O 或计算。
- Go 在启动健康检查时以短超时（默认 2s）调用 `ping`。
- Go 定期（每 5s）调用 `ping` 进行存活监控。

---

### 5.2 `chat`

**用途**: 非流式对话补全。向 LLM 发送消息并返回完整响应。

**Params**:

```json
{
    "jsonrpc": "2.0",
    "id": 2,
    "method": "chat",
    "params": {
        "model": "claude-sonnet-4-6",
        "system": "You are a helpful assistant.",
        "messages": [
            {
                "role": "user",
                "content": "Hello!"
            }
        ],
        "max_tokens": 4096,
        "tools": [
            {
                "name": "read_file",
                "description": "Read the contents of a file",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Path to the file"
                        }
                    },
                    "required": ["path"]
                }
            }
        ],
        "temperature": 0.7,
        "stop_sequences": ["\n\n"],
        "tool_choice": {"type": "auto"}
    }
}
```

**params schema**:

```
{
    "model":              string,       // 必填: 模型标识符
    "messages":           Message[],    // 必填: 消息数组（仅 user/assistant）
    "max_tokens":         integer,      // 必填: 最大输出 token 数
    "system"?:            string | TextBlock[],  // 可选: 系统提示词（顶层，不在 messages 中）
    "tools"?:             ToolDef[],    // 可选: 工具定义
    "temperature"?:       number,       // 可选: 采样温度 0.0-1.0
    "top_p"?:             number,       // 可选: 核采样
    "top_k"?:             integer,      // 可选: Top-K 采样
    "stop_sequences"?:    string[],     // 可选: 停止序列
    "tool_choice"?:       object,       // 可选: {type:"auto"|"any"|"tool"|"none", name?:string}
    "thinking"?:          object,       // 可选: {type:"enabled", budget_tokens:integer}
    "metadata"?:          object,       // 可选: 透传元数据
}
```

**Message 对象 schema**:

```
{
    "role":     "user" | "assistant",
    "content":  string | ContentBlock[],
}
```

- `content` 为字符串时等价于 `[{"type": "text", "text": "<content>"}]`。

**ContentBlock 类型**（content 为数组时使用）:

| type | 方向 | 用途 | 关键字段 |
|------|------|------|---------|
| `text` | 双向 | 文本内容 | `text: string` |
| `tool_use` | 响应 | 模型发起工具调用 | `id: string`, `name: string`, `input: object` |
| `tool_result` | 请求(user) | 工具执行结果 | `tool_use_id: string`, `content: string`, `is_error?: boolean` |

```
// text 块
{"type": "text", "text": "I'll check that file."}

// tool_use 块（assistant 消息的 content 中）
{"type": "tool_use", "id": "toolu_01AbCdEf...", "name": "read_file", "input": {"path": "/etc/hosts"}}

// tool_result 块（user 消息的 content 中）
{"type": "tool_result", "tool_use_id": "toolu_01AbCdEf...", "content": "127.0.0.1 localhost", "is_error": false}
```

- `tool_result.content` 为工具执行的返回内容。
- `tool_result.is_error` 为 `true` 时表示工具执行失败。

**ToolDef 对象 schema**:

```
{
    "name":              string,       // 必填: 工具名，匹配 ^[a-zA-Z0-9_-]{1,64}$
    "description"?:      string,       // 强烈建议: 工具描述
    "input_schema": {                  // 必填: JSON Schema 对象
        "type":          "object",
        "properties":    object,
        "required"?:     string[],
    }
}
```

**Result**:

```json
{
    "jsonrpc": "2.0",
    "id": 2,
    "result": {
        "id": "msg_01AbCdEfGhIjKlMnOpQrStUv",
        "type": "message",
        "role": "assistant",
        "content": [
            {"type": "text", "text": "Hello! How can I help you today?"}
        ],
        "model": "claude-sonnet-4-6",
        "stop_reason": "end_turn",
        "stop_sequence": null,
        "usage": {
            "input_tokens": 15,
            "output_tokens": 10,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0
        }
    }
}
```

**Result**（含 tool_use）:

```json
{
    "jsonrpc": "2.0",
    "id": 2,
    "result": {
        "id": "msg_01XyZ...",
        "type": "message",
        "role": "assistant",
        "content": [
            {"type": "text", "text": "Let me read that file for you."},
            {
                "type": "tool_use",
                "id": "toolu_01AbCdEfGhIjKlMnOpQrStUv",
                "name": "read_file",
                "input": {"path": "/etc/hosts"}
            }
        ],
        "model": "claude-sonnet-4-6",
        "stop_reason": "tool_use",
        "stop_sequence": null,
        "usage": {
            "input_tokens": 45,
            "output_tokens": 30,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0
        }
    }
}
```

**完整 result schema**:

```
{
    "id":                string,       // 消息 ID
    "type":              "message",
    "role":              "assistant",
    "content":           ContentBlock[],  // text + tool_use 块
    "model":             string,
    "stop_reason":       "end_turn" | "tool_use" | "max_tokens" | "stop_sequence" | "refusal",
    "stop_sequence"?:    string | null,
    "usage": {
        "input_tokens":              integer,
        "output_tokens":             integer,
        "cache_creation_input_tokens"?: integer,
        "cache_read_input_tokens"?:    integer,
    },
}
```

**`stop_reason` 取值**:

| 值 | 说明 |
|----|------|
| `end_turn` | 自然结束，无需工具调用 |
| `tool_use` | 模型调用了工具，等待工具结果 |
| `max_tokens` | 达到 max_tokens 上限 |
| `stop_sequence` | 遇到 stop_sequences 中的字符串 |
| `refusal` | 安全策略触发 |

**错误**: `-32000`（限流）、`-32001`（上下文过长）、`-32002`（认证错误）、`-32003`（超时）、`-32004`（模型不可用）。

---

### 5.3 `chat_stream`

**用途**: 流式对话补全。Python 将 Anthropic SSE 事件逐条映射为 JSON-RPC 通知下发，最后返回一条 JSON-RPC 响应。

**Params**: 与 `chat` 相同的 schema。

**流式协议**:

Python 发送一系列 JSON-RPC 通知（无 `id`，通过 `params.request_id` 关联请求），最后发送一条 JSON-RPC 响应（有 `id`）。通知类型对应 Anthropic SSE 事件：

| 通知 method | Anthropic SSE 事件 | 说明 |
|-------------|-------------------|------|
| `stream/message_start` | `message_start` | 消息开始，携带消息 ID/model/role |
| `stream/content_block_start` | `content_block_start` | 内容块开始，text 或 tool_use |
| `stream/content_block_delta` | `content_block_delta` | 增量内容，text_delta 或 input_json_delta |
| `stream/content_block_stop` | `content_block_stop` | 内容块结束 |
| `stream/message_delta` | `message_delta` | stop_reason + usage |
| `stream/message_stop` | `message_stop` | 消息流结束 |
| `stream/ping` | `ping` | 心跳（Go 忽略） |

**序列**（假设请求 id=3）:

```
[Go 发送请求]
--> {"jsonrpc":"2.0","id":3,"method":"chat_stream","params":{...}}

[Python 将 Anthropic SSE 事件逐条映射为 JSON-RPC 通知]
<-- {"jsonrpc":"2.0","method":"stream/message_start","params":{"request_id":3,"message":{"id":"msg_01...","type":"message","role":"assistant","model":"claude-sonnet-4-6"}}}

<-- {"jsonrpc":"2.0","method":"stream/content_block_start","params":{"request_id":3,"index":0,"content_block":{"type":"text","text":""}}}
<-- {"jsonrpc":"2.0","method":"stream/content_block_delta","params":{"request_id":3,"index":0,"delta":{"type":"text_delta","text":"Hello"}}}
<-- {"jsonrpc":"2.0","method":"stream/content_block_delta","params":{"request_id":3,"index":0,"delta":{"type":"text_delta","text":"! How"}}}
<-- {"jsonrpc":"2.0","method":"stream/content_block_delta","params":{"request_id":3,"index":0,"delta":{"type":"text_delta","text":" can I help?"}}}
<-- {"jsonrpc":"2.0","method":"stream/content_block_stop","params":{"request_id":3,"index":0}}

[如有 tool_use]
<-- {"jsonrpc":"2.0","method":"stream/content_block_start","params":{"request_id":3,"index":1,"content_block":{"type":"tool_use","id":"toolu_01...","name":"read_file","input":{}}}}
<-- {"jsonrpc":"2.0","method":"stream/content_block_delta","params":{"request_id":3,"index":1,"delta":{"type":"input_json_delta","partial_json":"{\"path\":\"/etc/hosts\"}"}}}
<-- {"jsonrpc":"2.0","method":"stream/content_block_stop","params":{"request_id":3,"index":1}}

[message_delta 携带 stop_reason 和 usage]
<-- {"jsonrpc":"2.0","method":"stream/message_delta","params":{"request_id":3,"delta":{"stop_reason":"end_turn","stop_sequence":null},"usage":{"output_tokens":24}}}

[流结束]
<-- {"jsonrpc":"2.0","method":"stream/message_stop","params":{"request_id":3}}

[最终 JSON-RPC 响应]
<-- {"jsonrpc":"2.0","id":3,"result":{"status":"completed"}}
```

**各通知 params 详细 schema**:

`stream/message_start`:
```
{
    "request_id":         integer,    // 必填: 关联的请求 id
    "message": {
        "id":             string,     // 消息 ID
        "type":           "message",
        "role":           "assistant",
        "model":          string,
    }
}
```

`stream/content_block_start`:
```
{
    "request_id":         integer,    // 必填: 关联的请求 id
    "index":              integer,    // 内容块索引（从 0 开始）
    "content_block": {
        "type":           "text" | "tool_use",
        // type="text":
        "text":           string,
        // type="tool_use":
        "id":             string,     // tool_use ID
        "name":           string,     // 工具名
        "input":          object,     // 始终为 {}，实际参数在 input_json_delta 中累积
    }
}
```

`stream/content_block_delta`:
```
{
    "request_id":         integer,    // 必填: 关联的请求 id
    "index":              integer,    // 内容块索引（与对应的 content_block_start 相同）
    "delta": {
        "type":           "text_delta" | "input_json_delta",
        // type="text_delta":
        "text":           string,     // 文本增量
        // type="input_json_delta":
        "partial_json":   string,     // 部分 JSON 字符串（需累积到 content_block_stop 后整体解析）
    }
}
```

`stream/content_block_stop`:
```
{
    "request_id":         integer,    // 必填: 关联的请求 id
    "index":              integer,    // 内容块索引
}
```

`stream/message_delta`:
```
{
    "request_id":         integer,    // 必填: 关联的请求 id
    "delta": {
        "stop_reason":    "end_turn" | "tool_use" | "max_tokens" | "stop_sequence" | "refusal",
        "stop_sequence"?: string | null,
    },
    "usage": {
        "output_tokens":  integer,    // message_start 中不含 usage，仅此处携带
    }
}
```

`stream/message_stop`:
```
{
    "request_id":         integer,    // 必填: 关联的请求 id
}
```

**流式规则**:
1. 事件顺序严格为: `message_start` → (content_block_start → content_block_delta* → content_block_stop)* → `message_delta` → `message_stop`。
2. 每个 content_block 的 index 在 start/delta/stop 中保持一致。
3. `input_json_delta` 的 `partial_json` 仅在整个 content_block 结束后（收到 stop）才构成有效 JSON。
4. `stream/ping` 心跳通知可由 Python 可选发送，Go 侧忽略。
5. Go 侧按 `(request_id, index)` 二元组重组内容块。

**错误**: 与 `chat` 相同。错误在两个阶段返回：
- 首个事件之前（如认证失败）→ 直接返回标准 JSON-RPC 错误响应
- 流中途（如连接断开）→ 发送 `stream/error` 通知 + 最终响应带 `status: "error"`

---

### 5.4 `count_tokens`

**用途**: 统计消息列表在指定模型下的 token 数。

**Params**:

```json
{
    "jsonrpc": "2.0",
    "id": 4,
    "method": "count_tokens",
    "params": {
        "model": "claude-sonnet-4-6",
        "system": "You are a helpful assistant.",
        "messages": [
            {"role": "user", "content": "Hello!"}
        ]
    }
}
```

**完整 params schema**:

```
{
    "model":              string,       // 必填: 模型标识符
    "messages":           Message[],    // 必填: 待统计的消息
    "system"?:            string | TextBlock[],  // 可选: 系统提示词（顶层）
    "tools"?:             ToolDef[],    // 可选: 工具定义（计入 token）
}
```

**Result**:

```json
{
    "jsonrpc": "2.0",
    "id": 4,
    "result": {
        "count": 15
    }
}
```

**完整 result schema**:

```
{
    "count":             integer,      // 总 token 数
}
```

**错误**: `-32602`（无效参数）、`-32004`（模型不支持 token 化）。

---

### 5.5 `shutdown`

**用途**: 优雅关闭 Python 进程。

**Params**:

```json
{
    "jsonrpc": "2.0",
    "id": 5,
    "method": "shutdown",
    "params": {}
}
```

**Result**:

```json
{
    "jsonrpc": "2.0",
    "id": 5,
    "result": "ok"
}
```

**实现说明**:
- Python handler: 设置关闭标志，写入 `"ok"` 响应，然后执行清理：
  1. 取消所有 pending LLM 请求。
  2. 关闭 API 客户端会话。
  3. 刷新日志。
  4. 以退出码 0 退出。
- 写入响应后 `asyncio` 事件循环应停止。
- Go 侧: 收到 `"ok"` 后，等待最多 `stop_timeout`，然后关闭管道。

---

## 6. 流式协议细节

### 6.1 事件序列

每次 `chat_stream` 请求产生严格有序的事件序列：

```
message_start           ← 1 次
  content_block_start   ← 每个内容块 1 次
  content_block_delta   ← 0 次或多次
  content_block_stop    ← 每个内容块 1 次
  (以上三事件可重复，text 和 tool_use 各自独立索引)
message_delta           ← 1 次
message_stop            ← 1 次
```

### 6.2 流中错误处理

**阶段 1: 首个事件之前出错**（参数校验失败、认证错误）
→ Python 不发送任何通知，直接返回标准 JSON-RPC 错误响应：
```
← {"jsonrpc":"2.0","id":3,"error":{"code":-32002,"message":"Auth Error"}}
```

**阶段 2: 流中途出错**（API 连接断开、中途限流）
→ Python 发送 `stream/error` 通知，然后返回最终响应：
```
← {"jsonrpc":"2.0","method":"stream/error","params":{"request_id":3,"code":-32003,"message":"Connection lost"}}
← {"jsonrpc":"2.0","id":3,"result":{"status":"error","error":{"code":-32003,"message":"Connection lost"}}}
```

### 6.3 取消流

Go 发送 `notifications/cancelled` 通知取消流式请求（参考 MCP 取消模式）：

```
--> {"jsonrpc":"2.0","method":"notifications/cancelled","params":{"request_id":3}}
```

Python 收到后取消 LLM 请求，发送最终响应（`status: "cancelled"`）。

### 6.4 流式通知汇总

| 通知 method | params 关键字段 | 发送时机 |
|-------------|----------------|---------|
| `stream/message_start` | `request_id`, `message` | 流开始 |
| `stream/content_block_start` | `request_id`, `index`, `content_block` | 每个内容块开始 |
| `stream/content_block_delta` | `request_id`, `index`, `delta` | 每次增量更新 |
| `stream/content_block_stop` | `request_id`, `index` | 每个内容块结束 |
| `stream/message_delta` | `request_id`, `delta`, `usage` | stop_reason + token 统计 |
| `stream/message_stop` | `request_id` | 流结束 |
| `stream/ping` | `request_id` | 心跳（可选，可忽略） |
| `stream/error` | `request_id`, `code`, `message` | 流中途出错 |
| `notifications/cancelled` | `request_id` | Go 取消流（Go→Python） |

---

## 7. 错误码注册表

| 错误码 | 名称 | 说明 | 触发条件 |
|---|---|---|---|
| `-32700` | Parse Error | 收到无效 JSON | stdin 包含格式错误的 JSON |
| `-32600` | Invalid Request | 非有效 JSON-RPC 请求 | 缺少 `method`、`jsonrpc` 版本无效 |
| `-32601` | Method Not Found | 未知方法 | method 字符串不在 handler 注册表中 |
| `-32602` | Invalid Params | 方法参数无效 | 缺少必填字段、类型错误 |
| `-32603` | Internal Error | Handler 未处理异常 | Python 异常、内部错误 |
| `-32000` | Rate Limit Exceeded | LLM API 限流 | 上游 API 返回 429 |
| `-32001` | Context Length Exceeded | 输入超过模型上下文窗口 | 上游 API 返回上下文长度相关的 400/413 |
| `-32002` | Auth Error | LLM API 认证失败 | 上游 API 返回 401/403 |
| `-32003` | API Timeout | LLM API 请求超时 | 上游超时（非 context deadline） |
| `-32004` | Model Not Available | 模型未找到或不支持 | 上游返回 404，或模型不在 Python 配置中 |