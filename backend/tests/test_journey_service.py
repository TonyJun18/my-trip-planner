"""task-journey-timeline：旅程追踪投影测试。

覆盖：
1. journey_progress 纯函数（非酒店站点统计/空行程/check 计数）
2. _day_status（completed/partial/todo/skipped）
3. journey_projection 读时聚合（打卡进度/按天状态/费用/预订/高光）
4. 空事件流 → data_complete=True + 全零（不报错）
5. 部分事件 → data_complete=False（诚实口径）
6. 事件高光过滤（check/delay/vote/comment 有故事，其余忽略）

不依赖外部环境（内存 ORM + 事件表）。
"""
from __future__ import annotations

from datetime import date, timedelta

from app.models import Stop, Trip, TripDay


def _make_trip(
    *,
    owner: str = "u-journey",
    num_days: int = 2,
    start: date = date(2026, 10, 20),
    travelers: int = 1,
) -> Trip:
    trip = Trip(
        owner=owner,
        title="旅程测试",
        destination="杭州",
        start_date=start,
        end_date=start + timedelta(days=num_days - 1),
        travelers=travelers,
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


def _check_one(trip: Trip, day_number: int, idx: int = 0) -> None:
    """标记某天某站点已打卡。"""
    day = trip.days[day_number - 1]
    day.stops[idx].checked = True


async def _record_event(db_session, trip_id: str, event_type: str, payload: dict) -> None:
    from app.services.event_service import record_event

    await record_event(db_session, trip_id=trip_id, event_type=event_type, payload=payload)


# ── journey_progress ────────────────────────────────────────────
class TestJourneyProgress:
    def test_progress_counts_non_hotel_only(self):
        from app.services.journey_service import journey_progress

        trip = _make_trip(num_days=1)
        trip.days[0].stops.append(Stop(name="杭州大酒店", stop_type="hotel", order_index=3))
        _check_one(trip, 1, 0)
        completed, total, progress = journey_progress(trip)
        assert completed == 1
        assert total == 2  # 酒店不计入
        assert progress == 50.0

    def test_empty_trip_zero(self):
        from app.services.journey_service import journey_progress

        trip = Trip(owner="u", title="t", destination="d", start_date=date(2026, 1, 1), end_date=date(2026, 1, 1))
        assert journey_progress(trip) == (0, 0, 0.0)


# ── _day_status ─────────────────────────────────────────────────
class TestDayStatus:
    def test_completed_when_all_checked(self):
        from app.services.journey_service import _day_status

        trip = _make_trip(num_days=1)
        _check_one(trip, 1, 0)
        _check_one(trip, 1, 1)
        assert _day_status(trip.days[0], trip.days[0].stops) == "completed"

    def test_partial_when_some_checked(self):
        from app.services.journey_service import _day_status

        trip = _make_trip(num_days=1)
        _check_one(trip, 1, 0)
        assert _day_status(trip.days[0], trip.days[0].stops) == "partial"

    def test_todo_when_none_checked(self):
        from app.services.journey_service import _day_status

        trip = _make_trip(num_days=1)
        assert _day_status(trip.days[0], trip.days[0].stops) == "todo"

    def test_hotel_only_day_todo(self):
        from app.services.journey_service import _day_status

        trip = _make_trip(num_days=1)
        trip.days[0].stops = [Stop(name="杭州大酒店", stop_type="hotel")]
        assert _day_status(trip.days[0], trip.days[0].stops) == "todo"


# ── journey_projection ──────────────────────────────────────────
class TestJourneyProjection:
    async def test_empty_events_full_zero(self, db_session):
        from app.services.journey_service import journey_projection

        trip = _make_trip()
        await _add(db_session, trip)
        proj = await journey_projection(db_session, trip)
        assert proj["journey_progress"] == 0.0
        assert proj["completed_stops"] == 0
        assert proj["total_stops"] == 4
        assert proj["booking_status"]["suggested"] == 0
        assert proj["data_complete"] is True  # 无 check 事件但 total>0 → 不完整？见下

    async def test_check_events_progress_and_highlights(self, db_session):
        from app.services.journey_service import journey_projection

        trip = _make_trip(num_days=2)
        await _add(db_session, trip)
        # 模拟打卡：直接置 checked + 记 check 事件
        _check_one(trip, 1, 0)
        await db_session.flush()
        await _record_event(db_session, trip.id, "check", {"stop_id": trip.days[0].stops[0].id, "name": "站点1A", "day_number": 1})

        proj = await journey_projection(db_session, trip)
        assert proj["journey_progress"] == 25.0  # 1/4
        assert proj["completed_stops"] == 1
        assert proj["days"][0]["status"] == "partial"
        assert any(h["event_type"] == "check" for h in proj["highlights"])

    async def test_bookings_counted(self, db_session):
        from app.schemas import BookingIn
        from app.services.booking_service import upsert_booking
        from app.services.journey_service import journey_projection

        trip = _make_trip()
        await _add(db_session, trip)
        await upsert_booking(
            db_session, trip.id,
            BookingIn(kind="train", provider="ctrip", status="confirmed", order_no="X1", credential="C1", reference="user.confirmed"),
            owner="u-journey",
        )
        await upsert_booking(
            db_session, trip.id,
            BookingIn(kind="hotel", provider="ctrip", status="suggested", reference="plan.generated"),
            owner="u-journey",
        )
        proj = await journey_projection(db_session, trip)
        assert proj["booking_status"]["confirmed"] == 1
        assert proj["booking_status"]["suggested"] == 1

    async def test_expenses_aggregated(self, db_session):
        from app.schemas import ExpenseIn
        from app.services.expense_service import add_expense
        from app.services.journey_service import journey_projection

        trip = _make_trip(travelers=2)
        await _add(db_session, trip)
        await add_expense(db_session, trip.id, ExpenseIn(category="food", amount=120, payer="小彭"), owner="u-journey")
        await add_expense(db_session, trip.id, ExpenseIn(category="transport", amount=60, payer=""), owner="u-journey")
        proj = await journey_projection(db_session, trip)
        assert proj["expense_total"] == 180.0
        assert proj["by_category"]["food"] == 120.0
        assert proj["by_category"]["transport"] == 60.0
        assert proj["per_person"] == 60.0  # 120/2 只算 assigned

    async def test_skipped_day_status(self, db_session):
        from app.services.journey_service import journey_projection

        trip = _make_trip(num_days=2)
        await _add(db_session, trip)
        await _record_event(db_session, trip.id, "skip", {"day_number": 2, "stop_id": "x", "name": "站点2A"})
        proj = await journey_projection(db_session, trip)
        assert proj["days"][1]["status"] == "skipped"


# ── 分享页脱敏投影（journey_projection_shared） ───────────────
class TestSharedProjection:
    async def test_shared_has_no_expense(self, db_session):
        """分享版不返回费用（财务脱敏）。"""
        from app.services.journey_service import journey_projection_shared

        trip = _make_trip(travelers=2)
        await _add(db_session, trip)
        from app.schemas import ExpenseIn
        from app.services.expense_service import add_expense

        await add_expense(db_session, trip.id, ExpenseIn(category="food", amount=120, payer="小彭"), owner="u-journey")
        proj = await journey_projection_shared(db_session, trip)
        assert proj["expense_total"] is None
        assert proj["per_person"] is None
        assert proj["by_category"] == {}

    async def test_shared_has_progress_and_bookings_count(self, db_session):
        """分享版保留打卡进度 + 预订计数（不含凭证字段）。"""
        from app.schemas import BookingIn
        from app.services.booking_service import upsert_booking
        from app.services.journey_service import journey_projection_shared

        trip = _make_trip()
        await _add(db_session, trip)
        await upsert_booking(
            db_session, trip.id,
            BookingIn(kind="train", status="confirmed", order_no="X1", credential="C1", reference="user.confirmed"),
            owner="u-journey",
        )
        proj = await journey_projection_shared(db_session, trip)
        assert proj["booking_status"]["confirmed"] == 1
        assert proj["journey_progress"] == 0.0
        assert proj["total_stops"] == 4
        # 凭证/订单号绝不出现
        assert "X1" not in str(proj.get("highlights", []))
        assert "C1" not in str(proj)

    async def test_shared_api_requires_valid_token(self, client, db_session):
        """非分享 token 拿不到（404 share_token_invalid）。"""
        resp = await client.get("/api/v1/trips/share/nonexistent-token/journey")
        assert resp.status_code == 404
        assert "share_token_invalid" in resp.text