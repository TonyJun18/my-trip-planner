"""发布驱动契约（浏览器/官方 API 等底层通道的统一抽象）。

``BasePublisher`` 负责「业务编排」，``PublishDriver`` 负责「怎么落到某个界面」。
两者用接口隔离：换驱动（Playwright / CDP 接管 / 未来官方 API）不影响策略，
换策略（manual / rpa / openapi）也不影响驱动——这就是"后续快速切换实现"的关键。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Protocol, runtime_checkable

DriverState = Literal["ready", "published", "unknown"]


@dataclass
class PublishForm:
    """要填进发布页的完整表单。"""

    title: str
    body: str
    topics: list[str] = field(default_factory=list)
    image_paths: list[str] = field(default_factory=list)
    visibility: str = "public"  # public | self | mutual
    is_original: bool = False
    schedule_at: datetime | None = None


@dataclass
class DriverOutcome:
    """驱动执行结果。``state`` 必须诚实：

    - ``ready``：表单已填好、**未**点发布
    - ``published``：点了发布且读到成功回执
    - ``unknown``：点了发布但拿不到回执（不假装成功）
    """

    state: DriverState = "unknown"
    submitted: bool = False
    note_url: str | None = None
    screenshot: str | None = None
    message: str | None = None


@runtime_checkable
class PublishDriver(Protocol):
    """发布驱动协议。实现方需保证 ``close`` 幂等。"""

    name: str

    async def open(self) -> None:
        """建立会话（浏览器 / HTTP 客户端）并打开发布页。"""
        ...

    async def is_logged_in(self) -> bool:
        """登录态探测（不弹窗、不代输密码）。"""
        ...

    async def fill_form(self, form: PublishForm) -> None:
        """填标题/正文/话题/图片；不点发布。"""
        ...

    async def submit(self) -> DriverOutcome:
        """点发布并尽力读取回执。"""
        ...

    async def screenshot(self) -> str | None:
        """落一张现场截图（失败取证），返回路径。"""
        ...

    async def close(self, *, keep_open: bool = False) -> None:
        """释放会话；``keep_open=True`` 用于半自动模式下让用户接着点发布。"""
        ...
