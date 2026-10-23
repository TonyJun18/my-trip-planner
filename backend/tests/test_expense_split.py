"""task-expense-split-mini：行中费用记录与人均结余测试。

覆盖：
1. compute_balance 纯函数（分摊口径：多人/单人/未指定支付人/空列表/异常人数）
2. add_expense 落库 + 归属校验（他人 404）+ 空 payer 归一
3. delete_expense 删除 + 删除他人记录 404 + 不存在 404
4. list_expenses 列表 + 汇总
5. API 端到端（POST /expenses → GET 汇总 → DELETE → 分摊重算）
"""
from __future__ import annotations

from app.models import TripExpense


# ── 纯函数：compute_balance ──────────────────────────────────────
def _rec(amount: float, payer: str = "", category: str = "other") -> TripExpense:
    return TripExpense(
        id="x", trip_id="t1", category=category,
        amount=amount, payer=payer, note=None,
    )


class TestComputeBalance:
    def test_empty_records(self):
        from app.services.expense_service import compute_balance

        b = compute_balance([], travelers=1)
        assert b["total"] == 0.0
        assert b["per_person"] == 0.0
        assert b["balances"] == {}
        assert b["unassigned"] == 0.0
        assert b["count"] == 0

    def test_single_payer_balances_positive(self):
        """一人垫付 300，两人行程 → 人均 150，结余 +150（别人欠他）。"""
        from app.services.expense_service import compute_balance

        b = compute_balance([_rec(300, "小彭")], travelers=2)
        assert b["total"] == 300.0
        assert b["per_person"] == 150.0
        assert b["balances"] == {"小彭": 150.0}
        assert b["unassigned"] == 0.0

    def test_two_payers_settle(self):
        """两人 AA：300/2 = 150 人均，小彭付 200（+50），阿兰付 100（-50）。"""
        from app.services.expense_service import compute_balance

        b = compute_balance(
            [_rec(200, "小彭"), _rec(100, "阿兰")],
            travelers=2,
        )
        assert b["per_person"] == 150.0
        assert b["balances"] == {"小彭": 50.0, "阿兰": -50.0}

    def test_unassigned_excluded_from_balance(self):
        """未指定支付人的记录计入 total，但不参与分摊。"""
        from app.services.expense_service import compute_balance

        b = compute_balance([_rec(100, "小彭"), _rec(60, "")], travelers=2)
        assert b["total"] == 160.0
        assert b["per_person"] == 50.0  # 只算 assigned 100
        assert b["balances"] == {"小彭": 50.0}
        assert b["unassigned"] == 60.0

    def test_travelers_guard_never_divide_by_zero(self):
        """travelers < 1 视为 1，不除零。"""
        from app.services.expense_service import compute_balance

        b = compute_balance([_rec(100, "小彭")], travelers=0)
        assert b["per_person"] == 100.0

    def test_multiple_records_same_payer_aggregate(self):
        from app.services.expense_service import compute_balance

        b = compute_balance(
            [_rec(50, "小彭"), _rec(60, "小彭"), _rec(30, "阿兰")],
            travelers=2,
        )
        assert b["total"] == 140.0
        assert b["per_person"] == 70.0
        assert b["balances"] == {"小彭": 40.0, "阿兰": -40.0}

    def test_rounding_to_cents(self):
        from app.services.expense_service import compute_balance

        # 100 / 3 = 33.333... → 人均 33.33；小彭付 100 → 结余 66.67
        b = compute_balance([_rec(100, "小彭")], travelers=3)
        assert b["per_person"] == 33.33
        assert b["balances"] == {"小彭": 66.67}


# ── 服务层：增删查 ────────────────────────────────────────────────
async def _make_trip(db_session, *, travelers: int = 2, owner: str = "u-expense"):
    from datetime import date

    from app.models import Trip, TripDay

    trip = Trip(
        owner=owner,
        title="费用测试",
        destination="杭州",
        start_date=date(2026, 10, 20),
        end_date=date(2026, 10, 21),
        travelers=travelers,
    )
    trip.days.append(TripDay(day_number=1, date=date(2026, 10, 20)))
    db_session.add(trip)
    await db_session.flush()
    return trip


class TestExpenseService:
    async def test_add_and_list(self, db_session):
        from app.schemas import ExpenseIn
        from app.services.expense_service import add_expense, list_expenses

        trip = await _make_trip(db_session)
        e1 = await add_expense(
            db_session, trip.id, ExpenseIn(category="food", amount=120, payer="小彭", note="晚餐"),
            owner="u-expense",
        )
        e2 = await add_expense(
            db_session, trip.id, ExpenseIn(category="transport", amount=60, payer=""),
            owner="u-expense",
        )
        records, balance = await list_expenses(db_session, trip.id, owner="u-expense")
        assert [r.id for r in records] == [e1.id, e2.id]
        assert records[0].payer == "小彭"
        assert records[0].note == "晚餐"
        assert balance["total"] == 180.0
        assert balance["per_person"] == 60.0  # 120/2
        assert balance["balances"] == {"小彭": 60.0}
        assert balance["unassigned"] == 60.0

    async def test_add_rejects_foreign_owner(self, db_session):
        from app.core.exceptions import NotFoundError
        from app.schemas import ExpenseIn
        from app.services.expense_service import add_expense

        trip = await _make_trip(db_session, owner="u-a")
        try:
            await add_expense(
                db_session, trip.id, ExpenseIn(category="food", amount=10, payer="小彭"),
                owner="u-b",
            )
            raise AssertionError("应抛出 NotFoundError")
        except NotFoundError:
            pass

    async def test_delete_and_recompute(self, db_session):
        from app.schemas import ExpenseIn
        from app.services.expense_service import add_expense, delete_expense, list_expenses

        trip = await _make_trip(db_session)
        e1 = await add_expense(
            db_session, trip.id, ExpenseIn(category="food", amount=120, payer="小彭"),
            owner="u-expense",
        )
        await add_expense(
            db_session, trip.id, ExpenseIn(category="food", amount=80, payer="小彭"),
            owner="u-expense",
        )
        await delete_expense(db_session, trip.id, e1.id, owner="u-expense")

        records, balance = await list_expenses(db_session, trip.id, owner="u-expense")
        assert len(records) == 1
        assert balance["total"] == 80.0
        assert balance["balances"] == {"小彭": 40.0}  # 80/2

    async def test_delete_missing_raises(self, db_session):
        from app.core.exceptions import NotFoundError
        from app.services.expense_service import delete_expense

        trip = await _make_trip(db_session)
        try:
            await delete_expense(db_session, trip.id, "no-such-id", owner="u-expense")
            raise AssertionError("应抛出 NotFoundError")
        except NotFoundError:
            pass

    async def test_delete_foreign_owner_rejected(self, db_session):
        from app.core.exceptions import NotFoundError
        from app.schemas import ExpenseIn
        from app.services.expense_service import add_expense, delete_expense

        trip = await _make_trip(db_session, owner="u-a")
        e1 = await add_expense(
            db_session, trip.id, ExpenseIn(category="food", amount=10, payer="小彭"),
            owner="u-a",
        )
        try:
            await delete_expense(db_session, trip.id, e1.id, owner="u-b")
            raise AssertionError("应抛出 NotFoundError")
        except NotFoundError:
            pass


# ── API 端到端 ───────────────────────────────────────────────────
async def _make_api_trip(client, headers, *, travelers: int = 2):
    resp = await client.post("/api/v1/trips", json={
        "title": "费用 API", "destination": "杭州",
        "start_date": "2026-10-20", "end_date": "2026-10-21",
        "travelers": travelers, "budget": 1000,
    }, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


class TestExpenseAPI:
    async def test_full_flow(self, client, auth_user):
        """记两笔 → 列表含汇总 → 删除一笔 → 汇总重算。"""
        _, headers = auth_user
        trip_id = await _make_api_trip(client, headers)

        resp = await client.post(f"/api/v1/trips/{trip_id}/expenses", json={
            "category": "food", "amount": 120, "payer": "小彭", "note": "晚餐",
        }, headers=headers)
        assert resp.status_code == 201, resp.text
        e1 = resp.json()

        resp = await client.post(f"/api/v1/trips/{trip_id}/expenses", json={
            "category": "transport", "amount": 60, "payer": "",
        }, headers=headers)
        assert resp.status_code == 201, resp.text
        e2 = resp.json()
        assert e2["payer"] == ""

        resp = await client.get(f"/api/v1/trips/{trip_id}/expenses", headers=headers)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert [i["id"] for i in data["items"]] == [e1["id"], e2["id"]]
        assert data["balance"]["total"] == 180.0
        assert data["balance"]["per_person"] == 60.0
        assert data["balance"]["balances"] == {"小彭": 60.0}

        # 删除第一笔 → 分摊重算
        resp = await client.delete(
            f"/api/v1/trips/{trip_id}/expenses/{e1['id']}", headers=headers)
        assert resp.status_code == 204, resp.text
        resp = await client.get(f"/api/v1/trips/{trip_id}/expenses", headers=headers)
        data = resp.json()
        assert len(data["items"]) == 1
        assert data["balance"]["total"] == 60.0

    async def test_requires_auth(self, client):
        resp = await client.get("/api/v1/trips/whatever/expenses")
        assert resp.status_code in (401, 403)

    async def test_validation_amount_must_be_positive(self, client, auth_user):
        _, headers = auth_user
        trip_id = await _make_api_trip(client, headers)

        resp = await client.post(f"/api/v1/trips/{trip_id}/expenses", json={
            "category": "food", "amount": 0, "payer": "小彭",
        }, headers=headers)
        assert resp.status_code == 422, resp.text

    async def test_foreign_owner_404(self, client, auth_user):
        """别人的行程 → 费用接口 404（不可见）。"""
        _, headers = auth_user
        trip_id = await _make_api_trip(client, headers)

        # 第二个用户
        import uuid

        email = f"other-{uuid.uuid4().hex[:8]}@test.com"
        resp = await client.post("/api/v1/auth/register", json={
            "email": email, "password": "test1234", "display_name": "别的用户",
        })
        other_headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}

        resp = await client.get(f"/api/v1/trips/{trip_id}/expenses", headers=other_headers)
        assert resp.status_code == 404, resp.text

    async def test_unknown_trip_404(self, client, auth_user):
        _, headers = auth_user
        resp = await client.get("/api/v1/trips/no-such-id/expenses", headers=headers)
        assert resp.status_code == 404, resp.text

    async def test_share_token_not_expose_expenses(self, client, auth_user):
        """只读分享链路不带费用（财务数据不暴露给任意链接持有者）。"""
        _, headers = auth_user
        trip_id = await _make_api_trip(client, headers)
        await client.post(f"/api/v1/trips/{trip_id}/expenses", json={
            "category": "food", "amount": 120, "payer": "小彭",
        }, headers=headers)

        resp = await client.post(f"/api/v1/trips/{trip_id}/share", headers=headers)
        share_token = resp.json()["share_token"]
        resp = await client.get(f"/api/v1/trips/share/{share_token}")
        assert resp.status_code == 200, resp.text
        assert "expenses" not in resp.json()
        assert "balance" not in resp.json()