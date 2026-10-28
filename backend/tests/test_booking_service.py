"""task-booking-outlink：预订服务测试。

覆盖：
1. _deeplink / build_deeplink 纯函数（train/hotel/未知 provider/manual/参数缺失）
2. upsert_booking 落库 + 幂等（同 provider+order_no 更新）+ 归属校验（他人 404）
3. update_booking_status 状态机（suggested→confirmed 带凭证 / 无凭证拒绝 /
   cancelled / 事件记录）
4. list_bookings / delete_booking
5. BookingStep 生成 plan.bookings（train + hotel / 无 transport / 兜底候选池）

全部不依赖外部环境（纯规则/内存 ORM，无 LLM/无网络）。
"""
from __future__ import annotations

from datetime import date

from app.models import Trip, TripDay


# ── 纯函数：_deeplink ───────────────────────────────────────────
class TestDeeplink:
    def test_train_url_ctrip(self):
        from app.services.booking_service import build_deeplink

        url = build_deeplink("ctrip", "train", {
            "departure": "杭州", "destination": "上海", "date": "2026-10-30",
        })
        assert url and "from=杭州" in url and "to=上海" in url and "2026-10-30" in url

    def test_hotel_url_ctrip(self):
        from app.services.booking_service import build_deeplink

        url = build_deeplink("ctrip", "hotel", {"city": "杭州"})
        assert url and "hotellist" in url and "city=" in url

    def test_train_missing_departure_returns_none(self):
        from app.services.booking_service import build_deeplink

        assert build_deeplink("ctrip", "train", {"destination": "上海", "date": "2026-10-30"}) is None

    def test_manual_returns_none(self):
        from app.services.booking_service import build_deeplink

        assert build_deeplink("manual", "train", {}) is None

    def test_unknown_provider_falls_back_to_home(self):
        from app.services.booking_service import build_deeplink

        url = build_deeplink("feizhu", "train", {"departure": "杭州", "destination": "上海", "date": "x"})
        assert url and "fliggy" in url


# ── 服务层 ──────────────────────────────────────────────────────
async def _make_trip(db_session, *, owner: str = "u-booking") -> Trip:
    trip = Trip(
        owner=owner,
        title="预订测试",
        destination="杭州",
        start_date=date(2026, 10, 20),
        end_date=date(2026, 10, 21),
        travelers=1,
    )
    trip.days.append(TripDay(day_number=1, date=date(2026, 10, 20)))
    db_session.add(trip)
    await db_session.flush()
    return trip


class TestUpsertBooking:
    async def test_add_suggested(self, db_session):
        from app.schemas import BookingIn
        from app.services.booking_service import list_bookings, upsert_booking

        trip = await _make_trip(db_session)
        b = await upsert_booking(
            db_session, trip.id,
            BookingIn(
                kind="train", provider="ctrip", title="杭州→上海",
                provider_url="https://m.ctrip.com/...", status="suggested",
                reference="plan.generated", order_no=None,
            ),
            owner="u-booking",
        )
        assert b.status == "suggested"
        assert b.reference == "plan.generated"
        assert b.amount is None
        items = await list_bookings(db_session, trip.id, owner="u-booking")
        assert len(items) == 1

    async def test_confirmed_requires_order_no(self, db_session):
        from app.core.exceptions import AppError
        from app.schemas import BookingIn
        from app.services.booking_service import upsert_booking

        trip = await _make_trip(db_session)
        try:
            await upsert_booking(
                db_session, trip.id,
                BookingIn(kind="train", provider="ctrip", status="confirmed", reference="user.confirmed"),
                owner="u-booking",
            )
            assert False, "应拒绝无凭证的 confirmed"
        except AppError as exc:
            assert exc.code == "booking_invalid_transition"

    async def test_upsert_idempotent_same_order_no(self, db_session):
        from app.schemas import BookingIn
        from app.services.booking_service import list_bookings, upsert_booking

        trip = await _make_trip(db_session)
        b1 = await upsert_booking(
            db_session, trip.id,
            BookingIn(
                kind="train", provider="ctrip", title="杭州→上海", order_no="CT20261030",
                status="suggested",
            ),
            owner="u-booking",
        )
        b2 = await upsert_booking(
            db_session, trip.id,
            BookingIn(
                kind="train", provider="ctrip", title="杭州→上海", order_no="CT20261030",
                status="confirmed", reference="user.confirmed", credential="AB123",
            ),
            owner="u-booking",
        )
        assert b1.id == b2.id  # 同 order_no 幂等更新
        assert b2.status == "confirmed"
        assert b2.credential == "AB123"
        items = await list_bookings(db_session, trip.id, owner="u-booking")
        assert len(items) == 1

    async def test_owner_isolation(self, db_session):
        from app.core.exceptions import NotFoundError
        from app.schemas import BookingIn
        from app.services.booking_service import upsert_booking

        trip = await _make_trip(db_session)
        try:
            await upsert_booking(db_session, trip.id, BookingIn(kind="train"), owner="other-user")
            assert False, "他人不应能新增预订"
        except NotFoundError:
            pass


class TestUpdateStatus:
    async def test_confirm_records_event(self, db_session):
        from app.schemas import BookingIn, BookingStatusIn
        from app.services.booking_service import update_booking_status, upsert_booking

        trip = await _make_trip(db_session)
        b = await upsert_booking(
            db_session, trip.id,
            BookingIn(kind="hotel", provider="ctrip", title="杭州大酒店", status="suggested", reference="plan.generated"),
            owner="u-booking",
        )
        updated = await update_booking_status(
            db_session, trip.id, b.id,
            BookingStatusIn(status="confirmed", order_no="HZ8888", credential="CN123"),
            owner="u-booking",
        )
        assert updated.status == "confirmed"
        assert updated.order_no == "HZ8888"

    async def test_confirm_without_credential_rejected(self, db_session):
        from app.core.exceptions import AppError
        from app.schemas import BookingIn, BookingStatusIn
        from app.services.booking_service import update_booking_status, upsert_booking

        trip = await _make_trip(db_session)
        b = await upsert_booking(
            db_session, trip.id,
            BookingIn(kind="train", status="suggested", reference="plan.generated"),
            owner="u-booking",
        )
        try:
            await update_booking_status(
                db_session, trip.id, b.id,
                BookingStatusIn(status="confirmed"),  # 无 order_no/credential
                owner="u-booking",
            )
            assert False, "应拒绝无凭证的 confirmed"
        except AppError as exc:
            assert exc.code == "booking_invalid_transition"

    async def test_cancel_records_event(self, db_session):
        from app.schemas import BookingIn, BookingStatusIn
        from app.services.booking_service import update_booking_status, upsert_booking

        trip = await _make_trip(db_session)
        b = await upsert_booking(
            db_session, trip.id,
            BookingIn(kind="train", status="confirmed", order_no="X1", credential="C1",
                      reference="user.confirmed"),
            owner="u-booking",
        )
        updated = await update_booking_status(
            db_session, trip.id, b.id, BookingStatusIn(status="cancelled"), owner="u-booking"
        )
        assert updated.status == "cancelled"
        assert updated.cancelled_at is not None


class TestListDelete:
    async def test_delete_own(self, db_session):
        from app.schemas import BookingIn
        from app.services.booking_service import delete_booking, list_bookings, upsert_booking

        trip = await _make_trip(db_session)
        b = await upsert_booking(
            db_session, trip.id,
            BookingIn(kind="train", status="suggested", reference="plan.generated"),
            owner="u-booking",
        )
        await delete_booking(db_session, trip.id, b.id, owner="u-booking")
        assert len(await list_bookings(db_session, trip.id, owner="u-booking")) == 0


# ── BookingStep：plan.bookings 生成 ─────────────────────────────
class TestBookingStep:
    async def test_generates_train_and_hotel(self):
        from app.agent.pipeline import BookingStep
        from app.agent.pipeline import PipelineContext

        plan = {
            "destination": "杭州",
            "days": [{
                "day_number": 1,
                "stops": [
                    {"name": "灵隐寺", "type": "attraction"},
                    {"name": "杭州西湖大酒店", "type": "hotel", "estimated_cost": 500},
                ],
            }],
            "transport": {
                "options": [
                    {"mode": "高铁", "price": 73},
                    {"mode": "飞机", "price": 400},
                ],
            },
        }
        request = {"departure": "上海", "destination": "杭州", "start_date": "2026-10-30"}
        step = BookingStep()
        result = await step.run(PipelineContext(request), plan=plan, trace=[])
        assert isinstance(result, dict)
        assert "bookings" in result
        bookings = result["bookings"]
        kinds = {b["kind"] for b in bookings}
        assert "train" in kinds and "hotel" in kinds
        train = next(b for b in bookings if b["kind"] == "train")
        assert train["provider_url"] and "from=" in train["provider_url"]
        assert train["price_estimate"] == 73  # 最低单程
        assert train["status"] == "suggested"
        assert train["reference"] == "plan.generated"

    async def test_no_transport_skips_train(self):
        from app.agent.pipeline import BookingStep, PipelineContext

        plan = {"destination": "杭州", "days": [], "transport": {}}
        request = {"departure": "上海", "destination": "杭州"}
        step = BookingStep()
        result = await step.run(PipelineContext(request), plan=plan, trace=[])
        assert "bookings" in result
        assert all(b["kind"] != "train" for b in result["bookings"])

    async def test_hotel_fallback_to_candidates(self):
        from app.agent.pipeline import BookingStep, PipelineContext

        plan = {
            "destination": "杭州",
            "days": [{"day_number": 1, "stops": [{"name": "灵隐寺", "type": "attraction"}]}],
            "hotels": [
                {"name": "杭州大酒店", "estimated_cost": 400},
                {"name": "西湖民宿", "estimated_cost": 300},
            ],
        }
        request = {"destination": "杭州"}
        step = BookingStep()
        result = await step.run(PipelineContext(request), plan=plan, trace=[])
        hotels = [b for b in result["bookings"] if b["kind"] == "hotel"]
        assert len(hotels) == 2
        assert {h["title"] for h in hotels} == {"杭州大酒店", "西湖民宿"}

    async def test_empty_plan_no_bookings(self):
        from app.agent.pipeline import BookingStep, PipelineContext

        step = BookingStep()
        result = await step.run(PipelineContext({"destination": "杭州"}), plan={"destination": "杭州"}, trace=[])
        assert result.get("bookings") == []