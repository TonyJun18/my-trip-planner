"""旅拍相框市场端到端验收（frame-marketplace，任务 8.2）。

一条测试串起 spec 全部服务端场景，作为商业闭环的回归护栏：
目录（匿名 locked）→ 兑换 → 目录 locked 刷新 → 单日投影 → 单日配文 →
整程总结投影 → 总结配文 → 非 owner 越权拒绝。
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.asyncio


async def _seed_catalog(db):
    """测试库无迁移种子，手工播种 2 免费 + 2 付费包（各 1 套模板）。"""
    templates = [
        ("minimal-day", "极简日志", "free", "minimal", '{"photo_slots":3}', 0),
        ("journal-day", "手账日常", "free", "journal", '{"photo_slots":4}', 0),
        ("warm-film", "暖光胶片", "paid", "warm", '{"photo_slots":3}', 690),
        ("cheerful-sticker", "元气贴纸", "paid", "cheerful", '{"photo_slots":4}', 690),
    ]
    for slug, name, tier, theme, config, price in templates:
        await db.execute(
            text(
                "INSERT INTO frame_templates "
                "(id, slug, name, tier, theme, layout_config, price_cents, active) "
                "VALUES (:id, :slug, :name, :tier, :theme, CAST(:config AS JSONB), :price, true) "
                "ON CONFLICT (slug) DO NOTHING"
            ),
            {"id": str(uuid.uuid4()), "slug": slug, "name": name, "tier": tier,
             "theme": theme, "config": config, "price": price},
        )
    for slug, pack_slugs in [
        ("pack-warm-memories", '["warm-film"]'),
        ("pack-cheerful-trip", '["cheerful-sticker"]'),
    ]:
        await db.execute(
            text(
                "INSERT INTO frame_packs (id, slug, name, template_slugs, price_cents, active) "
                "VALUES (:id, :slug, :name, CAST(:slugs AS JSONB), 690, true) "
                "ON CONFLICT (slug) DO NOTHING"
            ),
            {"id": str(uuid.uuid4()), "slug": slug, "name": slug, "slugs": pack_slugs},
        )
    await db.commit()


async def _register(client, tag: str) -> dict:
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": f"e2e-{tag}-{uuid.uuid4().hex[:8]}@test.com",
              "password": "test1234", "display_name": tag},
    )
    assert resp.status_code in (200, 201), resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def test_frame_marketplace_end_to_end(client, auth_user, db_session):
    await _seed_catalog(db_session)
    _, headers = auth_user

    # 1) 匿名目录：付费模板 locked，免费模板可用，响应不含权益信息
    anon = await client.get("/api/v1/frames/catalog")
    assert anon.status_code == 200
    anon_tpl = {t["slug"]: t for t in anon.json()["templates"]}
    assert anon_tpl["minimal-day"]["locked"] is False
    assert anon_tpl["warm-film"]["locked"] is True
    assert len(anon.json()["packs"]) == 2
    assert "entitlements" not in anon.json()

    # 2) 生成一枚兑换码（哈希入库，明文只在本地变量）
    code = f"FRM-E2E{uuid.uuid4().hex[:9].upper()}"
    await db_session.execute(
        text(
            "INSERT INTO redemption_codes (id, code_hash, pack_slug, status) "
            "VALUES (:id, :h, :pack, 'unused')"
        ),
        {"id": str(uuid.uuid4()),
         "h": hashlib.sha256(code.encode()).hexdigest(),
         "pack": "pack-warm-memories"},
    )
    await db_session.commit()

    # 3) 兑换 → 权益写入
    redeemed = await client.post("/api/v1/frames/redeem", json={"code": code}, headers=headers)
    assert redeemed.status_code == 200, redeemed.text
    assert "pack-warm-memories" in [p["pack_slug"] for p in redeemed.json()["entitlements"]]

    # 4) 目录 locked 刷新：包内解锁，另一包仍锁
    after = await client.get("/api/v1/frames/catalog", headers=headers)
    tpl = {t["slug"]: t for t in after.json()["templates"]}
    assert tpl["warm-film"]["locked"] is False
    assert tpl["cheerful-sticker"]["locked"] is True

    # 5) 创建「行中」行程并打卡一个站点
    today = date.today()
    trip_resp = await client.post("/api/v1/trips", headers=headers, json={
        "title": "端到端验收", "destination": "杭州",
        "start_date": today.isoformat(),
        "end_date": (today + timedelta(days=1)).isoformat(),
        "travelers": 2,
    })
    assert trip_resp.status_code == 201, trip_resp.text
    trip_id = trip_resp.json()["id"]
    day1 = (await client.post(f"/api/v1/trips/{trip_id}/days", headers=headers,
                              json={"day_number": 1, "note": "西湖日"})).json()
    day2 = (await client.post(f"/api/v1/trips/{trip_id}/days", headers=headers,
                              json={"day_number": 2, "note": "空日"})).json()
    stop = (await client.post(f"/api/v1/trips/days/{day1['id']}/stops", headers=headers, json={
        "name": "西湖", "stop_type": "attraction", "lat": 30.24, "lng": 120.15,
        "description": "断桥人山人海，但日落值得",
    })).json()
    await client.post(f"/api/v1/trips/days/{day1['id']}/stops", headers=headers,
                      json={"name": "灵隐寺", "stop_type": "attraction"})  # 未打卡
    checked = await client.post(
        f"/api/v1/trips/{trip_id}/live/stops/{stop['id']}/check", headers=headers, json={}
    )
    assert checked.status_code in (200, 201), checked.text

    # 6) 单日投影：只含 checked 站点，带趣事与当日 note
    day_data = await client.get(f"/api/v1/trips/{trip_id}/frames/{day1['id']}/data", headers=headers)
    assert day_data.status_code == 200, day_data.text
    body = day_data.json()
    assert body["empty"] is False
    assert [s["name"] for s in body["stops"]] == ["西湖"]
    assert body["stops"][0]["description"] == "断桥人山人海，但日落值得"
    assert body["day_note"] == "西湖日"
    # 无打卡的日子诚实返回空投影
    empty_day = await client.get(
        f"/api/v1/trips/{trip_id}/frames/{day2['id']}/data", headers=headers
    )
    assert empty_day.json()["empty"] is True

    # 7) 单日配文：LLM 不可用时降级模板，仍引用真实站点
    copy_resp = await client.post(
        f"/api/v1/trips/{trip_id}/frames/{day1['id']}/copy",
        headers=headers, json={"channel": "xhs", "provider": "openai"},
    )
    assert copy_resp.status_code == 200, copy_resp.text
    copy = copy_resp.json()
    assert copy["source"] in ("llm", "template")
    if copy["source"] == "template":
        assert "西湖" in copy["body"]
        assert "灵隐寺" not in copy["body"]

    # 8) 总结投影：空日跳过，统计正确
    summary = await client.get(f"/api/v1/trips/{trip_id}/frames/summary/data", headers=headers)
    assert summary.status_code == 200, summary.text
    s = summary.json()
    assert s["empty"] is False
    assert s["stats"]["days_with_checkins"] == 1
    assert s["stats"]["checked_stops"] == 1
    assert [d["day_number"] for d in s["days"]] == [1]

    # 9) 总结配文
    scopy = await client.post(
        f"/api/v1/trips/{trip_id}/frames/summary/copy",
        headers=headers, json={"channel": "xhs", "provider": "openai"},
    )
    assert scopy.status_code == 200, scopy.text
    assert scopy.json()["day_id"] is None
    assert scopy.json()["source"] in ("llm", "template")

    # 10) 非 owner 全部拒绝（投影 / 配文 / 总结）
    headers_b = await _register(client, "b")
    for path, payload in [
        (f"/api/v1/trips/{trip_id}/frames/{day1['id']}/data", None),
        (f"/api/v1/trips/{trip_id}/frames/summary/data", None),
    ]:
        resp = await client.get(path, headers=headers_b)
        assert resp.status_code in (403, 404), resp.text
    for path in [
        f"/api/v1/trips/{trip_id}/frames/{day1['id']}/copy",
        f"/api/v1/trips/{trip_id}/frames/summary/copy",
    ]:
        resp = await client.post(path, headers=headers_b, json={"channel": "xhs", "provider": "openai"})
        assert resp.status_code in (403, 404), resp.text

    # 11) 未登录不可兑换；错误码语义（不存在 / 已用）
    anon_redeem = await client.post("/api/v1/frames/redeem", json={"code": code})
    assert anon_redeem.status_code == 401
    missing = await client.post(
        "/api/v1/frames/redeem", json={"code": "FRM-NOTEXIST0000"}, headers=headers
    )
    assert missing.status_code == 404
    used_by_other = await client.post(
        "/api/v1/frames/redeem", json={"code": code}, headers=headers_b
    )
    assert used_by_other.status_code == 409
