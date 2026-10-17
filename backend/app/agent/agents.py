"""多 Agent 行程规划：AttractionSearchAgent / WeatherQueryAgent / HotelAgent / PlannerAgent。

角色分工（单一职责，提示词极简，各自只做一件事）：

1. ``AttractionSearchAgent``（景点搜索专家）
   输入：城市 + 用户偏好（"历史文化" / "自然风光" / "美食" ...）
   动作：把偏好映射为搜索关键词 → 调用 ``search_attractions`` 工具 → 返回景点 POI 列表

2. ``WeatherQueryAgent``（天气查询专家）
   输入：城市名
   动作：直接调用 ``query_weather`` 工具 → 返回未来几天天气预报
   —— 确定性路径：城市名 → 天气数据，不经过 LLM，几乎不会出错、零 token

3. ``HotelAgent``（酒店推荐专家）
   输入：城市 + 住宿需求（"经济型" / "豪华型" / "亲子" ...）
   动作：把住宿需求映射为搜索关键词 → 调用 ``search_hotels`` 工具 → 返回酒店 POI 列表

4. ``PlannerAgent``（行程规划专家）
   输入：前三个 Agent 的输出 + 用户原始需求（日期/预算/人数）
   动作：不调用任何外部工具，只做信息整合 —— 按天编排景点/餐饮/酒店，
   输出完整行程 JSON（经 Pydantic 强校验 + 失败自纠正）

编排（``run_planning_agents``）：
- 三个采集 Agent 并行执行（asyncio.gather），互相独立、可水平扩展
- 编排层补充餐饮 POI（真实数据），因为美食是行程的必备要素
- PlannerAgent 最后统一整合；LLM 的预算估值由代码 ``compute_budget`` 校准覆盖
"""
from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool as lc_tool

from app.agent import tools as agent_tools
from app.agent.providers import get_provider, invoke_with_resilience
from app.common.config import settings
from app.core.logging import get_logger
from app.i18n import normalize_locale
from app.i18n.prompts import get_prompt, plan_language_instruction, preference_keywords, preference_keys_to_keywords
from app.i18n.translations import t
from app.schemas.plan import validate_critique, validate_plan
from app.services.discount_service import discount_rules_for_request
from app.services.driving_service import check_plan_driving_async

logger = get_logger(__name__)

# WebSocket 实时推送：默认空实现（None），run_planning_agents 每产生一条
# trace 就调用 on_event；由规划任务端点（ws router）注入真正的发布函数。
# 用「可注入回调」而非直接 import hub，避免 agents 层与传输层耦合。
_on_plan_event: Any = None


def set_plan_event_callback(cb: Any) -> None:
    """注入规划事件回调（ws 端点启动时调用；测试可注入收集器）。"""
    global _on_plan_event
    _on_plan_event = cb


async def _emit_plan_event(event: dict[str, Any]) -> None:
    """向 WS 订阅者发布一条规划事件（phase / artifact / trace / status）。

    事件契约见 ``docs/interaction-redesign.md`` §4：
    - phase:    ``{"type": "phase", "phase": "collecting", "status": "running|completed", ...}``
    - artifact: ``{"type": "artifact", "artifact": "attractions", "data": [...]}``
    - trace:    ``{"type": "trace", "trace": {...}}``（技术日志，前端折叠区展示）
    - status:   ``{"type": "status", "status": "completed", ...}``（终态，由执行器补发）
    """
    cb = _on_plan_event
    if cb is not None:
        try:
            await cb(event)
        except Exception:  # noqa: BLE001 — 推送失败绝不阻断 Agent 执行
            logger.debug("规划事件推送失败: %s", event.get("type"))


# 事件发射辅助：fire-and-forget（推送失败/慢消费者不阻塞 Agent 主流程）
def _fire_event(event: dict[str, Any]) -> None:
    task = asyncio.create_task(_emit_plan_event(event))
    # 回收异常：回调内部（如 DB 持久化）抛错时避免
    # "Future exception was never retrieved" 噪音；推送失败本身已被静默
    task.add_done_callback(_consume_event_task)


def _consume_event_task(task: asyncio.Task) -> None:
    try:
        task.exception()
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.debug("规划事件任务异常（已回收）", exc_info=True)


def _fire_phase(phase: str, status: str, **extra: Any) -> None:
    """发射一条阶段事件（running / completed 及可选 summary）。"""
    _fire_event({"type": "phase", "phase": phase, "status": status, **extra})


def _fire_artifact(artifact: str, data: Any) -> None:
    """发射一条中间制品事件（轻量摘要；全量数据仍落 plan/trace 列）。"""
    _fire_event({"type": "artifact", "artifact": artifact, "data": data})


# ═══════════════════════════════════════════════════════════
#  工具（LangChain @tool 包装，供 bind_tools 使用）
# ═══════════════════════════════════════════════════════════
@lc_tool
async def search_attractions(city: str, query: str | None = None, limit: int = 8) -> str:
    """搜索某城市的推荐景点（可按偏好关键词），返回结构化 JSON（POI 列表）。"""
    result = await agent_tools.search_attractions(city, query=query, limit=limit)
    return json.dumps(result, ensure_ascii=False)


@lc_tool
async def search_hotels(city: str, query: str | None = None, limit: int = 6) -> str:
    """搜索某城市符合住宿需求的酒店，返回结构化 JSON（POI 列表）。"""
    result = await agent_tools.search_hotels(city, query=query, limit=limit)
    return json.dumps(result, ensure_ascii=False)


@lc_tool
async def query_weather(city: str, days: int = 3) -> str:
    """查询某城市未来几天的天气预报，返回结构化 JSON。"""
    result = await agent_tools.query_weather(city, days=days)
    return json.dumps(result, ensure_ascii=False)


@lc_tool
async def search_transport(departure: str, destination: str, date: str | None = None, limit: int = 4) -> str:
    """查询出发地到目的地的大交通方案（驾车/高铁/航班），返回结构化 JSON。

    价格可能缺失（无可信来源时不编造）；带 source_url 的条目才可引用。
    """
    result = await agent_tools.search_transport(departure, destination, date=date, limit=limit)
    return json.dumps(result, ensure_ascii=False)


@lc_tool
async def search_foods(city: str, query: str | None = None, limit: int = 6) -> str:
    """搜索某城市符合口味/菜系偏好的餐厅美食，返回结构化 JSON（POI 列表）。"""
    result = await agent_tools.search_foods(city, query=query, limit=limit)
    return json.dumps(result, ensure_ascii=False)


ATTRACTION_TOOLS = [search_attractions]
HOTEL_TOOLS = [search_hotels]
WEATHER_TOOLS = [query_weather]
TRANSPORT_TOOLS = [search_transport]
FOOD_TOOLS = [search_foods]
TOOL_MAP: dict[str, Any] = {
    t.name: t for t in (search_attractions, search_hotels, query_weather, search_transport, search_foods)
}


# ═══════════════════════════════════════════════════════════
#  Agent 提示词（i18n：语言由 get_prompt() 按 locale 选择）
#  ── 兼容层 ──
#  以下常量保留旧版默认语种（zh-CN），供旧调用方/测试引用；
#  新代码一律走 ``get_prompt(agent, locale)``（含输出语种指令）。
#  WEATHER/HOTEL/FOOD/TRANSPORT/PLANNER/CRITIC/REVISE_CRITIC/REVISE
#  的多行定义保留在下方，等价于 get_prompt(x, "zh-CN") 的正文部分。
# ═══════════════════════════════════════════════════════════
ATTRACTION_SYSTEM_PROMPT = get_prompt("attraction", "zh-CN")


WEATHER_SYSTEM_PROMPT = get_prompt("weather", "zh-CN")


HOTEL_SYSTEM_PROMPT = get_prompt("hotel", "zh-CN")


FOOD_SYSTEM_PROMPT = get_prompt("food", "zh-CN")


TRANSPORT_SYSTEM_PROMPT = get_prompt("transport", "zh-CN")


DISCOUNT_COLLECTOR_SYSTEM_PROMPT = """你是旅行规划团队中的【优惠收集专家】。你的唯一任务：收集目的地城市相关的折扣与优惠规则。

规则：
1. 用户会给你：目的地城市名
2. 调用工具 collect_discount_rules(city) 获取确定性折扣规则（学生/老年/儿童/军人折扣、旅游年卡、平台通用优惠）
3. 只能使用工具返回的规则；不要编造、不要添加工具没有的信息
4. 最终输出：把工具返回的 JSON 原样返回（数组）

你只负责"收集规则"，不做任何搜索、不生成实时比价。"""


# DiscountAgent 工具（确定性本地规则，零外部依赖；单独包装避免污染 TOOL_MAP）
@lc_tool
async def collect_discount_rules(city: str) -> str:
    """收集某城市的确定性折扣规则（学生/老年/儿童/军人折扣、旅游年卡、平台通用优惠），返回 JSON 数组。"""
    rules = discount_rules_for_request({"destination": city})
    return json.dumps(rules, ensure_ascii=False)


DISCOUNT_TOOLS = [collect_discount_rules]


PLANNER_SYSTEM_PROMPT = get_prompt("planner", "zh-CN")


CRITIC_SYSTEM_PROMPT = get_prompt("critic", "zh-CN")


# ═══════════════════════════════════════════════════════════
#  辅助
# ═══════════════════════════════════════════════════════════
def _extract_json(text: str) -> dict | list | None:
    """从 LLM 输出中提取第一个 JSON 对象/数组（容忍代码块与杂质）。"""
    if not text:
        return None
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end < start:
        start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None


def _request_locale(request: dict[str, Any] | None) -> str:
    """从请求快照取输出语种（语言信号已随 request_data 快照落库）。"""
    return normalize_locale((request or {}).get("language"))


def _validation_feedback(exc: Exception, locale: str = "zh-CN") -> str:
    """把 Pydantic ValidationError 转成给 LLM 的简短纠错提示。"""
    errors = getattr(exc, "errors", list)()
    lines = []
    for e in errors[:6]:
        loc = ".".join(str(x) for x in e.get("loc", []))
        lines.append(f"- {loc}: {e.get('msg', 'invalid')}")
    return t(locale, "agent.ctx.validation_feedback") + "\n" + "\n".join(lines)


def _questions_text(request: dict[str, Any]) -> str:
    """把主动提问 Q&A 组装成给 Planner/Critic 的补充上下文。

    仅保留用户实际回答过的问题（answer 非空）；未回答的不注入，
    避免无意义占位污染 LLM 上下文。无回答时返回空串。
    """
    locale = _request_locale(request)
    questions = request.get("questions") or []
    answered = [
        q for q in questions
        if isinstance(q, dict) and (q.get("answer") or "").strip()
    ]
    if not answered:
        return ""
    lines = [t(locale, "agent.ctx.qa_block")]
    for i, q in enumerate(answered, start=1):
        q_text = (q.get("question") or "").strip() or t(locale, "agent.ctx.qa_fallback_question", i=i)
        ans = (q.get("answer") or "").strip()
        lines.append(f"{i}. {q_text}：{ans}")
    return "\n".join(lines)


def _pace_constraint(pace: str | None, locale: str = "zh-CN") -> str:
    """节奏档 → 确定性排程约束（task-pacing-leisure 结构化排程约束）。

    与 TimeGate 的过饱和阈值同口径（MAX_STOPS_PER_DAY=5 / 480 分钟），
    让 LLM 的排程倾向与确定性校验一致，避免「LLM 排 6 个站 → TimeGate 报警 →
    PlanB 又把它挪松」的来回拉锯。未知档返回空串（不注入噪音）。
    """
    if pace == "compact":
        return t(locale, "agent.ctx.pace.compact")
    if pace == "relaxed":
        return t(locale, "agent.ctx.pace.relaxed")
    return ""  # balanced / 未指定 → 不注入（默认由 LLM 权衡）


def _profile_text(request: dict[str, Any]) -> str:
    """把跨会话用户画像摘要（create_task 时注入的 profile_text）组装成补充上下文。

    画像来自用户历史偏好（traveler_type/pace/budget_tier/favorite_cities 等），
    规划时优先尊重；与本次请求冲突时以本次请求为准。无画像返回空串。
    """
    locale = _request_locale(request)
    profile = request.get("profile_text") or ""
    if not isinstance(profile, str) or not profile.strip():
        return ""
    return t(locale, "agent.ctx.profile_block") + "\n" + profile.strip()


def _trip_type_hint(trip_type: str, locale: str = "zh-CN") -> str:
    """出行性质 → 规划约束提示（确定性规则，仅指导 LLM 侧重点，不硬编码站点）。

    未知/自定义性质时给出通用基调，避免误导 LLM。
    """
    prefix = "agent.ctx.triptype."
    hints = {
        "商务出差": prefix + "business",
        "亲子出游": prefix + "family",
        "蜜月度假": prefix + "honeymoon",
        "探亲访友": prefix + "visiting",
    }
    key = hints.get(trip_type, prefix + "default")
    return t(locale, key)


def _collect_list_output(state: dict[str, Any]) -> dict[str, Any] | None:
    """（列表输出型 Agent 共用）从消息历史取出工具结果并解析为统一 POI 列表。"""
    # agent 内部已把 ToolMessage 写入 messages；取最后一个工具结果
    for msg in reversed(state.get("messages", [])):
        if getattr(msg, "type", "") == "tool":
            try:
                raw = json.loads(msg.content)
            except (json.JSONDecodeError, TypeError):
                return None
            # 兼容两种形态：{results: [...]} 或直接数组
            items = raw.get("results") if isinstance(raw, dict) else raw
            if isinstance(items, list):
                return {"pois": items, "raw": raw}
    return None


def _normalize_hotels(hotels: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把 HotelAgent 采集的原始 POI 规范化为 plan.hotels 统一结构。

    保留 name/坐标/description 等核心字段，丢弃 LLM 无关元数据；
    estimated_cost 由编排层工具用「城市基准价×档位倍率」代码估算（见
    budget_service.estimate_hotel_cost），前端展示时标注「参考价，以实际询价为准」。
    """
    out: list[dict[str, Any]] = []
    for h in hotels or []:
        if not isinstance(h, dict) or not h.get("name"):
            continue
        out.append(
            {
                "name": h.get("name", ""),
                "type": "hotel",
                "lat": h.get("lat"),
                "lng": h.get("lng"),
                "estimated_cost": float(h.get("estimated_cost") or 0),
                "description": (h.get("description") or "")[:500],
                "address": (h.get("address") or h.get("display_name") or "")[:500],
                "source": h.get("source"),
                "source_url": h.get("source_url"),
                "rating": h.get("rating"),
            }
        )
    return out


# ═══════════════════════════════════════════════════════════
#  AttractionSearchAgent —— 景点搜索专家
# ═══════════════════════════════════════════════════════════
async def attraction_agent(
    city: str,
    preferences: list[str],
    *,
    request: dict[str, Any] | None = None,
    provider: str = "auto",
    max_iterations: int | None = None,
) -> dict[str, Any]:
    """偏好 → 关键词 → search_attractions → POI 列表。

    返回 {"status", "pois": [...]}；失败时 {"status": "failed", "error": ...}。
    request: 可选；传入完整规划请求，把其中的主动提问 Q&A 并入搜索上下文。
    max_iterations: 单次执行允许的工具调用上限（默认 settings.AGENT_MAX_ITERATIONS）。
    """

    async def _node(state: dict[str, Any]) -> dict[str, Any]:
        prov = get_provider(state.get("provider", "auto"))
        locale = normalize_locale(state.get("locale"))
        messages = [SystemMessage(content=get_prompt("attraction", locale))]
        messages.append(
            HumanMessage(
                content=(
                    f"{t(locale, 'agent.ctx.city', value=state['city'])}\n"
                    f"{t(locale, 'agent.ctx.pref', value=', '.join(state.get('preferences') or []) or t(locale, 'agent.ctx.none'))}\n"
                    f"{_questions_text(state.get('request') or {})}\n"
                    f"{_profile_text(state.get('request') or {})}\n"
                    f"{t(locale, 'agent.ctx.choose_keywords_attr')}"
                )
            )
        )
        response = await invoke_with_resilience(prov, messages, tools=ATTRACTION_TOOLS)
        tool_calls = getattr(response, "tool_calls", None) or []
        if not tool_calls:
            # 没走工具：直接解析内容中的 JSON
            parsed = _extract_json(str(getattr(response, "content", "")))
            if isinstance(parsed, list):
                return {"messages": [response], "pois": parsed, "status": "completed"}
            return {"messages": [response], "status": "failed", "error": "Agent 未调用搜索工具"}
        # 执行工具并回填 Observation（上限由 max_iterations 约束，防异常多调用）
        tool_calls = tool_calls[: max_iterations if max_iterations is not None else settings.AGENT_MAX_ITERATIONS]
        tool_msgs = []
        for tc in tool_calls:
            fn = TOOL_MAP.get(tc.get("name") or "")
            if fn is None:
                return {"messages": [response], "status": "failed", "error": f"未知工具 {tc.get('name')}"}
            try:
                result = await fn.ainvoke(tc.get("args") or {})
            except Exception as exc:  # noqa: BLE001
                result = f'{{"error": "{exc}"}}'
            tool_msgs.append(
                ToolMessage(
                    content=result if isinstance(result, str) else json.dumps(result, ensure_ascii=False),
                    tool_call_id=tc.get("id") or "call-attr",
                    name=tc["name"],
                )
            )
        # 最后一条消息是 ToolMessage：从中取 POI 列表（与 tools_node 一致）
        state["messages"] = [*state.get("messages", []), response, *tool_msgs]
        out = _collect_list_output(state)
        if out is None:
            return {"messages": state["messages"], "status": "failed", "error": "无法从工具结果解析 POI"}
        return {"messages": state["messages"], "status": "completed", "pois": out["pois"]}

    state: dict[str, Any] = {
        "city": city, "preferences": preferences, "provider": provider,
        "request": request, "locale": _request_locale(request), "messages": [],
    }
    try:
        result = await _node(state)
        if result.get("status") != "completed":
            return {"status": "failed", "error": result.get("error", t(_request_locale(request), "agent.ctx.attraction_search_failed")), "pois": []}
        # 校验 POI 是否含 name
        pois = [p for p in result.get("pois", []) if p.get("name")]
        return {"status": "completed", "pois": pois}
    except Exception as exc:  # noqa: BLE001 — 汇总为失败
        logger.warning("AttractionAgent 失败 city=%s err=%s", city, exc)
        return {"status": "failed", "error": str(exc), "pois": []}


# ═══════════════════════════════════════════════════════════
#  WeatherQueryAgent —— 天气查询专家（确定性路径，不走 LLM）
# ═══════════════════════════════════════════════════════════
async def weather_agent(city: str, *, days: int = 3) -> dict[str, Any]:
    """城市名 → query_weather → 天气预报。

    纯工具调用（无 LLM）：任务单一、几乎不会出错、零 token 成本。
    """
    try:
        result = await agent_tools.query_weather(city, days=days)
        return {"status": "completed", "weather": result}
    except Exception as exc:  # noqa: BLE001
        logger.warning("WeatherAgent 失败 city=%s err=%s", city, exc)
        return {"status": "failed", "error": str(exc), "weather": None}


# ═══════════════════════════════════════════════════════════
#  HotelAgent —— 酒店推荐专家
# ═══════════════════════════════════════════════════════════
async def hotel_agent(
    city: str,
    accommodation: list[str] | None = None,
    *,
    request: dict[str, Any] | None = None,
    provider: str = "auto",
    max_iterations: int | None = None,
) -> dict[str, Any]:
    """住宿需求 → 关键词 → search_hotels → 酒店 POI 列表。

    request: 可选；传入完整规划请求，把其中的主动提问 Q&A 并入搜索上下文。
    max_iterations: 单次执行允许的工具调用上限（默认 settings.AGENT_MAX_ITERATIONS）。
    """
    accommodation = accommodation or []

    async def _node(state: dict[str, Any]) -> dict[str, Any]:
        prov = get_provider(state.get("provider", "auto"))
        locale = normalize_locale(state.get("locale"))
        messages = [SystemMessage(content=get_prompt("hotel", locale))]
        messages.append(
            HumanMessage(
                content=(
                    f"{t(locale, 'agent.ctx.city', value=state['city'])}\n"
                    f"{t(locale, 'agent.ctx.accommodation', value=', '.join(state.get('accommodation') or []) or t(locale, 'agent.ctx.stay_no_pref'))}\n"
                    f"{_questions_text(state.get('request') or {})}\n"
                    f"{_profile_text(state.get('request') or {})}\n"
                    f"{t(locale, 'agent.ctx.choose_keywords_hotel')}"
                )
            )
        )
        response = await invoke_with_resilience(prov, messages, tools=HOTEL_TOOLS)
        tool_calls = getattr(response, "tool_calls", None) or []
        if not tool_calls:
            parsed = _extract_json(str(getattr(response, "content", "")))
            if isinstance(parsed, list):
                return {"messages": [response], "pois": parsed, "status": "completed"}
            return {"messages": [response], "status": "failed", "error": "Agent 未调用搜索工具"}
        # 执行工具并回填 Observation（上限由 max_iterations 约束，防异常多调用）
        tool_calls = tool_calls[: max_iterations if max_iterations is not None else settings.AGENT_MAX_ITERATIONS]
        tool_msgs = []
        for tc in tool_calls:
            fn = TOOL_MAP.get(tc.get("name") or "")
            if fn is None:
                return {"messages": [response], "status": "failed", "error": f"未知工具 {tc.get('name')}"}
            try:
                result = await fn.ainvoke(tc.get("args") or {})
            except Exception as exc:  # noqa: BLE001
                result = f'{{"error": "{exc}"}}'
            tool_msgs.append(
                ToolMessage(
                    content=result if isinstance(result, str) else json.dumps(result, ensure_ascii=False),
                    tool_call_id=tc.get("id") or "call-hotel",
                    name=tc["name"],
                )
            )
        state["messages"] = [*state.get("messages", []), response, *tool_msgs]
        out = _collect_list_output(state)
        if out is None:
            return {"messages": state["messages"], "status": "failed", "error": "无法从工具结果解析酒店"}
        return {"messages": state["messages"], "status": "completed", "pois": out["pois"]}

    state: dict[str, Any] = {
        "city": city, "accommodation": accommodation, "provider": provider,
        "request": request, "locale": _request_locale(request), "messages": [],
    }
    try:
        result = await _node(state)
        if result.get("status") != "completed":
            return {"status": "failed", "error": result.get("error", t(_request_locale(request), "agent.ctx.hotel_search_failed")), "pois": []}
        pois = [p for p in result.get("pois", []) if p.get("name")]
        return {"status": "completed", "pois": pois}
    except Exception as exc:  # noqa: BLE001
        logger.warning("HotelAgent 失败 city=%s err=%s", city, exc)
        return {"status": "failed", "error": str(exc), "pois": []}


# ═══════════════════════════════════════════════════════════
#  FoodAgent —— 餐饮搜索专家（口味/菜系偏好 → 高德美食 POI）
# ═══════════════════════════════════════════════════════════
async def food_agent(
    city: str,
    food_preferences: list[str] | None = None,
    *,
    request: dict[str, Any] | None = None,
    provider: str = "auto",
    max_iterations: int | None = None,
) -> dict[str, Any]:
    """口味/菜系偏好 → 关键词 → search_foods → 餐厅 POI 列表。

    request: 可选；传入完整规划请求，把其中的主动提问 Q&A 与画像并入搜索上下文。
    max_iterations: 单次执行允许的工具调用上限（默认 settings.AGENT_MAX_ITERATIONS）。
    """
    food_preferences = food_preferences or []

    async def _node(state: dict[str, Any]) -> dict[str, Any]:
        prov = get_provider(state.get("provider", "auto"))
        locale = normalize_locale(state.get("locale"))
        messages = [SystemMessage(content=get_prompt("food", locale))]
        messages.append(
            HumanMessage(
                content=(
                    f"{t(locale, 'agent.ctx.city', value=state['city'])}\n"
                    f"{t(locale, 'agent.ctx.taste', value=', '.join(state.get('food_preferences') or []) or t(locale, 'agent.ctx.none'))}\n"
                    f"{_questions_text(state.get('request') or {})}\n"
                    f"{_profile_text(state.get('request') or {})}\n"
                    f"{t(locale, 'agent.ctx.choose_keywords_food')}"
                )
            )
        )
        response = await invoke_with_resilience(prov, messages, tools=FOOD_TOOLS)
        tool_calls = getattr(response, "tool_calls", None) or []
        if not tool_calls:
            parsed = _extract_json(str(getattr(response, "content", "")))
            if isinstance(parsed, list):
                return {"messages": [response], "pois": parsed, "status": "completed"}
            return {"messages": [response], "status": "failed", "error": "Agent 未调用搜索工具"}
        # 执行工具并回填 Observation（上限由 max_iterations 约束，防异常多调用）
        tool_calls = tool_calls[: max_iterations if max_iterations is not None else settings.AGENT_MAX_ITERATIONS]
        tool_msgs = []
        for tc in tool_calls:
            fn = TOOL_MAP.get(tc.get("name") or "")
            if fn is None:
                return {"messages": [response], "status": "failed", "error": f"未知工具 {tc.get('name')}"}
            try:
                result = await fn.ainvoke(tc.get("args") or {})
            except Exception as exc:  # noqa: BLE001
                result = f'{{"error": "{exc}"}}'
            tool_msgs.append(
                ToolMessage(
                    content=result if isinstance(result, str) else json.dumps(result, ensure_ascii=False),
                    tool_call_id=tc.get("id") or "call-food",
                    name=tc["name"],
                )
            )
        state["messages"] = [*state.get("messages", []), response, *tool_msgs]
        out = _collect_list_output(state)
        if out is None:
            return {"messages": state["messages"], "status": "failed", "error": "无法从工具结果解析餐厅"}
        return {"messages": state["messages"], "status": "completed", "pois": out["pois"]}

    state: dict[str, Any] = {
        "city": city, "food_preferences": food_preferences, "provider": provider,
        "request": request, "locale": _request_locale(request), "messages": [],
    }
    try:
        result = await _node(state)
        if result.get("status") != "completed":
            return {"status": "failed", "error": result.get("error", t(_request_locale(request), "agent.ctx.food_search_failed")), "pois": []}
        pois = [p for p in result.get("pois", []) if p.get("name")]
        return {"status": "completed", "pois": pois}
    except Exception as exc:  # noqa: BLE001
        logger.warning("FoodAgent 失败 city=%s err=%s", city, exc)
        return {"status": "failed", "error": str(exc), "pois": []}


# ═══════════════════════════════════════════════════════════
#  TransportAgent —— 大交通专家（出发地 → 目的地）
# ═══════════════════════════════════════════════════════════
async def transport_agent(
    departure: str | None,
    destination: str,
    *,
    date: str | None = None,
    provider: str = "auto",
    max_iterations: int | None = None,
    locale: str = "zh-CN",
) -> dict[str, Any]:
    """出发地 → 目的地 的大交通方案采集。

    无出发地（用户未提供）→ 直接降级返回（status=skipped），不阻塞；
    否则调用 search_transport 获取真实方案，输出 plan.transport 结构。
    绝不编造价格：无可信来源的条目不返回（由工具层硬闸门保证）。
    """
    locale = normalize_locale(locale)
    if not departure or not departure.strip():
        return {"status": "skipped", "transport": None, "error": t(locale, "agent.ctx.no_departure")}

    async def _node(state: dict[str, Any]) -> dict[str, Any]:
        prov = get_provider(state.get("provider", "auto"))
        locale = normalize_locale(state.get("locale"))
        messages: list[Any] = [SystemMessage(content=get_prompt("transport", locale))]
        messages.append(
            HumanMessage(
                content=(
                    f"{t(locale, 'agent.ctx.departure_short', value=state['departure'])}\n"
                    f"{t(locale, 'agent.ctx.destination_short', value=state['destination'])}\n"
                    f"{t(locale, 'agent.ctx.date_short', value=state.get('date') or t(locale, 'agent.ctx.date_unspecified'))}\n"
                    f"{t(locale, 'agent.ctx.call_transport')}"
                )
            )
        )
        response = await invoke_with_resilience(prov, messages, tools=TRANSPORT_TOOLS)
        tool_calls = getattr(response, "tool_calls", None) or []
        if not tool_calls:
            parsed = _extract_json(str(getattr(response, "content", "")))
            if isinstance(parsed, dict) and parsed.get("options"):
                return {"messages": [response], "status": "completed", "transport": parsed}
            return {"messages": [response], "status": "failed", "error": t(locale, "agent.ctx.agent_no_transport_tool")}
        tool_calls = tool_calls[: max_iterations if max_iterations is not None else settings.AGENT_MAX_ITERATIONS]
        tool_msgs = []
        for tc in tool_calls:
            fn = TOOL_MAP.get(tc.get("name") or "")
            if fn is None:
                return {"messages": [response], "status": "failed", "error": t(locale, "agent.ctx.unknown_tool", name=tc.get("name"))}
            try:
                result = await fn.ainvoke(tc.get("args") or {})
            except Exception as exc:  # noqa: BLE001
                result = f'{{"error": "{exc}"}}'
            tool_msgs.append(
                ToolMessage(
                    content=result if isinstance(result, str) else json.dumps(result, ensure_ascii=False),
                    tool_call_id=tc.get("id") or "call-transport",
                    name=tc["name"],
                )
            )
        state["messages"] = [*state.get("messages", []), response, *tool_msgs]
        # 从最后一个 ToolMessage 提取 transport 结构
        transport: dict[str, Any] | None = None
        for msg in reversed(state["messages"]):
            if getattr(msg, "type", "") == "tool":
                try:
                    raw = json.loads(msg.content)
                except (json.JSONDecodeError, TypeError):
                    continue
                if isinstance(raw, dict) and raw.get("options") is not None:
                    transport = {
                        "from": raw.get("from") or state["departure"],
                        "to": raw.get("to") or state["destination"],
                        "options": raw.get("options") or [],
                        "count": len(raw.get("options") or []),
                        "status": raw.get("status", "completed"),
                        "note": raw.get("note"),
                    }
                    break
        if transport is None:
            return {"messages": state["messages"], "status": "failed", "error": t(locale, "agent.ctx.transport_parse_failed")}
        return {"messages": state["messages"], "status": "completed", "transport": transport}

    state: dict[str, Any] = {
        "departure": departure.strip(), "destination": destination,
        "date": date, "provider": provider, "locale": locale, "messages": [],
    }
    try:
        result = await _node(state)
        if result.get("status") != "completed":
            return {"status": "failed", "error": result.get("error", t(locale, "agent.ctx.transport_query_failed")), "transport": None}
        # 硬闸门：过滤掉缺 source_url / confidence<0.5 的条目（不编造）
        options = [
            o for o in (result.get("transport") or {}).get("options", [])
            if isinstance(o, dict) and o.get("source_url") and float(o.get("confidence", 0)) >= 0.5
        ]
        transport = result.get("transport") or {}
        transport["options"] = options
        transport["count"] = len(options)
        return {"status": "completed", "transport": transport}
    except Exception as exc:  # noqa: BLE001
        logger.warning("TransportAgent 失败 %s→%s err=%s", departure, destination, exc)
        return {"status": "failed", "error": str(exc), "transport": None}


# ═══════════════════════════════════════════════════════════
#  DiscountCollectorAgent —— 优惠规则收集专家（确定性本地规则）
# ═══════════════════════════════════════════════════════════
async def discount_agent(
    city: str,
    *,
    provider: str = "auto",
    max_iterations: int | None = None,
) -> dict[str, Any]:
    """目的地 → 确定性折扣规则列表（零外部依赖、零幻觉）。

    输出与 PlanSchema.discount_rules 兼容：city_discount_rules 的结果原样。
    失败（几乎不可能——纯本地调用）降级为空列表，不阻断主流程。
    """
    try:
        rules = discount_rules_for_request({"destination": city})
        return {"status": "completed", "rules": rules}
    except Exception as exc:  # noqa: BLE001
        logger.warning("DiscountAgent 失败 city=%s err=%s", city, exc)
        return {"status": "failed", "error": str(exc), "rules": []}


# ═══════════════════════════════════════════════════════════
#  PlannerAgent —— 行程规划专家（无工具，强校验 + 自纠正）
# ═══════════════════════════════════════════════════════════
async def planner_agent(
    request: dict[str, Any],
    materials: dict[str, Any],
    *,
    provider: str = "auto",
    max_corrections: int = 3,
    review_feedback: str | None = None,
) -> dict[str, Any]:
    """整合所有材料，输出最终行程 JSON。

    materials: {"attractions": [...], "hotels": [...], "foods": [...], "weather": {...}}
    review_feedback: 可选；TravelCriticAgent 的修改反馈（Evaluator-Optimizer 第二轮起传入），
                     为空表示首次生成。
    """
    prov = get_provider(provider)
    locale = _request_locale(request)
    messages: list[Any] = [SystemMessage(content=get_prompt("planner", locale))]
    messages.append(HumanMessage(content=_planner_user_text(request, materials, locale=locale)))
    if review_feedback:
        messages.append(SystemMessage(content=review_feedback))

    corrections = 0
    last_error: str | None = None
    for _ in range(max_corrections + 1):
        response = await invoke_with_resilience(prov, messages)
        content = str(getattr(response, "content", ""))
        final = _extract_json(content)
        if not isinstance(final, dict):
            corrections += 1
            last_error = "未找到合法 JSON"
            messages.append(SystemMessage(content=t(locale, "agent.ctx.msg_no_json_plan")))
            continue
        try:
            clean = validate_plan(final)
            return {"status": "completed", "plan": clean, "corrections": corrections}
        except Exception as exc:  # noqa: BLE001 — Pydantic ValidationError
            corrections += 1
            last_error = str(exc)
            logger.info("Planner 校验失败 (correction=%d): %s", corrections, exc)
            messages.append(SystemMessage(content=_validation_feedback(exc, locale)))
    return {"status": "failed", "error": f"Planner 多次校验失败: {last_error}", "plan": None}


def _planner_user_text(request: dict[str, Any], materials: dict[str, Any], *, locale: str = "zh-CN") -> str:
    """把用户需求 + 团队材料组装成给 Planner 的完整上下文。

    注意：规划往返期间的往返提示（评审反馈）由外层 caller 负责拼进消息，
    本函数只负责"第一版"的上下文（不含评审历史）。
    """
    locale = normalize_locale(locale)
    lines: list[str] = []
    lines.append(t(locale, "agent.ctx.user_request"))
    departure = request.get("departure") or ""
    dep_text = t(locale, "agent.ctx.departure", value=departure) if departure else ""
    # 出行性质（trip_type）：影响节奏/住宿/景点取舍；无则按默认休闲理解
    trip_type = (request.get("trip_type") or "").strip()
    tt_text = (
        t(locale, "agent.ctx.trip_type", value=trip_type) if trip_type
        else t(locale, "agent.ctx.trip_type", value=t(locale, "agent.ctx.trip_type.leisure"))
    )
    budget = request.get("budget")
    budget_text = (
        t(locale, "agent.ctx.budget", value=f"{budget} {t(locale, 'agent.ctx.currency.yuan')}")
        if budget is not None else t(locale, "agent.ctx.budget", value=t(locale, "agent.ctx.budget.unspecified"))
    )
    lines.append(
        f"{dep_text}{t(locale, 'agent.ctx.destination_short', value=request.get('destination', ''))}；"
        f"{t(locale, 'agent.ctx.dates', start=request.get('start_date', ''), end=request.get('end_date', ''))}；"
        f"{t(locale, 'agent.ctx.travelers', value=request.get('travelers', 1))}；{budget_text}；"
        f"{tt_text}{t(locale, 'agent.ctx.preferences', value=', '.join(request.get('preferences') or []) or t(locale, 'agent.ctx.none'))}"
    )
    # 出行性质 → 规划约束（仅在有明确性质时追加；让 LLM 更易遵循）
    if trip_type:
        hint = _trip_type_hint(trip_type, locale)
        lines.append(f"{t(locale, 'agent.ctx.trip_type_constraint')}{hint}")

    # 节奏档 → 确定性排程约束（与 TimeGate 同口径；relaxed/compact 才注入）
    pace = (request.get("pace") or "").strip() or None
    pace_text = _pace_constraint(pace, locale)
    if pace_text:
        lines.append(f"{t(locale, 'agent.ctx.pace_constraint')}{pace_text}")

    # 主动提问 Q&A（需求澄清）：有回答才注入，未回答的问题忽略
    qa_text = _questions_text(request)
    if qa_text:
        lines.append(f"\n{qa_text}")

    # 跨会话用户画像（历史偏好记忆）：有画像才注入，规划时优先尊重
    profile_text = _profile_text(request)
    if profile_text:
        lines.append(f"\n{profile_text}")

    # 采集失败的源：明确告知 Planner，让它仍然能编排（部分失败 → 优雅降级）
    failed_sources = materials.get("failed_sources") or []
    if failed_sources:
        lines.append("\n" + t(locale, "agent.ctx.collect_warning"))
        lines.append("、".join(failed_sources))

    attractions = materials.get("attractions") or []
    lines.append(f"\n{t(locale, 'agent.ctx.attraction_list', n=len(attractions))}")
    if attractions:
        lines.append(json.dumps(attractions, ensure_ascii=False)[:4000])
    else:
        lines.append(t(locale, "agent.ctx.attraction_empty"))

    weather = materials.get("weather") or {}
    lines.append("\n" + t(locale, "agent.ctx.weather_report"))
    lines.append(json.dumps(weather, ensure_ascii=False)[:1500])

    hotels = materials.get("hotels") or []
    lines.append(f"\n{t(locale, 'agent.ctx.hotel_list', n=len(hotels))}")
    if hotels:
        lines.append(json.dumps(hotels, ensure_ascii=False)[:4000])
    else:
        lines.append(t(locale, "agent.ctx.hotel_empty"))

    foods = materials.get("foods") or []
    if foods:
        lines.append(f"\n{t(locale, 'agent.ctx.restaurant_list', n=len(foods))}")
        lines.append(json.dumps(foods, ensure_ascii=False)[:4000])

    transport = materials.get("transport") or None
    if transport:
        lines.append("\n" + t(locale, "agent.ctx.transport_options"))
        lines.append(json.dumps(transport, ensure_ascii=False)[:2500])
        lines.append(t(locale, "agent.ctx.transport_hint"))

    discount_rules = materials.get("discount_rules") or []
    if discount_rules:
        lines.append(f"\n{t(locale, 'agent.ctx.discount_rules', n=len(discount_rules))}")
        lines.append(json.dumps(discount_rules, ensure_ascii=False)[:2000])

    lines.append("\n" + t(locale, "agent.ctx.integrate"))
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════
#  TravelCriticAgent —— 行程质检专家（Evaluator，无工具）
# ═══════════════════════════════════════════════════════════
# 质检通过线：score >= 80 视为通过（与 Critic prompt 内评分建议一致）
CRITIC_PASS_SCORE = 80


async def critic_agent(
    request: dict[str, Any],
    plan: dict[str, Any],
    *,
    provider: str = "auto",
    max_corrections: int = 2,
) -> dict[str, Any]:
    """审查一份行程 JSON，输出结构化质检报告。

    无工具调用（Evaluator 不修改任何东西，只评估）；输出经
    ``CritiqueSchema`` 强校验 + 有限自纠正。失败时返回降级报告
    （``{"status": "degraded", "critique": {...pass 默认通过...}}``），
    保证调用方永远能得到一份可消费的报告——质检绝不能阻断主流程。
    """
    prov = get_provider(provider)
    locale = _request_locale(request)
    messages: list[Any] = [SystemMessage(content=get_prompt("critic", locale))]
    budget_val = request.get("budget")
    budget_text = (
        f"{budget_val} {t(locale, 'agent.ctx.currency.yuan')}"
        if budget_val is not None else t(locale, "agent.ctx.budget.unspecified")
    )
    critic_req = (
        f"{t(locale, 'agent.ctx.user_request')}"
        f"{t(locale, 'agent.ctx.destination_short', value=request.get('destination', ''))}；"
        f"{t(locale, 'agent.ctx.dates', start=request.get('start_date', ''), end=request.get('end_date', ''))}；"
        f"{t(locale, 'agent.ctx.travelers', value=request.get('travelers', 1))}；"
        f"{t(locale, 'agent.ctx.budget', value=budget_text)}；"
        f"{t(locale, 'agent.ctx.preferences', value=', '.join(request.get('preferences') or []) or t(locale, 'agent.ctx.none'))}"
    )
    qa_text = _questions_text(request)
    if qa_text:
        critic_req += f"\n{qa_text}"
    pace = (request.get("pace") or "").strip() or None
    pace_text = _pace_constraint(pace, locale)
    if pace_text:
        critic_req += f"\n{t(locale, 'agent.ctx.pace_constraint')}{pace_text}"
    profile_text = _profile_text(request)
    if profile_text:
        critic_req += f"\n{profile_text}"
    messages.append(
        HumanMessage(
            content=(
                f"{critic_req}\n\n"
                f"{t(locale, 'agent.ctx.critic_under_review')}\n{json.dumps(plan, ensure_ascii=False)[:6000]}\n\n"
                f"{t(locale, 'agent.ctx.critic_review_prompt')}"
            )
        )
    )

    corrections = 0
    last_error: str | None = None
    for _ in range(max_corrections + 1):
        try:
            # 显式传 providers=[prov]：Critic 不参与自动兜底链。
            # 质检是可选优化（失败降级放行、绝不阻断），若接入兜底，
            # 主 provider 失败会切到兜底继续评审，改变「失败即降级」的契约。
            response = await invoke_with_resilience(prov, messages, providers=[prov])
        except Exception as exc:  # noqa: BLE001 — LLM 调用失败也要降级，绝不阻断主流程
            logger.warning("Critic 调用失败，降级放行: %s", exc)
            return {"status": "degraded", "critique": _pass_critique(t(locale, "agent.ctx.qa_pass_summary")), "corrections": corrections}
        content = str(getattr(response, "content", ""))
        parsed = _extract_json(content)
        if not isinstance(parsed, dict):
            corrections += 1
            last_error = "未找到合法 JSON"
            messages.append(SystemMessage(content=t(locale, "agent.ctx.msg_no_json_qa")))
            continue
        try:
            clean = validate_critique(parsed)
            # 归一化 passed：以 score 为准（>=80），避免 LLM 自相矛盾
            clean["passed"] = clean["score"] >= CRITIC_PASS_SCORE
            return {"status": "completed", "critique": clean, "corrections": corrections}
        except Exception as exc:  # noqa: BLE001 — Pydantic ValidationError
            corrections += 1
            last_error = str(exc)
            logger.info("Critic 校验失败 (correction=%d): %s", corrections, exc)
            messages.append(SystemMessage(content=_validation_feedback(exc, locale)))

    logger.warning("Critic 多次校验失败，降级放行: %s", last_error)
    return {"status": "degraded", "critique": _pass_critique(t(locale, "agent.ctx.qa_report_failed")), "corrections": corrections}


def _pass_critique(summary: str) -> dict[str, Any]:
    """构造一份「通过」的默认质检报告（用于 Critic 降级）。"""
    return {
        "score": CRITIC_PASS_SCORE,
        "passed": True,
        "issues": [],
        "summary": summary,
    }


# ═══════════════════════════════════════════════════════════
#  ReviseCriticAgent —— 修订复核质检专家（task-revise-qa-loop 新增）
# ═══════════════════════════════════════════════════════════
# 与 TravelCriticAgent 同一 CritiqueSchema 契约，但语境是「修订后的行程」：
# 审查重点 = 本次修改是否忠实满足用户请求 + 是否引入新的业务问题。
# 未通过且问题可精确修复时附带 fix（CriticFixSchema），修订闭环把它转成
# 可执行 diff 应用后继续下一轮复审（Evaluator-Optimizer 循环）。
REVISE_CRITIC_SYSTEM_PROMPT = get_prompt("revise_critic", "zh-CN")


async def revise_critic_agent(
    request: dict[str, Any],
    plan: dict[str, Any],
    *,
    provider: str = "auto",
    max_corrections: int = 2,
) -> dict[str, Any]:
    """复核一次修订后的行程，输出结构化质检报告（可带精确 fix）。

    与 ``critic_agent`` 同契约（CritiqueSchema 强校验 + 失败降级放行），
    但请求语境包含「用户本次修订请求 + 已执行修订摘要」，让质检能判断
    「修订是否忠实满足用户意图」。调用方（revise_service 复审闭环）承诺
    永远得到可消费报告——质检绝不阻断已落库的合法修订。
    """
    prov = get_provider(provider)
    locale = _request_locale(request)
    messages: list[Any] = [SystemMessage(content=get_prompt("revise_critic", locale))]
    budget_val = request.get("budget")
    budget_text = (
        f"{budget_val} {t(locale, 'agent.ctx.currency.yuan')}"
        if budget_val is not None else t(locale, "agent.ctx.budget.unspecified")
    )
    critic_req = (
        f"{t(locale, 'agent.ctx.user_request')}"
        f"{t(locale, 'agent.ctx.destination_short', value=request.get('destination', ''))}；"
        f"{t(locale, 'agent.ctx.travelers', value=request.get('travelers', 1))}；"
        f"{t(locale, 'agent.ctx.budget', value=budget_text)}；"
        f"{t(locale, 'agent.ctx.preferences', value=', '.join(request.get('preferences') or []) or t(locale, 'agent.ctx.none'))}"
    )
    if request.get("message"):
        critic_req += f"\n{t(locale, 'agent.ctx.critic_modify_request')}{request['message']}"
    if request.get("revise_summary"):
        critic_req += f"\n{t(locale, 'agent.ctx.critic_summary_done')}{request['revise_summary']}"
    messages.append(
        HumanMessage(
            content=(
                f"{critic_req}\n\n"
                f"{t(locale, 'agent.ctx.critic_revised_json')}\n{json.dumps(plan, ensure_ascii=False)[:6000]}\n\n"
                f"{t(locale, 'agent.ctx.critic_review_prompt')}"
            )
        )
    )

    corrections = 0
    last_error: str | None = None
    for _ in range(max_corrections + 1):
        try:
            # 显式传 providers=[prov]：与 critic_agent 一致，不参与自动兜底链
            response = await invoke_with_resilience(prov, messages, providers=[prov])
        except Exception as exc:  # noqa: BLE001 — 质检失败降级放行，绝不阻断主流程
            logger.warning("ReviseCritic 调用失败，降级放行: %s", exc)
            return {
                "status": "degraded",
                "critique": _pass_critique(t(locale, "agent.ctx.qa_revise_call_failed")),
                "corrections": corrections,
            }
        content = str(getattr(response, "content", ""))
        parsed = _extract_json(content)
        if not isinstance(parsed, dict):
            corrections += 1
            last_error = "未找到合法 JSON"
            messages.append(SystemMessage(content=t(locale, "agent.ctx.msg_no_json_qa")))
            continue
        try:
            clean = validate_critique(parsed)
            # 归一化 passed：以 score 为准（>=80），避免 LLM 自相矛盾
            clean["passed"] = clean["score"] >= CRITIC_PASS_SCORE
            return {"status": "completed", "critique": clean, "corrections": corrections}
        except Exception as exc:  # noqa: BLE001 — Pydantic ValidationError
            corrections += 1
            last_error = str(exc)
            logger.info("ReviseCritic 校验失败 (correction=%d): %s", corrections, exc)
            messages.append(SystemMessage(content=_validation_feedback(exc, locale)))

    logger.warning("ReviseCritic 多次校验失败，降级放行: %s", last_error)
    return {
        "status": "degraded",
        "critique": _pass_critique(t(locale, "agent.ctx.qa_revise_report_failed")),
        "corrections": corrections,
    }


# ═══════════════════════════════════════════════════════════
#  PlanReviseAgent —— 行程修订专家（方案 B：对话改行程）
# ═══════════════════════════════════════════════════════════
REVISE_SYSTEM_PROMPT = get_prompt("revise", "zh-CN")


async def plan_revise_agent(
    request: dict[str, Any],
    plan: dict[str, Any],
    *,
    provider: str = "auto",
    max_corrections: int = 3,
) -> dict[str, Any]:
    """用户消息 + 当前行程 → 结构化变更 diff。

    输出经 ``ReviseDiff`` 强校验 + 自纠正；失败返回明确错误（调用方
    转成 4xx，不产生任何落库变更）。
    """
    from app.schemas import ReviseDiff

    prov = get_provider(provider)
    locale = _request_locale(request)
    messages: list[Any] = [SystemMessage(content=get_prompt("revise", locale))]
    budget_val = request.get("budget")
    budget_text = (
        f"{budget_val} {t(locale, 'agent.ctx.currency.yuan')}"
        if budget_val is not None else t(locale, "agent.ctx.budget.unspecified")
    )
    messages.append(
        HumanMessage(
            content=(
                f"{t(locale, 'agent.ctx.user_request')}"
                f"{t(locale, 'agent.ctx.destination_short', value=request.get('destination', ''))}；"
                f"{t(locale, 'agent.ctx.budget', value=budget_text)}\n"
                f"{t(locale, 'agent.ctx.critic_modify_request')}{request.get('message', '')}\n\n"
                f"{t(locale, 'agent.ctx.revise_current_json')}\n{json.dumps(plan, ensure_ascii=False)[:5000]}\n\n"
                f"{t(locale, 'agent.ctx.revise_prompt')}"
            )
        )
    )

    corrections = 0
    last_error: str | None = None
    for _ in range(max_corrections + 1):
        response = await invoke_with_resilience(prov, messages)
        content = str(getattr(response, "content", ""))
        parsed = _extract_json(content)
        if not isinstance(parsed, dict):
            corrections += 1
            last_error = "未找到合法 JSON"
            messages.append(SystemMessage(content=t(locale, "agent.ctx.msg_no_json_revise")))
            continue
        try:
            clean = ReviseDiff.model_validate(parsed).model_dump(mode="json")
            return {
                "status": "completed",
                "diff": clean,
                "corrections": corrections,
                "trace": [{
                    "agent": "PlanReviseAgent",
                    "action": "revise",
                    "observation": f"{len(clean.get('actions') or [])} actions · {clean.get('summary') or ''}",
                    "status": "completed",
                }],
                "provider": prov.name,
                "model": prov.model_id,
            }
        except Exception as exc:  # noqa: BLE001 — Pydantic ValidationError
            corrections += 1
            last_error = str(exc)
            logger.info("ReviseAgent 校验失败 (correction=%d): %s", corrections, exc)
            messages.append(SystemMessage(content=_validation_feedback(exc, locale)))

    return {"status": "failed", "error": f"修订指令解析多次失败: {last_error}", "diff": None}


def _critic_feedback(critique: dict[str, Any], locale: str = "zh-CN") -> str:
    """把质检报告转成给 Planner 的修改指令（只含未通过项，避免信息过载）。"""
    issues = critique.get("issues") or []
    actionable = [i for i in issues if i.get("severity") in ("critical", "warning")]
    if not actionable:
        return t(locale, "agent.ctx.review_pass")

    lines = [t(locale, "agent.ctx.critic_feedback_title")]
    for i, issue in enumerate(actionable, start=1):
        loc = f"（Day {issue.get('day_number')}）" if issue.get("day_number") else ""
        lines.append(
            f"{i}. [{issue.get('severity', 'warning')}/{issue.get('category', 'info')}]{loc} "
            f"{issue.get('message', '')}"
        )
        if issue.get("suggestion"):
            lines.append(t(locale, "agent.ctx.critic_feedback_suggestion", value=issue["suggestion"]))
    lines.append(t(locale, "agent.ctx.critic_feedback_fix"))
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════
#  编排：并行采集 → 补餐厅 → Planner 整合 → 质检评审 → 预算校准
# ═══════════════════════════════════════════════════════════
async def run_planning_agents(
    request: dict[str, Any],
    *,
    provider: str = "auto",
    max_corrections: int = 3,
    max_review_rounds: int = 2,
    max_iterations: int | None = None,
) -> dict[str, Any]:
    """多 Agent 全流程：采集 → 整合 → 质检评审 → 自驾约束 → 输出 {plan, trace, status, error, agents}。

    Evaluator-Optimizer：Planner 生成后交给 TravelCriticAgent 评审，
    未通过则带反馈重生成，最多 ``max_review_rounds`` 轮后强制定稿
    （任务有界，不会无限循环）。Critic 自身失败时降级「通过」，绝不阻断。

    自驾约束（DrivingGate）：Planner 每代输出后由确定性代码 ``check_plan_driving``
    校验站点间驾车距离/时长/折返（TripPlanner AI 差异化——经停优化、避免折返）。
    critical 问题存在且还有评审轮次 → 拒绝该站点组合并带反馈重生成；
    达最大评审轮 → 强制定稿但保留告警，并把 driving 报告注入 plan.driving
    （系统始终产出某种东西，从不因自驾检查而整体失败）。

    ``max_iterations``：全局 Agent 迭代上限（默认取 settings.AGENT_MAX_ITERATIONS），
    覆盖采集 agent 的工具调用次数与评审重生成轮数的合计，防止异常路径无限循环。

    trace 每步标注 agent 名，前端可展示“哪个专家在做什么”。
    """
    city = request.get("destination", "")
    prefs = request.get("preferences") or []
    locale = _request_locale(request)
    # 偏好解析：前端可能传「稳定 key」（food/nature）或「当前语言 label」；
    # 统一转成搜索关键词（语言无关契约），采集 Agent 不再依赖 UI 语言。
    pref_keywords = preference_keys_to_keywords(locale, prefs)
    trace: list[dict[str, Any]] = []
    review_history: list[dict[str, Any]] = []  # 每次评审的报告（给 Planner 作为上下文）

    # 阶段事件：任务开始 → collecting
    _fire_phase("collecting", "running")

    # 1) 六个采集 Agent 并行（request 传入后，主动提问 Q&A 会并入搜索上下文）
    #    采集 agent 内部最多调用工具一次，无 LLM 迭代循环，但通过参数显式带上限。
    #    FoodAgent 主路径（口味偏好 → search_foods）；失败由下方降级补位代码兜底。
    agent_max_iter = max_iterations if max_iterations is not None else settings.AGENT_MAX_ITERATIONS
    attraction_task = attraction_agent(city, pref_keywords, request=request, provider=provider, max_iterations=agent_max_iter)
    weather_task = weather_agent(city)
    hotel_task = hotel_agent(city, _accommodation_hints(request), request=request, provider=provider, max_iterations=agent_max_iter)
    food_task = food_agent(city, _food_hints(pref_keywords), request=request, provider=provider, max_iterations=agent_max_iter)
    transport_task = transport_agent(
        request.get("departure"), city,
        date=request.get("start_date"), provider=provider, max_iterations=agent_max_iter,
    )
    discount_task = discount_agent(city)

    a_res, w_res, h_res, food_res, t_res, d_res = await asyncio.gather(
        attraction_task, weather_task, hotel_task, food_task, transport_task, discount_task,
    )

    def _append_trace(entry: dict[str, Any]) -> None:
        """追加一条 trace 并向 WS 订阅者实时推送（推送失败不影响主流程）。"""
        trace.append(entry)
        asyncio.create_task(_emit_plan_event({"type": "trace", "trace": entry}))

    _append_trace({"agent": "AttractionSearchAgent", "action": "search_attractions",
                  "observation": t(locale, "plan.trace.collecting.attractions", city=city, n=len(a_res.get("pois", []))),
                  "status": a_res.get("status")})
    _append_trace({"agent": "WeatherQueryAgent", "action": "query_weather",
                  "observation": t(locale, "plan.trace.collecting.weather", city=city, source=w_res.get("weather", {}).get("source", "?")),
                  "status": w_res.get("status")})
    _append_trace({"agent": "HotelAgent", "action": "search_hotels",
                  "observation": t(locale, "plan.trace.collecting.hotels", city=city, n=len(h_res.get("pois", []))),
                  "status": h_res.get("status")})
    _append_trace({"agent": "FoodAgent", "action": "search_foods",
                  "observation": t(locale, "plan.trace.collecting.foods", city=city, n=len(food_res.get("pois", []))),
                  "status": food_res.get("status")})
    _append_trace({"agent": "TransportAgent", "action": "search_transport",
                  "observation": (
                      t(locale, "plan.trace.collecting.transport",
                        departure=request.get("departure") or t(locale, "plan.trace.collecting.transport.skipped"),
                        city=city, n=len((t_res.get("transport") or {}).get("options", [])))
                  ),
                  "status": t_res.get("status")})
    _append_trace({"agent": "DiscountAgent", "action": "collect_discount_rules",
                  "observation": t(locale, "plan.trace.collecting.discounts", city=city, n=len(d_res.get("rules", []))),
                  "status": d_res.get("status")})

    # 2) 餐饮：FoodAgent 主路径；失败时降级到编排层确定性补位（search_foods 直调），
    #    再失败则保留空列表（Planner 可用通用描述，绝不编造）——系统始终产出某种东西。
    foods: list[dict[str, Any]] = []
    if food_res.get("status") == "completed":
        foods = [p for p in food_res.get("pois", []) if isinstance(p, dict) and p.get("name")]
        _append_trace({"agent": "FoodAgent", "action": "search_foods",
                      "observation": t(locale, "plan.trace.collecting.foods", city=city, n=len(foods)), "status": "completed"})
    else:
        try:
            food_fb = await agent_tools.search_foods(city, query=preference_keywords(locale, "food"), limit=5)
            foods = food_fb.get("results", [])
            _append_trace({"agent": "orchestrator", "action": "search_food_fallback",
                          "observation": t(locale, "plan.trace.food.fallback", city=city, n=len(foods)),
                          "status": "completed"})
        except Exception as exc:  # noqa: BLE001
            _append_trace({"agent": "orchestrator", "action": "search_food_fallback",
                          "observation": t(locale, "plan.trace.food.fallback.fail", err=exc), "status": "failed"})
            logger.warning("餐饮搜索失败 city=%s err=%s", city, exc)

    # ── 采集完成：逐项发射中间制品（前端阶段视图实时展示候选）──
    # 轻量摘要：只保留前端 chips 需要的字段（name/type/花费/时长），避免 events 行膨胀
    attr_pois = [p for p in a_res.get("pois", []) if isinstance(p, dict) and p.get("name")]
    hotel_pois = [p for p in h_res.get("pois", []) if isinstance(p, dict) and p.get("name")]
    _fire_artifact("attractions", [
        {"name": p.get("name"), "type": p.get("type") or "attraction",
         "estimated_cost": p.get("estimated_cost"), "duration_minutes": p.get("duration_minutes")}
        for p in attr_pois[:12]
    ])
    _fire_artifact("weather", (w_res.get("weather") or {}).get("days") or [])
    _fire_artifact("hotels", [
        {"name": p.get("name"), "type": "hotel",
         "estimated_cost": p.get("estimated_cost"), "rating": p.get("rating")}
        for p in hotel_pois[:10]
    ])
    foods_art = [
        {"name": p.get("name"), "type": "food",
         "estimated_cost": p.get("estimated_cost"), "duration_minutes": p.get("duration_minutes")}
        for p in foods if isinstance(p, dict) and p.get("name")
    ]
    _fire_artifact("foods", foods_art[:10])
    transport_art = (t_res.get("transport") or {}).get("options") or []
    _fire_artifact("transport", [
        {"mode": o.get("mode"), "duration_minutes": o.get("duration_minutes"),
         "price_range": o.get("price_range"), "source": o.get("source"),
         "note": (o.get("note") or "")[:60]}
        for o in transport_art[:6] if isinstance(o, dict)
    ])
    _fire_artifact("discount_rules", (d_res.get("rules") or [])[:10])
    _fire_phase("collecting", "completed", summary=t(
        locale, "plan.phase.collecting.summary",
        a=len(attr_pois), w=len((w_res.get("weather") or {}).get("days") or []),
        h=len(hotel_pois), f=len(foods_art), t=len(transport_art), d=len(d_res.get("rules", [])),
    ))
    _fire_phase("assembling", "running")

    # 3) Planner 整合（无工具），Evaluator-Optimizer 评审循环 + 自驾 DrivingGate
    materials = {
        "attractions": a_res.get("pois", []),
        "hotels": h_res.get("pois", []),
        "foods": foods,
        "weather": (w_res.get("weather") or {}),
        "transport": (t_res.get("transport") or None),
        "discount_rules": d_res.get("rules", []),
    }
    plan: dict[str, Any] | None = None
    planner: dict[str, Any] = {"status": "failed", "error": "未执行"}  # 循环前预初始化（静态分析）
    review_rounds = 0
    driving_reports: list[dict[str, Any]] = []  # 每代自驾校验报告（给最终 plan.driving 用）

    for round_idx in range(max_review_rounds + 1):
        review_feedback = _critic_feedback(review_history[-1], locale) if review_history else None
        if round_idx > 0:
            _fire_phase("reviewing", "running")
            _fire_phase("assembling", "running")
        planner = await planner_agent(
            request, materials, provider=provider, max_corrections=max_corrections,
            review_feedback=review_feedback,
        )
        _append_trace({
            "agent": "PlannerAgent",
            "action": "integrate" if round_idx == 0 else f"revise (round {round_idx})",
            "observation": (
                f"integrate {len(materials['attractions'])} attractions / {len(materials['hotels'])} hotels / {len(foods)} restaurants"
                + ("; revised per review" if round_idx > 0 else "")
            ),
            "status": planner.get("status"),
        })
        if planner.get("status") != "completed" or planner.get("plan") is None:
            return {"plan": None, "trace": trace, "status": "failed",
                    "error": planner.get("error") or t(locale, "agent.ctx.planner_failed"), "agents": {},
                    "review_rounds": review_rounds}

        candidate = planner["plan"]

        # 预算校准前置：先以真实 stops 计算预算（覆盖 LLM 估值），再交给质检；
        # 若采集阶段有大交通参考价，则把「往返参考价」并入 by_type.transport 与总额，
        # 使 plan.budget 与详情页 budget API（compute_budget(plan_data=...)）口径一致。
        all_stops = [s for d in candidate.get("days", []) for s in d.get("stops", [])]
        candidate["budget"] = agent_tools.compute_budget(all_stops)
        from app.services.budget_service import transport_round_trip_cost

        transport_cost = transport_round_trip_cost(t_res.get("transport") if isinstance(t_res, dict) else None)
        if transport_cost is not None:
            candidate["budget"]["by_type"]["transport"] = transport_cost
            candidate["budget"]["total_estimated"] = round(
                float(candidate["budget"].get("total_estimated") or 0.0) + transport_cost, 2
            )
        candidate["hotels"] = _normalize_hotels(materials.get("hotels") or [])

        # 行程草案制品（每代都发；前端「编排阶段」实时展示天数/主题）
        _fire_artifact("draft", {
            "days": len(candidate.get("days", [])),
            "themes": [f"Day {d.get('day_number')} {d.get('theme') or ''}".strip()
                       for d in candidate.get("days", [])][:10],
            "round": round_idx + 1,
        })
        if round_idx == 0:
            _fire_phase("assembling", "completed", summary=t(locale, "plan.phase.assembling.draft", n=len(candidate.get("days", []))))

        # ── DrivingGate：自驾约束校验（确定性代码，超距/超时/折返；真实路径优先） ──
        driving = await check_plan_driving_async(candidate, locale=locale)
        driving_reports.append(driving)
        if not driving["passed"] and round_idx < max_review_rounds:
            # 拒绝该站点组合：带自驾反馈重新生成（不进 Critic，省一次评审 token）
            logger.info("自驾校验未通过 round=%d critical=%d，进入修订", round_idx + 1, driving["critical_count"])
            _append_trace({
                "agent": "DrivingGate",
                "action": "check_driving",
                "observation": (
                    t(locale, "plan.trace.driving.fail",
                      n=driving["critical_count"], summary=driving["summary"])
                ),
                "status": "failed",
            })
            review_history.append(_driving_feedback(driving, locale))  # 作为修订反馈
            review_rounds += 1
            continue

        review_rounds += 1

        # 交给 TravelCriticAgent 评审（最后一代无需再评：强制定稿）
        if round_idx >= max_review_rounds:
            plan = candidate
            _append_trace({"agent": "TravelCriticAgent", "action": "review",
                          "observation": t(locale, "plan.trace.review.max_rounds", n=max_review_rounds), "status": "completed"})
            break

        critic = await critic_agent(request, candidate, provider=provider)
        critique = critic.get("critique") or _pass_critique(t(locale, "agent.ctx.planner_review_degraded"))
        review_history.append(critique)
        n_issues = len(critique.get("issues") or [])
        # 质检评分制品：前端「AI 质检」阶段实时展示分数与问题数
        _fire_artifact("quality", {
            "score": critique.get("score"),
            "passed": bool(critique.get("passed")),
            "round": round_idx + 1,
            "max_rounds": max_review_rounds,
            "issues": critique.get("issues") or [],
        })
        if round_idx == 0:
            _fire_phase("reviewing", "completed", summary=t(locale, "plan.phase.reviewing.score", score=critique.get("score")))
        _append_trace({
            "agent": "TravelCriticAgent",
            "action": "review",
            "observation": (
                t(locale, "plan.trace.review.score",
                  score=critique.get("score"),
                  n=len([i for i in critique.get("issues") or [] if i.get("severity") in ("critical", "warning")]))
                + (f"（{critique.get('summary') or ''}）" if critique.get("summary") else "")
            ),
            "status": "completed" if critic.get("status") == "completed" else "degraded",
        })

        if critique.get("passed") or n_issues == 0 or not _has_actionable_issues(critique):
            plan = candidate
            break  # 质检通过 / 无待修改项 → 定稿

        logger.info("行程评审未通过 round=%d score=%s issues=%d，进入下一轮修订",
                    round_idx + 1, critique.get("score"), n_issues)

        # ── Critic 协作者：优先应用精确修订 diff（复用修订执行器语义）──
        # 不过审时 Critic 附带 fix（站点级动作）。编排层代码应用成功 →
        # 跳过 Planner 整段重生成（省一次大模型生成、保留其余站点细节）；
        # 应用失败（目标不存在/字段非法等）→ 回退整段重生成，绝不静默丢失。
        fix = critique.get("fix")
        if isinstance(fix, dict) and fix.get("actions"):
            applied = _apply_critic_fix(candidate, fix)
            if applied:
                review_history[-1] = {**critique, "fix_applied": True}
                plan = candidate
                _append_trace({
                    "agent": "TravelCriticAgent",
                    "action": "apply_fix",
                    "observation": (
                        t(locale, "plan.trace.review.fix_applied", n=len(fix.get("actions") or []))
                        + (f"（{fix.get('summary') or ''}）" if fix.get("summary") else "")
                    ),
                    "status": "completed",
                })
                break  # 已按 Critic 指令修正 → 定稿（不重复整段重生成）
            logger.info("Critic fix 应用失败，回退 Planner 整段重生成 (round=%d)", round_idx + 1)

    # 兜底：若循环异常退出（理论上不会），仍保留最后一代
    if plan is None:
        return {"plan": None, "trace": trace, "status": "failed",
                "error": t(locale, "plan.error.qa_loop_exit"), "agents": {}, "review_rounds": review_rounds}

    # 质检摘要注入 plan.quality（随 plan JSON 落库，前端可直接消费）
    plan["quality"] = _plan_quality(review_history, review_rounds, max_review_rounds)
    # ── 采集产物回填（task: 详情页大交通/折扣）──────────────────
    # 采集阶段的 TransportAgent / DiscountAgent 产物只出现在 materials，
    # 若不回填 plan，落库后的 plan_data.transport / .discount_rules 恒为
    # null / []（PlanSchema 默认值），详情页 TripServicing 因 options 为空
    # 直接不渲染大交通卡片。回填后前端零改动即恢复展示；预算口径依赖此数据。
    plan["transport"] = (t_res.get("transport") or {}) if isinstance(t_res, dict) else None
    plan["discount_rules"] = (d_res.get("rules") or []) if isinstance(d_res, dict) else []
    # 自驾校验报告注入 plan.driving（最终一代；前端可展示里程/时长/折返告警）
    if driving_reports:
        final_driving = driving_reports[-1]
        # 只保留最终代完整报告，历史各代摘要放进 driving_history（避免 plan 膨胀）
        plan["driving"] = {
            **{k: v for k, v in final_driving.items() if k != "legs"},
            "legs": final_driving.get("legs") or [],
            "history": [{"passed": r.get("passed"), "critical_count": r.get("critical_count"),
                         "summary": r.get("summary")} for r in driving_reports],
        }
        _append_trace({
            "agent": "DrivingGate",
            "action": "check_driving",
            "observation": (
                (t(locale, "plan.trace.driving.pass") if final_driving["passed"] else t(locale, "plan.trace.driving.warn", n=final_driving["critical_count"]))
                + t(locale, "plan.trace.driving.distance", km=final_driving["total_km"])
            ),
            "status": "completed" if final_driving["passed"] else "warning",
        })

    # 阶段收尾：assembling/reviewing 完成 → servicing（第二段） → 整体 completed
    _fire_phase("assembling", "completed", summary=t(locale, "plan.phase.assembling.final", n=len(plan.get("days", []))))
    _fire_phase("reviewing", "completed", summary=t(locale, "plan.phase.reviewing.completed"))

    # ── TimeGate：营业时间/游玩时长确定性校验（规则库，零 LLM）──
    # 与 DrivingGate 同风格：只报告，不阻断。所有 issue 为 warning（建议级），
    # 注入 plan.time_gate 供前端质检卡展示；真实营业时间以 POI 现场为准。
    from app.services.time_validation import check_plan_time_gate

    time_gate = check_plan_time_gate(plan, locale=locale)
    plan["time_gate"] = {
        **{k: v for k, v in time_gate.items() if k != "issues"},
        "issues": time_gate.get("issues") or [],
        "basis": "rule_based",
    }
    for iss in time_gate.get("issues") or []:
        plan.setdefault("warnings", []).append(
            t(locale, "plan.warning.timegate", message=iss.get("message") or "",
              extra=(t(locale, "plan.warning.timegate.sugg", suggestion=iss.get("suggestion")) if iss.get("suggestion") else ""))
        )
    _append_trace({
        "agent": "TimeGate",
        "action": "check_time",
        "observation": (
            (t(locale, "plan.trace.timegate.pass") if time_gate.get("passed") else t(locale, "plan.trace.timegate.warn", n=time_gate.get("warning_count", 0)))
            + t(locale, "plan.trace.timegate.basis")
        ),
        "status": "completed" if time_gate.get("passed") else "warning",
    })
    _fire_artifact("time_gate", {
        "passed": time_gate.get("passed"),
        "warning_count": time_gate.get("warning_count", 0),
        "issues": time_gate.get("issues") or [],
    })

    # ── 第二段 servicing：定稿后的可执行服务（市内通勤 / 入住办理 / 折扣比价）──
    # 消费已定稿 plan，与采集/规划解耦；任一失败只记 warnings，绝不阻断主流程。
    _fire_phase("servicing", "running")
    from app.services.servicing_service import run_servicing

    servicing = await run_servicing(plan, provider=provider, locale=locale)
    if servicing.get("transit"):
        plan["transit"] = servicing["transit"]
        _fire_artifact("transit", {
            "count": servicing["transit"].get("count", 0),
            "legs": servicing["transit"].get("legs", [])[:10],
        })
    if servicing.get("checkin"):
        plan["checkin"] = servicing["checkin"]
        _fire_artifact("checkin", {
            "hotel_name": servicing["checkin"].get("hotel_name"),
            "docs_required": servicing["checkin"].get("docs_required", []),
            "steps": servicing["checkin"].get("steps", [])[:8],
            "source": servicing["checkin"].get("source"),
        })
    if servicing.get("discounts"):
        plan["discounts"] = servicing["discounts"]
        _fire_artifact("discounts", {
            "count": servicing["discounts"].get("count", 0),
            "items": servicing["discounts"].get("items", [])[:10],
            "note": servicing["discounts"].get("note"),
        })
    _append_trace({
        "agent": "ServicingGate", "action": "servicing",
        "observation": (
            t(locale, "plan.trace.servicing",
              n=len((servicing.get("transit") or {}).get("legs", [])),
              checkin=(t(locale, "plan.servicing.checkin.yes") if servicing.get("checkin") else t(locale, "plan.servicing.checkin.degraded")),
              d=len((servicing.get("discounts") or {}).get("items", [])))
        ),
        "status": "completed" if not servicing.get("warnings") else "warning",
    })
    for w in servicing.get("warnings", []):
        plan.setdefault("warnings", []).append(w)
    _fire_phase("servicing", "completed", summary=t(
        locale, "plan.phase.servicing.summary",
        n=len((servicing.get("transit") or {}).get("legs", [])),
        src=servicing.get("checkin", {}).get("source", "-"),
        d=len((servicing.get("discounts") or {}).get("items", [])),
    ))
    _fire_phase("completed", "completed")

    return {
        "plan": plan,
        "trace": trace,
        "status": "completed",
        "error": None,
        "provider": get_provider(provider).name,
        "model": get_provider(provider).model_id,
        "review_rounds": review_rounds,
        "review_history": review_history,
        "agents": {
            "attractions": a_res.get("status"),
            "weather": w_res.get("status"),
            "hotels": h_res.get("status"),
            "foods": food_res.get("status"),
            "transport": t_res.get("status"),
            "discounts": d_res.get("status"),
            "planner": planner.get("status"),
        },
    }


def _has_actionable_issues(critique: dict[str, Any]) -> bool:
    """质检报告里是否有需要 Planner 修改的（critical/warning）问题。"""
    return any(i.get("severity") in ("critical", "warning") for i in (critique.get("issues") or []))


# ── Critic 协作者：精确修订 diff 应用（复用 ReviseDiff 执行器语义） ──
# 与 revise_service._apply_diff 同一套 op 契约（AI 只出指令，代码执行），
# 但操作对象是内存中的 plan dict（JSON 字段名），不是 ORM Trip：
# - replace/remove/reorder 必须命中真实存在的站点（name 或 index），否则整体失败
# - add 必须带 name / type（attraction|food|hotel），字段白名单与修订服务一致
# - 任一动作非法 → 返回 False（调用方回退 Planner 整段重生成，绝不静默丢失）
_CRITIC_FIX_FIELDS = {"name", "type", "lat", "lng", "description", "estimated_cost", "duration_minutes"}
_CRITIC_FIX_TYPES = {"attraction", "food", "hotel"}


def _apply_critic_fix(plan: dict[str, Any], fix: dict[str, Any]) -> bool:
    """把 Critic 的精确修订 diff 应用到内存 plan；成功返回 True，任一动作非法返回 False。"""
    actions = fix.get("actions") or []
    if not actions:
        return False
    days = {d.get("day_number"): d for d in plan.get("days") or []}

    # 预检（原子）：全部动作合法才执行，任一失败整体放弃
    resolved: list[tuple[dict[str, Any], dict[str, Any], int | None]] = []
    for action in actions:
        day = days.get(action.get("day_number"))
        if day is None:
            return False
        stops = day.get("stops") or []
        op = action.get("op")
        if op == "add":
            fields = action.get("fields") or {}
            if not fields.get("name") or fields.get("type") not in _CRITIC_FIX_TYPES:
                return False
            unknown = set(fields) - _CRITIC_FIX_FIELDS
            if unknown:
                return False
            idx = action.get("index")
            if idx is not None and (idx < 1 or idx > len(stops) + 1):
                return False
            resolved.append((action, day, None))
            continue
        if op not in ("replace", "remove", "reorder"):
            return False
        target = action.get("target") or {}
        idx = None
        if isinstance(target, dict):
            if target.get("name"):
                idx = next((i for i, s in enumerate(stops) if s.get("name") == target["name"]), None)
            elif target.get("index"):
                ti = int(target["index"])
                if 1 <= ti <= len(stops):
                    idx = ti - 1
        if idx is None:
            return False
        if op == "replace":
            fields = action.get("fields") or {}
            unknown = set(fields) - _CRITIC_FIX_FIELDS
            if unknown:
                return False
            new_type = fields.get("type")
            if new_type is not None and new_type not in _CRITIC_FIX_TYPES:
                return False
        if op == "reorder" and (action.get("index") or 0) < 1:
            return False
        resolved.append((action, day, idx))

    # 执行
    for action, day, idx in resolved:
        stops = day.get("stops") or []
        op = action.get("op")
        if op == "add":
            fields = dict(action.get("fields") or {})
            new_stop = {
                "name": fields.get("name"),
                "type": fields.get("type", "food"),
                "lat": fields.get("lat"),
                "lng": fields.get("lng"),
                "estimated_cost": float(fields.get("estimated_cost") or 0),
                "duration_minutes": fields.get("duration_minutes"),
                "description": fields.get("description"),
            }
            pos = action.get("index")
            if pos and 1 <= pos <= len(stops) + 1:
                stops.insert(pos - 1, new_stop)
            else:
                stops.append(new_stop)
            day["stops"] = stops
            continue
        # replace / remove / reorder：预检已保证目标存在，idx 必为 int
        assert idx is not None
        if op == "remove":
            day["stops"] = [s for i, s in enumerate(stops) if i != idx]
        elif op == "replace":
            stop = stops[idx]
            for k, v in (action.get("fields") or {}).items():
                if v is None:
                    continue
                if k == "type":
                    stop["type"] = v
                elif k == "estimated_cost":
                    stop["estimated_cost"] = float(v)
                else:
                    stop[k] = v
        elif op == "reorder":
            stop = stops.pop(idx)
            pos = min(max(action.get("index", 1) - 1, 0), len(stops))
            stops.insert(pos, stop)
            day["stops"] = stops
    return True


def _driving_feedback(driving: dict[str, Any], locale: str = "zh-CN") -> dict[str, Any]:
    """把自驾校验报告转成一条「质检报告」塞进 review_history，驱动 Planner 修订。

    只保留 critical（超距/超时，必须修改）与 warning（折返，建议修改），
    缺坐标的 logistics warning 不反馈（无法据此修订站点序列）。
    输出结构与 CritiqueSchema 兼容（score/passed/issues/summary），
    保证 _critic_feedback 无需改动即可消费。
    """
    actionable = [i for i in driving.get("issues") or []
                  if i.get("severity") in ("critical", "warning") and i.get("category") != "logistics"]
    return {
        "severity": "critical" if driving.get("critical_count", 0) > 0 else "warning",
        "score": max(0, 100 - driving.get("critical_count", 0) * 30),
        "passed": driving.get("passed", False),
        "issues": actionable,
        "summary": driving.get("summary", t(locale, "driving.summary.fail", n=driving.get("critical_count", 0))),
        "source": "DrivingGate",
    }


def _plan_quality(
    review_history: list[dict[str, Any]],
    rounds: int,
    max_rounds: int,
) -> dict[str, Any]:
    """把评审过程归纳成给前端展示的 plan.quality 摘要。

    结构：
    {
      "score": 92,          # 最终评分（最后一次评审；无评审为 None）
      "passed": true,       # 是否最终通过
      "rounds": 2,          # 实际评审轮数
      "max_rounds": 2,      # 配置的最大评审轮数
      "finalized": false,   # 是否因达上限强制定稿
      "issues": [...],      # 最后一次评审的问题列表
      "summary": "..."      # 最后一次评审总结
    }
    """
    base = {
        "score": None,
        "passed": True,
        "rounds": 0,
        "max_rounds": max_rounds,
        "finalized": False,
        "issues": [],
        "summary": None,
    }
    if not review_history:
        return base
    last = review_history[-1]
    base.update(
        {
            "score": last.get("score"),
            "passed": bool(last.get("passed", True)),
            "rounds": len(review_history),
            # 达上限仍不通过 → 强制定稿
            "finalized": bool(len(review_history) >= max_rounds and not last.get("passed", True)),
            "issues": last.get("issues") or [],
            "summary": last.get("summary"),
        }
    )
    return base


def _accommodation_hints(request: dict[str, Any]) -> list[str]:
    """从请求里提取住宿需求（偏好里带"住/酒店/经济/豪华"等词，或空列表）。"""
    prefs = request.get("preferences") or []
    hints = [p for p in prefs if any(k in p for k in ("住", "酒店", "经济", "豪华", "亲子", "商务", "民宿"))]
    return hints or []


def _food_hints(prefs: list[str]) -> list[str]:
    """从偏好里提取口味/菜系词（美食/吃/菜/海鲜/火锅/小吃 等），供 FoodAgent 用。"""
    keys = ("美食", "吃", "菜", "海鲜", "火锅", "小吃", "烧烤", "面", "咖啡", "甜品", "素食")
    return [p for p in prefs if any(k in p for k in keys)]