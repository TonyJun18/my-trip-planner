"""统一日志配置。

- 开发环境（默认）：人类可读文本格式
- 生产/JSON 日志：``LOG_FORMAT=json`` 时输出单行 JSON（含 trace_id 等结构化字段），
  可直接被日志采集器（ELK / Loki / CloudWatch）消费
- trace_id：由 ``app.core.tracing`` 的中间件生成并放入 contextvar，
  本模块的 ``get_logger().info(..., extra=...)`` 自动带上当前 trace_id
"""
from __future__ import annotations

import json
import logging
import sys
from typing import Any, TextIO

from app.common.config import settings

_LOGGERS: list[logging.Logger] = []


def _trace_id() -> str | None:
    """从 contextvar 读取当前请求 trace_id（无则 None）。"""
    try:
        from app.core.tracing import current_trace_id

        return current_trace_id()
    except Exception:  # noqa: BLE001 — 日志绝不能被 tracing 初始化问题拖垮
        return None


class JSONFormatter(logging.Formatter):
    """单行 JSON 日志格式（采集器友好）。"""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # 附带 extra 结构化字段（如 request_id / user_id / agent）
        for key in ("trace_id", "request_id", "user_id", "agent", "task_id", "cost_usd"):
            val = getattr(record, key, None)
            if val is not None:
                payload[key] = val
        tid = _trace_id()
        if tid and "trace_id" not in payload:
            payload["trace_id"] = tid
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def _build_handler(stream: TextIO = sys.stdout) -> logging.Handler:
    handler = logging.StreamHandler(stream)
    if (settings.LOG_FORMAT or "").lower() == "json":
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
    return handler


def setup_logging(level: str | None = None) -> None:
    """配置根 logger（幂等，可多次调用）。"""
    root = logging.getLogger()
    root.setLevel((level or settings.LOG_LEVEL).upper())
    if not any(isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler) for h in root.handlers):
        root.addHandler(_build_handler())
    # 降噪第三方库
    for noisy in ("uvicorn.access", "httpx", "httpcore", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """获取带模块名的 logger。"""
    logger = logging.getLogger(name)
    if name not in _LOGGERS:
        _LOGGERS.append(logger)
    return logger