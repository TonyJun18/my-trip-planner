# Agent Runtime 设计文档（移植 earendil-works/pi 的 pi-agent-core 理念）

> 2026-10-27 · 立项（用户确认方案 A + B 组合）
> 参考：https://github.com/earendil-works/pi（MIT）`packages/agent/src/agent-loop.ts` / `agent.ts`
> 状态：**设计定稿，A 期实现中**

## 0. 为什么移植 Pi

Pi = "minimal, extensible agent harness"。本项目与其重叠/缺口分析：

| Pi 包 | 内容 | 本项目现状 | 处置 |
|---|---|---|---|
| pi-ai | 统一多 provider、模型目录、cost 追踪 | `providers.py` 已覆盖（注册/重试/熔断/兜底链/观测） | **不移植**，保留 |
| **pi-agent-core** | **有状态 Agent 循环**：turn/事件流/工具编排/终止钩子/上下文变换 | **无通用循环**；8 个 agent 全是手写函数（同构样板 100+ 行/个，planner 校验重试是手搓 for 循环） | **移植核心** |
| pi-durable | 持久化 conversation/task/document | 有 plan 落库，无会话级持久 | B 期简化移植 |
| chord / telemetry | 插件宿主 / 遥测 | 单机小项目，过度设计 | 不移植 |

技术栈不同（TS vs Python）：**设计移植，非代码搬运**。MIT 许可下理念复用合规，实现完全重写。

## 1. 目标与原则

- **A 期**：通用 AgentLoop 运行时（`backend/app/agent/runtime.py`），统一 turn/事件/工具编排/终止护栏；现有 agent 迁移后**函数签名与返回契约不变**（tests 不破）。
- **B 期**：对话式行程助手（持久会话 + 聊天 API + WS 流式 + 前端聊天面板），参考 pi-durable 的 conversation 简化版。
- 原则：零新依赖（不引 pi npm 包）；LLM 调用全部走 `invoke_with_resilience`（保留熔断/兜底/观测）；WS 事件契约沿用 `phase/artifact/trace/status`，新增 `message`/`tool` 增量事件（可选）。

## 2. A 期：AgentLoop 运行时

### 2.1 核心抽象（`app/agent/runtime.py`）

```python
@dataclass
class AgentTool:
    name: str
    description: str
    parameters: type[BaseModel] | None      # pydantic 参数模型 → JSON schema（供 bind_tools）
    execute: Callable[..., Awaitable[str]]   # 返回 observation 文本（失败 raise，由 loop 捕获标 is_error）

@dataclass
class AgentEvent:                            # 事件 = 类型化 dict（与 WS 兼容）
    type: str                                # agent_start|turn_start|message_start|message_update|
                                             # message_end|tool_execution_start|tool_execution_end|turn_end|agent_end
    ...                                      # 随类型携带 message/toolCall/result/delta

class AgentLoopConfig:
    system_prompt: str
    agent_tools: list[AgentTool]
    provider: str = "auto"
    temperature: float = 0.2
    max_iterations: int = settings.AGENT_MAX_ITERATIONS   # 硬护栏（含工具+重生成轮次）
    convert_to_llm: Callable | None          # AgentMessage[] → LLM Message[]（默认过滤）
    transform_context: Callable | None       # 上下文压缩/裁剪钩子（pi transformContext）
    before_tool_call / after_tool_call       # 钩子：可拦截工具、可 terminate
    should_stop_after_turn                   # turn 后终止判定（pi shouldStopAfterTurn）
    validator: Callable | None               # 输出强校验（Pydantic validate_plan 等）；
                                             # 失败 → 自动把错误摘要反馈回 LLM 重试（受 max_corrections 限制）
class AgentLoop:
    def __init__(self, config, *, on_event: Callable[[AgentEvent], Awaitable[None]] | None)
    async def run(self, human_message: str | list) -> dict   # 返回 {status, output, messages, trace, corrections}
```

### 2.2 Loop 语义（对照 pi agent-loop.ts）

```
run(prompt)
├─ emit agent_start
├─ turn: message_start/user → LLM(invoke_with_resilience, tools) → message_start/update(delta)/end
├─ 有 tool_calls？
│   ├─ stopReason=length → 全部按 is_error 拒绝（参数可能被截断，不执行）
│   ├─ before_tool_call 可 block
│   └─ 执行工具（可并行，默认串行保守）→ emit tool_execution_start/end → 回填 ToolMessage
├─ emit turn_end
├─ validator 失败 → 转成 SystemMessage 反馈，continue（≤ max_corrections）
├─ should_stop_after_turn / terminate → agent_end
└─ 迭代超限 → agent_end(status=failed)
```

### 2.3 与现有代码的接缝

| 现有件 | 接法 |
|---|---|
| `invoke_with_resilience` | loop 内部唯一 LLM 入口，保留重试/熔断/兜底/observation |
| `TOOL_MAP`（LangChain @tool） | 迁移期用包装函数桥接：`AgentTool(name, execute=lambda **kw: TOOL_MAP[name].ainvoke(kw))`；新写工具直接用 AgentTool |
| `_extract_json` / `validate_plan` / `validate_critique` | 作为 loop 的 `validator` 回调（Planner/Critic 的"校验失败→反馈重试"统一进 loop，删手搓 for） |
| `_emit_plan_event`（WS） | `on_event` 适配器：`message`/`tool` 事件映射为现有 `trace`/`artifact`；`delta` 留给 B 期聊天流式 |
| agent 函数签名（`attraction_agent(city, prefs, ...)`） | **保持不变**，内部改为调 `AgentLoop`（兼容层：tests 不破） |

### 2.4 A 期交付

1. `backend/app/agent/runtime.py`（AgentTool + AgentLoop + 事件 + 护栏 + validator 循环）
2. 迁移试点：`attraction_agent` / `hotel_agent`（同构工具采集型）→ runtime 内芯
3. `backend/tests/test_agent_runtime.py`（loop 单测：无工具轮 / 工具轮 / 工具失败 / validator 重试 / 迭代护栏 / terminate）
4. 回归：全套 pytest + mock LLM

## 3. B 期：对话式行程助手（参考 pi-durable 简化版）

### 3.1 会话模型（Postgres 新表）

```
chat_sessions(id, user_id FK, title, created_at, updated_at, meta jsonb)
chat_messages(id, session_id FK, role, content jsonb, tool_call jsonb, created_at)
```
- 持久会话恢复：加载 messages → 直接作为 LLM 上下文（pi-durable conversation 的最小化）
- 上下文预算：超限时摘要压缩历史（保留关键字段），压缩失败则提示截断停止（绝不静默丢必需字段）

### 3.2 API + 前端

- `POST /api/v1/chat/sessions`（建会话）、`GET /api/v1/chat/sessions/{id}/messages`、`POST /api/v1/chat/sessions/{id}/messages`（发消息）
- `WS /ws/chat/{session_id}`：推 `message_delta` / `tool_execution` / `done`（复用 ws 基建）
- 前端：行程页/首页聊天入口 → 聊天面板（气泡 + 流式渲染 + 工具调用折叠展示）

### 3.3 对话 Agent 能力

- 工具：`search_attractions` / `search_hotels` / `search_foods` / `query_weather` / `search_transport` + 读取/修订当前 trip（复用 revise_service）
- 多轮工具调用（A 期 runtime 天然支持）
- 结果可一键转正式规划（把对话产物喂给 run_planning_agents 或直接落 trip）

### 3.4 风险与缓解

| 风险 | 缓解 |
|---|---|
| 对话 LLM 成本/滥用 | 绑定登录用户 + 每会话 token 预算 + 沿用 invoke 熔断 |
| 注入（对话里塞指令） | 内容与指令隔离；工具输出 schema 校验（复用 note_import 敌意输入策略） |
| 上下文爆炸 | transform_context 摘要钩子 + 硬上限，超限停下上报 |

## 4. 验收

- A：runtime 单测绿；迁移 agent 专项测试绿（与原断言一致）；全套 pytest 绿；ruff 通过
- B：会话 CRUD + 聊天 WS 冒烟；前端 build 通过；i18n 键 zh/en