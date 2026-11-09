"""小红书发布器契约 + 模板方法（策略模式基类）。

三种设计模式在本包里的分工：

- **策略模式**：``BasePublisher`` 的每个子类是一种可互换的发布策略
  （``manual`` / ``rpa`` / 未来 ``openapi``）。调用方只依赖契约，不关心实现。
- **模板方法模式**：``publish_note`` 是固定编排
  （校验 → 规范化 → 资产投递 → 检查就绪 → 提交 → 收尾），
  子类只实现 ``_submit`` 等钩子，保证每条通道走同样的校验与日志口径。
- **工厂模式**：``registry.PublisherFactory`` 按配置/显式参数返回策略实例，
  新增通道只需 ``@register_publisher("openapi")`` 一行。

诚实口径（项目哲学）：``PublishResult.state`` 区分
``manual`` / ``ready`` / ``published`` / ``unknown`` / ``failed``。
**填完表单但没点发布 = ``ready``，不是 ``published``**；点了发布但没读到
小红书回执 = ``unknown``，绝不假装成功。
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

logger = logging.getLogger(__name__)

# 小红书图文笔记的公开约束（超限直接报错，不静默截断）
MAX_TITLE_CHARS = 20
MAX_BODY_CHARS = 1000
MAX_TOPICS = 10

PublishState = Literal["manual", "ready", "published", "unknown", "failed"]
Visibility = Literal["public", "self", "mutual"]


# ── 数据契约 ────────────────────────────────────────────────
@dataclass
class XhsNote:
    """小红书笔记产物（标题 / 正文 / 话题）。"""

    title: str
    body: str
    topics: list[str] = field(default_factory=list)

    @property
    def full_text(self) -> str:
        """完整文案 = 正文 + 话题标签（与前端预览一致）。"""
        topics_text = " ".join(f"#{t}" for t in self.topics) if self.topics else ""
        if topics_text:
            return f"{self.body}\n\n{topics_text}"
        return self.body


@dataclass
class NoteImageSpec:
    """封面图规格（小红书图文笔记首图 3:4，1080×1440）。"""

    width: int = 1080
    height: int = 1440
    ratio: str = "3:4"


@dataclass
class PreparedNote:
    """规范化之后的笔记（标题去掉首尾空白、话题去重去 #、超量话题丢弃）。"""

    title: str
    body: str
    topics: list[str] = field(default_factory=list)

    @property
    def tags_line(self) -> str:
        return " ".join(f"#{t}" for t in self.topics)


@dataclass
class PublishResult:
    """发布结果（所有通道统一返回）。"""

    channel: str = "xhs"
    mode: str = "manual"
    state: PublishState = "failed"
    submitted: bool = False
    note_url: str | None = None
    assets: list[str] = field(default_factory=list)
    screenshot: str | None = None
    reason: str | None = None
    message: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        """``ready``（待人工点发布）也算成功——它完成了自动化该做的部分。"""
        return self.state in ("ready", "published")


class PublishError(Exception):
    """发布失败（带稳定 reason 码，前端据此给不同引导）。

    兼容旧用法 ``PublishError("人话消息")``：此时 reason 退化为 ``failed``。
    """

    def __init__(self, reason: str, message: str | None = None) -> None:
        if message is None:
            message, reason = reason, "failed"
        self.reason = reason
        self.message = message
        super().__init__(message)


# ── 模板方法基类 ────────────────────────────────────────────
class BasePublisher(ABC):
    """社交平台发布器统一契约（模板方法：``publish_note`` 不可覆写）。

    子类需要实现：
    - ``_submit``：真正投递（唯一抽象方法）
    子类可选覆写：
    - ``_validate``（先调 ``super()._validate``）
    - ``_prepare`` / ``_deliver_assets`` / ``_check_ready`` / ``_finalize``
    """

    channel: str = "xhs"
    mode: str = "manual"
    requires_images: bool = False
    supports_auto_submit: bool = False
    external_agent: bool = False
    """True = 本通道由外部客户端（浏览器扩展/本地助手）执行，服务端只下发任务。"""
    hint: str = ""

    # ── 模板方法：固定顺序，子类不得覆写 ────────────────────
    async def publish_note(
        self,
        note: XhsNote,
        assets: Sequence[str] | None = None,
        *,
        auto_submit: bool = False,
        schedule_at: datetime | None = None,
        visibility: Visibility = "public",
        is_original: bool = False,
    ) -> PublishResult:
        asset_list = list(assets or [])
        # 1) 校验（共用口径：标题/正文长度、图片要求）
        self._validate(note, asset_list, auto_submit=auto_submit)
        # 2) 规范化（去空白、话题去重）
        prepared = self._prepare(note, asset_list)
        # 3) 资产投递（本地路径校验 / 未来官方 API 上传换 media_id）
        delivered = await self._deliver_assets(prepared, asset_list)
        # 4) 就绪检查（登录态 / 会话可用）
        await self._check_ready(prepared, delivered)
        # 5) 提交（唯一抽象方法）
        result = await self._submit(
            prepared,
            delivered,
            auto_submit=auto_submit,
            schedule_at=schedule_at,
            visibility=visibility,
            is_original=is_original,
        )
        # 6) 收尾（统一补 channel/mode/assets + 记账日志）
        return self._finalize(prepared, delivered, result)

    # ── 钩子：默认实现 ──────────────────────────────────────
    def _validate(self, note: XhsNote, assets: list[str], *, auto_submit: bool) -> None:
        title = (note.title or "").strip()
        body = (note.body or "").strip()
        if not title:
            raise PublishError("empty_title", "标题不能为空")
        if len(title) > MAX_TITLE_CHARS:
            raise PublishError(
                "title_too_long", f"标题最多 {MAX_TITLE_CHARS} 字（当前 {len(title)} 字）"
            )
        if not body:
            raise PublishError("empty_body", "正文不能为空")
        if len(body) > MAX_BODY_CHARS:
            raise PublishError(
                "body_too_long", f"正文最多 {MAX_BODY_CHARS} 字（当前 {len(body)} 字）"
            )
        if self.requires_images and not assets:
            raise PublishError("no_images", "小红书图文笔记至少需要 1 张图片")
        if auto_submit and not self.supports_auto_submit:
            raise PublishError(
                "auto_submit_unsupported", f"{self.mode} 通道不支持自动点发布，请用半自动模式"
            )

    def _prepare(self, note: XhsNote, assets: list[str]) -> PreparedNote:
        seen: set[str] = set()
        topics: list[str] = []
        for raw in note.topics or []:
            tag = str(raw).strip().lstrip("#").strip()
            if not tag or tag in seen:
                continue
            seen.add(tag)
            topics.append(tag)
        if len(topics) > MAX_TOPICS:
            logger.debug("话题超过 %s 个，丢弃多余部分", MAX_TOPICS)
            topics = topics[:MAX_TOPICS]
        return PreparedNote(
            title=(note.title or "").strip(),
            body=(note.body or "").strip(),
            topics=topics,
        )

    async def _deliver_assets(self, note: PreparedNote, assets: list[str]) -> list[str]:
        """默认原样透传（本地路径策略）；官方 API 策略会在此上传换 media_id。"""
        return list(assets)

    async def _check_ready(self, note: PreparedNote, assets: list[str]) -> None:
        """默认就绪；需要登录态的通道在此抛 ``PublishError("login_required")``。"""

    @abstractmethod
    async def _submit(
        self,
        note: PreparedNote,
        assets: list[str],
        *,
        auto_submit: bool,
        schedule_at: datetime | None,
        visibility: Visibility,
        is_original: bool,
    ) -> PublishResult:
        """真正投递（唯一必须实现的钩子）。"""

    def _finalize(
        self, note: PreparedNote, assets: list[str], result: PublishResult
    ) -> PublishResult:
        result.channel = result.channel or self.channel
        result.mode = self.mode
        if not result.assets:
            result.assets = list(assets)
        log = logger.info if result.ok else logger.warning
        log(
            "xhs 发布结束 channel=%s mode=%s state=%s submitted=%s title=%r reason=%s",
            result.channel,
            result.mode,
            result.state,
            result.submitted,
            note.title,
            result.reason,
        )
        return result

    # ── 对外自检（供 API 快速失败 + 前端展示通道能力） ──────
    def validate(
        self, note: XhsNote, assets: Sequence[str] | None = None, *, auto_submit: bool = False
    ) -> None:
        """同步校验（API 层用它把错误在 400 阶段就返回，不必等 job）。"""
        self._validate(note, list(assets or []), auto_submit=auto_submit)

    async def describe(self) -> dict[str, Any]:
        return {
            "channel": self.channel,
            "mode": self.mode,
            "connected": self.mode != "manual",
            "requires_images": self.requires_images,
            "supports_auto_submit": self.supports_auto_submit,
            "external_agent": self.external_agent,
            "hint": self.hint,
        }

    async def health(self) -> dict[str, Any]:
        return {"channel": self.channel, "ok": True, "mode": self.mode}
