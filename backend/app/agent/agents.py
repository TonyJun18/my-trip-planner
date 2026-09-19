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

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool as lc_tool

from app.agent import tools as agent_tools
from app.agent.providers import get_provider, invoke_with_resilience
from app.core.logging import get_logger
from app.schemas.plan import validate_plan

logger = get_logger(__name__)


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


ATTRACTION_TOOLS = [search_attractions]
HOTEL_TOOLS = [search_hotels]
WEATHER_TOOLS = [query_weather]
TOOL_MAP: dict[str, Any] = {t.name: t for t in (search_attractions, search_hotels, query_weather)}


# ═══════════════════════════════════════════════════════════
#  Agent 提示词（极简，单一职责）
# ═══════════════════════════════════════════════════════════
ATTRACTION_SYSTEM_PROMPT = """你是旅行规划团队中的【景点搜索专家】。你的唯一任务：根据用户的偏好关键词，搜索景点。

规则：
1. 用户会给你：目的地城市 + 偏好（如"历史文化"、"自然风光"、"亲子"、"博物馆"等）
2. 把偏好转换为 2-4 个中文关键词（如偏好"历史文化" → "历史遗迹 博物馆 古建筑"）
3. 调用工具 search_attractions(city, query=关键词, limit=8) 获取真实景点
4. 不要编造景点数据；工具返回什么就用什么
5. 最终输出：一个 JSON 数组，元素为 {name, type, lat, lng, estimated_cost, duration_minutes, description}
   —— 直接提取工具返回 results 里的字段，不要添加或修改

你只负责"找到并列出景点"，不做行程编排。"""


WEATHER_SYSTEM_PROMPT = """你是旅行规划团队中的【天气查询专家】。你的唯一任务：查询目的地未来几天的天气。

规则：
1. 你会收到目的地城市名（可能有日期范围）
2. 调用工具 query_weather(city, days=3) 获取天气预报
3. 不要编造天气数据
4. 最终输出：把工具返回的 JSON 原样返回（含 date / text_day / temp_max / temp_min / humidity）

你只负责"查询并报告天气"，不做行程编排。"""


HOTEL_SYSTEM_PROMPT = """你是旅行规划团队中的【酒店推荐专家】。你的唯一任务：根据用户的住宿需求，搜索合适的酒店。

规则：
1. 用户会给你：目的地城市 + 住宿需求（如"经济型"、"豪华型"、"亲子"、"近市中心"等）
2. 把住宿需求转换为 1-3 个中文关键词（如"经济型" → "经济 连锁 便宜"）
3. 调用工具 search_hotels(city, query=关键词, limit=6) 获取真实酒店
4. 不要编造酒店数据；工具返回什么就用什么
5. 最终输出：一个 JSON 数组，元素为 {name, type:"hotel", lat, lng, estimated_cost, duration_minutes, description}

你只负责"找到并列出酒店"，不做行程编排。"""


PLANNER_SYSTEM_PROMPT = """你是旅行规划团队中的【行程规划专家】。你负责整合团队产出，输出最终完整行程。

你将收到（按顺序）：
- 用户原始需求：目的地、日期、人数、预算、偏好
- 景点列表（来自景点搜索专家）
- 天气预报（来自天气查询专家）
- 酒店列表（来自酒店推荐专家）
- 餐饮信息（来自餐厅搜索，可选）

你的规则：
1. 不要调用任何工具，不要编造不在给定列表中的地点
2. 只能在给定列表中选择景点/酒店；餐饮从餐厅列表选择；若没有餐厅列表，可用合理的通用描述（如"当地特色餐馆"），但不要编造具体餐厅名
3. 按天编排：每天 2-4 个站点，含景点 + 餐饮，最后一天可含酒店（住宿）
4. 日期必须是 YYYY-MM-DD，与用户给定日期范围一致；day_number 从 1 开始
5. 预算：基于站点 estimated_cost 汇总出 total_estimated 与 by_type（attraction/food/hotel）
6. 只输出一个 JSON 对象，不要任何多余文字（不要 ``` 代码块）

最终 JSON 结构：
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


def _validation_feedback(exc: Exception) -> str:
    """把 Pydantic ValidationError 转成给 LLM 的简短纠错提示。"""
    errors = getattr(exc, "errors", list)()
    lines = []
    for e in errors[:6]:
        loc = ".".join(str(x) for x in e.get("loc", []))
        lines.append(f"- {loc}: {e.get('msg', 'invalid')}")
    return "你的最终行程 JSON 校验失败，请修正后重新输出完整的 JSON（不要解释）：\n" + "\n".join(lines)


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
    高德 POI 的 estimated_cost 恒为 0（tools 未解析价格），保持原样，
    前端展示时可标注「价格以实际询价为准」。
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
    provider: str = "auto",
) -> dict[str, Any]:
    """偏好 → 关键词 → search_attractions → POI 列表。

    返回 {"status", "pois": [...]}；失败时 {"status": "failed", "error": ...}。
    """

    async def _node(state: dict[str, Any]) -> dict[str, Any]:
        prov = get_provider(state.get("provider", "auto"))
        messages = [SystemMessage(content=ATTRACTION_SYSTEM_PROMPT)]
        messages.append(
            HumanMessage(
                content=(
                    f"目的地城市：{state['city']}\n"
                    f"用户偏好：{', '.join(state.get('preferences') or []) or '无特别偏好'}\n"
                    "请选择合适的搜索关键词，调用 search_attractions 工具获取景点列表。"
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
        # 执行工具并回填 Observation
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

    state: dict[str, Any] = {"city": city, "preferences": preferences, "provider": provider, "messages": []}
    try:
        result = await _node(state)
        if result.get("status") != "completed":
            return {"status": "failed", "error": result.get("error", "景点搜索失败"), "pois": []}
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
    provider: str = "auto",
) -> dict[str, Any]:
    """住宿需求 → 关键词 → search_hotels → 酒店 POI 列表。"""
    accommodation = accommodation or []

    async def _node(state: dict[str, Any]) -> dict[str, Any]:
        prov = get_provider(state.get("provider", "auto"))
        messages = [SystemMessage(content=HOTEL_SYSTEM_PROMPT)]
        messages.append(
            HumanMessage(
                content=(
                    f"目的地城市：{state['city']}\n"
                    f"住宿需求：{', '.join(state.get('accommodation') or []) or '无特别需求（默认推荐评分较高的酒店）'}\n"
                    "请选择合适的搜索关键词，调用 search_hotels 工具获取酒店列表。"
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

    state: dict[str, Any] = {"city": city, "accommodation": accommodation, "provider": provider, "messages": []}
    try:
        result = await _node(state)
        if result.get("status") != "completed":
            return {"status": "failed", "error": result.get("error", "酒店搜索失败"), "pois": []}
        pois = [p for p in result.get("pois", []) if p.get("name")]
        return {"status": "completed", "pois": pois}
    except Exception as exc:  # noqa: BLE001
        logger.warning("HotelAgent 失败 city=%s err=%s", city, exc)
        return {"status": "failed", "error": str(exc), "pois": []}


# ═══════════════════════════════════════════════════════════
#  PlannerAgent —— 行程规划专家（无工具，强校验 + 自纠正）
# ═══════════════════════════════════════════════════════════
async def planner_agent(
    request: dict[str, Any],
    materials: dict[str, Any],
    *,
    provider: str = "auto",
    max_corrections: int = 3,
) -> dict[str, Any]:
    """整合所有材料，输出最终行程 JSON。

    materials: {"attractions": [...], "hotels": [...], "foods": [...], "weather": {...}}
    """
    prov = get_provider(provider)
    messages: list[Any] = [SystemMessage(content=PLANNER_SYSTEM_PROMPT)]
    messages.append(HumanMessage(content=_planner_user_text(request, materials)))

    corrections = 0
    last_error: str | None = None
    for _ in range(max_corrections + 1):
        response = await invoke_with_resilience(prov, messages)
        content = str(getattr(response, "content", ""))
        final = _extract_json(content)
        if not isinstance(final, dict):
            corrections += 1
            last_error = "未找到合法 JSON"
            messages.append(SystemMessage(content="你的输出中未找到合法的行程 JSON。请只输出一个 JSON 对象，不要解释。"))
            continue
        try:
            clean = validate_plan(final)
            return {"status": "completed", "plan": clean, "corrections": corrections}
        except Exception as exc:  # noqa: BLE001 — Pydantic ValidationError
            corrections += 1
            last_error = str(exc)
            logger.info("Planner 校验失败 (correction=%d): %s", corrections, exc)
            messages.append(SystemMessage(content=_validation_feedback(exc)))
    return {"status": "failed", "error": f"Planner 多次校验失败: {last_error}", "plan": None}


def _planner_user_text(request: dict[str, Any], materials: dict[str, Any]) -> str:
    """把用户需求 + 团队材料组装成给 Planner 的完整上下文。"""
    lines: list[str] = []
    lines.append("【用户原始需求】")
    lines.append(
        f"目的地：{request.get('destination', '')}；日期：{request.get('start_date', '')} 至 {request.get('end_date', '')}；"
        f"人数：{request.get('travelers', 1)}；预算：{request.get('budget', '未指定')} 元；"
        f"偏好：{', '.join(request.get('preferences') or []) or '无'}"
    )

    attractions = materials.get("attractions") or []
    lines.append(f"\n【景点列表】（{len(attractions)} 个，来自景点搜索专家）")
    lines.append(json.dumps(attractions, ensure_ascii=False)[:4000])

    weather = materials.get("weather") or {}
    lines.append("\n【天气预报】（来自天气查询专家）")
    lines.append(json.dumps(weather, ensure_ascii=False)[:1500])

    hotels = materials.get("hotels") or []
    lines.append(f"\n【酒店列表】（{len(hotels)} 个，来自酒店推荐专家）")
    lines.append(json.dumps(hotels, ensure_ascii=False)[:4000])

    foods = materials.get("foods") or []
    if foods:
        lines.append(f"\n【餐厅列表】（{len(foods)} 个，来自餐厅搜索）")
        lines.append(json.dumps(foods, ensure_ascii=False)[:4000])

    lines.append("\n请整合以上全部信息，输出完整行程 JSON。")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════
#  编排：并行采集 → 补餐厅 → Planner 整合 → 预算校准
# ═══════════════════════════════════════════════════════════
async def run_planning_agents(
    request: dict[str, Any],
    *,
    provider: str = "auto",
    max_corrections: int = 3,
) -> dict[str, Any]:
    """多 Agent 全流程：采集 → 整合 → 输出 {plan, trace, status, error, agents}。

    trace 每步标注 agent 名，前端可展示“哪个专家在做什么”。
    """
    city = request.get("destination", "")
    prefs = request.get("preferences") or []
    trace: list[dict[str, Any]] = []

    # 1) 三个采集 Agent 并行
    attraction_task = attraction_agent(city, prefs, provider=provider)
    weather_task = weather_agent(city)
    hotel_task = hotel_agent(city, _accommodation_hints(request), provider=provider)

    a_res, w_res, h_res = await asyncio.gather(attraction_task, weather_task, hotel_task)

    trace.append({"agent": "AttractionSearchAgent", "action": "search_attractions",
                  "observation": f"{city} 景点 {len(a_res.get('pois', []))} 个",
                  "status": a_res.get("status")})
    trace.append({"agent": "WeatherQueryAgent", "action": "query_weather",
                  "observation": f"{city} 未来天气（source={w_res.get('weather', {}).get('source', '?')}）",
                  "status": w_res.get("status")})
    trace.append({"agent": "HotelAgent", "action": "search_hotels",
                  "observation": f"{city} 酒店 {len(h_res.get('pois', []))} 个",
                  "status": h_res.get("status")})

    # 2) 编排层补充餐饮（真实数据；失败不影响主流程）
    foods: list[dict[str, Any]] = []
    try:
        food_res = await agent_tools.search_foods(city, query="必吃 美食 餐厅", limit=5)
        foods = food_res.get("results", [])
        trace.append({"agent": "orchestrator", "action": "search_food",
                      "observation": f"{city} 餐厅 {len(foods)} 个", "status": "completed"})
    except Exception as exc:  # noqa: BLE001
        trace.append({"agent": "orchestrator", "action": "search_food",
                      "observation": f"餐厅搜索失败: {exc}", "status": "failed"})
        logger.warning("餐饮搜索失败 city=%s err=%s", city, exc)

    # 3) Planner 整合（无工具）
    materials = {
        "attractions": a_res.get("pois", []),
        "hotels": h_res.get("pois", []),
        "foods": foods,
        "weather": (w_res.get("weather") or {}),
    }
    planner = await planner_agent(request, materials, provider=provider, max_corrections=max_corrections)
    trace.append({"agent": "PlannerAgent", "action": "integrate",
                  "observation": f"整合 {len(materials['attractions'])} 景点 / {len(materials['hotels'])} 酒店 / {len(foods)} 餐厅",
                  "status": planner.get("status")})

    if planner.get("status") != "completed" or planner.get("plan") is None:
        return {"plan": None, "trace": trace, "status": "failed",
                "error": planner.get("error") or "Planner 未能生成行程", "agents": {}}

    plan = planner["plan"]

    # 4) 预算校准：以真实 stops 的 estimated_cost 重新计算（覆盖 LLM 估值）
    all_stops = [s for d in plan.get("days", []) for s in d.get("stops", [])]
    plan["budget"] = agent_tools.compute_budget(all_stops)

    # 5) 酒店候选回填：酒店列表由 HotelAgent 采集（真实数据），由编排层代码
    #    直接填入 plan.hotels —— 不依赖 LLM 是否把酒店编排进 stops。
    #    经 PlanSchema 校验时 extra="ignore" 会保留该字段（合法输出不丢数据）。
    plan["hotels"] = _normalize_hotels(materials.get("hotels") or [])

    return {
        "plan": plan,
        "trace": trace,
        "status": "completed",
        "error": None,
        "provider": get_provider(provider).name,
        "model": get_provider(provider).model_id,
        "agents": {
            "attractions": a_res.get("status"),
            "weather": w_res.get("status"),
            "hotels": h_res.get("status"),
            "planner": planner.get("status"),
        },
    }


def _accommodation_hints(request: dict[str, Any]) -> list[str]:
    """从请求里提取住宿需求（偏好里带"住/酒店/经济/豪华"等词，或空列表）。"""
    prefs = request.get("preferences") or []
    hints = [p for p in prefs if any(k in p for k in ("住", "酒店", "经济", "豪华", "亲子", "商务", "民宿"))]
    return hints or []