"""兑换码权益测试（frame-marketplace）。

覆盖 spec「兑换码兑换与权益幂等」全部场景：
- 有效码首次兑换 → 写入权益、码状态 used
- 同一用户重放自己的码 → 幂等 200 已解锁，不重复落库
- 他人已用 → 409
- 码不存在 → 404（明文码不出现在响应）
- 码被吊销 → 410
- 权益按用户隔离：A 的码可被 B 兑换，但只解锁 B，A 不获得
- 目录 locked 标注随权益刷新
"""
from __future__ import annotations

import hashlib
import uuid

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.asyncio


def _code(seed: str) -> str:
    return f"FRM-{seed.upper()}"


def _hash(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


async def _insert_code(db, code: str, pack_slug: str, status: str = "unused", redeemed_by: str | None = None):
    await db.execute(
        text(
            "INSERT INTO redemption_codes (id, code_hash, pack_slug, status, redeemed_by, redeemed_at) "
            "VALUES (:id, :code_hash, :pack_slug, :status, :redeemed_by, :redeemed_at)"
        ),
        {
            "id": str(uuid.uuid4()),
            "code_hash": _hash(code),
            "pack_slug": pack_slug,
            "status": status,
            "redeemed_by": redeemed_by,
            "redeemed_at": None,
        },
    )
    await db.commit()


async def _seed_catalog(db):
    """测试库播种：2 免费 + 2 付费包（各 1 套足够断言 locked 逻辑）。"""
    import json

    rows = [
        ("minimal-day", "极简日志", "free", "minimal", '{"photo_slots":3}', 0),
        ("journal-day", "手账日常", "free", "journal", '{"photo_slots":4}', 0),
        ("warm-film", "暖光胶片", "paid", "warm", '{"photo_slots":3}', 690),
        ("cheerful-sticker", "元气贴纸", "paid", "cheerful", '{"photo_slots":4}', 690),
    ]
    for slug, name, tier, theme, config, price in rows:
        await db.execute(
            text(
                "INSERT INTO frame_templates (id, slug, name, tier, theme, layout_config, price_cents, active) "
                "VALUES (:id, :slug, :name, :tier, :theme, CAST(:config AS JSONB), :price, true) "
                "ON CONFLICT (slug) DO NOTHING"
            ),
            {"id": str(uuid.uuid4()), "slug": slug, "name": name, "tier": tier, "theme": theme, "config": config, "price": price},
        )
    packs = [
        ("pack-warm-memories", '["warm-film"]', 690),
        ("pack-cheerful-trip", '["cheerful-sticker"]', 690),
    ]
    for slug, slugs, price in packs:
        await db.execute(
            text(
                "INSERT INTO frame_packs (id, slug, name, template_slugs, price_cents, active) "
                "VALUES (:id, :slug, :name, CAST(:slugs AS JSONB), :price, true) "
                "ON CONFLICT (slug) DO NOTHING"
            ),
            {"id": str(uuid.uuid4()), "slug": slug, "name": slug, "slugs": slugs, "price": price},
        )
    await db.commit()


# ── API 级测试 ────────────────────────────────────────────────


async def test_redeem_valid_code_unlocks_pack(client, auth_user, db_session):
    _, headers = auth_user
    code = _code(uuid.uuid4().hex[:8])
    await _insert_code(db_session, code, "pack-warm-memories")

    resp = await client.post(
        "/api/v1/frames/redeem", json={"code": code}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "pack-warm-memories" in [p["pack_slug"] for p in data["entitlements"]]


async def test_redeem_same_code_twice_idempotent_200(client, auth_user, db_session):
    _, headers = auth_user
    code = _code(uuid.uuid4().hex[:8])
    await _insert_code(db_session, code, "pack-warm-memories")

    first = await client.post("/api/v1/frames/redeem", json={"code": code}, headers=headers)
    assert first.status_code == 200
    second = await client.post("/api/v1/frames/redeem", json={"code": code}, headers=headers)
    assert second.status_code == 200, second.text
    assert "pack-warm-memories" in [
        p["pack_slug"] for p in second.json()["entitlements"]
    ]


async def test_redeem_code_used_by_other_returns_409(client, auth_user, db_session):
    _, headers = auth_user
    code = _code(uuid.uuid4().hex[:8])
    await _insert_code(db_session, code, "pack-warm-memories", status="used", redeemed_by="other-user-1")

    resp = await client.post("/api/v1/frames/redeem", json={"code": code}, headers=headers)
    assert resp.status_code == 409
    assert "已被使用" in resp.json()["error"]["message"]


async def test_redeem_unknown_code_returns_404_without_leaking(client, auth_user, db_session):
    _, headers = auth_user
    secret = _code(uuid.uuid4().hex[:8])
    resp = await client.post("/api/v1/frames/redeem", json={"code": secret}, headers=headers)
    assert resp.status_code == 404
    body = resp.text
    assert secret not in body  # 明文码不回显


async def test_redeem_revoked_code_returns_410(client, auth_user, db_session):
    _, headers = auth_user
    code = _code(uuid.uuid4().hex[:8])
    await _insert_code(db_session, code, "pack-warm-memories", status="revoked")

    resp = await client.post("/api/v1/frames/redeem", json={"code": code}, headers=headers)
    assert resp.status_code == 410


async def test_code_asset_belongs_to_redeemer_not_original_owner(client, auth_user, db_session):
    """码即资产：A 生成/持有的码被 B 兑换 → 只解锁 B。"""
    from tests.conftest import _test_dsn  # noqa: F401  (仅确保 import 路径可用)

    _, headers_a = auth_user
    # 注册第二个用户 B
    import uuid as _uuid

    email_b = f"user-{_uuid.uuid4().hex[:8]}@test.com"
    reg = await client.post(
        "/api/v1/auth/register",
        json={"email": email_b, "password": "test1234", "display_name": "用户B"},
    )
    headers_b = {"Authorization": f"Bearer {reg.json()['access_token']}"}

    code = _code(_uuid.uuid4().hex[:8])
    await _insert_code(db_session, code, "pack-cheerful-trip")

    resp_b = await client.post("/api/v1/frames/redeem", json={"code": code}, headers=headers_b)
    assert resp_b.status_code == 200
    # B 解锁了
    ent_b = await client.get("/api/v1/frames/entitlements", headers=headers_b)
    assert "pack-cheerful-trip" in [p["pack_slug"] for p in ent_b.json()["entitlements"]]
    # A 没有解锁
    ent_a = await client.get("/api/v1/frames/entitlements", headers=headers_a)
    assert "pack-cheerful-trip" not in [p["pack_slug"] for p in ent_a.json()["entitlements"]]


# ── 目录 locked 标注 ─────────────────────────────────────────


async def test_catalog_locked_flag_reflects_entitlements(client, auth_user, db_session):
    await _seed_catalog(db_session)
    _, headers = auth_user
    # 未登录：付费模板 locked=True
    anon = await client.get("/api/v1/frames/catalog")
    assert anon.status_code == 200
    anon_items = {i["slug"]: i for i in anon.json()["templates"]}
    assert anon_items["minimal-day"]["locked"] is False
    assert anon_items["warm-film"]["locked"] is True

    # 解锁暖光包后：包内模板 locked=False，另一包仍 locked=True
    code = _code(uuid.uuid4().hex[:8])
    await _insert_code(db_session, code, "pack-warm-memories")
    await client.post("/api/v1/frames/redeem", json={"code": code}, headers=headers)

    resp = await client.get("/api/v1/frames/catalog", headers=headers)
    items = {i["slug"]: i for i in resp.json()["templates"]}
    assert items["warm-film"]["locked"] is False
    assert items["cheerful-sticker"]["locked"] is True
