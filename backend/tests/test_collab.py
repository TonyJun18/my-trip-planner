"""分享页协作 API 测试：评论 + 站点投票（免登录，凭 share_token）。"""
from __future__ import annotations


async def _make_shared_trip(client, headers) -> tuple[str, str, str]:
    """建行程 + Day + 站点 → 生成分享 token → 返回 (trip_id, token, stop_id)。"""
    from datetime import date

    today = date.today()
    resp = await client.post("/api/v1/trips", json={
        "title": "杭州三日游", "destination": "杭州",
        "start_date": today.isoformat(), "end_date": today.isoformat(),
        "travelers": 2, "budget": 3000,
    }, headers=headers)
    assert resp.status_code == 201, resp.text
    trip_id = resp.json()["id"]

    resp = await client.post(f"/api/v1/trips/{trip_id}/days", json={"day_number": 1, "note": "第一天"}, headers=headers)
    assert resp.status_code == 201, resp.text
    day_id = resp.json()["id"]

    resp = await client.post(f"/api/v1/trips/days/{day_id}/stops", json={
        "name": "西湖", "stop_type": "attraction", "lat": 30.245, "lng": 120.15,
        "estimated_cost": 0, "description": "环湖",
    }, headers=headers)
    assert resp.status_code == 201, resp.text
    stop_id = resp.json()["id"]

    resp = await client.post(f"/api/v1/trips/{trip_id}/share", headers=headers)
    assert resp.status_code == 200, resp.text
    token = resp.json()["share_token"]
    return trip_id, token, stop_id


# ── 评论 ─────────────────────────────────────────────────────
async def test_share_comments_flow(client, auth_user):
    """免登录发表评论 → 列表可见（时间正序）→ 空评论被拒。"""
    _, headers = auth_user
    _, token, _ = await _make_shared_trip(client, headers)

    # 初始为空
    resp = await client.get(f"/api/v1/trips/share/{token}/comments")
    assert resp.status_code == 200
    assert resp.json() == []

    # 发表两条（无 auth header）
    resp = await client.post(f"/api/v1/trips/share/{token}/comments", json={
        "author_name": "小明", "content": "第三天西湖改成半天会更好",
    })
    assert resp.status_code == 201, resp.text
    assert resp.json()["author_name"] == "小明"
    assert resp.json()["content"] == "第三天西湖改成半天会更好"

    resp = await client.post(f"/api/v1/trips/share/{token}/comments", json={
        "content": "同意，楼外楼必须安排上",
    })
    assert resp.status_code == 201, resp.text
    assert resp.json()["author_name"] is None

    resp = await client.get(f"/api/v1/trips/share/{token}/comments")
    assert resp.status_code == 200
    comments = resp.json()
    assert len(comments) == 2
    assert comments[0]["author_name"] == "小明"
    assert comments[1]["author_name"] is None

    # 空白评论 → 422
    resp = await client.post(f"/api/v1/trips/share/{token}/comments", json={"content": "   "})
    assert resp.status_code == 422

    # 无效 token → 404
    resp = await client.get("/api/v1/trips/share/bad-token/comments")
    assert resp.status_code == 404


# ── 站点投票 ─────────────────────────────────────────────────
async def test_share_vote_flow(client, auth_user):
    """免登录投票：👍 计数 +1 → 同访客翻转 👎（替换不叠加）→ 同向重复幂等。"""
    _, headers = auth_user
    _, token, stop_id = await _make_shared_trip(client, headers)

    # 初始汇总为空/0
    resp = await client.get(f"/api/v1/trips/share/{token}/votes")
    assert resp.status_code == 200
    votes = resp.json()
    assert votes.get(stop_id, {}).get("up", 0) == 0

    # 投 👍（同一客户端 UA，模拟同一访客）
    resp = await client.post(
        f"/api/v1/trips/share/{token}/votes/{stop_id}",
        json={"value": 1},
        headers={"User-Agent": "test-agent"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["up"] == 1 and body["down"] == 0
    assert body["my_value"] == 1

    # 汇总带 my_value
    resp = await client.get(f"/api/v1/trips/share/{token}/votes", headers={"User-Agent": "test-agent"})
    assert resp.status_code == 200
    assert resp.json()[stop_id]["up"] == 1
    assert resp.json()[stop_id]["my_value"] == 1

    # 同访客翻转成 👎（up 减到 0、down 变 1，不叠加）
    resp = await client.post(
        f"/api/v1/trips/share/{token}/votes/{stop_id}",
        json={"value": -1},
        headers={"User-Agent": "test-agent"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["up"] == 0 and body["down"] == 1
    assert body["my_value"] == -1

    # 同向重复：幂等，计数不变
    resp = await client.post(
        f"/api/v1/trips/share/{token}/votes/{stop_id}",
        json={"value": -1},
        headers={"User-Agent": "test-agent"},
    )
    assert resp.json()["down"] == 1

    # 不同访客（不同 UA）投 👍 → up=1, down=1
    resp = await client.post(
        f"/api/v1/trips/share/{token}/votes/{stop_id}",
        json={"value": 1},
        headers={"User-Agent": "another-visitor"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["up"] == 1 and body["down"] == 1


async def test_share_vote_validation(client, auth_user):
    """非法方向 / 无效 token / 不是本行程的 stop → 拒绝。"""
    _, headers = auth_user
    trip_id, token, stop_id = await _make_shared_trip(client, headers)

    # 非法 value（2 / 0 边界外的 -2）
    resp = await client.post(f"/api/v1/trips/share/{token}/votes/{stop_id}", json={"value": 2})
    assert resp.status_code == 422
    resp = await client.post(f"/api/v1/trips/share/{token}/votes/{stop_id}", json={"value": -2})
    assert resp.status_code == 422

    # 无效 token
    resp = await client.post("/api/v1/trips/share/bad-token/votes/whatever", json={"value": 1})
    assert resp.status_code == 404

    # 不存在的 stop
    resp = await client.post(f"/api/v1/trips/share/{token}/votes/no-such-stop", json={"value": 1})
    assert resp.status_code == 404

    # 其它行程的站点不能投：B 用户建独立行程 → 用 A 的 token 投 B 的 stop
    from datetime import date

    resp_b = await client.post("/api/v1/trips", json={
        "title": "B 的行程", "destination": "北京",
        "start_date": date.today().isoformat(), "end_date": date.today().isoformat(),
    }, headers=headers)
    trip_b = resp_b.json()["id"]
    resp_day = await client.post(f"/api/v1/trips/{trip_b}/days", json={"day_number": 1}, headers=headers)
    day_b = resp_day.json()["id"]
    resp_stop = await client.post(f"/api/v1/trips/days/{day_b}/stops", json={
        "name": "故宫", "stop_type": "attraction",
    }, headers=headers)
    stop_b = resp_stop.json()["id"]

    resp = await client.post(f"/api/v1/trips/share/{token}/votes/{stop_b}", json={"value": 1})
    assert resp.status_code == 404