"""本机发布器（agent 通道）测试：任务生命周期 / 隔离 / 选择器下发。

覆盖的是"服务器零凭证"这条承诺的可验证部分：
- 服务端只建任务，不启动任何浏览器（本文件不依赖 playwright）；
- 任务只能被本人领取/回写；
- 状态只前进不回退，终态不可修改；
- 选择器由服务端下发（扩展不写死 CSS）。
"""
from __future__ import annotations

import base64
import struct
import time
import zlib
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

from app.common.config import settings
from app.models import XhsPublishTask
from app.services import xhs_agent_service, xhs_publish_service, xhs_service


def make_png(width: int = 2, height: int = 2) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + b"\xff\x00\x00" * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def png_data_url() -> str:
    return "data:image/png;base64," + base64.b64encode(make_png()).decode()


@pytest.fixture(autouse=True)
def agent_mode(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "XHS_ASSET_DIR", str(tmp_path / "assets"))
    monkeypatch.setattr(settings, "XHS_AGENT_TASK_TTL_MINUTES", 30)
    xhs_publish_service.reset_for_tests()
    xhs_service.factory.set_driver_factory(None)
    yield
    xhs_service.factory.set_driver_factory(None)


async def _make_trip(client: AsyncClient, headers: dict) -> str:
    resp = await client.post(
        "/api/v1/trips",
        headers=headers,
        json={
            "title": "本地发布器行程",
            "destination": "杭州",
            "departure": "上海",
            "start_date": "2026-11-01",
            "end_date": "2026-11-03",
            "travelers": 2,
            "budget": 3000,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _upload_asset(client: AsyncClient, headers: dict, trip_id: str) -> str:
    resp = await client.post(
        f"/api/v1/trips/{trip_id}/xhs-assets", headers=headers, json={"data_url": png_data_url()}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["asset_id"]


async def _publish(client: AsyncClient, headers: dict, trip_id: str, asset_id: str) -> dict:
    resp = await client.post(
        f"/api/v1/trips/{trip_id}/xhs-publish",
        headers=headers,
        json={
            "title": "杭州3天2夜",
            "body": "西湖骑行 + 灵隐寺",
            "topics": ["杭州", "旅行"],
            "asset_ids": [asset_id],
            "mode": "agent",
        },
    )
    assert resp.status_code == 202, resp.text
    return resp.json()


# ── 通道能力 ────────────────────────────────────────────────
async def test_channels_agent_mode_exposes_external_agent(client, auth_user):
    _, headers = auth_user
    trip_id = await _make_trip(client, headers)
    resp = await client.get(f"/api/v1/trips/{trip_id}/xhs-channels?mode=agent", headers=headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["mode"] == "agent"
    assert data["external_agent"] is True
    assert data["requires_images"] is True
    assert "agent" in data["available_modes"]


async def test_selectors_are_served_by_backend(client, auth_user):
    """扩展不写死 CSS：选择器与版本号由服务端下发。"""
    _, headers = auth_user
    resp = await client.get("/api/v1/xhs/agent/selectors", headers=headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["version"]
    assert data["publish_url"].startswith("https://creator.xiaohongshu.com")
    assert data["selectors"]["title"] and data["selectors"]["editor"]
    assert data["selectors"]["submit_bar"]  # closed shadow 动作栏


# ── 任务生命周期 ────────────────────────────────────────────
async def test_publish_creates_pending_task_without_browser(client, auth_user):
    _, headers = auth_user
    trip_id = await _make_trip(client, headers)
    asset_id = await _upload_asset(client, headers, trip_id)

    job = await _publish(client, headers, trip_id, asset_id)
    assert job["mode"] == "agent"
    assert job["state"] == "pending_agent"
    assert job["submitted"] is False
    assert job["hint_key"] == "xhsNote.publishAgentHint"

    # 前端轮询：agent 任务不在内存 job 表里，要能回落到数据库任务
    poll = await client.get(f"/api/v1/trips/{trip_id}/xhs-publish/{job['job_id']}", headers=headers)
    assert poll.status_code == 200, poll.text
    assert poll.json()["state"] == "pending_agent"


async def test_agent_lists_and_claims_task(client, auth_user):
    _, headers = auth_user
    trip_id = await _make_trip(client, headers)
    asset_id = await _upload_asset(client, headers, trip_id)
    job = await _publish(client, headers, trip_id, asset_id)

    listing = await client.get("/api/v1/xhs/agent/tasks?state=pending", headers=headers)
    assert listing.status_code == 200, listing.text
    items = listing.json()["items"]
    assert [t["task_id"] for t in items] == [job["job_id"]]
    task = items[0]
    assert task["title"] == "杭州3天2夜"
    assert task["topics"] == ["杭州", "旅行"]
    assert task["images"][0]["url"].startswith(f"/api/v1/trips/{trip_id}/xhs-assets/")

    claim = await client.post(
        f"/api/v1/xhs/agent/tasks/{job['job_id']}/claim",
        headers=headers,
        json={"agent": "chrome-ext:test"},
    )
    assert claim.status_code == 200, claim.text
    body = claim.json()
    assert body["task"]["state"] == "claimed"
    assert body["selectors"]["version"]

    # 重复领取幂等
    again = await client.post(
        f"/api/v1/xhs/agent/tasks/{job['job_id']}/claim", headers=headers, json={}
    )
    assert again.status_code == 200
    assert again.json()["task"]["state"] == "claimed"


async def test_agent_reports_filled_then_published(client, auth_user):
    _, headers = auth_user
    trip_id = await _make_trip(client, headers)
    asset_id = await _upload_asset(client, headers, trip_id)
    job = await _publish(client, headers, trip_id, asset_id)
    task_id = job["job_id"]

    filled = await client.post(
        f"/api/v1/xhs/agent/tasks/{task_id}/result",
        headers=headers,
        json={"state": "filled", "message": "表单已填好"},
    )
    assert filled.status_code == 200, filled.text
    poll = await client.get(f"/api/v1/trips/{trip_id}/xhs-publish/{task_id}", headers=headers)
    assert poll.json()["state"] == "ready"

    published = await client.post(
        f"/api/v1/xhs/agent/tasks/{task_id}/result",
        headers=headers,
        json={"state": "published", "note_url": "https://www.xiaohongshu.com/explore/abc"},
    )
    assert published.status_code == 200, published.text
    poll = await client.get(f"/api/v1/trips/{trip_id}/xhs-publish/{task_id}", headers=headers)
    data = poll.json()
    assert data["state"] == "published"
    assert data["submitted"] is True
    assert data["note_url"].endswith("/abc")


async def test_terminal_task_cannot_be_rewritten(client, auth_user):
    _, headers = auth_user
    trip_id = await _make_trip(client, headers)
    asset_id = await _upload_asset(client, headers, trip_id)
    job = await _publish(client, headers, trip_id, asset_id)
    task_id = job["job_id"]

    await client.post(
        f"/api/v1/xhs/agent/tasks/{task_id}/result", headers=headers, json={"state": "published"}
    )
    resp = await client.post(
        f"/api/v1/xhs/agent/tasks/{task_id}/result", headers=headers, json={"state": "failed"}
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "task_closed"


async def test_publish_again_supersedes_old_pending(client, auth_user):
    _, headers = auth_user
    trip_id = await _make_trip(client, headers)
    asset_id = await _upload_asset(client, headers, trip_id)

    first = await _publish(client, headers, trip_id, asset_id)
    second = await _publish(client, headers, trip_id, asset_id)

    listing = await client.get("/api/v1/xhs/agent/tasks?state=pending", headers=headers)
    ids = [t["task_id"] for t in listing.json()["items"]]
    assert ids == [second["job_id"]]

    old = await client.get(f"/api/v1/trips/{trip_id}/xhs-publish/{first['job_id']}", headers=headers)
    assert old.json()["state"] == "failed"  # cancelled → 前端映射为 failed
    assert old.json()["reason"] == "superseded"


async def test_task_is_owner_only(client, auth_user):
    _, owner = auth_user
    trip_id = await _make_trip(client, owner)
    asset_id = await _upload_asset(client, owner, trip_id)
    job = await _publish(client, owner, trip_id, asset_id)

    other = await client.post(
        "/api/v1/auth/register",
        json={"email": f"x-{time.time_ns()}@test.com", "password": "test1234"},
    )
    other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}

    # 别人的任务：列表里看不到
    listing = await client.get("/api/v1/xhs/agent/tasks", headers=other_headers)
    assert listing.json()["items"] == []
    # 领取被拒（不泄露"存在但不属于你"）
    claim = await client.post(
        f"/api/v1/xhs/agent/tasks/{job['job_id']}/claim", headers=other_headers, json={}
    )
    assert claim.status_code == 400
    assert claim.json()["error"]["code"] == "task_not_found"


async def test_expired_task_is_not_claimable(client, auth_user, db_session):
    _, headers = auth_user
    trip_id = await _make_trip(client, headers)
    asset_id = await _upload_asset(client, headers, trip_id)
    job = await _publish(client, headers, trip_id, asset_id)

    task = await db_session.get(XhsPublishTask, job["job_id"])
    task.created_at = datetime.now(UTC) - timedelta(hours=2)
    await db_session.commit()

    listing = await client.get("/api/v1/xhs/agent/tasks?state=pending", headers=headers)
    assert listing.json()["items"] == []
    claim = await client.post(
        f"/api/v1/xhs/agent/tasks/{job['job_id']}/claim", headers=headers, json={}
    )
    assert claim.status_code == 400
    assert claim.json()["error"]["code"] == "task_not_claimable"


async def test_agent_requires_images(client, auth_user):
    _, headers = auth_user
    trip_id = await _make_trip(client, headers)
    resp = await client.post(
        f"/api/v1/trips/{trip_id}/xhs-publish",
        headers=headers,
        json={"title": "杭州", "body": "正文", "mode": "agent"},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "no_images"


def test_selector_bundle_shape():
    """选择器包契约（扩展靠它，不写死 CSS）。"""
    bundle = xhs_agent_service.selector_bundle()
    assert set(bundle) >= {"version", "publish_url", "selectors", "body_template"}
    assert bundle["body_template"] == "{body}\n\n{topics}"
    assert all(isinstance(v, list) for v in bundle["selectors"].values())
