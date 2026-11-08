"""日程批量生成回归（``POST /trips/{id}/days/generate``）。

背景：2026-11-08 IA 阶段二验收时实测该端点 500 —— ``DayOut.stops`` 是懒加载关系，
bulk 创建后直接 ``model_validate`` 触发 ``MissingGreenlet``。``add_day`` 早就有
eager-load 注释，批量路径漏了同一处，属于「同类缺陷只修了一处」。

这里锁住三条：批量生成可用 / 边界（倒序、超 31 天）返回 409 / 空结果不炸。
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient


async def _make_trip(client: AsyncClient, headers: dict) -> str:
    resp = await client.post(
        "/api/v1/trips",
        headers=headers,
        json={
            "title": "日程生成验收",
            "destination": "厦门",
            "start_date": "2026-11-20",
            "end_date": "2026-11-23",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


@pytest.mark.asyncio
async def test_generate_days_ok(client: AsyncClient, auth_user):
    """批量生成 4 天 → 201/200 + 每天带 stops 空数组（不触发 MissingGreenlet）。"""
    _user, headers = auth_user
    trip_id = await _make_trip(client, headers)

    resp = await client.post(
        f"/api/v1/trips/{trip_id}/days/generate",
        headers=headers,
        params={"start": "2026-11-20", "end": "2026-11-23"},
    )
    assert resp.status_code == 200, resp.text
    days = resp.json()
    assert [d["day_number"] for d in days] == [1, 2, 3, 4]
    assert all(d["stops"] == [] for d in days)
    assert [d["date"] for d in days] == ["2026-11-20", "2026-11-21", "2026-11-22", "2026-11-23"]


@pytest.mark.asyncio
async def test_generate_days_is_idempotent_on_existing_numbers(client: AsyncClient, auth_user):
    """重复生成已存在的 day_number → 跳过，不重复插入、不报错。"""
    _user, headers = auth_user
    trip_id = await _make_trip(client, headers)

    first = await client.post(
        f"/api/v1/trips/{trip_id}/days/generate",
        headers=headers,
        params={"start": "2026-11-20", "end": "2026-11-21"},
    )
    assert first.status_code == 200

    again = await client.post(
        f"/api/v1/trips/{trip_id}/days/generate",
        headers=headers,
        params={"start": "2026-11-20", "end": "2026-11-21"},
    )
    assert again.status_code == 200
    assert again.json() == []


@pytest.mark.asyncio
async def test_generate_days_rejects_invalid_range(client: AsyncClient, auth_user):
    """倒序 / 超 31 天 → 409（ConflictError），不是 500。"""
    _user, headers = auth_user
    trip_id = await _make_trip(client, headers)

    reversed_resp = await client.post(
        f"/api/v1/trips/{trip_id}/days/generate",
        headers=headers,
        params={"start": "2026-11-23", "end": "2026-11-20"},
    )
    assert reversed_resp.status_code == 409

    too_long = await client.post(
        f"/api/v1/trips/{trip_id}/days/generate",
        headers=headers,
        params={"start": "2026-11-20", "end": "2027-01-20"},
    )
    assert too_long.status_code == 409
