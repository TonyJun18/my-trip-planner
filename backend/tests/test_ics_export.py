"""行程 ICS 日历导出测试（task-ics-export）。

覆盖：结构合法（VCALENDAR/CRLF/75 字节折行）、每站一个全天 VEVENT、
TEXT 转义、空天退化、无日期按 start_date 推导、owner 归属隔离、
分享令牌免登录、无效令牌 404、**令牌零泄漏**。
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient


async def _make_trip(
    client: AsyncClient,
    headers: dict,
    *,
    start_date: str = "2026-11-01",
    end_date: str = "2026-11-03",
) -> str:
    resp = await client.post("/api/v1/trips", headers=headers, json={
        "title": "ICS 导出行程", "destination": "杭州", "departure": "上海",
        "start_date": start_date, "end_date": end_date, "travelers": 2, "budget": 3000,
    })
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _add_day(client: AsyncClient, headers: dict, trip_id: str, day_number: int,
                   date: str | None = None, note: str | None = None) -> str:
    payload: dict = {"day_number": day_number}
    if date:
        payload["date"] = date
    if note:
        payload["note"] = note
    resp = await client.post(f"/api/v1/trips/{trip_id}/days", headers=headers, json=payload)
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["id"]


async def _add_stop(client: AsyncClient, headers: dict, day_id: str, **fields) -> dict:
    payload = {"name": fields.pop("name"), "stop_type": fields.pop("stop_type", "attraction")}
    payload.update(fields)
    resp = await client.post(f"/api/v1/trips/days/{day_id}/stops", headers=headers, json=payload)
    assert resp.status_code in (200, 201), resp.text
    return resp.json()


def _lines(body: str) -> list[str]:
    assert body.endswith("\r\n"), "ICS 必须以 CRLF 结尾"
    return body[:-2].split("\r\n")


def _events(body: str) -> list[list[str]]:
    events, current, inside = [], [], False
    for line in _lines(body):
        if line == "BEGIN:VEVENT":
            inside, current = True, ["BEGIN:VEVENT"]
        elif line == "END:VEVENT":
            current.append("END:VEVENT")
            events.append(current)
            inside = False
        elif inside:
            current.append(line)
    return events


def _unfold(lines: list[str]) -> list[str]:
    """还原折行（续行以空格开头）。"""
    out: list[str] = []
    for line in lines:
        if line.startswith(" ") and out:
            out[-1] += line[1:]
        else:
            out.append(line)
    return out


@pytest.mark.asyncio
async def test_ics_structure(client: AsyncClient, auth_user):
    """基本结构：text/calendar + 附件头 + VCALENDAR 头尾 + 折行不超 75 字节。"""
    _user, headers = auth_user
    trip_id = await _make_trip(client, headers)
    day_id = await _add_day(client, headers, trip_id, 1, date="2026-11-01")
    await _add_stop(client, headers, day_id, name="西湖", estimated_cost=100.0,
                    estimated_duration_minutes=120, lat=30.2461, lng=120.1490)

    resp = await client.get(f"/api/v1/trips/{trip_id}/export/ics", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/calendar")
    assert ".ics" in resp.headers["content-disposition"]

    body = resp.text
    lines = _lines(body)
    assert lines[0] == "BEGIN:VCALENDAR"
    assert lines[-1] == "END:VCALENDAR"
    assert "VERSION:2.0" in lines
    assert any(line.startswith("PRODID:") for line in lines)
    # RFC 5545：每行（含 CRLF 前的折行）不超过 75 字节
    for line in lines:
        assert len(line.encode("utf-8")) <= 75, line


@pytest.mark.asyncio
async def test_ics_one_event_per_stop(client: AsyncClient, auth_user):
    """每站一个全天 VEVENT：DTSTART 全天、SUMMARY=站名、LOCATION=目的地、GEO=坐标。"""
    _user, headers = auth_user
    trip_id = await _make_trip(client, headers)
    day_id = await _add_day(client, headers, trip_id, 1, date="2026-11-01")
    await _add_stop(client, headers, day_id, name="西湖", lat=30.2461, lng=120.1490)
    await _add_stop(client, headers, day_id, name="灵隐寺", estimated_cost=45.0)

    body = (await client.get(f"/api/v1/trips/{trip_id}/export/ics", headers=headers)).text
    events = _events(body)
    assert len(events) == 2
    summaries = [_unfold(e) for e in events]
    assert any("SUMMARY:西湖" in e for e in summaries)
    assert any("SUMMARY:灵隐寺" in e for e in summaries)

    for event in summaries:
        assert any(line == "DTSTART;VALUE=DATE:20261101" for line in event)
        # 全天事件 DTEND = 次日（RFC 5545 排他）
        assert any(line == "DTEND;VALUE=DATE:20261102" for line in event)
        assert any(line.startswith("UID:trip-") for line in event)
        assert any(line.startswith("DTSTAMP:") for line in event)
        assert any(line.startswith("LOCATION:杭州") for line in event)

    # 有坐标的站带 GEO，无坐标的不编造
    assert any(line.startswith("GEO:30.246100;120.149000") for e in summaries for line in e)
    assert sum(1 for e in summaries for line in e if line.startswith("GEO:")) == 1


@pytest.mark.asyncio
async def test_ics_escapes_text(client: AsyncClient, auth_user):
    """TEXT 转义：逗号/分号/反斜杠/换行不得破坏结构。"""
    _user, headers = auth_user
    trip_id = await _make_trip(client, headers)
    day_id = await _add_day(client, headers, trip_id, 1, date="2026-11-01")
    await _add_stop(client, headers, day_id, name="断桥,残雪;断桥\\残雪")

    body = (await client.get(f"/api/v1/trips/{trip_id}/export/ics", headers=headers)).text
    raw_summary = next(line for line in _lines(body) if line.startswith("SUMMARY:"))
    assert "\\," in raw_summary and "\\;" in raw_summary
    assert raw_summary.count("SUMMARY:") == 1


@pytest.mark.asyncio
async def test_ics_day_without_stops(client: AsyncClient, auth_user):
    """空天退化成一个整天事件，日程不断层。"""
    _user, headers = auth_user
    trip_id = await _make_trip(client, headers)
    await _add_day(client, headers, trip_id, 1, date="2026-11-02", note="休整 / 自由活动")

    body = (await client.get(f"/api/v1/trips/{trip_id}/export/ics", headers=headers)).text
    events = [_unfold(e) for e in _events(body)]
    assert len(events) == 1
    assert any("SUMMARY:Day 1" in line for line in events[0])
    assert any("休整" in line for line in events[0])


@pytest.mark.asyncio
async def test_ics_derives_date_from_start_date(client: AsyncClient, auth_user):
    """day.date 缺失 → 用 start_date + (day_number-1) 推导，不编造别的日期。"""
    _user, headers = auth_user
    trip_id = await _make_trip(client, headers, start_date="2026-11-01", end_date="2026-11-03")
    day1 = await _add_day(client, headers, trip_id, 1)
    await _add_stop(client, headers, day1, name="第一天景点")
    day3 = await _add_day(client, headers, trip_id, 3)
    await _add_stop(client, headers, day3, name="第三天景点")

    body = (await client.get(f"/api/v1/trips/{trip_id}/export/ics", headers=headers)).text
    events = [_unfold(e) for e in _events(body)]
    starts = sorted(line for e in events for line in e if line.startswith("DTSTART"))
    assert starts == ["DTSTART;VALUE=DATE:20261101", "DTSTART;VALUE=DATE:20261103"]


@pytest.mark.asyncio
async def test_ics_owner_isolation(client: AsyncClient, auth_user):
    """归属隔离：他人行程不可导出。"""
    _user, headers = auth_user
    trip_id = await _make_trip(client, headers)

    other = await client.post("/api/v1/auth/register", json={
        "email": "other-ics@test.com", "password": "test1234", "display_name": "他者",
    })
    assert other.status_code == 201, other.text
    other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}

    resp = await client.get(f"/api/v1/trips/{trip_id}/export/ics", headers=other_headers)
    assert resp.status_code in (403, 404)


@pytest.mark.asyncio
async def test_ics_requires_login(client: AsyncClient, auth_user):
    _user, headers = auth_user
    trip_id = await _make_trip(client, headers)
    resp = await client.get(f"/api/v1/trips/{trip_id}/export/ics")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_ics_shared_token(client: AsyncClient, auth_user):
    """分享令牌免登录导出，且响应里不出现令牌本身。"""
    _user, headers = auth_user
    trip_id = await _make_trip(client, headers)
    day_id = await _add_day(client, headers, trip_id, 1, date="2026-11-01")
    await _add_stop(client, headers, day_id, name="西湖")

    share = await client.post(f"/api/v1/trips/{trip_id}/share", headers=headers)
    assert share.status_code == 200, share.text
    token = share.json()["share_token"]

    resp = await client.get(f"/api/v1/trips/share/{token}/export/ics")
    assert resp.status_code == 200, resp.text
    assert "SUMMARY:西湖" in "".join(_unfold(_lines(resp.text)))
    # 令牌绝不进导出产物
    assert token not in resp.text
    assert "share_token" not in resp.text


@pytest.mark.asyncio
async def test_ics_shared_invalid_token(client: AsyncClient):
    resp = await client.get("/api/v1/trips/share/not-a-real-token/export/ics")
    assert resp.status_code == 404
