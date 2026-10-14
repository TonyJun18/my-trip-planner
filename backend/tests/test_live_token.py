"""task-live-today-view · 免登录令牌版：分享/受邀编辑 live 端点测试。

覆盖（可选增强：分享页同伴操作）：
1. GET  /share/{token}/live —— 只读分享令牌可看行中快照（无写端点）
2. GET  /edit/{token}/live —— 受邀编辑令牌可看行中快照
3. POST /edit/{token}/live/stops/{id}/check —— 免登录打卡/取消
4. POST /edit/{token}/live/stops/{id}/skip —— 免登录跳过
5. POST /edit/{token}/live/delay —— 免登录迟到顺延（日期 +1）
6. 生命周期门禁：edit_token 被收回后 live 端点返回 404（与受邀编辑同语义）

时区稳定性：monkeypatch live_service.datetime（固定 UTC 日期）。
"""
from __future__ import annotations

from datetime import date, datetime, timezone


class _FakeDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 10, 14, 4, 0, 0, tzinfo=timezone.utc)


async def _make_live_trip_with_tokens(client, headers, *, start: date, end: date):
    """建行中行程 + 1 天 2 站点 + share_token + edit_token。

    返回 (trip_id, share_token, edit_token, stop_ids)。
    """
    resp = await client.post("/api/v1/trips", json={
        "title": "令牌行中", "destination": "杭州",
        "start_date": start.isoformat(), "end_date": end.isoformat(),
        "travelers": 1, "budget": 1000,
    }, headers=headers)
    assert resp.status_code == 201, resp.text
    trip_id = resp.json()["id"]

    # 分享令牌
    resp = await client.post(f"/api/v1/trips/{trip_id}/share", headers=headers)
    assert resp.status_code == 200, resp.text
    share_token = resp.json()["share_token"]

    # 受邀编辑令牌
    resp = await client.post(f"/api/v1/trips/{trip_id}/share/edit", headers=headers)
    assert resp.status_code == 200, resp.text
    edit_token = resp.json()["edit_token"]

    # 日程 + 站点
    resp = await client.post(f"/api/v1/trips/{trip_id}/days",
                             json={"day_number": 1, "date": start.isoformat()}, headers=headers)
    assert resp.status_code == 201, resp.text
    day_id = resp.json()["id"]

    stop_ids = []
    for name in ("西湖", "灵隐寺"):
        r = await client.post(f"/api/v1/trips/days/{day_id}/stops", json={
            "name": name, "stop_type": "attraction",
            "estimated_cost": 50, "estimated_duration_minutes": 120,
        }, headers=headers)
        assert r.status_code == 201, r.text
        stop_ids.append(r.json()["id"])
    return trip_id, share_token, edit_token, stop_ids


class TestShareTokenLiveReadonly:
    async def test_share_token_reads_live_snapshot(self, client, auth_user, monkeypatch):
        """只读分享令牌可看行中快照（无写端点，只读语义）。"""
        from app.services import live_service

        monkeypatch.setattr(live_service, "datetime", _FakeDatetime)
        user_info, headers = auth_user
        _, share_token, _, _ = await _make_live_trip_with_tokens(
            client, headers, start=date(2026, 10, 14), end=date(2026, 10, 14))

        resp = await client.get(f"/api/v1/trips/share/{share_token}/live")
        assert resp.status_code == 200, resp.text
        snap = resp.json()
        assert snap["phase"] == "live"
        assert snap["total"] == 2
        assert snap["stops"][0]["name"] == "西湖"

    async def test_share_token_rejected_for_write_ops(self, client, auth_user, monkeypatch):
        """分享令牌只有读：写端点（/edit/...）对其返回 404（令牌无效）。"""
        from app.services import live_service

        monkeypatch.setattr(live_service, "datetime", _FakeDatetime)
        user_info, headers = auth_user
        _, share_token, _, (stop_a, _) = await _make_live_trip_with_tokens(
            client, headers, start=date(2026, 10, 14), end=date(2026, 10, 14))

        # 用 share_token 当 edit_token 调写端点 → 无效（该行程 edit_token 是另一个值）
        resp = await client.post(
            f"/api/v1/trips/edit/{share_token}/live/stops/{stop_a}/check",
            json={"checked": True})
        assert resp.status_code == 404, resp.text


class TestEditTokenLiveOps:
    async def test_edit_token_live_snapshot(self, client, auth_user, monkeypatch):
        """受邀编辑令牌可看行中快照。"""
        from app.services import live_service

        monkeypatch.setattr(live_service, "datetime", _FakeDatetime)
        user_info, headers = auth_user
        _, _, edit_token, _ = await _make_live_trip_with_tokens(
            client, headers, start=date(2026, 10, 14), end=date(2026, 10, 14))

        resp = await client.get(f"/api/v1/trips/edit/{edit_token}/live")
        assert resp.status_code == 200, resp.text
        assert resp.json()["phase"] == "live"

    async def test_edit_token_check_and_skip_and_delay(self, client, auth_user, monkeypatch, db_session):
        """免登录打卡 → 跳过 → 迟到顺延 全流程（结果与 owner 版一致）。"""
        from app.services import live_service

        monkeypatch.setattr(live_service, "datetime", _FakeDatetime)
        user_info, headers = auth_user
        trip_id, _, edit_token, (stop_a, stop_b) = await _make_live_trip_with_tokens(
            client, headers, start=date(2026, 10, 14), end=date(2026, 10, 14))

        # 打卡 A
        resp = await client.post(
            f"/api/v1/trips/edit/{edit_token}/live/stops/{stop_a}/check",
            json={"checked": True})
        assert resp.status_code == 200, resp.text
        assert resp.json()["completed"] == 1

        # 跳过 B
        resp = await client.post(
            f"/api/v1/trips/edit/{edit_token}/live/stops/{stop_b}/skip")
        assert resp.status_code == 200, resp.text
        assert resp.json()["total"] == 1
        assert [s["name"] for s in resp.json()["stops"]] == ["西湖"]

        # 迟到顺延（日期 +1；结束日期同步）
        resp = await client.post(f"/api/v1/trips/edit/{edit_token}/live/delay")
        assert resp.status_code == 200, resp.text
        assert resp.json()["phase"] == "live"
        # 落库验证（用 db_session 查）：end_date +1
        from sqlalchemy import select as _select

        from app.models import Trip as _Trip

        row = (await db_session.execute(
            _select(_Trip).where(_Trip.id == trip_id)
        )).scalar_one()
        assert row.end_date == date(2026, 10, 15)

    async def test_edit_token_revoked_returns_404(self, client, auth_user, monkeypatch):
        """edit_token 被 owner 收回后，行中端点返回 404（与受邀编辑同语义）。"""
        from app.services import live_service

        monkeypatch.setattr(live_service, "datetime", _FakeDatetime)
        user_info, headers = auth_user
        trip_id, _, edit_token, (stop_a, _) = await _make_live_trip_with_tokens(
            client, headers, start=date(2026, 10, 14), end=date(2026, 10, 14))

        # 收回
        resp = await client.delete(f"/api/v1/trips/{trip_id}/share/edit", headers=headers)
        assert resp.status_code == 204, resp.text

        resp = await client.get(f"/api/v1/trips/edit/{edit_token}/live")
        assert resp.status_code == 404, resp.text

        resp = await client.post(
            f"/api/v1/trips/edit/{edit_token}/live/stops/{stop_a}/check",
            json={"checked": True})
        assert resp.status_code == 404, resp.text