"""LLM Provider：openai / deepseek / ollama 统一接口。

默认行为：
- ``DEFAULT_LLM_PROVIDER`` 显式指定 provider（deepseek / openai / ollama）
- ``auto``：按已配置的 API key 顺序探测（deepseek → openai → ollama）
- 没有任何可用 key 时抛 ``LLMProviderError``（不再静默降级到 mock）

同时提供 LLM 调用的统一重试与熔断（system-level resilience）：

- 重试：瞬时故障（网络/超时/限流/5xx）按指数退避重试，``LLM_MAX_RETRIES`` 控制次数
- 熔断：滚动窗口内连续失败达到 ``LLM_BREAKER_FAILURE_THRESHOLD`` 直接开门，冷却后 HALF-OPEN 试探
"""
from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI

from app.common.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class LLMProviderError(Exception):
    """LLM 调用失败（配置缺失 / 未熔断的超时与 5xx）。"""


class LLMCircuitOpenError(LLMProviderError):
    """熔断器打开：短时间内对 LLM 的失败太多，拒绝调用以保护下游。"""


class BaseLLMProvider(ABC):
    name: str = "base"

    @abstractmethod
    def get_chat_model(self, temperature: float = 0.2) -> BaseChatModel:
        """返回 LangChain ChatModel。"""

    @property
    def model_id(self) -> str | None:
        return None

    def healthcheck(self) -> bool:
        """轻量可用性检查（如 base_url 可达）。默认认为可用。"""
        return True


class OpenAILikeProvider(BaseLLMProvider):
    """OpenAI 兼容接口（OpenAI / DeepSeek / 任意 base_url）。"""

    def __init__(
        self,
        *,
        name: str,
        api_key: str,
        base_url: str,
        model: str,
    ) -> None:
        if not api_key:
            raise LLMProviderError(f"{name} 缺少 API Key（请配置对应环境变量）")
        self.name = name
        self._api_key = api_key
        self._base_url = base_url
        self._model = model

    def get_chat_model(self, temperature: float = 0.2) -> BaseChatModel:
        return ChatOpenAI(
            model=self._model,
            api_key=self._api_key,
            base_url=self._base_url,
            temperature=temperature,
            timeout=settings.LLM_TIMEOUT,
            max_retries=settings.LLM_MAX_RETRIES,
        )

    @property
    def model_id(self) -> str | None:
        return self._model


class OllamaProvider(BaseLLMProvider):
    name = "ollama"

    def get_chat_model(self, temperature: float = 0.2) -> BaseChatModel:
        return ChatOllama(
            model=settings.OLLAMA_MODEL,
            base_url=settings.OLLAMA_BASE_URL,
            temperature=temperature,
        )

    @property
    def model_id(self) -> str | None:
        return settings.OLLAMA_MODEL

    def healthcheck(self) -> bool:
        """检查 Ollama 服务是否在监听。"""
        try:
            import socket
            from urllib.parse import urlparse

            parsed = urlparse(settings.OLLAMA_BASE_URL)
            with socket.create_connection((parsed.hostname or "127.0.0.1", parsed.port or 11434), timeout=2):
                return True
        except OSError:
            return False


class LLMCircuitBreaker:
    """进程内熔断器：滚动窗口滑动计数，失败达阈值即打开。

    线程安全（asyncio 单线程模型下足够），供 ``invoke_with_resilience`` 使用。
    """

    def __init__(
        self,
        *,
        failure_threshold: int = 3,
        recovery_timeout: float = 30.0,
        window_seconds: float = 60.0,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.window_seconds = window_seconds
        self._failures: list[float] = []
        self._state = "closed"  # closed / open / half_open
        self._opened_at: float | None = None

    @property
    def state(self) -> str:
        if self._state == "open" and self._opened_at is not None and time.monotonic() - self._opened_at >= self.recovery_timeout:
            self._state = "half_open"
        return self._state

    def allow(self) -> bool:
        st = self.state
        if st == "open":
            return False
        if st == "half_open_trial":
            return False  # 试探请求发出后、结果回来前，不再放行
        if st == "half_open":
            # 只放行一个试探请求
            self._state = "half_open_trial"
            return True
        return True

    def record_success(self) -> None:
        self._failures.clear()
        self._state = "closed"

    def record_failure(self) -> None:
        now = time.monotonic()
        self._failures = [t for t in self._failures if now - t < self.window_seconds]
        self._failures.append(now)
        if len(self._failures) >= self.failure_threshold:
            self._state = "open"
            self._opened_at = now


# 全局熔断器（进程级）
_circuit_breaker = LLMCircuitBreaker(
    failure_threshold=settings.LLM_BREAKER_FAILURE_THRESHOLD,
    recovery_timeout=settings.LLM_BREAKER_RECOVERY_TIMEOUT,
)


def available_provider_chain(preferred: str | None = None) -> list[BaseLLMProvider]:
    """按优先级返回可用 provider 实例列表（用于兜底链）。

    - ``preferred`` 非空且可用 → 放首位（主路径）
    - 其余按 auto 探测顺序（deepseek → openai → ollama）
    - ollama 会做 healthcheck，不可达自动跳过
    """
    chain: list[BaseLLMProvider] = []
    seen: set[str] = set()

    order = [preferred] if preferred and preferred != "auto" else []
    order += [
        name
        for name in _probe_available_providers()
        if not order or name != order[0]
    ]
    for name in order:
        if name in seen:
            continue
        try:
            prov = get_provider(name)
        except LLMProviderError:
            continue  # ollama 不可达 / 未知名 → 跳过，继续下一个
        seen.add(name)
        chain.append(prov)
    return chain


async def invoke_with_resilience(
    provider: BaseLLMProvider,
    messages: list[Any],
    *,
    temperature: float = 0.2,
    tools: list[Any] | None = None,
    providers: list[BaseLLMProvider] | None = None,
) -> AIMessage:
    """带重试 + 熔断 + Provider 兜底链的 LLM 调用。

    - 熔断打开 → 直接抛 ``LLMCircuitOpenError``（不发起网络请求）
    - 瞬时错误（TimeoutError / ConnectionError / 5xx / 限流）→ 指数退避重试
    - 主 provider 整链失败 → 依次尝试 ``providers`` 中的下一个（兜底链）
    - 成功 → 记录成功并返回
    - ``tools`` 非空时先 bind_tools（Agent 场景必须传入，否则 LLM 不知道可用工具）

    返回的 AIMessage 附 ``observation`` 元数据（response_metadata）：
    ``{"latency_ms", "attempts", "provider_chain", "token_usage", "cost_usd"}``，
    供调用方做结构化观测（每次 Agent 调用一条日志）。
    """
    chain = providers or [provider]
    last_error: Exception | None = None
    used_chain: list[str] = []
    total_attempts = 0

    for idx, prov in enumerate(chain):
        used_chain.append(prov.name)
        if not _circuit_breaker.allow():
            raise LLMCircuitOpenError(
                f"LLM 熔断已打开（{settings.LLM_BREAKER_FAILURE_THRESHOLD} 次失败），"
                f"冷却 {settings.LLM_BREAKER_RECOVERY_TIMEOUT}s 后自动试探"
            )

        model = prov.get_chat_model(temperature=temperature)
        if tools:
            model = model.bind_tools(tools)
        start = time.monotonic()

        for attempt in range(1, settings.LLM_MAX_RETRIES + 1):
            total_attempts += 1
            try:
                response = await model.ainvoke(messages)
                _circuit_breaker.record_success()
                latency_ms = int((time.monotonic() - start) * 1000)
                obs = _extract_observation(response, prov, latency_ms, used_chain, total_attempts)
                response.response_metadata = {**(getattr(response, "response_metadata", None) or {}), **obs}
                return response
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                is_transient = _is_transient_error(exc)
                if not is_transient or attempt == settings.LLM_MAX_RETRIES:
                    break
                delay = min(
                    settings.LLM_RETRY_BASE_DELAY * (2 ** (attempt - 1)),
                    settings.LLM_RETRY_MAX_DELAY,
                )
                await asyncio.sleep(delay)

        _circuit_breaker.record_failure()
        # 该 provider 已彻底失败 → 换下一个兜底 provider（若有），否则抛出
        if idx < len(chain) - 1:
            logger.warning("LLM provider=%s 失败，切换到下一个: %s", prov.name, chain[idx + 1].name)
            continue
        break

    raise LLMProviderError(
        f"LLM 调用失败（chain={used_chain}, attempts={total_attempts}）: {last_error}"
    ) from last_error


def _extract_observation(
    response: AIMessage,
    provider: BaseLLMProvider,
    latency_ms: int,
    provider_chain: list[str],
    attempts: int,
) -> dict[str, Any]:
    """从响应元数据提取结构化观测字段（token 用量/粗略成本）。"""
    meta = getattr(response, "response_metadata", None) or {}
    token_usage = meta.get("token_usage") or meta.get("usage") or {}
    prompt_tokens = int(token_usage.get("prompt_tokens") or token_usage.get("input_tokens") or 0)
    completion_tokens = int(token_usage.get("completion_tokens") or token_usage.get("output_tokens") or 0)
    total_tokens = prompt_tokens + completion_tokens

    # 粗略成本估算（美元）：仅在配置了单价时计算；否则 0（表示未核算）
    cost = 0.0
    in_rate = getattr(settings, "LLM_INPUT_PRICE_PER_1K", None)
    out_rate = getattr(settings, "LLM_OUTPUT_PRICE_PER_1K", None)
    if in_rate and out_rate:
        cost = round((prompt_tokens / 1000) * float(in_rate) + (completion_tokens / 1000) * float(out_rate), 6)

    return {
        "latency_ms": latency_ms,
        "attempts": attempts,
        "provider_chain": provider_chain,
        "provider": provider.name,
        "model": provider.model_id,
        "token_usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens, "total_tokens": total_tokens},
        "cost_usd": cost,
    }


def _is_transient_error(exc: Exception) -> bool:
    """判断是否为可重试的瞬时错误。"""
    if isinstance(exc, (TimeoutError, ConnectionError, OSError)):
        return True
    try:
        import openai

        if isinstance(exc, openai.APIError):
            return exc.status_code is None or exc.status_code >= 500 or exc.status_code == 429
    except ImportError:
        pass
    return False


# ── 注册表 ─────────────────────────────────────────────
PROVIDER_REGISTRY: dict[str, BaseLLMProvider] = {}


def _probe_available_providers() -> list[str]:
    """按优先级返回当前配置了 key、可用的 provider 名。"""
    candidates: list[tuple[str, bool]] = [
        ("deepseek", bool(settings.DEEPSEEK_API_KEY)),
        ("openai", bool(settings.OPENAI_API_KEY)),
        ("ollama", True),  # 本地服务，healthcheck 时再确认
    ]
    return [name for name, ok in candidates if ok]


def get_provider(name: str = "auto") -> BaseLLMProvider:
    """按名称（或 auto 探测）返回 provider 实例。

    - auto 且无任何 key → 抛 ``LLMProviderError``（明确报错，不默默降级）
    - ollama 会自动做 healthcheck，不可达则视为不可用
    """
    if name == "auto":
        available = _probe_available_providers()
        if not available:
            raise LLMProviderError(
                "未配置任何 LLM API Key（DEEPSEEK_API_KEY / OPENAI_API_KEY / 本地 Ollama）。"
                "请先在 backend/.env 中配置。"
            )
        name = available[0]

    if name in PROVIDER_REGISTRY:
        provider = PROVIDER_REGISTRY[name]
        if name == "ollama" and not provider.healthcheck():
            raise LLMProviderError("Ollama 服务不可达，请确认已启动（ollama serve）")
        return provider

    provider: BaseLLMProvider
    if name == "openai":
        provider = OpenAILikeProvider(
            name="openai",
            api_key=settings.OPENAI_API_KEY or "",
            base_url=settings.OPENAI_BASE_URL or "https://api.openai.com/v1",
            model=settings.OPENAI_MODEL,
        )
    elif name == "deepseek":
        provider = OpenAILikeProvider(
            name="deepseek",
            api_key=settings.DEEPSEEK_API_KEY or "",
            base_url=settings.DEEPSEEK_BASE_URL,
            model=settings.DEEPSEEK_MODEL,
        )
    elif name == "ollama":
        provider = OllamaProvider()
        if not provider.healthcheck():
            raise LLMProviderError("Ollama 服务不可达，请确认已启动（ollama serve）")
    else:
        raise LLMProviderError(f"未知 LLM provider: {name}")

    PROVIDER_REGISTRY[name] = provider
    return provider