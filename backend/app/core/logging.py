"""统一日志配置。"""
from __future__ import annotations

import logging
import sys
from typing import TextIO

from app.common.config import settings

_LOGGERS: list[logging.Logger] = []


def _build_handler(stream: TextIO = sys.stdout) -> logging.Handler:
    handler = logging.StreamHandler(stream)
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