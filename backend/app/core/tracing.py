"""请求级 Trace 上下文：为每个 HTTP 请求生成 trace_id，并在整个请求生命周期内共享。

- ``trace_id``：uuid4 hex（12 位短前缀即可，保证请求唯一且可读）
- contextvar 保证并发安全：并发的多个请求各持自己的 trace_id，互不串扰
- ``RequestIdMiddleware``：生成/透传 trace_id → 写入 contextvar → 响应头 ``X-Trace-ID``
- 日志系统（``app.core.logging``）自动读取当前 trace_id 附加到结构化日志

用法（业务代码无需显式传递）：
    from app.core.tracing import current_trace_id
    trace_id = current_trace_id()  # 请求内任意位置可读

支持从上游透传（``X-Trace-ID`` 请求头），便于 nginx / 网关 / 客户端将
前端链路与后端日志关联。
"""
from __future__ import annotations

import uuid
from contextlib import contextmanager
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

_trace_id_var: ContextVar[str | None] = ContextVar("trace_id", default=None)

# 透传头名称（客户端 / 网关可携带，后端优先采用）
TRACE_ID_HEADER = "X-Trace-ID"


def current_trace_id() -> str | None:
    """当前请求的 trace_id（无请求上下文时返回 None）。"""
    return _trace_id_var.get()


def _new_trace_id() -> str:
    return uuid.uuid4().hex[:16]


@contextmanager
def trace_context(trace_id: str):
    """把一段代码包进指定 trace_id 作用域（后台任务 / 定时任务 / worker 使用）。

    用法：
        with trace_context(f"task-{task_id}"):
            ...  # 期间所有 logger 输出自动携带该 trace_id
    """
    token = _trace_id_var.set(trace_id)
    try:
        yield
    finally:
        _trace_id_var.reset(token)


class RequestIdMiddleware(BaseHTTPMiddleware):
    """为每个请求生成 / 透传 trace_id，并写入响应头与 contextvar。

    顺序：优先采用上游 ``X-Trace-ID``（透传），否则生成新 id。
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        trace_id = request.headers.get(TRACE_ID_HEADER) or _new_trace_id()
        token = _trace_id_var.set(trace_id)
        try:
            response = await call_next(request)
        finally:
            _trace_id_var.reset(token)
        response.headers[TRACE_ID_HEADER] = trace_id
        return response