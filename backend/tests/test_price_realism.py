"""高德 POI 真实价格接入（task-price-realism-eval，2026-10-28）单元测试。

覆盖：
- _parse_amap_cost：biz_ext.cost 人均消费解析（字符串/数字/缺失/非法/零值）
- search_pois_amap：extensions=all 请求 + 景点/美食取真实人均消费
- 酒店维持城市基准价×档位估算（高德无标准房价字段）
- cost 缺失 → 0（不编造价格）
"""
from __future__ import annotations

from typing import Any

import pytest

from app.agent.tools import _parse_amap_cost, search_pois_amap

_AMAP_OK = {
    "status": "1",
    "pois": [
        {
            "name": "西湖",
            "location": "120.150,30.274",
            "type": "风景名胜;风景名胜",
            "biz_ext": {"cost": "0", "rating": "4.8"},
        }
    ],
}


def test_parse_cost_string():
    """字符串人均消费 → float。"""
    assert _parse_amap_cost("75") == 75.0
    assert _parse_amap_cost("120.5") == 120.5


def test_parse_cost_number():
    """数字人均消费 → float。"""
    assert _parse_amap_cost(60) == 60.0
    assert _parse_amap_cost(88.8) == 88.8


def test_parse_cost_missing_or_invalid():
    """缺失/空串/非数字/零 → 0（不编造）。"""
    assert _parse_amap_cost(None) == 0.0
    assert _parse_amap_cost("") == 0.0
    assert _parse_amap_cost("未知") == 0.0
    assert _parse_amap_cost("0") == 0.0


@pytest.mark.asyncio
async def test_search_amap_uses_real_cost_for_attraction(monkeypatch):
    """景点：extensions=all 返回 biz_ext.cost → estimated_cost 取真实人均消费。"""
    from app.common.config import settings

    monkeypatch.setattr(settings, "AMAP_API_KEY", "test-key")

    captured: dict[str, Any] = {}

    async def _fake_get(self, url, params=None, **kw):  # noqa: ARG001
        captured["params"] = params
        return _FakeResp(_AMAP_OK)

    import httpx

    monkeypatch.setattr(httpx.AsyncClient, "get", _fake_get)
    result = await search_pois_amap("杭州", want_type="attraction")
    assert captured["params"]["extensions"] == "all"
    assert result["results"][0]["estimated_cost"] == 0.0  # cost="0" → 0


@pytest.mark.asyncio
async def test_search_amap_parse_cost_from_biz_ext(monkeypatch):
    """景点：biz_ext.cost=75 → estimated_cost=75（真实人均消费进预算）。"""
    from app.common.config import settings

    monkeypatch.setattr(settings, "AMAP_API_KEY", "test-key")
    payload = {
        "status": "1",
        "pois": [
            {
                "name": "灵隐寺",
                "location": "120.11,30.24",
                "type": "风景名胜;寺庙",
                "biz_ext": {"cost": "75", "rating": "4.6"},
            }
        ],
    }

    async def _fake_get(self, url, params=None, **kw):  # noqa: ARG001
        return _FakeResp(payload)

    import httpx

    monkeypatch.setattr(httpx.AsyncClient, "get", _fake_get)
    result = await search_pois_amap("杭州", want_type="attraction")
    assert result["results"][0]["estimated_cost"] == 75.0


@pytest.mark.asyncio
async def test_search_amap_food_uses_real_cost(monkeypatch):
    """美食：biz_ext.cost 人均消费进 estimated_cost。"""
    from app.common.config import settings

    monkeypatch.setattr(settings, "AMAP_API_KEY", "test-key")
    payload = {
        "status": "1",
        "pois": [
            {
                "name": "楼外楼",
                "location": "120.14,30.25",
                "type": "餐饮服务;中餐厅",
                "biz_ext": {"cost": "180", "rating": "4.5"},
            }
        ],
    }

    async def _fake_get(self, url, params=None, **kw):  # noqa: ARG001
        return _FakeResp(payload)

    import httpx

    monkeypatch.setattr(httpx.AsyncClient, "get", _fake_get)
    result = await search_pois_amap("杭州", want_type="food")
    assert result["results"][0]["estimated_cost"] == 180.0


@pytest.mark.asyncio
async def test_search_amap_hotel_keeps_base_estimate(monkeypatch):
    """酒店：biz_ext.cost 不用于房价（高德无标准房价字段）→ 维持基准价×档位估算。"""
    from app.common.config import settings

    monkeypatch.setattr(settings, "AMAP_API_KEY", "test-key")
    payload = {
        "status": "1",
        "pois": [
            {
                "name": "杭州经济型酒店",
                "location": "120.15,30.26",
                "type": "餐饮服务;中餐厅",
                "biz_ext": {"cost": "300", "rating": "4.2"},
            }
        ],
    }

    async def _fake_get(self, url, params=None, **kw):  # noqa: ARG001
        return _FakeResp(payload)

    import httpx

    monkeypatch.setattr(httpx.AsyncClient, "get", _fake_get)
    result = await search_pois_amap("杭州", want_type="hotel")
    # 城市基准价 430 × 经济档 0.7 = 301.0（忽略高德 biz_ext.cost=300）
    assert result["results"][0]["estimated_cost"] == round(430 * 0.7, 2)


@pytest.mark.asyncio
async def test_search_amap_missing_biz_ext_keeps_zero(monkeypatch):
    """biz_ext 缺失：estimated_cost=0（不编造价格，保持原行为）。"""
    from app.common.config import settings

    monkeypatch.setattr(settings, "AMAP_API_KEY", "test-key")
    payload = {
        "status": "1",
        "pois": [
            {"name": "某免费公园", "location": "120.10,30.20", "type": "风景名胜;公园"}
        ],
    }

    async def _fake_get(self, url, params=None, **kw):  # noqa: ARG001
        return _FakeResp(payload)

    import httpx

    monkeypatch.setattr(httpx.AsyncClient, "get", _fake_get)
    result = await search_pois_amap("杭州", want_type="attraction")
    assert result["results"][0]["estimated_cost"] == 0.0


# ── 增强：顶层 cost/rating 双读（2026-10-28 worker-4 接管核验补齐）────────
# v3 place/text 官方文档把 cost（人均消费）/rating（评分）列为 POI 顶层字段
# （仅餐饮/酒店/景点/影院类），部分场景返回在 biz_ext 深度信息 → 顶层优先 + biz_ext 兜底
def test_parse_amap_rating_units():
    """_parse_amap_rating：字符串/数字/非法/越界裁剪。"""
    from app.agent.tools import _parse_amap_rating

    assert _parse_amap_rating("4.8") == 4.8
    assert _parse_amap_rating(4.6) == 4.6
    assert _parse_amap_rating("9.9") == 5.0
    assert _parse_amap_rating("-1") == 0.0
    assert _parse_amap_rating(None) is None
    assert _parse_amap_rating("") is None
    assert _parse_amap_rating("很好") is None


@pytest.mark.asyncio
async def test_search_amap_top_level_cost_preferred(monkeypatch):
    """顶层 cost 优先于 biz_ext.cost（官方文档顶层字段为准）。"""
    from app.common.config import settings

    monkeypatch.setattr(settings, "AMAP_API_KEY", "test-key")
    payload = {
        "status": "1",
        "pois": [
            {
                "name": "西湖",
                "location": "120.150,30.274",
                "type": "风景名胜;风景名胜",
                "cost": "88",
                "rating": "4.9",
                "biz_ext": {"cost": "60", "rating": "4.5"},
            }
        ],
    }

    async def _fake_get(self, url, params=None, **kw):  # noqa: ARG001
        return _FakeResp(payload)

    import httpx

    monkeypatch.setattr(httpx.AsyncClient, "get", _fake_get)
    result = await search_pois_amap("杭州", want_type="attraction")
    p = result["results"][0]
    assert p["estimated_cost"] == 88.0  # 顶层 cost 优先
    assert p["rating"] == 4.9  # 顶层 rating 优先


@pytest.mark.asyncio
async def test_search_amap_biz_ext_fallback_when_top_level_missing(monkeypatch):
    """顶层 cost 缺失 → biz_ext.cost 兜底（兼容旧版返回结构）。"""
    from app.common.config import settings

    monkeypatch.setattr(settings, "AMAP_API_KEY", "test-key")
    payload = {
        "status": "1",
        "pois": [
            {
                "name": "灵隐寺",
                "location": "120.11,30.24",
                "type": "风景名胜;寺庙",
                "biz_ext": {"cost": "75", "rating": "4.6"},
            }
        ],
    }

    async def _fake_get(self, url, params=None, **kw):  # noqa: ARG001
        return _FakeResp(payload)

    import httpx

    monkeypatch.setattr(httpx.AsyncClient, "get", _fake_get)
    result = await search_pois_amap("杭州", want_type="attraction")
    p = result["results"][0]
    assert p["estimated_cost"] == 75.0
    assert p["rating"] == 4.6


class _FakeResp:
    """最小 httpx.Response 替身（只暴露 .json()）。"""

    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:  # noqa: D102
        return None

    def json(self) -> dict[str, Any]:
        return self._payload