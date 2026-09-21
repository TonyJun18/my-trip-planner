# Agent 的容错工程：重试、熔断、降级，以及 FakeLLM 测试

> 写给：要把 Agent 放进生产环境的工程师。
> Agent 系统对外部依赖（LLM API、搜索、天气）的失败处理，决定了它是 demo 还是产品。
> 本文用真实代码讲四件事：重试怎么退避、熔断怎么开、数据源怎么降级、容错怎么自动化测试。

## 全景：Agent 依赖什么，就容错什么

一个 Agent 系统至少依赖三类外部服务，每一类都要有失败策略：

| 依赖 | 失败形态 | 应对 |
|---|---|---|
| LLM API | 超时、5xx、限流 429、网络抖动 | 指数退避重试 + 熔断 |
| 搜索/地理编码（Tavily/Nominatim/高德） | HTTP 错、超时、配额、空结果 | 多源降级 + 有界超时 |
| 本地服务（Ollama） | 端口不通 | 启动期 healthcheck + 明确报错 |

## 第一件：LLM 调用的统一重试（指数退避）

不要让每个 Agent 自己处理重试——**收口到一个函数**（`backend/app/agent/providers.py` 的 `invoke_with_resilience`）：所有对 LLM 的调用都走它。

```python
async def invoke_with_resilience(provider, messages, *, temperature=0.2, tools=None):
    if not _circuit_breaker.allow():
        raise LLMCircuitOpenError("LLM 熔断已打开，冷却后自动试探")

    model = provider.get_chat_model(temperature=temperature)
    if tools:
        model = model.bind_tools(tools)   # Agent 场景必须 bind_tools
    last_error = None

    for attempt in range(1, settings.LLM_MAX_RETRIES + 1):
        try:
            response = await model.ainvoke(messages)
            _circuit_breaker.record_success()
            return response
        except Exception as exc:
            last_error = exc
            if not _is_transient_error(exc) or attempt == settings.LLM_MAX_RETRIES:
                break
            delay = min(settings.LLM_RETRY_BASE_DELAY * (2 ** (attempt - 1)),
                        settings.LLM_RETRY_MAX_DELAY)
            await asyncio.sleep(delay)   # 指数退避

    _circuit_breaker.record_failure()
    raise LLMProviderError(f"LLM 调用失败: {last_error}") from last_error
```

要点：

- **只重试瞬时错误**（`TimeoutError / ConnectionError / 5xx / 429`），4xx 业务错误不重试
- **指数退避**（base × 2^n，封顶），避免雪崩式重试打爆 API
- **统一收口**——所有 Agent、所有工具调用都经过它，行为一致

## 第二件：进程内熔断器（滑动窗口）

重试只能救"抖一下"，救不了"API 挂了 5 分钟"——那时每次重试都在白白浪费时间。熔断器解决这个问题（`LLMCircuitBreaker`）：

```python
class LLMCircuitBreaker:
    """进程内熔断器：滚动窗口滑动计数，失败达阈值即打开。"""

    def __init__(self, *, failure_threshold=3, recovery_timeout=30.0, window_seconds=60.0):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.window_seconds = window_seconds
        self._failures: list[float] = []
        self._state = "closed"   # closed / open / half_open
        self._opened_at = None

    @property
    def state(self):
        if (self._state == "open" and self._opened_at is not None
                and time.monotonic() - self._opened_at >= self.recovery_timeout):
            self._state = "half_open"   # 冷却结束，放一个试探请求
        return self._state

    def allow(self) -> bool:
        st = self.state
        if st == "open":
            return False
        if st == "half_open_trial":
            return False  # 试探请求已发出，结果回来前不再放行
        if st == "half_open":
            self._state = "half_open_trial"
            return True
        return True

    def record_success(self):
        self._failures.clear()
        self._state = "closed"

    def record_failure(self):
        now = time.monotonic()
        self._failures = [t for t in self._failures if now - t < self.window_seconds]
        self._failures.append(now)
        if len(self._failures) >= self.failure_threshold:
            self._state = "open"
            self._opened_at = now
```

**状态机**：closed（正常）→ open（连续失败达阈值，拒绝所有请求）→ 冷却期后 half_open（放行一个试探请求）→ 成功回到 closed / 失败回到 open。

**效果**：LLM 挂掉时，请求在熔断器这一层就被拒绝（零网络开销），而不是每个请求都去撞墙等超时。用户拿到的是明确的"LLM 熔断已打开，请稍后重试"，而不是 30 秒超时后一个 500。

## 第三件：数据源多级降级

搜索和天气，主源挂了要有备用（`backend/app/agent/tools.py`）：

```python
async def search_attractions(city, *, query=None, limit=8):
    """真实数据：优先高德 POI，未配置降级 Tavily + Nominatim。"""
    if settings.AMAP_API_KEY:
        return await search_pois_amap(city, query=query, limit=limit, want_type="attraction")
    return await _search_pois_tavily(city, query=query, limit=limit, want_type="attraction")

async def query_weather(city, *, days=3):
    if settings.AMAP_API_KEY:
        try:
            return await _weather_amap(city, days=days)
        except SearchServiceError as exc:
            logger.warning("高德天气失败，降级 wttr.in city=%s err=%s", city, exc)
    return await _weather_wttr(city, days=days)
```

降级链设计原则：

- **主源失败 → 自动切备用**（高德 → Tavily/wttr.in），用户无感
- **日志记录降级路径**——事后能知道"今天高德挂了，我们用了备用源"
- **备用源也要有界超时**（Nominatim 限速 1.1s/请求、并发 6 上限）——免费的源更要尊重，不然被封
- **降级不是永远的**——每次都先试主源，主源恢复了自然切回去

## 第四件：容错怎么自动化测试（FakeLLM）

容错代码最怕"看起来对，没测过"。用测试替身模拟外部故障（`backend/tests/conftest.py`）：

```python
class FakeLLM:
    """测试替身：第一次返回坏 JSON，之后返回好 JSON。"""
    def __init__(self, bad_first: bool = True):
        self.calls = 0
        self.bad_first = bad_first

    async def ainvoke(self, messages):
        self.calls += 1
        if self.bad_first and self.calls == 1:
            return AIMessage(content='{"destination": "杭州", "days": []}')
        return AIMessage(content=GOOD_PLAN_JSON)
```

容错的测试场景：

- **重试**：只跑一次 `invoke_with_resilience`，断言 `LLM_MAX_RETRIES` 次调用后抛 `LLMProviderError`
- **熔断**：连续 `failure_threshold` 次失败后，断言 `allow() == False`；冷却期后再断言放行试探
- **降级**：mock 掉高德 `search_pois_amap` 抛错，断言自动走 `_search_pois_tavily`
- **自纠正**：FakeLLM 先出坏 JSON 再出好 JSON，断言 corrections 递增、最终 completed

**全部测试不耗 token、不依赖网络、毫秒级跑完。** 这在 CI 里能稳定跑，而真实 LLM 测试在 CI 里是灾难（慢、贵、flaky）。

## 小结：容错的四层防线

1. **重试**（指数退避）—— 救瞬时抖动
2. **熔断**（滑动窗口）—— 救持续故障，拒绝撞墙
3. **降级**（多源切换）—— 救单点依赖
4. **测试替身**（FakeLLM）—— 保证前三层真的work，且永不 flaky

**Agent 系统的可靠性不是 LLM 的巧合，而是工程层一层层兜出来的。**

---

*项目源码：github.com/TonyJun18/my-trip-planner*
*系列上一篇：[《让 Agent 稳定输出：Pydantic 强校验 + 失败自纠正》](./02-structured-output-validation.md)*