"""小红书发布通道 API 测试：资产上传 / 通道能力 / 异步发布任务。

用 ``FakeDriver`` 注入工厂，把「HTTP → 任务编排 → 策略 → 驱动 → 状态回写」
整条链路真实跑通，不需要浏览器、不产生任何对外副作用。
"""
from __future__ import annotations

import asyncio
import base64
import struct
import time
import zlib

import pytest
from httpx import AsyncClient

from app.common.config import settings
from app.services import xhs_publish_service, xhs_service
from app.services.publishers.drivers.fake import FakeDriver


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


async def _make_trip(client: AsyncClient, headers: dict) -> str:
    resp = await client.post(
        "/api/v1/trips",
        headers=headers,
        json={
            "title": "小红书发布行程",
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


async def _wait_job(
    client: AsyncClient, headers: dict, trip_id: str, job_id: str, timeout: float = 5.0
) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        resp = await client.get(f"/api/v1/trips/{trip_id}/xhs-publish/{job_id}", headers=headers)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        if data["state"] not in ("queued", "running"):
            return data
        await asyncio.sleep(0.02)
    raise AssertionError("发布任务未在时限内结束")


@pytest.fixture(autouse=True)
def isolated_publish(tmp_path, monkeypatch):
    """独立资产目录 + 每个测试重置 job 表与驱动注入。"""
    monkeypatch.setattr(settings, "XHS_ASSET_DIR", str(tmp_path / "assets"))
    xhs_publish_service.reset_for_tests()
    xhs_service.factory.set_driver_factory(None)
    yield
    xhs_service.factory.set_driver_factory(None)
    xhs_publish_service.reset_for_tests()


# ── 通道能力 ────────────────────────────────────────────────
async def test_channels_default_to_manual(client, auth_user, monkeypatch):
    _, headers = auth_user
    monkeypatch.setattr(settings, "XHS_PUBLISH_MODE", "manual")
    trip_id = await _make_trip(client, headers)

    resp = await client.get(f"/api/v1/trips/{trip_id}/xhs-channels", headers=headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["mode"] == "manual"
    assert data["connected"] is False
    assert data["available_modes"] == ["manual", "rpa"]
    assert data["driver"] is None


async def test_channels_rpa_mode(client, auth_user, monkeypatch):
    _, headers = auth_user
    monkeypatch.setattr(settings, "XHS_PUBLISH_MODE", "rpa")
    trip_id = await _make_trip(client, headers)

    resp = await client.get(f"/api/v1/trips/{trip_id}/xhs-channels", headers=headers)
    data = resp.json()
    assert data["mode"] == "rpa"
    assert data["requires_images"] is True
    assert data["driver"] == "playwright"


async def test_channels_requires_auth(client, auth_user):
    _, headers = auth_user
    trip_id = await _make_trip(client, headers)
    resp = await client.get(f"/api/v1/trips/{trip_id}/xhs-channels")
    assert resp.status_code in (401, 403)


# ── 图片资产 ────────────────────────────────────────────────
async def test_upload_and_fetch_asset(client, auth_user):
    _, headers = auth_user
    trip_id = await _make_trip(client, headers)

    resp = await client.post(
        f"/api/v1/trips/{trip_id}/xhs-assets",
        headers=headers,
        json={"data_url": png_data_url()},
    )
    assert resp.status_code == 201, resp.text
    asset = resp.json()
    assert asset["mime"] == "image/png"
    assert (asset["width"], asset["height"]) == (2, 2)

    got = await client.get(f"/api/v1/trips/{trip_id}/xhs-assets/{asset['asset_id']}", headers=headers)
    assert got.status_code == 200
    assert got.headers["content-type"].startswith("image/png")
    assert got.content[:8] == b"\x89PNG\r\n\x1a\n"


async def test_upload_rejects_non_image(client, auth_user):
    _, headers = auth_user
    trip_id = await _make_trip(client, headers)
    resp = await client.post(
        f"/api/v1/trips/{trip_id}/xhs-assets",
        headers=headers,
        json={"data_url": "data:image/gif;base64,R0lGODlhAQABAAAAACw="},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "bad_asset_mime"


async def test_asset_is_owner_only(client, auth_user):
    """别人的行程读不到资产（404，而不是 403 泄露存在性）。"""
    _, owner = auth_user
    trip_id = await _make_trip(client, owner)
    asset = (
        await client.post(
            f"/api/v1/trips/{trip_id}/xhs-assets", headers=owner, json={"data_url": png_data_url()}
        )
    ).json()

    other = await client.post(
        "/api/v1/auth/register",
        json={"email": f"other-{time.time_ns()}@test.com", "password": "test1234"},
    )
    other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}
    resp = await client.get(
        f"/api/v1/trips/{trip_id}/xhs-assets/{asset['asset_id']}", headers=other_headers
    )
    assert resp.status_code == 404


# ── 发布任务 ────────────────────────────────────────────────
async def test_publish_manual_mode_returns_copy_payload(client, auth_user, monkeypatch):
    _, headers = auth_user
    monkeypatch.setattr(settings, "XHS_PUBLISH_MODE", "manual")
    trip_id = await _make_trip(client, headers)

    resp = await client.post(
        f"/api/v1/trips/{trip_id}/xhs-publish",
        headers=headers,
        json={"title": "杭州3天2夜", "body": "西湖骑行", "topics": ["杭州"]},
    )
    assert resp.status_code == 202, resp.text
    job = await _wait_job(client, headers, trip_id, resp.json()["job_id"])
    assert job["state"] == "manual"
    assert job["submitted"] is False


async def test_publish_rpa_semi_auto_fills_form(client, auth_user, monkeypatch):
    _, headers = auth_user
    monkeypatch.setattr(settings, "XHS_PUBLISH_MODE", "rpa")
    drivers: list[FakeDriver] = []

    def _factory() -> FakeDriver:
        driver = FakeDriver()
        drivers.append(driver)
        return driver

    xhs_service.factory.set_driver_factory(_factory)
    trip_id = await _make_trip(client, headers)

    asset = (
        await client.post(
            f"/api/v1/trips/{trip_id}/xhs-assets", headers=headers, json={"data_url": png_data_url()}
        )
    ).json()

    resp = await client.post(
        f"/api/v1/trips/{trip_id}/xhs-publish",
        headers=headers,
        json={
            "title": "杭州3天2夜",
            "body": "西湖骑行 + 灵隐寺",
            "topics": ["杭州", "旅行"],
            "asset_ids": [asset["asset_id"]],
        },
    )
    assert resp.status_code == 202, resp.text
    job = await _wait_job(client, headers, trip_id, resp.json()["job_id"])

    assert job["state"] == "ready"
    assert job["submitted"] is False
    assert job["mode"] == "rpa"
    assert job["hint_key"] == "xhsNote.publishReadyHint"
    assert len(drivers) == 1
    form = drivers[0].form
    assert form is not None
    assert form.title == "杭州3天2夜"
    assert form.image_paths and form.image_paths[0].endswith(".png")
    assert form.image_paths[0].isascii()
    assert "submit" not in drivers[0].calls  # 半自动绝不点发布


async def test_publish_rpa_auto_submit(client, auth_user, monkeypatch):
    _, headers = auth_user
    monkeypatch.setattr(settings, "XHS_PUBLISH_MODE", "rpa")
    xhs_service.factory.set_driver_factory(
        lambda: FakeDriver(note_url="https://www.xiaohongshu.com/explore/xyz789")
    )
    trip_id = await _make_trip(client, headers)
    asset = (
        await client.post(
            f"/api/v1/trips/{trip_id}/xhs-assets", headers=headers, json={"data_url": png_data_url()}
        )
    ).json()

    resp = await client.post(
        f"/api/v1/trips/{trip_id}/xhs-publish",
        headers=headers,
        json={
            "title": "杭州3天2夜",
            "body": "西湖骑行",
            "asset_ids": [asset["asset_id"]],
            "auto_submit": True,
        },
    )
    job = await _wait_job(client, headers, trip_id, resp.json()["job_id"])
    assert job["state"] == "published"
    assert job["submitted"] is True
    assert job["note_url"] == "https://www.xiaohongshu.com/explore/xyz789"


async def test_publish_requires_image_in_rpa_mode(client, auth_user, monkeypatch):
    _, headers = auth_user
    monkeypatch.setattr(settings, "XHS_PUBLISH_MODE", "rpa")
    trip_id = await _make_trip(client, headers)

    resp = await client.post(
        f"/api/v1/trips/{trip_id}/xhs-publish",
        headers=headers,
        json={"title": "杭州3天2夜", "body": "西湖骑行"},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "no_images"


async def test_publish_rejects_too_long_title(client, auth_user, monkeypatch):
    _, headers = auth_user
    monkeypatch.setattr(settings, "XHS_PUBLISH_MODE", "manual")
    trip_id = await _make_trip(client, headers)

    resp = await client.post(
        f"/api/v1/trips/{trip_id}/xhs-publish",
        headers=headers,
        json={"title": "一" * 21, "body": "正文"},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "title_too_long"


async def test_publish_reports_login_required(client, auth_user, monkeypatch):
    _, headers = auth_user
    monkeypatch.setattr(settings, "XHS_PUBLISH_MODE", "rpa")
    xhs_service.factory.set_driver_factory(lambda: FakeDriver(logged_in=False))
    trip_id = await _make_trip(client, headers)
    asset = (
        await client.post(
            f"/api/v1/trips/{trip_id}/xhs-assets", headers=headers, json={"data_url": png_data_url()}
        )
    ).json()

    resp = await client.post(
        f"/api/v1/trips/{trip_id}/xhs-publish",
        headers=headers,
        json={
            "title": "杭州3天2夜",
            "body": "西湖骑行",
            "asset_ids": [asset["asset_id"]],
        },
    )
    job = await _wait_job(client, headers, trip_id, resp.json()["job_id"])
    assert job["state"] == "failed"
    assert job["reason"] == "login_required"


async def test_publish_job_from_other_trip_is_404(client, auth_user, monkeypatch):
    _, headers = auth_user
    monkeypatch.setattr(settings, "XHS_PUBLISH_MODE", "manual")
    trip_a = await _make_trip(client, headers)
    trip_b = await _make_trip(client, headers)

    resp = await client.post(
        f"/api/v1/trips/{trip_a}/xhs-publish",
        headers=headers,
        json={"title": "杭州", "body": "正文"},
    )
    job_id = resp.json()["job_id"]
    await _wait_job(client, headers, trip_a, job_id)

    resp = await client.get(f"/api/v1/trips/{trip_b}/xhs-publish/{job_id}", headers=headers)
    assert resp.status_code == 404
