"""对话式行程助手（B 期）API + 服务测试。

覆盖：
- 会话 CRUD：创建 / 列表 / 详情 / 删除（owner 隔离：他人看不到/删不掉）
- 消息：发送消息 → 持久化 user + assistant；历史消息可查
- 鉴权：未登录 401；他人会话 404
- LLM 路径全部 mock（不触真实模型）
"""
from __future__ import annotations

from typing import Any

import pytest


# ── 测试替身：mock AgentLoop.run（不触真实 LLM） ─────────────────
class _FakeLoop:
    """伪 AgentLoop：run 直接返回预设结果（不触 provider / 工具）。"""

    def __init__(self, reply: str = "已为你查询杭州：西湖、灵隐寺。", status: str = "completed"):
        self.reply = reply
        self.status = status

    async def run(self, message: str) -> dict[str, Any]:
        return {
            "status": self.status,
            "output": self.reply if self.status == "completed" else None,
            "messages": [],
            "trace": [],
            "corrections": 0,
            "error": None if self.status == "completed" else "llm down",
            "provider": "fake",
            "model": "fake-model",
        }


@pytest.fixture
def mock_loop(monkeypatch: pytest.MonkeyPatch):
    """把 chat_service 里的 AgentLoop 换成语义替身（返回固定回复）。

    注意：必须 patch ``app.services.chat_service.AgentLoop``（消费方模块级绑定），
    而不是 ``app.agent.runtime.AgentLoop``（定义处）——chat_service 顶层
    ``from app.agent.runtime import AgentLoop`` 是绑定到本模块的引用。
    """
    captured: dict[str, Any] = {}

    def _fake_agent_loop(**kwargs: Any) -> _FakeLoop:
        captured["kwargs"] = kwargs
        return _FakeLoop()

    monkeypatch.setattr("app.services.chat_service.AgentLoop", _fake_agent_loop)
    return captured


# ═══════════════ 会话 CRUD ═══════════════

async def test_create_and_list_sessions(client, auth_user, mock_loop):
    _, headers = auth_user
    resp = await client.post("/api/v1/chat/sessions", json={}, headers=headers)
    assert resp.status_code == 201, resp.text
    session = resp.json()
    assert session["id"]
    assert session["title"] == "新对话"

    resp = await client.get("/api/v1/chat/sessions", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["id"] == session["id"]


async def test_create_session_with_context_and_title(client, auth_user, mock_loop):
    _, headers = auth_user
    resp = await client.post(
        "/api/v1/chat/sessions",
        json={"title": "杭州攻略", "context": {"destination": "杭州", "trip_id": "t1"}},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["title"] == "杭州攻略"
    assert data["context"] == {"destination": "杭州", "trip_id": "t1"}


async def test_session_owner_isolation(client, auth_user):
    """owner 隔离：A 建的会话，B 看不到也删不掉。"""
    _, headers_a = auth_user
    # 建第二个用户 B
    import uuid

    email_b = f"user-b-{uuid.uuid4().hex[:8]}@test.com"
    resp_b = await client.post(
        "/api/v1/auth/register",
        json={"email": email_b, "password": "test1234", "display_name": "用户B"},
    )
    headers_b = {"Authorization": f"Bearer {resp_b.json()['access_token']}"}

    # A 建会话
    resp = await client.post("/api/v1/chat/sessions", json={}, headers=headers_a)
    session_id = resp.json()["id"]

    # B 查 A 的会话 → 404
    resp = await client.get(f"/api/v1/chat/sessions/{session_id}", headers=headers_b)
    assert resp.status_code == 404

    # B 删 A 的会话 → 404（实际删不到）
    resp = await client.delete(f"/api/v1/chat/sessions/{session_id}", headers=headers_b)
    assert resp.status_code == 404

    # A 自己能看到
    resp = await client.get(f"/api/v1/chat/sessions/{session_id}", headers=headers_a)
    assert resp.status_code == 200


async def test_delete_session(client, auth_user, mock_loop):
    _, headers = auth_user
    resp = await client.post("/api/v1/chat/sessions", json={}, headers=headers)
    session_id = resp.json()["id"]

    resp = await client.delete(f"/api/v1/chat/sessions/{session_id}", headers=headers)
    assert resp.status_code == 204

    resp = await client.get(f"/api/v1/chat/sessions/{session_id}", headers=headers)
    assert resp.status_code == 404


async def test_requires_auth(client):
    """未登录访问会话相关端点 → 401。"""
    resp = await client.get("/api/v1/chat/sessions")
    assert resp.status_code == 401


# ═══════════════ 消息 ═══════════════

async def test_send_message_persists_and_returns_reply(client, auth_user, mock_loop):
    _, headers = auth_user
    resp = await client.post("/api/v1/chat/sessions", json={}, headers=headers)
    session_id = resp.json()["id"]

    resp = await client.post(
        f"/api/v1/chat/sessions/{session_id}/messages",
        json={"message": "杭州有什么好玩的？"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["role"] == "assistant"
    assert "西湖" in data["content"]

    # 历史消息：user + assistant
    resp = await client.get(f"/api/v1/chat/sessions/{session_id}/messages", headers=headers)
    assert resp.status_code == 200
    msgs = resp.json()["items"]
    assert len(msgs) == 2
    assert msgs[0]["role"] == "user"
    assert msgs[0]["content"] == "杭州有什么好玩的？"
    assert msgs[1]["role"] == "assistant"


async def test_send_message_requires_session_owner(client, auth_user, mock_loop):
    _, headers = auth_user
    resp = await client.post("/api/v1/chat/sessions", json={}, headers=headers)
    session_id = resp.json()["id"]

    # 未登录发消息 → 401
    resp = await client.post(
        f"/api/v1/chat/sessions/{session_id}/messages",
        json={"message": "hi"},
    )
    assert resp.status_code == 401

    # 不存在的会话 → 404
    resp = await client.post(
        "/api/v1/chat/sessions/nonexistent/messages",
        json={"message": "hi"},
        headers=headers,
    )
    assert resp.status_code == 404


async def test_send_message_empty_rejected(client, auth_user, mock_loop):
    _, headers = auth_user
    resp = await client.post("/api/v1/chat/sessions", json={}, headers=headers)
    session_id = resp.json()["id"]

    resp = await client.post(
        f"/api/v1/chat/sessions/{session_id}/messages",
        json={"message": ""},
        headers=headers,
    )
    assert resp.status_code == 422


async def test_mock_loop_receives_system_prompt_and_tools(client, auth_user, mock_loop):
    """验证 chat_service 用 AgentLoop 装配了系统提示 + 工具。"""
    _, headers = auth_user
    resp = await client.post("/api/v1/chat/sessions", json={}, headers=headers)
    session_id = resp.json()["id"]

    await client.post(
        f"/api/v1/chat/sessions/{session_id}/messages",
        json={"message": "查天气"},
        headers=headers,
    )
    kwargs = mock_loop["kwargs"]
    assert kwargs["system_prompt"]
    assert "旅行助手" in kwargs["system_prompt"]
    # 工具集包含查询工具
    tool_names = [t.name for t in kwargs["tools"]]
    assert "search_attractions" in tool_names
    assert "query_weather" in tool_names
    # 护栏
    assert kwargs["max_iterations"] == 8