"""自驾模式（task-roadtrip-mode）单元测试。

覆盖：
- haversine / 时长估算 / 单段超距 / 单段超时 / 单日累计超限
- 折返识别（先走远再折回）
- 缺坐标降级（warning，不阻断）
- DrivingGate 集成到规划编排（超距组合 → 拒绝并修订）
- revise_service 修订后超距 → 整体拒绝（revise_driving_violation）
"""
from __future__ import annotations

import json

import pytest
from langchain_core.messages import AIMessage

from app.services.driving_service import (
    check_day_stops,
    check_plan_driving,
    estimate_drive_minutes,
    haversine_km,
    leg_distance_km,
)


def _stop(name: str, lat: float, lng: float) -> dict:
    return {"name": name, "type": "attraction", "lat": lat, "lng": lng,
            "estimated_cost": 0, "duration_minutes": 60, "description": ""}


# ── 纯函数 ─────────────────────────────────────────────────
def test_haversine_known_distance():
    # 上海(31.23, 121.47) → 杭州(30.27, 120.15)，直线约 150-160km
    d = haversine_km(31.23, 121.47, 30.27, 120.15)
    assert 130 < d < 200


def test_leg_distance_missing_coords():
    assert leg_distance_km({"name": "A"}, {"name": "B"}) is None
    assert leg_distance_km(_stop("A", 30, 120), {"name": "B"}) is None


def test_estimate_drive_minutes():
    assert estimate_drive_minutes(100, avg_kmh=50) == 120
    assert estimate_drive_minutes(0) == 0


# ── check_day_stops ────────────────────────────────────────
def test_single_leg_ok():
    report = check_day_stops(
        [_stop("A", 30.0, 120.0), _stop("B", 30.1, 120.1)],
        day_number=1,
    )
    assert report["passed"] is True
    assert report["issues"] == []
    assert len(report["legs"]) == 1
    assert 10 < report["legs"][0]["distance_km"] < 20  # 约 13km


def test_over_distance_leg_rejected():
    # A(杭州) → B(上海)：直线约 155km，超过 120km 上限 → critical
    report = check_day_stops(
        [_stop("杭州", 30.27, 120.15), _stop("上海", 31.23, 121.47)],
        day_number=2,
    )
    assert report["passed"] is False
    assert report["legs"][0]["distance_km"] > 120
    critical = [i for i in report["issues"] if i["severity"] == "critical"]
    assert critical
    assert "超过" in critical[0]["message"]
    assert critical[0]["day_number"] == 2
    # 兼容 CritiqueIssueSchema 消费
    assert critical[0]["category"] == "geography"


def test_daily_total_over_limit():
    # 3 段约 280km（杭州→绍兴→宁波→台州链），把单日上限压到 260 → 累计 critical
    report = check_day_stops(
        [
            _stop("杭州", 30.27, 120.15),
            _stop("绍兴", 30.00, 120.58),
            _stop("宁波", 29.87, 121.55),
            _stop("台州", 28.66, 121.42),
        ],
        day_number=1,
        max_leg_km=150,
        max_daily_km=260,
    )
    assert report["passed"] is False
    assert report["total_km"] > 260
    daily = [i for i in report["issues"] if "累计驾驶" in i["message"]]
    assert any(i["severity"] == "critical" for i in daily)


def test_missing_coords_warning_not_blocking():
    report = check_day_stops(
        [{"name": "无坐标A", "type": "attraction", "lat": None, "lng": None},
         {"name": "无坐标B", "type": "attraction"}],
        day_number=3,
    )
    assert report["passed"] is True  # 无法校验 → 不阻断
    assert report["legs"] == []
    assert any(i["severity"] == "warning" and i["category"] == "logistics" for i in report["issues"])


def test_backtrack_warning():
    # A(北京天安门 39.90,116.40) → B(八达岭 40.36,116.02) → C(天坛 39.88,116.41)
    # B 距 A 约 54km，C 紧贴 A（< 0.4*54=21.6km），且 B→C 约 55km → 折返 warning
    report = check_day_stops(
        [_stop("天安门", 39.90, 116.40), _stop("八达岭", 40.36, 116.02), _stop("天坛", 39.88, 116.41)],
        day_number=1,
    )
    backtrack = [i for i in report["issues"] if "折返" in i["message"]]
    assert len(backtrack) == 1
    assert backtrack[0]["severity"] == "warning"
    assert report["passed"] is True  # warning 不阻断


# ── check_plan_driving ─────────────────────────────────────
def test_plan_summary_ok():
    plan = {"days": [{"day_number": 1, "stops": [_stop("A", 30.0, 120.0), _stop("B", 30.1, 120.1)]}]}
    report = check_plan_driving(plan)
    assert report["passed"] is True
    assert report["summary"] == "自驾路线校验通过"
    assert report["mode"] == "driving"
    assert report["per_day"][0]["day_number"] == 1


def test_plan_summary_rejected():
    plan = {"days": [{"day_number": 1, "stops": [_stop("杭州", 30.27, 120.15), _stop("上海", 31.23, 121.47)]}]}
    report = check_plan_driving(plan)
    assert report["passed"] is False
    assert report["critical_count"] >= 1
    assert "未通过" in report["summary"]


# ── DrivingGate 编排集成（超距 → 修订 → 通过） ───────────────
def _install_offline_tools(monkeypatch):
    from app.agent import agents as agents_mod
    from app.agent import tools as tools_mod

    async def _fake_search(city, *, query=None, limit=8, want_type="attraction"):
        return {"city": city, "count": 1, "results": [
            {"name": "西湖", "type": want_type, "lat": 30.245, "lng": 120.15,
             "estimated_cost": 0, "duration_minutes": 180, "description": "环湖",
             "source": "fake", "source_url": "", "geocoded": True}
        ]}

    async def _fake_search_hotels(city, *, query=None, limit=6):
        return {"city": city, "count": 1, "results": [
            {"name": "西湖大酒店", "type": "hotel", "lat": 30.25, "lng": 120.16,
             "estimated_cost": 300, "duration_minutes": None, "description": "近西湖",
             "source": "fake", "source_url": "", "geocoded": True}
        ]}

    async def _fake_weather(city, *, days=3):
        return {"city": city, "days": [
            {"date": "2026-10-01", "text_day": "晴", "temp_max": "25", "temp_min": "16", "humidity": "40"}
        ], "count": 1, "source": "fake"}

    async def _fake_foods(city, *, query=None, limit=8):
        return {"city": city, "count": 1, "results": [
            {"name": "楼外楼", "type": "food", "lat": 30.25, "lng": 120.14,
             "estimated_cost": 200, "duration_minutes": 90, "description": "杭帮菜",
             "source": "fake", "source_url": "", "geocoded": True}
        ]}

    monkeypatch.setattr(tools_mod, "search_attractions", _fake_search)
    monkeypatch.setattr(tools_mod, "search_hotels", _fake_search_hotels)
    monkeypatch.setattr(tools_mod, "search_foods", _fake_foods)
    monkeypatch.setattr(tools_mod, "query_weather", _fake_weather)


def _fake_provider(name: str, llm) -> None:
    from app.agent.providers import PROVIDER_REGISTRY

    class _P:
        name = "fake"
        model_id = "m"

        def __init__(self):
            self._llm = llm
            self.name = name  # 实例级覆盖 provider 名

        def get_chat_model(self, temperature=0.2):
            return self._llm

    PROVIDER_REGISTRY[name] = _P()  # type: ignore[assignment]


@pytest.mark.asyncio
async def test_driving_gate_rejects_overdistance_then_revises(monkeypatch):
    """Planner 首版包含超距组合 → DrivingGate 拒绝并反馈 → 二版通过。"""
    from app.agent import agents as agents_mod
    from app.agent.providers import PROVIDER_REGISTRY

    _install_offline_tools(monkeypatch)

    stops_v1 = [
        {"name": "西湖", "type": "attraction", "lat": 30.245, "lng": 120.15,
         "estimated_cost": 0, "duration_minutes": 180, "description": "环湖"},
        {"name": "外滩", "type": "attraction", "lat": 31.24, "lng": 121.49,
         "estimated_cost": 0, "duration_minutes": 120, "description": "上海"},
    ]
    stops_v2 = [stops_v1[0]]  # 修订版：删掉超距的外滩

    class _DrivingLoopLLM:
        _llm_type = "fake-driving-loop"

        def __init__(self):
            self.planner_calls = 0

        def bind_tools(self, tools, **kwargs):
            return self

        async def ainvoke(self, messages):
            sys_prompt = next((getattr(m, "content", "") or "" for m in messages
                               if getattr(m, "type", "") == "system"), "")
            if "行程质检专家" in sys_prompt:
                return AIMessage(content=json.dumps(
                    {"score": 92, "passed": True, "issues": [], "summary": "通过"},
                    ensure_ascii=False))
            if "行程规划专家" in sys_prompt:
                self.planner_calls += 1
                stops = stops_v1 if self.planner_calls == 1 else stops_v2
                return AIMessage(content=json.dumps({
                    "destination": "杭州",
                    "days": [{"day_number": 1, "date": "2026-10-01", "theme": "西湖",
                              "stops": stops}],
                    "budget": {"total_estimated": 0.0, "by_type": {}, "currency": "CNY"},
                }, ensure_ascii=False))
            if "景点搜索专家" in sys_prompt:
                return AIMessage(content="Thought: 搜索景点。",
                                 tool_calls=[{"name": "search_attractions", "args": {"city": "杭州", "query": "自然风光"},
                                              "id": "a1", "type": "tool_call"}])
            if "酒店推荐专家" in sys_prompt:
                return AIMessage(content="Thought: 查询酒店。",
                                 tool_calls=[{"name": "search_hotels", "args": {"city": "杭州", "query": "经济酒店"},
                                              "id": "h1", "type": "tool_call"}])
            return AIMessage(content='{"error": "unknown role"}')

    _fake_provider("fake-driving", _DrivingLoopLLM())
    try:
        result = await agents_mod.run_planning_agents(
            {"destination": "杭州", "start_date": "2026-10-01", "end_date": "2026-10-01",
             "travelers": 1, "budget": 2000, "preferences": []},
            provider="fake-driving", max_review_rounds=2,
        )
        assert result["status"] == "completed"
        # 定稿是修订版（只保留西湖）
        assert len(result["plan"]["days"][0]["stops"]) == 1
        assert result["plan"]["days"][0]["stops"][0]["name"] == "西湖"
        # DrivingGate 在 trace 里出现过（拒绝了首版）
        gate_steps = [s for s in result["trace"] if s.get("agent") == "DrivingGate"]
        assert len(gate_steps) >= 1
        assert any("未通过" in (s.get("observation") or "") for s in gate_steps)
        # plan.driving 注入最终报告
        assert result["plan"]["driving"]["passed"] is True
        assert result["plan"]["driving"]["history"][0]["passed"] is False
    finally:
        PROVIDER_REGISTRY.pop("fake-driving", None)


@pytest.mark.asyncio
async def test_driving_gate_forced_finalize_keeps_warning(monkeypatch):
    """Planner 永不修正超距 → 达最大评审轮 → 强制定稿但 driving.passed=False + trace warning。"""
    from app.agent import agents as agents_mod
    from app.agent.providers import PROVIDER_REGISTRY

    _install_offline_tools(monkeypatch)

    class _StubbornLLM:
        _llm_type = "fake-driving-stubborn"

        def __init__(self):
            self.planner_calls = 0

        def bind_tools(self, tools, **kwargs):
            return self

        async def ainvoke(self, messages):
            sys_prompt = next((getattr(m, "content", "") or "" for m in messages
                               if getattr(m, "type", "") == "system"), "")
            if "行程规划专家" in sys_prompt:
                self.planner_calls += 1
                return AIMessage(content=json.dumps({
                    "destination": "杭州",
                    "days": [{"day_number": 1, "date": "2026-10-01", "theme": "西湖",
                              "stops": [
                                  {"name": "西湖", "type": "attraction", "lat": 30.245, "lng": 120.15,
                                   "estimated_cost": 0, "duration_minutes": 180, "description": "环湖"},
                                  {"name": "外滩", "type": "attraction", "lat": 31.24, "lng": 121.49,
                                   "estimated_cost": 0, "duration_minutes": 120, "description": "上海"},
                              ]}],
                    "budget": {"total_estimated": 0.0, "by_type": {}, "currency": "CNY"},
                }, ensure_ascii=False))
            if "景点搜索专家" in sys_prompt:
                return AIMessage(content="Thought: 搜索景点。",
                                 tool_calls=[{"name": "search_attractions", "args": {"city": "杭州", "query": "自然风光"},
                                              "id": "a1", "type": "tool_call"}])
            if "酒店推荐专家" in sys_prompt:
                return AIMessage(content="Thought: 查询酒店。",
                                 tool_calls=[{"name": "search_hotels", "args": {"city": "杭州", "query": "经济酒店"},
                                              "id": "h1", "type": "tool_call"}])
            return AIMessage(content='{"error": "unknown role"}')

    _fake_provider("fake-driving-stubborn", _StubbornLLM())
    try:
        result = await agents_mod.run_planning_agents(
            {"destination": "杭州", "start_date": "2026-10-01", "end_date": "2026-10-01",
             "travelers": 1, "budget": 2000, "preferences": []},
            provider="fake-driving-stubborn", max_review_rounds=2,
        )
        assert result["status"] == "completed"  # 强制定稿，系统仍产出
        assert result["plan"]["driving"]["passed"] is False
        assert result["plan"]["driving"]["critical_count"] >= 1
        # 最终 trace 有 DrivingGate warning
        assert any(s.get("agent") == "DrivingGate" and s.get("status") == "warning"
                   for s in result["trace"])
    finally:
        PROVIDER_REGISTRY.pop("fake-driving-stubborn", None)


# ── revise_service 集成 ────────────────────────────────────
@pytest.mark.asyncio
async def test_revise_rejects_overdistance_add(monkeypatch):
    """修订把行程改成超距组合 → 落库前整体拒绝（AppError 400）。"""
    from app.core.exceptions import AppError
    from app.services import revise_service

    trip = _fake_trip(
        starts=[
            {"name": "西湖", "stop_type": "attraction", "lat": 30.245, "lng": 120.15,
             "estimated_cost": 0, "estimated_duration_minutes": 180, "order_index": 1},
        ]
    )
    diff = {
        "actions": [{
            "op": "add",
            "day_number": 1,
            "fields": {"name": "外滩", "stop_type": "attraction", "lat": 31.24, "lng": 121.49},
        }],
        "summary": "加一个外滩",
    }
    with pytest.raises(AppError) as exc_info:
        revise_service._apply_diff(trip, diff)
        revise_service._enforce_driving_constraints(trip)
    assert exc_info.value.code == "revise_driving_violation"
    assert "超距" in exc_info.value.message or "自驾" in exc_info.value.message
    assert exc_info.value.detail["issues"]


def _fake_trip(*, starts: list[dict]):
    """构造一个带 trip/days/stops 的最小对象（不落库，供纯逻辑测试）。"""
    from app.models import Stop, Trip, TripDay

    trip = Trip(id="t1", destination="杭州")
    day = TripDay(id="d1", trip_id="t1", day_number=1)
    trip.days = [day]
    day.stops = [Stop(id=f"s{i}", day_id="d1", **s) for i, s in enumerate(starts, start=1)]
    return trip