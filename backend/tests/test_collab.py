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


# ── 受邀编辑（edit_token：受限字段 + 顺序重排，owner 可收回） ─────────
async def _make_edit_trip(client, headers) -> tuple[str, str, str, str]:
    """建行程 + Day + 2 站点 → 生成 edit_token → 返回 (trip_id, edit_token, day_id, [stop1, stop2])。"""
    trip_id, _, stop1 = await _make_shared_trip(client, headers)
    # 加第二个站点
    resp = await client.get(f"/api/v1/trips/{trip_id}", headers=headers)
    day_id = resp.json()["days"][0]["id"]
    resp = await client.post(f"/api/v1/trips/days/{day_id}/stops", json={
        "name": "灵隐寺", "stop_type": "attraction",
    }, headers=headers)
    assert resp.status_code == 201, resp.text
    stop2 = resp.json()["id"]
    resp = await client.post(f"/api/v1/trips/{trip_id}/share/edit", headers=headers)
    assert resp.status_code == 200, resp.text
    edit_token = resp.json()["edit_token"]
    return trip_id, edit_token, day_id, stop1


async def test_edit_token_generate_view_revoke(client, auth_user):
    """owner 生成 edit_token → 受邀者可见含预算 → owner 收回 → 链接失效。"""
    _, headers = auth_user
    trip_id, edit_token, _, _ = await _make_edit_trip(client, headers)

    # 幂等复用
    resp = await client.post(f"/api/v1/trips/{trip_id}/share/edit", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["edit_token"] == edit_token
    assert "edit=1" in resp.json()["edit_url"]

    # 受邀者凭 edit_token 查看（免登录）
    resp = await client.get(f"/api/v1/trips/edit/{edit_token}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == trip_id
    assert "budget_summary" in body
    assert body["days"][0]["stops"][0]["checked"] is False

    # owner 收回 → 旧链接失效
    resp = await client.delete(f"/api/v1/trips/{trip_id}/share/edit", headers=headers)
    assert resp.status_code == 204
    resp = await client.get(f"/api/v1/trips/edit/{edit_token}")
    assert resp.status_code == 404

    # 且行程详情里 edit_token 已清空
    resp = await client.get(f"/api/v1/trips/{trip_id}", headers=headers)
    assert resp.json()["edit_token"] is None


async def test_invited_stop_edit_flow(client, auth_user):
    """受邀者改站点受限字段：名称/描述/勾选 → 仅这些字段变化。"""
    _, headers = auth_user
    _, edit_token, day_id, stop1 = await _make_edit_trip(client, headers)

    # 更新（免登录，凭 edit_token）
    resp = await client.patch(f"/api/v1/trips/edit/{edit_token}/stops/{stop1}", json={
        "name": "西湖（改）",
        "description": "环湖加雷峰塔",
        "checked": True,
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["name"] == "西湖（改）"
    assert body["description"] == "环湖加雷峰塔"
    assert body["checked"] is True
    assert body["order_index"] == 1  # 未动

    # 下一个站点未受影响
    resp = await client.get(f"/api/v1/trips/edit/{edit_token}")
    stops = resp.json()["days"][0]["stops"]
    other = [s for s in stops if s["id"] != stop1][0]
    assert other["checked"] is False

    # 只更新 checked（不传 name/description）→ 其余保持
    resp = await client.patch(f"/api/v1/trips/edit/{edit_token}/stops/{stop1}", json={"checked": False})
    assert resp.status_code == 200
    assert resp.json()["checked"] is False
    assert resp.json()["name"] == "西湖（改）"


async def test_invited_reorder_flow(client, auth_user):
    """受邀者重排整日站点顺序（幂等，须包含全部站点 id）。"""
    _, headers = auth_user
    _, edit_token, day_id, stop1 = await _make_edit_trip(client, headers)
    resp = await client.get(f"/api/v1/trips/edit/{edit_token}")
    stops = resp.json()["days"][0]["stops"]
    stop2 = [s for s in stops if s["id"] != stop1][0]["id"]

    # 交换顺序
    resp = await client.put(
        f"/api/v1/trips/edit/{edit_token}/days/{day_id}/stops/order",
        json={"order": [stop2, stop1]},
    )
    assert resp.status_code == 200, resp.text
    ordered = [s["id"] for s in resp.json()]
    assert ordered == [stop2, stop1]

    # 缺站点 → 400
    resp = await client.put(
        f"/api/v1/trips/edit/{edit_token}/days/{day_id}/stops/order",
        json={"order": [stop1]},
    )
    assert resp.status_code == 400

    # 无效令牌 → 404
    resp = await client.put(
        "/api/v1/trips/edit/bad-token/days/x/stops/order",
        json={"order": [stop2, stop1]},
    )
    assert resp.status_code == 404


async def test_invited_edit_validation(client, auth_user):
    """只读 share_token 不能编辑（404 不泄露区分）；无效令牌 404；跨行程站点 404。"""
    _, headers = auth_user
    trip_id, edit_token, _, stop1 = await _make_edit_trip(client, headers)

    # 用只读 share_token 调编辑接口 → 404（edit_token 列查不到，不泄露 token 有效）
    share_resp = await client.post(f"/api/v1/trips/{trip_id}/share", headers=headers)
    share_token = share_resp.json()["share_token"]
    resp = await client.patch(f"/api/v1/trips/edit/{share_token}/stops/{stop1}", json={"checked": True})
    assert resp.status_code == 404

    # 无效 edit_token → 404
    resp = await client.patch("/api/v1/trips/edit/bad-token/stops/whatever", json={"checked": True})
    assert resp.status_code == 404

    # 跨行程站点：B 用户的行程站点不能用 A 的 edit_token 改
    from datetime import date

    resp_b = await client.post("/api/v1/trips", json={
        "title": "B 的行程", "destination": "北京",
        "start_date": date.today().isoformat(), "end_date": date.today().isoformat(),
    }, headers=headers)
    trip_b = resp_b.json()["id"]
    resp_day = await client.post(f"/api/v1/trips/{trip_b}/days", json={"day_number": 1}, headers=headers)
    day_b = resp_day.json()["id"]
    resp_stop = await client.post(f"/api/v1/trips/days/{day_b}/stops", json={"name": "故宫"}, headers=headers)
    stop_b = resp_stop.json()["id"]

    resp = await client.patch(f"/api/v1/trips/edit/{edit_token}/stops/{stop_b}", json={"checked": True})
    assert resp.status_code == 404

    # 受邀者不能改 owner 才有的字段（estimated_cost 不在白名单 → pydantic 忽略未声明字段）
    resp = await client.patch(f"/api/v1/trips/edit/{edit_token}/stops/{stop1}", json={"estimated_cost": 999})
    assert resp.status_code == 200
    assert resp.json()["estimated_cost"] == 0.0  # 保持原值，未被改成 999


# ── 渐进式推进（consensus）：已投票成员 ≥ 50% 即「小组一致」，未响应不阻塞 ──
async def _make_trip_with_travelers(client, headers, travelers: int) -> tuple[str, str, list[str]]:
    """建 travelers 人行程 + 站点 + 分享 token → (trip_id, token, stop_id)。"""
    from datetime import date

    today = date.today()
    resp = await client.post("/api/v1/trips", json={
        "title": f"{travelers}人协作行程", "destination": "东京",
        "start_date": today.isoformat(), "end_date": today.isoformat(),
        "travelers": travelers, "budget": 10000,
    }, headers=headers)
    assert resp.status_code == 201, resp.text
    trip_id = resp.json()["id"]

    resp = await client.post(f"/api/v1/trips/{trip_id}/days", json={"day_number": 1}, headers=headers)
    day_id = resp.json()["id"]
    stop_ids = []
    for name in ("晴空塔", "浅草寺"):
        resp = await client.post(f"/api/v1/trips/days/{day_id}/stops", json={
            "name": name, "stop_type": "attraction",
        }, headers=headers)
        assert resp.status_code == 201, resp.text
        stop_ids.append(resp.json()["id"])

    resp = await client.post(f"/api/v1/trips/{trip_id}/share", headers=headers)
    token = resp.json()["share_token"]
    return trip_id, token, stop_ids


async def test_consensus_half_majority_progressive(client, auth_user):
    """渐进式推进：3 人行 → 2 人投赞成即 consensus=True；未响应第 3 人不阻塞。"""
    _, headers = auth_user
    _, token, stop_ids = await _make_trip_with_travelers(client, headers, travelers=3)
    stop_a, stop_b = stop_ids

    # 成员 A 投 👍（UA=member-a）
    resp = await client.post(
        f"/api/v1/trips/share/{token}/votes/{stop_a}", json={"value": 1},
        headers={"User-Agent": "member-a"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["up"] == 1
    assert body["consensus"] is False  # 1/3 < 50%，未到阈值

    # 成员 B 投 👍（UA=member-b）→ 2/3 ≥ 50% → consensus=True
    resp = await client.post(
        f"/api/v1/trips/share/{token}/votes/{stop_a}", json={"value": 1},
        headers={"User-Agent": "member-b"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["up"] == 2
    assert body["consensus"] is True

    # 汇总接口同样带 consensus 标记（未投票的 stop_b 本就不在汇总里 → 不出现）
    resp = await client.get(f"/api/v1/trips/share/{token}/votes", headers={"User-Agent": "member-a"})
    assert resp.status_code == 200
    votes = resp.json()
    assert votes[stop_a]["consensus"] is True
    assert stop_b not in votes


async def test_vote_participation_transparency(client, auth_user):
    """参与率透出（task-collab-democracy-eval 最小版）：responded/group_size/participation。

    借鉴 MonkeyTravel：不响应 ≠ 反对；参与率让共识更有信息量。
    """
    _, headers = auth_user
    _, token, stop_ids = await _make_trip_with_travelers(client, headers, travelers=3)
    stop_a, _ = stop_ids

    # 1/3 表态：participaton≈0.33，consensus False
    resp = await client.post(
        f"/api/v1/trips/share/{token}/votes/{stop_a}", json={"value": 1},
        headers={"User-Agent": "member-a"},
    )
    body = resp.json()
    assert body["responded"] == 1
    assert body["group_size"] == 3
    assert abs(body["participation"] - 0.33) <= 0.01
    assert body["consensus"] is False

    # 2/3 表态：参与率 0.67，consensus True
    resp = await client.post(
        f"/api/v1/trips/share/{token}/votes/{stop_a}", json={"value": 1},
        headers={"User-Agent": "member-b"},
    )
    body = resp.json()
    assert body["responded"] == 2
    assert abs(body["participation"] - 0.67) <= 0.01
    assert body["consensus"] is True

    # 汇总接口同样透出参与率
    resp = await client.get(f"/api/v1/trips/share/{token}/votes", headers={"User-Agent": "member-a"})
    votes = resp.json()
    assert votes[stop_a]["responded"] == 2
    assert votes[stop_a]["group_size"] == 3
    assert votes[stop_a]["participation"] > 0.6


async def test_consensus_threshold_ceil_and_solo(client, auth_user):
    """边界：4 人行 → 2 人即可；单人行程永不标记 consensus。"""
    _, headers = auth_user
    _, token4, stop_ids4 = await _make_trip_with_travelers(client, headers, travelers=4)
    stop_a = stop_ids4[0]
    # 2/4 = 50% → ceil(4/2)=2 → consensus=True
    for ua in ("m1", "m2"):
        resp = await client.post(
            f"/api/v1/trips/share/{token4}/votes/{stop_a}", json={"value": 1},
            headers={"User-Agent": ua},
        )
        assert resp.status_code == 200
    resp = await client.get(f"/api/v1/trips/share/{token4}/votes")
    assert resp.json()[stop_a]["consensus"] is True

    # 单人行程：travelers=1 → 不启用共识（threshold=0）→ 永远 False
    _, token1, stop_ids1 = await _make_trip_with_travelers(client, headers, travelers=1)
    resp = await client.post(
        f"/api/v1/trips/share/{token1}/votes/{stop_ids1[0]}", json={"value": 1},
        headers={"User-Agent": "solo"},
    )
    assert resp.status_code == 200
    assert resp.json()["consensus"] is False


async def test_consensus_flip_removes_progress(client, auth_user):
    """翻转投票：过半但赞成不占多数 → 不标记；多数反对则标记回落。"""
    _, headers = auth_user
    _, token, stop_ids = await _make_trip_with_travelers(client, headers, travelers=4)
    stop_a = stop_ids[0]

    # 2 人 👍 → consensus=True（2/4 达标且赞成多数）
    for ua in ("flip-a", "flip-b"):
        resp = await client.post(
            f"/api/v1/trips/share/{token}/votes/{stop_a}", json={"value": 1},
            headers={"User-Agent": ua},
        )
        assert resp.status_code == 200
    assert resp.json()["consensus"] is True

    # 成员 flip-c 投 👎 → 2👍1👎：表态 3/4 ≥50% 但赞成 2 > 1 仍多数 → True
    resp = await client.post(
        f"/api/v1/trips/share/{token}/votes/{stop_a}", json={"value": -1},
        headers={"User-Agent": "flip-c"},
    )
    assert resp.status_code == 200
    assert resp.json()["up"] == 2 and resp.json()["down"] == 1
    assert resp.json()["consensus"] is True

    # 成员 flip-a 翻转成 👎 → 1👍2👎：赞成不再多数 → consensus=False
    resp = await client.post(
        f"/api/v1/trips/share/{token}/votes/{stop_a}", json={"value": -1},
        headers={"User-Agent": "flip-a"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["up"] == 1 and body["down"] == 2
    assert body["consensus"] is False