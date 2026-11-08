"""Feature flag 下发测试（GET /api/v1/flags + 解析纯函数）。

对应 ``docs/plans/2026-11-08-trip-detail-ia-v2-phase2-closeout.md`` §3.1 A2。
重点不是「能解析」，而是**坏输入不让服务崩**：
非法 JSON / 非对象 / 非白名单前缀 / 非法值，全部降级为空开关 + warning。
"""
from __future__ import annotations

import pytest

from app.common.config import settings
from app.services import feature_flags


# ── 解析纯函数 ──────────────────────────────────────────────
def test_parse_empty_and_none():
    assert feature_flags.parse_flags(None) == {}
    assert feature_flags.parse_flags("") == {}
    assert feature_flags.parse_flags("   ") == {}


def test_parse_valid_bool_and_dict_form():
    raw = '{"tripDetail.ia.v2": false, "tripDetail.ia.v2.tabs": {"on": true}}'
    assert feature_flags.parse_flags(raw) == {
        "tripDetail.ia.v2": False,
        "tripDetail.ia.v2.tabs": True,
    }


def test_parse_invalid_json_degrades_to_empty():
    assert feature_flags.parse_flags("{not json") == {}


def test_parse_non_object_degrades_to_empty():
    assert feature_flags.parse_flags('["tripDetail.ia.v2"]') == {}


def test_parse_rejects_foreign_prefix_and_bad_value():
    raw = '{"secret.token": true, "tripDetail.ia.v2": "off", "tripDetail.ia.v2.hoist": 1}'
    assert feature_flags.parse_flags(raw) == {}


def test_revision_is_stable_and_short():
    first = feature_flags.flags_revision('{"tripDetail.ia.v2": false}')
    second = feature_flags.flags_revision('{"tripDetail.ia.v2": false}')
    assert first == second
    assert len(first) == 8
    assert first != feature_flags.flags_revision('{"tripDetail.ia.v2": true}')
    assert feature_flags.flags_revision("") == ""


# ── HTTP 端点 ──────────────────────────────────────────────
@pytest.mark.asyncio
async def test_flags_endpoint_empty_by_default(client, monkeypatch):
    """env 未配置 → 空开关（前端不会被「远端没提」覆盖，继续用本地/默认值）。"""
    monkeypatch.setattr(settings, "FEATURE_FLAGS_JSON", "{}", raising=False)
    resp = await client.get("/api/v1/flags")
    assert resp.status_code == 200
    assert resp.json() == {"flags": {}, "revision": ""}
    assert resp.headers["cache-control"] == "public, max-age=60"


@pytest.mark.asyncio
async def test_flags_endpoint_serves_kill_switch(client, monkeypatch):
    """服务端 kill switch：下发总闸 false → 前端据此整块回滚。"""
    raw = '{"tripDetail.ia.v2": false}'
    monkeypatch.setattr(settings, "FEATURE_FLAGS_JSON", raw, raising=False)
    resp = await client.get("/api/v1/flags")
    assert resp.status_code == 200
    body = resp.json()
    assert body["flags"] == {"tripDetail.ia.v2": False}
    assert body["revision"] == feature_flags.flags_revision(raw)


@pytest.mark.asyncio
async def test_flags_endpoint_never_500_on_broken_env(client, monkeypatch):
    """坏配置也不能让端点 500——回滚口本身不能成为新故障源。"""
    monkeypatch.setattr(settings, "FEATURE_FLAGS_JSON", "{oops", raising=False)
    resp = await client.get("/api/v1/flags")
    assert resp.status_code == 200
    assert resp.json()["flags"] == {}
