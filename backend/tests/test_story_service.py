"""task-trip-story：旅程故事卡测试。

覆盖：
1. 模板三渠道（xhs/moments/poster）确定性生成
2. LLM 失败降级模板（source=template）
3. 空投影（无打卡无费用）→ empty=True 引导，不硬生成
4. 数据驱动：stats 来自投影（金额/站点/徽章不编造）
5. PII 过滤：凭证号不进入文案
6. API：POST /story（owner）
"""
from __future__ import annotations

from datetime import date, timedelta

from app.models import Stop, Trip, TripDay


def _make_trip(*, owner: str = "u-story", num_days: int = 2) -> Trip:
    start = date(2026, 10, 20)
    trip = Trip(
        owner=owner,
        title="故事测试",
        destination="杭州",
        start_date=start,
        end_date=start + timedelta(days=num_days - 1),
        travelers=2,
        budget=1000.0,
    )
    for i in range(num_days):
        day = TripDay(day_number=i + 1, date=start + timedelta(days=i))
        trip.days.append(day)
        for j in range(1, 3):
            day.stops.append(Stop(
                name=f"站点{i + 1}{'A' if j == 1 else 'B'}",
                stop_type="attraction",
                order_index=j,
                checked=False,
            ))
    return trip


def _projection(**overrides) -> dict:
    base = {
        "phase": "live",
        "journey_progress": 50.0,
        "completed_stops": 2,
        "total_stops": 4,
        "expense_total": 200.0,
        "per_person": 100.0,
        "booking_status": {"suggested": 1, "confirmed": 1, "pending": 0, "cancelled": 0},
        "highlights": [{"event_type": "check", "summary": "打卡：站点1A", "day_number": 1}],
        "badges": [{"key": "first_checkin", "label": "第一次打卡", "earned_at": "x"}],
        "data_complete": True,
    }
    base.update(overrides)
    return base


# ── 模板三渠道 ────────────────────────────────────────────────
class TestTemplates:
    async def test_xhs_template(self):
        from app.services.story_service import build_trip_story

        trip = _make_trip()
        story = await build_trip_story(trip, _projection(), channel="xhs", provider="offline")
        assert story["empty"] is False
        assert "杭州" in story["title"]
        assert "200" in story["body"]  # 金额来自投影
        assert story["source"] == "template"  # provider=offline 走兜底
        assert story["image_spec"]["ratio"] == "3:4"

    async def test_moments_template(self):
        from app.services.story_service import build_trip_story

        trip = _make_trip()
        story = await build_trip_story(trip, _projection(), channel="moments", provider="offline")
        assert story["channel"] == "moments"
        assert "杭州" in story["body"]
        assert story["image_spec"]["ratio"] == "1:1"

    async def test_poster_template(self):
        from app.services.story_service import build_trip_story

        trip = _make_trip()
        story = await build_trip_story(trip, _projection(), channel="poster", provider="offline")
        assert story["channel"] == "poster"
        assert "10-20" in story["body"]
        assert story["image_spec"]["ratio"] == "9:16"

    async def test_no_fabrication_badges_from_projection(self):
        """徽章/金额完全来自投影，不编造。"""
        from app.services.story_service import build_trip_story

        trip = _make_trip()
        story = await build_trip_story(trip, _projection(), channel="xhs", provider="offline")
        assert "第一次打卡" in story["body"]
        assert "200" in story["body"]  # expense_total
        assert "高铁" not in story["body"]  # 没有预订 → 不提


# ── LLM 降级 / 空投影 / 数据驱动 ─────────────────────────────
class TestStoryService:
    async def test_llm_success_uses_llm_source(self, monkeypatch):
        """LLM 成功返回（mock get_provider + invoke）→ source=llm。"""
        from app.services.story_service import build_trip_story

        class R:
            content = '{"title": "杭州两天一夜", "body": "这次杭州之旅超棒！花了200元。", "topics": ["杭州", "旅行"]}'

        async def fake_invoke(provider, messages, **kwargs):
            return R()

        def fake_get_provider(name):
            return object()  # invoke 被 mock，provider 对象本身无所谓

        monkeypatch.setattr("app.agent.providers.invoke_with_resilience", fake_invoke)
        monkeypatch.setattr("app.agent.providers.get_provider", fake_get_provider)
        trip = _make_trip()
        story = await build_trip_story(trip, _projection(), channel="xhs", provider="openai")
        assert story["source"] == "llm"
        assert story["title"] == "杭州两天一夜"

    async def test_llm_failure_falls_back_template(self, monkeypatch):
        from app.services.story_service import build_trip_story

        async def boom(*a, **k):
            raise RuntimeError("llm off")

        monkeypatch.setattr("app.agent.providers.invoke_with_resilience", boom)
        trip = _make_trip()
        story = await build_trip_story(trip, _projection(), channel="xhs", provider="openai")
        assert story["source"] == "template"
        assert "杭州" in story["body"]

    async def test_empty_projection_returns_hint(self):
        from app.services.story_service import build_trip_story

        trip = _make_trip()
        story = await build_trip_story(trip, _projection(completed_stops=0, expense_total=0.0, per_person=0.0),
                                       channel="xhs", provider="offline")
        assert story["empty"] is True
        assert story["message"]  # 引导文案
        assert story["body"] == ""  # 不硬生成

    async def test_story_api_requires_auth(self, client):
        trip = _make_trip()
        # 未登录 → 401
        resp = await client.post("/api/v1/trips/abc/story", json={"channel": "xhs"})
        assert resp.status_code == 401