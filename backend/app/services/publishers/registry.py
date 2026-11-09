"""发布器工厂 + 策略注册表。

为什么用注册表而不是 if/elif：
- 新增通道（官方 ``openapi`` / 第三方 ``saas``）**不改这个文件**，
  只在新模块里 ``@register_publisher("openapi")`` 即可被工厂发现；
- 切换通道靠配置 ``XHS_PUBLISH_MODE``（或调用方显式传 mode），
  上线后换实现不需要动业务代码——这就是"快速切换实现"的落点。

降级策略：配置了未知 mode 时**不抛错**，回落到 ``manual`` 并告警。
发布是用户已经点过按钮的动作，不能因为一行配置写错就炸掉整个对话框。
"""
from __future__ import annotations

import logging
from collections.abc import Callable

from app.services.publishers.base import BasePublisher, PublishError
from app.services.publishers.manual import ManualPublisher
from app.services.publishers.rpa import RpaPublisher

logger = logging.getLogger(__name__)

PublisherCtor = Callable[[], BasePublisher] | type[BasePublisher]

_REGISTRY: dict[str, PublisherCtor] = {}


def register_publisher(mode: str) -> Callable[[PublisherCtor], PublisherCtor]:
    """注册一个发布策略（装饰器）。"""

    def _decorator(cls: PublisherCtor) -> PublisherCtor:
        _REGISTRY[mode] = cls
        return cls

    return _decorator


register_publisher("manual")(ManualPublisher)
register_publisher("rpa")(RpaPublisher)


class PublisherFactory:
    """按 mode 返回发布策略实例。"""

    def __init__(self) -> None:
        self._registry: dict[str, PublisherCtor] = dict(_REGISTRY)
        self._driver_factory: Callable[[], object] | None = None

    # ── 注册 / 注入 ─────────────────────────────────────────
    def register(self, mode: str, ctor: PublisherCtor) -> None:
        self._registry[mode] = ctor

    def set_driver_factory(self, factory: Callable[[], object] | None) -> None:
        """注入驱动工厂（测试用 FakeDriver / 生产用 Playwright 驱动）。"""
        self._driver_factory = factory

    def modes(self) -> list[str]:
        return sorted(self._registry)

    # ── 解析 ────────────────────────────────────────────────
    def default_mode(self) -> str:
        from app.common.config import settings

        return (getattr(settings, "XHS_PUBLISH_MODE", "manual") or "manual").strip().lower()

    def resolve_mode(self, mode: str | None = None) -> str:
        """显式 mode > 配置 > manual；未知值回落 manual（告警不阻断）。"""
        candidate = (mode or self.default_mode()).strip().lower()
        if candidate in self._registry:
            return candidate
        logger.warning("未知的小红书发布 mode=%r，回落 manual（可用：%s）", candidate, self.modes())
        return "manual"

    # ── 创建 ────────────────────────────────────────────────
    def create(self, mode: str | None = None, *, channel: str = "xhs") -> BasePublisher:
        if channel != "xhs":
            raise PublishError("unsupported_channel", f"不支持的渠道: {channel}")
        resolved = self.resolve_mode(mode)
        ctor = self._registry[resolved]
        if isinstance(ctor, type):
            publisher = ctor() if resolved != "rpa" else ctor(self._driver_factory)  # type: ignore[call-arg]
        else:  # pragma: no cover - 预留 lambda 工厂
            publisher = ctor()
        if self._driver_factory is not None and resolved == "rpa":
            publisher._driver_factory = self._driver_factory  # type: ignore[attr-defined]
        return publisher


factory = PublisherFactory()


def get_publisher(channel: str = "xhs", mode: str | None = None) -> BasePublisher:
    """兼容旧调用的模块级入口（等价于 ``factory.create()``）。"""
    return factory.create(mode, channel=channel)


def reset_factory_for_tests() -> None:
    """测试隔离：清掉注入的驱动工厂（注册表保持）。"""
    factory.set_driver_factory(None)
