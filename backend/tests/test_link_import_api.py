"""task-screenshot-import（验收升级）链接提取 API 层测试。

依赖 conftest 的 client / auth_user 夹具（真实测试库 + ASGI 传输）。
抓取用 monkeypatch 注入假 fetch_page（零网络），确定性验证链路：
鉴权 / 成功提取 / 静默降级（fetch 失败、无 meta）/ URL 非法 422。
"""
from __future__ import annotations

import pytest

from app.services import link_import as li

FAKE_HTML = (
    '<html><head>'
    '<meta property="og:title" content="杭州西湖三日游攻略"/>'
    '<meta property="og:description" content="1. 西湖，环湖绿道\n2. 灵隐寺，门票75元"/>'
    '</head></html>'
)


@pytest.fixture()
def fake_fetch(monkeypatch):
    """注入假 fetch_page：返回 FAKE_HTML；测试可改写返回值。"""
    monkeypatch.setattr(li, "fetch_page", lambda url: FAKE_HTML)


async def test_link_import_requires_auth(client, fake_fetch):
    resp = await client.post(
        "/api/v1/trips/link/import",
        json={"url": "https://www.xiaohongshu.com/explore/abc"},
    )
    assert resp.status_code == 401


async def test_link_import_api_extract_flow(client, auth_user, fake_fetch):
    _, headers = auth_user
    resp = await client.post(
        "/api/v1/trips/link/import",
        json={"url": "https://www.xiaohongshu.com/explore/abc"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["extracted"] is True
    assert body["platform"] == "xiaohongshu"
    assert body["title"] == "杭州西湖三日游攻略"
    names = [c["name"] for c in body["candidates"]]
    assert "西湖" in names
    assert "灵隐寺" in names


async def test_link_import_api_degrades_on_fetch_failure(client, auth_user, monkeypatch):
    """fetch 抛错 → 200 + extracted=false（静默降级为链接收藏）。"""
    _, headers = auth_user

    def _boom(url: str) -> str:
        raise li.LinkImportError("fetch_failed", "网络错误")

    monkeypatch.setattr(li, "fetch_page", _boom)
    resp = await client.post(
        "/api/v1/trips/link/import",
        json={"url": "https://www.xiaohongshu.com/explore/abc"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["extracted"] is False
    assert body["platform"] == "xiaohongshu"
    assert body["candidates"] == []


async def test_link_import_api_degrades_on_no_meta(client, auth_user, monkeypatch):
    _, headers = auth_user
    monkeypatch.setattr(li, "fetch_page", lambda url: "<html><head></head><body>反爬壳</body></html>")
    resp = await client.post(
        "/api/v1/trips/link/import",
        json={"url": "https://www.mafengwo.cn/i/2.html"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["extracted"] is False
    assert body["platform"] == "mafengwo"


async def test_link_import_api_rejects_bad_url(client, auth_user, fake_fetch):
    _, headers = auth_user
    resp = await client.post(
        "/api/v1/trips/link/import",
        json={"url": "javascript:alert(1)"},
        headers=headers,
    )
    assert resp.status_code == 422
    body = resp.json()
    # javascript: scheme → 服务层 LinkImportError → 全局 handler 包成 http_error
    assert body["error"]["code"] == "http_error"
    assert "unsupported_scheme" in body["error"]["message"]


async def test_link_import_api_rejects_oversized_url(client, auth_user, fake_fetch):
    _, headers = auth_user
    resp = await client.post(
        "/api/v1/trips/link/import",
        json={"url": "https://example.com/" + "a" * 5000},
        headers=headers,
    )
    assert resp.status_code == 422
    body = resp.json()
    assert body["error"]["code"] == "validation_error"