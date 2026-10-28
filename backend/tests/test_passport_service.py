"""task-journey-passport：旅程护照徽章测试。

覆盖：
1. 徽章规则纯函数（first_checkin/full_day/money_saver/train_goer/hotel_stayer/
   early_bird/night_owl）
2. ensure_passport 创建（trip_id 唯一）
3. maybe_award 幂等（badges 只增不减）+ 事件后自动触发
4. backfill 历史回填
5. API：GET /passport（owner）+ /share/{token}/passport（免登录只读）

不依赖外部环境（内存 ORM + 事件表）。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from app.models import Stop, Trip, TripDay, TripEvent, TripPassport


def _make_trip(*, owner: str = "u-passport", num_days: int = 2) -> Trip:
    start = date(2026, 10, 20)
    trip = Trip(
        owner=owner,
        title="护照测试",
        destination="杭州",
        start_date=start,
        end_date=start + timedelta(days=num_days - 1),
        travelers=1,
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


async def _add(db_session, trip: Trip) -> None:
    db_session.add(trip)
    await db_session.flush()


def _ev(event_type: str, *, dt: datetime | None = None, **payload) -> TripEvent:
    return TripEvent(
        id="x", trip_id="t1", event_type=event_type,
        payload=payload, created_at=dt or datetime.now(timezone.utc),
    )


# ── 纯函数规则 ────────────────────────────────────────────────
class TestBadgeRules:
    def test_first_checkin(self):
        from app.services.passport_service import _rule_first_checkin

        assert _rule_first_checkin([_ev("check", stop_id="s1", name="A", day_number=1)]) is True
        assert _rule_first_checkin([_ev("revise")]) is False

    def test_full_day_all_checked(self):
        from app.services.passport_service import _rule_full_day

        trip = _make_trip(num_days=1)
        for s in trip.days[0].stops:
            s.checked = True
        assert _rule_full_day(trip, [_ev("check", stop_id="s1", day_number=1)]) is True

    def test_full_day_skipped_day_excluded(self):
        from app.services.passport_service import _rule_full_day

        trip = _make_trip(num_days=2)
        # Day2 有 skip 事件 → 不计入；Day1 全打 → True
        for s in trip.days[0].stops:
            s.checked = True
        events = [_ev("skip", day_number=2, stop_id="x", name="x")]
        assert _rule_full_day(trip, events) is True

    async def test_money_saver_under_90(self, db_session):
        from app.schemas import ExpenseIn
        from app.services.expense_service import add_expense
        from app.services.passport_service import _rule_money_saver_async

        trip = _make_trip()
        await _add(db_session, trip)
        await add_expense(db_session, trip.id, ExpenseIn(category="food", amount=300, payer=""), owner="u-passport")
        # budget=1000, 花费 300 < 900 → True
        assert await _rule_money_saver_async(db_session, trip) is True

    async def test_money_saver_over_90(self, db_session):
        from app.schemas import ExpenseIn
        from app.services.expense_service import add_expense
        from app.services.passport_service import _rule_money_saver_async

        trip = _make_trip()
        await _add(db_session, trip)
        await add_expense(db_session, trip.id, ExpenseIn(category="hotel", amount=950, payer=""), owner="u-passport")
        assert await _rule_money_saver_async(db_session, trip) is False

    async def test_train_hotel_goer(self, db_session):
        from app.schemas import BookingIn
        from app.services.booking_service import upsert_booking
        from app.services.passport_service import _rule_hotel_stayer, _rule_train_goer

        trip = _make_trip()
        await _add(db_session, trip)
        b = await upsert_booking(
            db_session, trip.id,
            BookingIn(kind="train", status="confirmed", order_no="X1", credential="C1", reference="user.confirmed"),
            owner="u-passport",
        )
        assert _rule_train_goer([b]) is True
        assert _rule_hotel_stayer([b]) is False

    async def test_foodie_and_all_days_done(self):
        """新增徽章：美食家（≥2 个已打卡美食）+ 全程制霸（所有天完成）。"""
        from app.services.passport_service import _rule_all_days_done, _rule_foodie

        trip = _make_trip(num_days=1)
        trip.days[0].stops.append(Stop(name="楼外楼", stop_type="food", order_index=3, checked=True))
        trip.days[0].stops.append(Stop(name="外婆家", stop_type="food", order_index=4, checked=True))
        for s in trip.days[0].stops:
            s.checked = True
        events = [_ev("check", stop_id="s1", name="A", day_number=1)]
        assert _rule_foodie(trip) is True
        assert _rule_all_days_done(trip, events) is True

    async def test_group_voter(self):
        """群众参与：有 vote/comment 事件。"""
        from app.services.passport_service import _rule_group_voter

        assert _rule_group_voter([_ev("vote", stop_id="s1", value="up")]) is True
        assert _rule_group_voter([_ev("check", stop_id="s1")]) is False

    async def test_passport_out_has_badge_keys(self):
        """passport_out 返回全量 badge_keys（前端锁定态渲染用）。"""
        from app.services.passport_service import passport_out

        trip = _make_trip()
        p = TripPassport(trip_id=trip.id, phase="upcoming", badges=[])
        out = passport_out(p)
        assert "badge_keys" in out
        assert "foodie" in out["badge_keys"]

    def test_early_bird_before_start(self):
        from app.services.passport_service import _rule_early_bird

        # 行程未开始（start 在未来）+ 3 次修订 → True
        trip = _make_trip()
        trip.start_date = date(2040, 10, 20)  # 未来行程
        trip.end_date = date(2040, 10, 22)
        events = [_ev("revise"), _ev("revise"), _ev("revise")]
        assert _rule_early_bird(trip, events) is True

    def test_early_bird_started_false(self):
        from app.services.passport_service import _rule_early_bird as rule

        # 行程已开始（今天 > start）→ False，即使有多次修订
        trip = _make_trip()  # start 2026-10-20，今天 2026-10-28
        assert rule(trip, [_ev("revise"), _ev("revise"), _ev("revise")]) is False

    def test_night_owl(self):
        from app.services.passport_service import _rule_night_owl

        late = datetime(2026, 10, 20, 23, 30, tzinfo=timezone.utc)
        assert _rule_night_owl([_ev("check", dt=late, name="A")]) is True
        early = datetime(2026, 10, 20, 10, 0, tzinfo=timezone.utc)
        assert _rule_night_owl([_ev("check", dt=early, name="A")]) is False


# ── ensure_passport / maybe_award / backfill ──────────────────
class TestPassportService:
    async def test_ensure_creates(self, db_session):
        from app.services.passport_service import ensure_passport

        trip = _make_trip()
        trip.start_date = date(2040, 10, 20)  # 未来行程 → phase=upcoming
        trip.end_date = date(2040, 10, 22)
        await _add(db_session, trip)
        p = await ensure_passport(db_session, trip)
        assert p is not None
        assert p.trip_id == trip.id
        assert p.phase == "upcoming"  # 未来行程

    async def test_maybe_award_first_checkin(self, db_session):
        from app.services.event_service import record_event
        from app.services.passport_service import maybe_award

        trip = _make_trip()
        await _add(db_session, trip)
        await record_event(db_session, trip_id=trip.id, event_type="check",
                           payload={"stop_id": trip.days[0].stops[0].id, "name": "站点1A", "day_number": 1},
                           commit=False)
        p = await maybe_award(db_session, trip)
        assert p is not None
        keys = {b["key"] for b in (p.badges or [])}
        assert "first_checkin" in keys
        assert "full_day" not in keys  # 只打了一个站

    async def test_maybe_award_idempotent(self, db_session):
        from app.services.event_service import record_event
        from app.services.passport_service import maybe_award

        trip = _make_trip()
        await _add(db_session, trip)
        for _ in range(3):  # 多次打卡同一站
            await record_event(db_session, trip_id=trip.id, event_type="check",
                               payload={"stop_id": trip.days[0].stops[0].id, "name": "站点1A", "day_number": 1},
                               commit=False)
        p = await maybe_award(db_session, trip)
        keys = {b["key"] for b in (p.badges or [])}
        assert "first_checkin" in keys
        # 幂等：badges 里 first_checkin 只出现一次
        assert sum(1 for b in (p.badges or []) if b["key"] == "first_checkin") == 1

    async def test_full_day_badge_and_money_saver(self, db_session):
        from app.schemas import ExpenseIn
        from app.services.event_service import record_event
        from app.services.expense_service import add_expense
        from app.services.passport_service import maybe_award

        trip = _make_trip(num_days=1)
        await _add(db_session, trip)
        for s in trip.days[0].stops:
            s.checked = True
            await record_event(db_session, trip_id=trip.id, event_type="check",
                               payload={"stop_id": s.id, "name": s.name, "day_number": 1},
                               commit=False)
        await add_expense(db_session, trip.id, ExpenseIn(category="food", amount=300, payer=""), owner="u-passport")
        p = await maybe_award(db_session, trip)
        keys = {b["key"] for b in (p.badges or [])}
        assert "full_day" in keys
        assert "money_saver" in keys

    async def test_record_event_hook_auto_awards(self, db_session):
        """record_event 后自动触发护照判定（hook 链路）。"""
        from app.services.event_service import record_event
        from app.services.passport_service import get_passport

        trip = _make_trip()
        await _add(db_session, trip)
        await record_event(db_session, trip_id=trip.id, event_type="check",
                           payload={"stop_id": trip.days[0].stops[0].id, "name": "站点1A", "day_number": 1},
                           commit=True)
        p = await get_passport(db_session, trip)
        keys = {b["key"] for b in (p.badges or [])}
        assert "first_checkin" in keys

    async def test_backfill_history(self, db_session):
        from app.services.event_service import record_event
        from app.services.passport_service import backfill, get_passport

        trip = _make_trip()
        await _add(db_session, trip)
        await record_event(db_session, trip_id=trip.id, event_type="check",
                           payload={"stop_id": trip.days[0].stops[0].id, "name": "站点1A", "day_number": 1},
                           commit=True)
        # 清掉护照表（模拟"老行程无护照"）
        from sqlalchemy import delete
        from app.models import TripPassport

        await db_session.execute(delete(TripPassport))
        await db_session.commit()
        p = await backfill(db_session, trip)
        assert p is not None
        keys = {b["key"] for b in (p.badges or [])}
        assert "first_checkin" in keys


# ── API ───────────────────────────────────────────────────────
class TestPassportAPI:
    async def test_get_passport_owner(self, client, db_session):
        trip = _make_trip()
        await _add(db_session, trip)
        from app.services.event_service import record_event

        await record_event(db_session, trip_id=trip.id, event_type="check",
                           payload={"stop_id": trip.days[0].stops[0].id, "name": "站点1A", "day_number": 1},
                           commit=True)
        resp = await client.get(f"/api/v1/trips/{trip.id}/passport")
        assert resp.status_code in (200, 401)  # 未登录 401；有 token 200
        if resp.status_code == 200:
            data = resp.json()
            assert "badges" in data
            assert data["trip_id"] == trip.id

    async def test_get_passport_shared_token(self, client, db_session):
        trip = _make_trip()
        await _add(db_session, trip)
        trip.share_token = "tok-passport"
        await db_session.commit()
        resp = await client.get("/api/v1/trips/share/tok-passport/passport")
        # 免登录：200（无需 auth）
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "badges" in data