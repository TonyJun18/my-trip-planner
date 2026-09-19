"""LangGraph T-A-O（Thought-Action-Observation）Agent 状态图。

流程：
  plan_request -> [Thought -> Action(tool_calls) -> Observation(ToolMessage)] 循环
                -> finalize（输出完整行程 JSON，经 Pydantic 强校验）

标准工具调用范式：
  - ``agent_node``：LLM (bind_tools) 输出结构化 tool_calls，或直接输出最终 JSON
  - ``tools_node``：按 tool_calls 真实执行工具，回填 ToolMessage（Observation）
  - ``should_continue``：有 tool_calls → 继续循环；有计划（已校验）→ 结束；超迭代 → 失败

LLM 输出鲁棒性：
  - 最终 JSON 必须通过 ``PlanSchema`` 强校验（字段/类型/日期/预算）
  - 校验失败 → 把错误摘要作为反馈消息喂回 LLM 自纠正（受 ``max_corrections`` 限制）
  - 调用统一走 ``invoke_with_resilience``（重试 + 熔断）
"""
from __future__ import annotations

import json
import re
from typing import Annotated, Any, Literal

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.tools import tool as lc_tool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.graph.state import CompiledStateGraph
from typing_extensions import TypedDict

from app.agent import tools as agent_tools
from app.agent.providers import get_provider, invoke_with_resilience
from app.core.logging import get_logger
from app.schemas.plan import validate_plan

logger = get_logger(__name__)


class AgentState(TypedDict, total=False):
    request: dict[str, Any]
    messages: Annotated[list[BaseMessage], add_messages]
    plan: dict[str, Any] | None
    trace: list[dict[str, Any]]
    iterations: int
    max_iterations: int
    corrections: int
    max_corrections: int
    status: Literal["running", "completed", "failed"]
    error: str | None
    provider: str


# ── 工具定义（LangChain @tool，供 bind_tools 使用） ─────────────
@lc_tool
async def search_attractions(city: str, query: str | None = None, limit: int = 8) -> str:
    """搜索某城市的推荐景点/餐厅，返回结构化 JSON。真实数据：Tavily + 地理编码。"""
    result = await agent_tools.search_attractions(city, query=query, limit=limit)
    return json.dumps(result, ensure_ascii=False)


@lc_tool
def compute_budget(stops: list[dict]) -> str:
    """根据站点列表计算预算明细，返回 JSON。"""
    result = agent_tools.compute_budget(stops)
    return json.dumps(result, ensure_ascii=False)


TOOLS = [search_attractions, compute_budget]
TOOL_MAP = {t.name: t for t in TOOLS}


SYSTEM_PROMPT = """你是一个智能旅行规划助手。请使用提供的工具逐步规划行程（Thought-Action-Observation 循环）。

可用工具：
- search_attractions(city: str, query?: str, limit?: int): 搜索某城市的推荐景点/餐厅，返回结构化 JSON（含经纬度，可能为 null）
- compute_budget(stops: list): 根据站点列表计算预算明细，返回 JSON

流程要求：
1. 先思考（Thought），再调用工具获取信息（Action）
2. 观察工具返回的结果（Observation）
3. 信息不足就继续调用工具；信息充分后，停止调用工具，直接输出最终行程 JSON

重要规则：
- 每个站点必须有 name；type 只能是 attraction / food / hotel
- lat/lng 可能为 null（地理编码失败），此时描述里注明"需手动确认位置"
- 每天建议 2-4 个站点，包含景点与餐饮，可含住宿（hotel）
- 日期必须是 YYYY-MM-DD 格式，与用户给定日期范围一致
- 预算 by_type 的 key 只能是 attraction / food / hotel

最终 JSON 必须严格遵循以下结构（不要输出任何多余文字，直接给 JSON）：
{
  "destination": "城市名",
  "days": [
    {
      "day_number": 1,
      "date": "YYYY-MM-DD",
      "theme": "当日主题",
      "stops": [
        {"name": "...", "type": "attraction|food|hotel", "lat": 0.0, "lng": 0.0,
         "estimated_cost": 0, "duration_minutes": 120, "description": "..."}
      ]
    }
  ],
  "budget": {
    "total_estimated": 0.0,
    "by_type": {"attraction": 0.0, "food": 0.0, "hotel": 0.0},
    "currency": "CNY"
  }
}"""


# ── 辅助 ──────────────────────────────────────────────────────
def _user_request_text(req: dict[str, Any]) -> str:
    parts = [
        f"请为 {req.get('destination', '未知目的地')} 规划行程",
        f"日期：{req.get('start_date', '?')} 至 {req.get('end_date', '?')}",
        f"人数：{req.get('travelers', 1)}",
    ]
    if req.get("budget"):
        parts.append(f"预算：{req['budget']} 元")
    if req.get("preferences"):
        parts.append(f"偏好：{', '.join(req['preferences'])}")
    return "；".join(parts) + "。"


def _trail_step(thought: str, action: str, action_input: str, observation: str) -> dict[str, str]:
    return {
        "thought": thought,
        "action": action,
        "action_input": action_input,
        "observation": observation,
    }


def _extract_thought(content: str) -> str:
    m = re.search(r"[Tt]hought:?\s*[:：]?\s*(.+?)(?:\n|$)", content)
    return m.group(1).strip() if m else ""


def _extract_json(text: str) -> dict | None:
    """从 LLM 输出提取 JSON（容忍代码块/杂质）。"""
    if not text:
        return None
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None


def _validation_feedback(exc: Exception) -> str:
    """把 Pydantic ValidationError 转成给 LLM 的简短纠错提示。"""
    errors = getattr(exc, "errors", list)()
    lines = []
    for e in errors[:6]:
        loc = ".".join(str(x) for x in e.get("loc", []))
        lines.append(f"- {loc}: {e.get('msg', 'invalid')}")
    return "你的最终行程 JSON 校验失败，请修正后重新输出完整的 JSON（不要解释）：\n" + "\n".join(lines)


# ── Graph 节点 ────────────────────────────────────────────────
async def agent_node(state: AgentState) -> dict[str, Any]:
    """LLM 节点：bind_tools 调用，输出 tool_calls 或最终 JSON（经强校验）。"""
    provider = get_provider(state.get("provider", "auto"))

    messages = [SystemMessage(content=SYSTEM_PROMPT)] + state.get("messages", [])
    if not any(isinstance(m, HumanMessage) for m in messages):
        messages.insert(1, HumanMessage(content=_user_request_text(state.get("request", {}))))

    response = await invoke_with_resilience(provider, messages, tools=TOOLS)
    content = response.content if isinstance(response, AIMessage) else str(getattr(response, "content", response))

    iterations = state.get("iterations", 0) + 1
    tool_calls = getattr(response, "tool_calls", None) or []

    if tool_calls:
        # 需要调用工具 → 交给 tools_node
        return {"messages": [response], "iterations": iterations}

    # 无工具调用 → 视为最终答案，提取并强校验 JSON
    final = _extract_json(content)
    if final is None:
        corrections = state.get("corrections", 0) + 1
        if corrections > state.get("max_corrections", 3):
            return {
                "messages": [response],
                "iterations": iterations,
                "status": "failed",
                "error": "LLM 多次输出无法解析为 JSON",
            }
        feedback = SystemMessage(
            content="你的输出中未找到合法的 JSON 行程数据。请只输出一个 JSON 对象（不要解释、不要额外文字），遵循系统提示中的结构。"
        )
        return {"messages": [response, feedback], "iterations": iterations, "corrections": corrections}

    try:
        clean = validate_plan(final)
        return {
            "messages": [response],
            "plan": clean,
            "iterations": iterations,
            "status": "completed",
        }
    except Exception as exc:  # noqa: BLE001 — Pydantic ValidationError
        corrections = state.get("corrections", 0) + 1
        if corrections > state.get("max_corrections", 3):
            logger.warning("Agent 计划校验失败且超过纠错上限: %s", exc)
            return {
                "messages": [response],
                "iterations": iterations,
                "status": "failed",
                "error": f"LLM 输出校验失败: {exc}",
            }
        logger.info("Agent 计划校验失败，反馈自纠正 (correction=%d): %s", corrections, exc)
        feedback = SystemMessage(content=_validation_feedback(exc))
        return {"messages": [response, feedback], "iterations": iterations, "corrections": corrections}


async def tools_node(state: AgentState) -> dict[str, Any]:
    """按最后一条 AIMessage 的 tool_calls 执行工具，回填 Observation。"""
    messages = list(state.get("messages", []))
    trace = list(state.get("trace", []))
    last = messages[-1] if messages else None
    if not isinstance(last, AIMessage) or not last.tool_calls:
        raise RuntimeError("tools_node 前缺少带 tool_calls 的 AIMessage")

    tool_messages: list[ToolMessage] = []
    for tc in last.tool_calls:
        fn = TOOL_MAP.get(tc.get("name") or "")
        if fn is None:
            raise RuntimeError(f"未知工具: {tc.get('name')}")
        try:
            result = await fn.ainvoke(tc.get("args") or {})
        except Exception as exc:  # noqa: BLE001 — 工具失败也要回填 Observation
            result = f'{{"error": "工具执行失败: {exc}"}}'
        obs = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
        tool_messages.append(
            ToolMessage(content=obs, tool_call_id=tc.get("id") or f"call-{len(trace)}", name=tc["name"])
        )
        # T-A-O 轨迹
        thought = _extract_thought(str(last.content))
        trace.append(
            _trail_step(
                thought,
                tc["name"],
                json.dumps(tc.get("args") or {}, ensure_ascii=False),
                obs,
            )
        )

    return {"messages": tool_messages, "trace": trace}


def should_continue(state: AgentState) -> Literal["tools", "agent", "end"]:
    """路由决策：

    - 已产出 plan（校验通过）→ end
    - 已失败（纠错超限）→ end
    - 最后一条是带 tool_calls 的 AIMessage → tools（执行工具）
    - 其他（纠正反馈 SystemMessage 等）→ agent（回 LLM 继续）
    - 超过最大迭代 → failed → end
    """
    if state.get("plan") is not None or state.get("status") == "failed":
        return "end"
    if state.get("iterations", 0) >= state.get("max_iterations", 10):
        state["status"] = "failed"
        state["error"] = f"达到最大迭代次数 {state.get('max_iterations')}"
        return "end"
    last = (state.get("messages") or [None])[-1]
    if isinstance(last, AIMessage) and getattr(last, "tool_calls", None):
        return "tools"
    return "agent"


# ── 图构建 ────────────────────────────────────────────────────
def build_agent_graph() -> CompiledStateGraph:
    graph = StateGraph(AgentState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tools_node)
    graph.add_edge(START, "agent")
    graph.add_edge("tools", "agent")
    graph.add_conditional_edges(
        "agent",
        should_continue,
        {"tools": "tools", "agent": "agent", "end": END},
    )
    return graph.compile()


async def run_agent(
    request: dict[str, Any],
    *,
    provider: str = "auto",
    max_iterations: int = 10,
    max_corrections: int = 3,
) -> dict[str, Any]:
    """执行 Agent，返回 {plan, trace, provider, model, status, error}。"""
    graph = build_agent_graph()
    state: AgentState = {
        "request": request,
        "messages": [],
        "plan": None,
        "trace": [],
        "iterations": 0,
        "max_iterations": max_iterations,
        "corrections": 0,
        "max_corrections": max_corrections,
        "status": "running",
        "error": None,
        "provider": provider,
    }
    result = await graph.ainvoke(state)

    prov = get_provider(result.get("provider") or provider)
    return {
        "plan": result.get("plan"),
        "trace": result.get("trace", []),
        "provider": prov.name,
        "model": prov.model_id,
        "status": result.get("status", "completed"),
        "error": result.get("error"),
    }