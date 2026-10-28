"""Provider 层回归测试（app/agent/providers.py）。

背景：2026-10-28 事故——本机 ollama 只有 batiai/gemma4-12b:q4，而 OLLAMA_MODEL
落回默认 qwen2.5:7b（.env 未配置）。OllamaProvider.healthcheck 只做端口连通检查，
把"模型缺失"的坏 provider 放进了兜底链，直到真正调用才 404，把配置错误伪装成
瞬时故障，白白烧掉一次失败并计入熔断器。

钉住的行为：
- 模型存在 → healthcheck True（正常放行）
- 模型缺失（/api/show 404）→ healthcheck False（坏 provider 不进兜底链，fail-fast）
- 网络/解析异常 → healthcheck False（绝不把坏 provider 放进链）
- healthcheck 先查端口、再查模型存在性（缺一不可）

预期确定性输出，所有网络均被 mock，不触真实 ollama。
"""
from __future__ import annotations

from unittest import mock

from app.agent.providers import OllamaProvider


class _Resp:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


class _FakeBasicResponse:
    """socket.create_connection 上下文管理器返回体（模拟端口连通）。"""

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:  # noqa: ANN002
        return None


def _patch_socket(monkeypatch) -> None:
    """默认让端口连通（healthcheck 测试聚焦在模型校验层）。"""
    monkeypatch.setattr(
        "socket.create_connection",
        lambda *a, **k: _FakeBasicResponse(),
    )


def test_healthcheck_true_when_model_exists(monkeypatch) -> None:
    _patch_socket(monkeypatch)
    monkeypatch.setattr(
        "httpx.post",
        lambda *a, **k: _Resp(status_code=200),
    )
    assert OllamaProvider().healthcheck() is True


def test_healthcheck_false_when_model_missing(monkeypatch) -> None:
    """ollama 未拉取配置的模型（/api/show 404）→ 视为不可用，不进兜底链。"""
    _patch_socket(monkeypatch)
    monkeypatch.setattr(
        "httpx.post",
        lambda *a, **k: _Resp(status_code=404),
    )
    assert OllamaProvider().healthcheck() is False


def test_healthcheck_false_when_network_error(monkeypatch) -> None:
    """模型校验请求异常 → 不可用（绝不把坏 provider 放进链）。"""
    _patch_socket(monkeypatch)

    def _raise(*a, **k):
        raise RuntimeError("ollama http error")

    monkeypatch.setattr("httpx.post", _raise)
    assert OllamaProvider().healthcheck() is False


def test_healthcheck_false_when_port_closed(monkeypatch) -> None:
    """端口不通 → 直接 False，不发起模型校验。"""
    def _raise(*a, **k):
        raise ConnectionRefusedError("port closed")

    monkeypatch.setattr("socket.create_connection", _raise)
    assert OllamaProvider().healthcheck() is False


def test_healthcheck_checks_port_then_model(monkeypatch) -> None:
    """端口连通后必须校验模型存在（两段都走才算可用）。"""
    calls: list[str] = []
    _patch_socket(monkeypatch)

    def _http(*a, **k):
        calls.append("http")
        return _Resp(status_code=200)

    monkeypatch.setattr("httpx.post", _http)
    assert OllamaProvider().healthcheck() is True
    assert calls == ["http"]


def test_healthcheck_does_not_call_http_when_port_closed(monkeypatch) -> None:
    """端口不通时不应发起模型校验请求（fail-fast）。"""
    def _raise(*a, **k):
        raise ConnectionRefusedError("port closed")

    monkeypatch.setattr("socket.create_connection", _raise)
    http_calls: list[str] = []

    def _http(*a, **k):
        http_calls.append("http")
        return _Resp(status_code=200)

    monkeypatch.setattr("httpx.post", _http)
    assert OllamaProvider().healthcheck() is False
    assert http_calls == []