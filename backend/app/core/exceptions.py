"""业务异常体系 + FastAPI 异常处理器。"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class AppError(Exception):
    """业务异常基类。"""

    status_code = 400
    code = "app_error"

    def __init__(self, message: str, *, code: str | None = None, detail: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        self.detail = detail or {}


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


class LLMError(AppError):
    status_code = 502
    code = "llm_error"


class UnauthorizedError(AppError):
    """未认证 / 凭证无效（401）。"""

    status_code = 401
    code = "unauthorized"


class ExternalServiceError(AppError):
    status_code = 502
    code = "external_service_error"


def _error_response(status: int, code: str, message: str, detail: dict | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "detail": detail or {}}},
    )


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error_handler(_: Request, exc: AppError) -> JSONResponse:
        return _error_response(exc.status_code, exc.code, exc.message, exc.detail)

    @app.exception_handler(RequestValidationError)
    async def _validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Pydantic v2 错误 ctx 可能携带不可 JSON 序列化的异常对象（如 ValueError），
        # 直接塞进响应体会导致 500 —— 统一转成字符串再返回。
        def _safe(e: dict) -> dict:
            e = dict(e)
            ctx = e.get("ctx")
            if ctx:
                e["ctx"] = {k: (str(v) if isinstance(v, BaseException) else v) for k, v in ctx.items()}
            return e

        return _error_response(422, "validation_error", "请求参数校验失败", {"errors": [_safe(e) for e in exc.errors()[:5]]})

    @app.exception_handler(StarletteHTTPException)
    async def _http_error_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return _error_response(exc.status_code, "http_error", str(exc.detail))