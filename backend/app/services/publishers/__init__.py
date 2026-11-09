"""小红书发布通道（可插拔策略包）。

对外只暴露契约与工厂：
``from app.services.publishers import BasePublisher, PublishError, XhsNote, get_publisher``
"""
from __future__ import annotations

from app.services.publishers.base import (
    BasePublisher,
    NoteImageSpec,
    PreparedNote,
    PublishError,
    PublishResult,
    XhsNote,
)
from app.services.publishers.manual import ManualPublisher
from app.services.publishers.registry import (
    PublisherFactory,
    factory,
    get_publisher,
    register_publisher,
)
from app.services.publishers.rpa import RpaPublisher

__all__ = [
    "BasePublisher",
    "ManualPublisher",
    "NoteImageSpec",
    "PreparedNote",
    "PublishError",
    "PublishResult",
    "PublisherFactory",
    "RpaPublisher",
    "XhsNote",
    "factory",
    "get_publisher",
    "register_publisher",
]
