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


ATTRACTION_TOOLS = [search_attractions]
HOTEL_TOOLS = [search_hotels]
WEATHER_TOOLS = [query_weather]
TRANSPORT_TOOLS = [search_transport]
TOOL_MAP: dict[str, Any] = {
    t.name: t for t in (search_attractions, search_hotels, query_weather, search_transport)
}


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


TRANSPORT_SYSTEM_PROMPT = """你是旅行规划团队中的【交通专家】。你的唯一任务：查询出发地到目的地的大交通方案（驾车/高铁/航班）。

规则：
1. 用户会给你：出发地 + 目的地（+ 日期）
2. 调用工具 search_transport(departure, destination, date) 获取真实交通方案
3. 不要编造班次/价格；工具返回什么就用什么；价格缺失就标 None
4. 最终输出：一个 JSON 对象，结构为
   {
     "from": "出发地", "to": "目的地",
     "options": [
       {"mode": "driving|train|flight|bus|advice",
        "duration_minutes": 数字或 null, "price_range": [min,max] 或 null,
        "source": "amap|tavily", "source_url": "来源链接", "confidence": 0.9,
        "note": "简短说明"}
     ],
     "summary": "一句话概括最推荐的方式"
   }
5. 只保留有 source_url 的条目；没有可信来源的不写进 options

你只负责"查询并报告大交通"，不做行程编排。"""


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


CRITIC_SYSTEM_PROMPT = """你是旅行规划团队中的【行程质检专家】。你的唯一任务：审查 Planner 生成的行程 JSON，找出业务合理性问题。

你将收到：
1. 用户原始需求（目的地/日期/人数/预算/偏好）
2. Planner 生成的完整行程 JSON（含 days / budget / hotels）

审查维度（按重要性排序）：
1. schedule（日程合理性）：日期是否连续、与用户日期一致；站点时间是否冲突；每天是否过满（>6 个站点）；闭馆日/淡旺季常识性错误
2. budget（预算）：total 是否与 by_type 吻合；是否超出用户预算；估算是否明显离谱
3. geography（地理路线）：同一天站点是否在地理上严重绕路（跨城/相距极远）；坐标是否缺失或异常
4. logistics（内容完整性）：是否有"编造"的、不在给定列表中的具体地点；酒店/餐厅是否缺失；关键字段是否为空

输出规则：
1. 只输出一个 JSON 对象，不要任何多余文字（不要 ``` 代码块）
2. JSON 结构：
{
  "score": 82,
  "passed": true,
  "issues": [
    {
      "severity": "critical|warning|info",
      "category": "schedule|budget|geography|logistics|info",
      "message": "具体问题描述",
      "suggestion": "建议的修改方向（可选）",
      "day_number": 1
    }
  ],
  "summary": "一句话总结"
}
3. severity 语义：critical=必须修改 / warning=建议修改 / info=提示
4. 评分建议：>=80 为 passed=true 可通过；70-79 有 warning；<70 有 critical
5. 只审查你实际看到的问题；没有就列空 issues，不要为了凑数编造问题"""


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


def _questions_text(request: dict[str, Any]) -> str:
    """把主动提问 Q&A 组装成给 Planner/Critic 的补充上下文。

    仅保留用户实际回答过的问题（answer 非空）；未回答的不注入，
    避免无意义占位污染 LLM 上下文。无回答时返回空串。
    """
    questions = request.get("questions") or []
    answered = [
        q for q in questions
        if isinstance(q, dict) and (q.get("answer") or "").strip()
    ]
    if not answered:
        return ""
    lines = ["【需求澄清 · 用户追问答复】（规划必须尊重以下答复，与偏好冲突时以答复为准）"]
    for i, q in enumerate(answered, start=1):
        q_text = (q.get("question") or "").strip() or f"追问 {i}"
        ans = (q.get("answer") or "").strip()
        lines.append(f"{i}. {q_text}：{ans}")
    return "\n".join(lines)


def _profile_text(request: dict[str, Any]) -> str:
    """把跨会话用户画像摘要（create_task 时注入的 profile_text）组装成补充上下文。

    画像来自用户历史偏好（traveler_type/pace/budget_tier/favorite_cities 等），
    规划时优先尊重；与本次请求冲突时以本次请求为准。无画像返回空串。
    """
    profile = request.get("profile_text") or ""
    if not isinstance(profile, str) or not profile.strip():
        return ""
    return "【跨会话用户画像】（来自该用户历史偏好，规划时请优先尊重；与本次请求冲突时以本次请求为准）\n" + profile.strip()


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
        messages = [SystemMessage(content=ATTRACTION_SYSTEM_PROMPT)]
        messages.append(
            HumanMessage(
                content=(
                    f"目的地城市：{state['city']}\n"
                    f"用户偏好：{', '.join(state.get('preferences') or []) or '无特别偏好'}\n"
                    f"{_questions_text(state.get('request') or {})}\n"
                    f"{_profile_text(state.get('request') or {})}\n"
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
        "request": request, "messages": [],
    }
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
        messages = [SystemMessage(content=HOTEL_SYSTEM_PROMPT)]
        messages.append(
            HumanMessage(
                content=(
                    f"目的地城市：{state['city']}\n"
                    f"住宿需求：{', '.join(state.get('accommodation') or []) or '无特别需求（默认推荐评分较高的酒店）'}\n"
                    f"{_questions_text(state.get('request') or {})}\n"
                    f"{_profile_text(state.get('request') or {})}\n"
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
        "request": request, "messages": [],
    }
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
#  TransportAgent —— 大交通专家（出发地 → 目的地）
# ═══════════════════════════════════════════════════════════
async def transport_agent(
    departure: str | None,
    destination: str,
    *,
    date: str | None = None,
    provider: str = "auto",
    max_iterations: int | None = None,
) -> dict[str, Any]:
    """出发地 → 目的地 的大交通方案采集。

    无出发地（用户未提供）→ 直接降级返回（status=skipped），不阻塞；
    否则调用 search_transport 获取真实方案，输出 plan.transport 结构。
    绝不编造价格：无可信来源的条目不返回（由工具层硬闸门保证）。
    """
    if not departure or not departure.strip():
        return {"status": "skipped", "transport": None, "error": "未提供出发地"}

    async def _node(state: dict[str, Any]) -> dict[str, Any]:
        prov = get_provider(state.get("provider", "auto"))
        messages: list[Any] = [SystemMessage(content=TRANSPORT_SYSTEM_PROMPT)]
        messages.append(
            HumanMessage(
                content=(
                    f"出发地：{state['departure']}\n"
                    f"目的地：{state['destination']}\n"
                    f"日期：{state.get('date') or '未指定'}\n"
                    "请调用 search_transport 获取大交通方案。"
                )
            )
        )
        response = await invoke_with_resilience(prov, messages, tools=TRANSPORT_TOOLS)
        tool_calls = getattr(response, "tool_calls", None) or []
        if not tool_calls:
            parsed = _extract_json(str(getattr(response, "content", "")))
            if isinstance(parsed, dict) and parsed.get("options"):
                return {"messages": [response], "status": "completed", "transport": parsed}
            return {"messages": [response], "status": "failed", "error": "Agent 未调用交通工具"}
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
            return {"messages": state["messages"], "status": "failed", "error": "无法解析交通方案"}
        return {"messages": state["messages"], "status": "completed", "transport": transport}

    state: dict[str, Any] = {
        "departure": departure.strip(), "destination": destination,
        "date": date, "provider": provider, "messages": [],
    }
    try:
        result = await _node(state)
        if result.get("status") != "completed":
            return {"status": "failed", "error": result.get("error", "交通查询失败"), "transport": None}
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
    messages: list[Any] = [SystemMessage(content=PLANNER_SYSTEM_PROMPT)]
    messages.append(HumanMessage(content=_planner_user_text(request, materials)))
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
    """把用户需求 + 团队材料组装成给 Planner 的完整上下文。

    注意：规划往返期间的往返提示（评审反馈）由外层 caller 负责拼进消息，
    本函数只负责"第一版"的上下文（不含评审历史）。
    """
    lines: list[str] = []
    lines.append("【用户原始需求】")
    lines.append(
        f"目的地：{request.get('destination', '')}；日期：{request.get('start_date', '')} 至 {request.get('end_date', '')}；"
        f"人数：{request.get('travelers', 1)}；预算：{request.get('budget', '未指定')} 元；"
        f"偏好：{', '.join(request.get('preferences') or []) or '无'}"
    )

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
        lines.append("\n【采集告警】以下信息来源失败（不要编造替代数据，但可以给出合理通用描述，并在对应位置标注降级）：")
        lines.append("、".join(failed_sources))

    attractions = materials.get("attractions") or []
    lines.append(f"\n【景点列表】（{len(attractions)} 个，来自景点搜索专家）")
    if attractions:
        lines.append(json.dumps(attractions, ensure_ascii=False)[:4000])
    else:
        lines.append("（空：景点搜索失败或未返回结果）")

    weather = materials.get("weather") or {}
    lines.append("\n【天气预报】（来自天气查询专家）")
    lines.append(json.dumps(weather, ensure_ascii=False)[:1500])

    hotels = materials.get("hotels") or []
    lines.append(f"\n【酒店列表】（{len(hotels)} 个，来自酒店推荐专家）")
    if hotels:
        lines.append(json.dumps(hotels, ensure_ascii=False)[:4000])
    else:
        lines.append("（空：酒店搜索失败或未返回结果，可给出通用住宿建议）")

    foods = materials.get("foods") or []
    if foods:
        lines.append(f"\n【餐厅列表】（{len(foods)} 个，来自餐厅搜索）")
        lines.append(json.dumps(foods, ensure_ascii=False)[:4000])

    transport = materials.get("transport") or None
    if transport:
        lines.append("\n【大交通方案】（来自交通专家）")
        lines.append(json.dumps(transport, ensure_ascii=False)[:2500])
        lines.append("提示：首日到达时间/末日离开时间应参考大交通方案，避免行程与班次冲突。")

    discount_rules = materials.get("discount_rules") or []
    if discount_rules:
        lines.append(f"\n【折扣规则】（{len(discount_rules)} 条，来自优惠收集专家，估算预算时可参考）")
        lines.append(json.dumps(discount_rules, ensure_ascii=False)[:2000])

    lines.append("\n请整合以上全部信息，输出完整行程 JSON。")
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
    messages: list[Any] = [SystemMessage(content=CRITIC_SYSTEM_PROMPT)]
    critic_req = (
        f"【用户原始需求】目的地：{request.get('destination', '')}；"
        f"日期：{request.get('start_date', '')} 至 {request.get('end_date', '')}；"
        f"人数：{request.get('travelers', 1)}；预算：{request.get('budget', '未指定')} 元；"
        f"偏好：{', '.join(request.get('preferences') or []) or '无'}"
    )
    qa_text = _questions_text(request)
    if qa_text:
        critic_req += f"\n{qa_text}"
    profile_text = _profile_text(request)
    if profile_text:
        critic_req += f"\n{profile_text}"
    messages.append(
        HumanMessage(
            content=(
                f"{critic_req}\n\n"
                f"【待审查行程 JSON】\n{json.dumps(plan, ensure_ascii=False)[:6000]}\n\n"
                "请审查并输出质检报告 JSON。"
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
            return {"status": "degraded", "critique": _pass_critique("质检调用失败，按通过处理"), "corrections": corrections}
        content = str(getattr(response, "content", ""))
        parsed = _extract_json(content)
        if not isinstance(parsed, dict):
            corrections += 1
            last_error = "未找到合法 JSON"
            messages.append(SystemMessage(content="你的输出中未找到合法的质检 JSON。请只输出一个 JSON 对象，不要解释。"))
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
            messages.append(SystemMessage(content=_validation_feedback(exc)))

    logger.warning("Critic 多次校验失败，降级放行: %s", last_error)
    return {"status": "degraded", "critique": _pass_critique("质检报告生成失败，按通过处理"), "corrections": corrections}


def _pass_critique(summary: str) -> dict[str, Any]:
    """构造一份「通过」的默认质检报告（用于 Critic 降级）。"""
    return {
        "score": CRITIC_PASS_SCORE,
        "passed": True,
        "issues": [],
        "summary": summary,
    }


# ═══════════════════════════════════════════════════════════
#  PlanReviseAgent —— 行程修订专家（方案 B：对话改行程）
# ═══════════════════════════════════════════════════════════
REVISE_SYSTEM_PROMPT = """你是旅行规划团队中的【行程修订专家】。你的唯一任务：把用户对已生成行程的修改请求，转成结构化的变更指令（diff）。

你将收到：
1. 用户原始需求（目的地 / 预算）+ 新的修改消息
2. 当前行程 JSON（days / budget）

规则：
1. 不要直接修改行程，只输出变更指令（diff）—— 由编排层代码执行
2. 只对「当前行程里真实存在」的目标做操作；找不到就报错，不要编造
3. 支持的操作：
   - replace：修改某个现有站点的字段（target 用 name 或 index）
   - add：新增一个站点（day_number + fields.name + 可选 index）
   - remove：删除一个站点（target 用 name 或 index）
   - reorder：调整站点顺序（target + index）
4. 字段白名单：name / stop_type / lat / lng / description / estimated_cost / estimated_duration_minutes
5. stop_type 只能是 attraction / food / hotel
6. 一次消息里有多件事 → 生成多个 actions；无法理解 → 输出空 actions + 说明
7. 日期、人数、预算等行程级变更 → 用 replace 改 day 或整体（暂不支持改行程元信息，说明不支持即可）
8. summary：一句给用户看的变更摘要

输出 JSON（不要 ``` 代码块）：
{
  "actions": [
    {
      "op": "replace|add|remove|reorder",
      "day_number": 1,
      "target": {"name": "西湖"} 或 {"index": 1},
      "fields": {"name": "...", "stop_type": "food", "estimated_cost": 80, "estimated_duration_minutes": 90},
      "index": 2
    }
  ],
  "summary": "已把第三天西湖调整为半天，新增楼外楼晚餐"
}"""


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
    messages: list[Any] = [SystemMessage(content=REVISE_SYSTEM_PROMPT)]
    messages.append(
        HumanMessage(
            content=(
                f"【用户原始需求】目的地：{request.get('destination', '')}；"
                f"预算：{request.get('budget', '未指定')} 元\n"
                f"【用户本次修改请求】{request.get('message', '')}\n\n"
                f"【当前行程 JSON】\n{json.dumps(plan, ensure_ascii=False)[:5000]}\n\n"
                "请输出修订 diff JSON。"
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
            messages.append(SystemMessage(content="你的输出中未找到合法的修订 JSON。请只输出一个 JSON 对象，不要解释。"))
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
                    "observation": f"{len(clean.get('actions') or [])} 条变更指令 · {clean.get('summary') or ''}",
                    "status": "completed",
                }],
                "provider": prov.name,
                "model": prov.model_id,
            }
        except Exception as exc:  # noqa: BLE001 — Pydantic ValidationError
            corrections += 1
            last_error = str(exc)
            logger.info("ReviseAgent 校验失败 (correction=%d): %s", corrections, exc)
            messages.append(SystemMessage(content=_validation_feedback(exc)))

    return {"status": "failed", "error": f"修订指令解析多次失败: {last_error}", "diff": None}


def _critic_feedback(critique: dict[str, Any]) -> str:
    """把质检报告转成给 Planner 的修改指令（只含未通过项，避免信息过载）。"""
    issues = critique.get("issues") or []
    actionable = [i for i in issues if i.get("severity") in ("critical", "warning")]
    if not actionable:
        return "质检通过，无需修改。"

    lines = ["【行程质检报告】以下问题需要你修改后重新输出完整行程 JSON（不要解释，只输出新的 JSON）："]
    for i, issue in enumerate(actionable, start=1):
        loc = f"（Day {issue.get('day_number')}）" if issue.get("day_number") else ""
        lines.append(
            f"{i}. [{issue.get('severity', 'warning')}/{issue.get('category', 'info')}]{loc} "
            f"{issue.get('message', '')}"
        )
        if issue.get("suggestion"):
            lines.append(f"   建议：{issue['suggestion']}")
    lines.append("请基于以上反馈修正行程并重新输出完整 JSON，不要解释。")
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
    trace: list[dict[str, Any]] = []
    review_history: list[dict[str, Any]] = []  # 每次评审的报告（给 Planner 作为上下文）

    # 阶段事件：任务开始 → collecting
    _fire_phase("collecting", "running")

    # 1) 五个采集 Agent 并行（request 传入后，主动提问 Q&A 会并入搜索上下文）
    #    采集 agent 内部最多调用工具一次，无 LLM 迭代循环，但通过参数显式带上限。
    agent_max_iter = max_iterations if max_iterations is not None else settings.AGENT_MAX_ITERATIONS
    attraction_task = attraction_agent(city, prefs, request=request, provider=provider, max_iterations=agent_max_iter)
    weather_task = weather_agent(city)
    hotel_task = hotel_agent(city, _accommodation_hints(request), request=request, provider=provider, max_iterations=agent_max_iter)
    transport_task = transport_agent(
        request.get("departure"), city,
        date=request.get("start_date"), provider=provider, max_iterations=agent_max_iter,
    )
    discount_task = discount_agent(city)

    a_res, w_res, h_res, t_res, d_res = await asyncio.gather(
        attraction_task, weather_task, hotel_task, transport_task, discount_task,
    )

    def _append_trace(entry: dict[str, Any]) -> None:
        """追加一条 trace 并向 WS 订阅者实时推送（推送失败不影响主流程）。"""
        trace.append(entry)
        asyncio.create_task(_emit_plan_event({"type": "trace", "trace": entry}))

    _append_trace({"agent": "AttractionSearchAgent", "action": "search_attractions",
                  "observation": f"{city} 景点 {len(a_res.get('pois', []))} 个",
                  "status": a_res.get("status")})
    _append_trace({"agent": "WeatherQueryAgent", "action": "query_weather",
                  "observation": f"{city} 未来天气（source={w_res.get('weather', {}).get('source', '?')}）",
                  "status": w_res.get("status")})
    _append_trace({"agent": "HotelAgent", "action": "search_hotels",
                  "observation": f"{city} 酒店 {len(h_res.get('pois', []))} 个",
                  "status": h_res.get("status")})
    _append_trace({"agent": "TransportAgent", "action": "search_transport",
                  "observation": (
                      f"{request.get('departure') or '未提供出发地'}→{city} 交通方案 "
                      f"{len((t_res.get('transport') or {}).get('options', []))} 条"
                  ),
                  "status": t_res.get("status")})
    _append_trace({"agent": "DiscountAgent", "action": "collect_discount_rules",
                  "observation": f"{city} 折扣规则 {len(d_res.get('rules', []))} 条",
                  "status": d_res.get("status")})

    # 2) 编排层补充餐饮（真实数据；失败不影响主流程）
    foods: list[dict[str, Any]] = []
    try:
        food_res = await agent_tools.search_foods(city, query="必吃 美食 餐厅", limit=5)
        foods = food_res.get("results", [])
        _append_trace({"agent": "orchestrator", "action": "search_food",
                      "observation": f"{city} 餐厅 {len(foods)} 个", "status": "completed"})
    except Exception as exc:  # noqa: BLE001
        _append_trace({"agent": "orchestrator", "action": "search_food",
                      "observation": f"餐厅搜索失败: {exc}", "status": "failed"})
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
    _fire_phase("collecting", "completed", summary=(
        f"景点 {len(attr_pois)} · 天气 {len((w_res.get('weather') or {}).get('days') or [])} 天"
        f" · 酒店 {len(hotel_pois)} · 餐厅 {len(foods_art)}"
        f" · 交通 {len(transport_art)} · 折扣 {len(d_res.get('rules', []))}"
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
        review_feedback = _critic_feedback(review_history[-1]) if review_history else None
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
                f"整合 {len(materials['attractions'])} 景点 / {len(materials['hotels'])} 酒店 / {len(foods)} 餐厅"
                + ("；按评审意见修订" if round_idx > 0 else "")
            ),
            "status": planner.get("status"),
        })
        if planner.get("status") != "completed" or planner.get("plan") is None:
            return {"plan": None, "trace": trace, "status": "failed",
                    "error": planner.get("error") or "Planner 未能生成行程", "agents": {},
                    "review_rounds": review_rounds}

        candidate = planner["plan"]

        # 预算校准前置：先以真实 stops 计算预算（覆盖 LLM 估值），再交给质检
        all_stops = [s for d in candidate.get("days", []) for s in d.get("stops", [])]
        candidate["budget"] = agent_tools.compute_budget(all_stops)
        candidate["hotels"] = _normalize_hotels(materials.get("hotels") or [])

        # 行程草案制品（每代都发；前端「编排阶段」实时展示天数/主题）
        _fire_artifact("draft", {
            "days": len(candidate.get("days", [])),
            "themes": [f"Day {d.get('day_number')} {d.get('theme') or ''}".strip()
                       for d in candidate.get("days", [])][:10],
            "round": round_idx + 1,
        })
        if round_idx == 0:
            _fire_phase("assembling", "completed", summary=f"生成 {len(candidate.get('days', []))} 天草案")

        # ── DrivingGate：自驾约束校验（确定性代码，超距/超时/折返；真实路径优先） ──
        driving = await check_plan_driving_async(candidate)
        driving_reports.append(driving)
        if not driving["passed"] and round_idx < max_review_rounds:
            # 拒绝该站点组合：带自驾反馈重新生成（不进 Critic，省一次评审 token）
            logger.info("自驾校验未通过 round=%d critical=%d，进入修订", round_idx + 1, driving["critical_count"])
            _append_trace({
                "agent": "DrivingGate",
                "action": "check_driving",
                "observation": (
                    f"自驾校验未通过：{driving['critical_count']} 个超距/超时问题"
                    f"（{driving['summary']}）"
                ),
                "status": "failed",
            })
            review_history.append(_driving_feedback(driving))  # 作为修订反馈
            review_rounds += 1
            continue

        review_rounds += 1

        # 交给 TravelCriticAgent 评审（最后一代无需再评：强制定稿）
        if round_idx >= max_review_rounds:
            plan = candidate
            _append_trace({"agent": "TravelCriticAgent", "action": "review",
                          "observation": f"达到最大评审轮数（{max_review_rounds}），强制定稿", "status": "completed"})
            break

        critic = await critic_agent(request, candidate, provider=provider)
        critique = critic.get("critique") or _pass_critique("质检未返回报告，按通过处理")
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
            _fire_phase("reviewing", "completed", summary=f"评分 {critique.get('score')}/100")
        _append_trace({
            "agent": "TravelCriticAgent",
            "action": "review",
            "observation": (
                f"评分 {critique.get('score')}/100 · {len([i for i in critique.get('issues') or [] if i.get('severity') in ('critical', 'warning')])} 个待修改项"
                + (f"（{critique.get('summary') or ''}）" if critique.get("summary") else "")
            ),
            "status": "completed" if critic.get("status") == "completed" else "degraded",
        })

        if critique.get("passed") or n_issues == 0 or not _has_actionable_issues(critique):
            plan = candidate
            break  # 质检通过 / 无待修改项 → 定稿

        logger.info("行程评审未通过 round=%d score=%s issues=%d，进入下一轮修订",
                    round_idx + 1, critique.get("score"), n_issues)

    # 兜底：若循环异常退出（理论上不会），仍保留最后一代
    if plan is None:
        return {"plan": None, "trace": trace, "status": "failed",
                "error": "质检循环异常退出", "agents": {}, "review_rounds": review_rounds}

    # 质检摘要注入 plan.quality（随 plan JSON 落库，前端可直接消费）
    plan["quality"] = _plan_quality(review_history, review_rounds, max_review_rounds)
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
                "自驾校验" + ("通过" if final_driving["passed"] else f"未通过（{final_driving['critical_count']} 个 critical）")
                + f"：总里程约 {final_driving['total_km']}km"
            ),
            "status": "completed" if final_driving["passed"] else "warning",
        })

    # 阶段收尾：assembling/reviewing 完成 → servicing（第二段） → 整体 completed
    _fire_phase("assembling", "completed", summary=f"定稿 {len(plan.get('days', []))} 天行程")
    _fire_phase("reviewing", "completed", summary="质检完成")

    # ── 第二段 servicing：定稿后的可执行服务（市内通勤 / 入住办理 / 折扣比价）──
    # 消费已定稿 plan，与采集/规划解耦；任一失败只记 warnings，绝不阻断主流程。
    _fire_phase("servicing", "running")
    from app.services.servicing_service import run_servicing

    servicing = await run_servicing(plan, provider=provider)
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
            f"市内通勤 {len((servicing.get('transit') or {}).get('legs', []))} 段"
            f" · 入住指引 {('已生成' if servicing.get('checkin') else '降级')}"
            f" · 折扣比价 {len((servicing.get('discounts') or {}).get('items', []))} 条"
        ),
        "status": "completed" if not servicing.get("warnings") else "warning",
    })
    for w in servicing.get("warnings", []):
        plan.setdefault("warnings", []).append(w)
    _fire_phase("servicing", "completed", summary=(
        f"市内通勤 {len((servicing.get('transit') or {}).get('legs', []))} 段"
        f" · 入住指引 {servicing.get('checkin', {}).get('source', '-')}"
        f" · 折扣 {len((servicing.get('discounts') or {}).get('items', []))} 条"
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
            "transport": t_res.get("status"),
            "discounts": d_res.get("status"),
            "planner": planner.get("status"),
        },
    }


def _has_actionable_issues(critique: dict[str, Any]) -> bool:
    """质检报告里是否有需要 Planner 修改的（critical/warning）问题。"""
    return any(i.get("severity") in ("critical", "warning") for i in (critique.get("issues") or []))


def _driving_feedback(driving: dict[str, Any]) -> dict[str, Any]:
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
        "summary": driving.get("summary", "自驾路线校验未通过"),
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