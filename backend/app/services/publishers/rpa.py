"""自动化发布策略（方案 C）：驱动小红书创作服务平台完成填表。

流程（模板方法固定顺序，本类只填钩子）：

    validate → prepare → deliver_assets(路径校验) → check_ready(登录态)
             → submit(填表；可选点发布) → finalize

两条关键设计取舍（都是踩过坑之后的决定）：

1. **默认半自动**：填好标题/正文/图片后**停住**，由人点「发布」。
   风控、责任、以及"内容最终由人负责"三点都更干净，成本几乎一样。
   ``auto_submit=True`` 才尝试点发布，且拿不到回执只报 ``unknown``。
2. **驱动可注入**：``driver_factory`` 是构造参数，测试用 ``FakeDriver``
   就能把整条编排真实跑一遍，不需要浏览器、不产生副作用。
"""
from __future__ import annotations

import logging
import os
from collections.abc import Callable
from datetime import datetime

from app.services.publishers.base import (
    BasePublisher,
    PreparedNote,
    PublishError,
    PublishResult,
    Visibility,
)
from app.services.publishers.drivers.protocol import DriverOutcome, PublishDriver, PublishForm

logger = logging.getLogger(__name__)


def _default_driver_factory() -> PublishDriver:
    """延迟导入：没装 playwright 时只有真正用 rpa 通道才会报错。"""
    from app.services.publishers.drivers.playwright_creator import PlaywrightCreatorDriver

    return PlaywrightCreatorDriver()


class RpaPublisher(BasePublisher):
    """驱动创作服务平台的发布策略（半自动为主）。"""

    mode = "rpa"
    requires_images = True
    supports_auto_submit = True
    hint = "自动打开小红书创作服务平台并填好标题/正文/图片，你在窗口里确认后点发布"

    def __init__(self, driver_factory: Callable[[], PublishDriver] | None = None) -> None:
        self._driver_factory = driver_factory or _default_driver_factory
        self._driver: PublishDriver | None = None

    # ── 钩子实现 ────────────────────────────────────────────
    async def _deliver_assets(self, note: PreparedNote, assets: list[str]) -> list[str]:
        """RPA 直接吃本地文件：必须存在、可读、路径不含非 ASCII 字符。

        非 ASCII 路径在浏览器 `set_input_files` 与部分系统编码下会静默失败，
        社区实现也把「图片路径不能含中文」写进了排查清单，所以这里前置拦住。
        """
        resolved: list[str] = []
        for raw in assets:
            path = os.path.abspath(os.path.expanduser(raw))
            if not os.path.isfile(path):
                raise PublishError("asset_missing", f"图片文件不存在：{path}")
            if not path.isascii():
                raise PublishError(
                    "asset_path_not_ascii",
                    f"图片路径含非 ASCII 字符：{path}（请先重命名为英文/数字）",
                )
            resolved.append(path)
        return resolved

    async def _check_ready(self, note: PreparedNote, assets: list[str]) -> None:
        """打开发布页并确认已登录；未登录直接失败（绝不代输密码/验证码）。"""
        driver = self._ensure_driver()
        try:
            await driver.open()
            if not await driver.is_logged_in():
                raise PublishError(
                    "login_required",
                    "小红书创作服务平台未登录：请先执行一次扫码登录（登录态会持久化复用）",
                )
        except PublishError:
            await self._safe_close(keep_open=False)
            raise
        except Exception as exc:  # 驱动环境问题统一成可读原因
            await self._safe_close(keep_open=False)
            raise PublishError("driver_not_ready", f"发布驱动不可用：{exc}") from exc

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
        driver = self._ensure_driver()
        form = PublishForm(
            title=note.title,
            body=note.body,
            topics=list(note.topics),
            image_paths=list(assets),
            visibility=visibility,
            is_original=is_original,
            schedule_at=schedule_at,
        )
        keep_open = not auto_submit and self._keep_open_enabled()
        try:
            await driver.fill_form(form)
            screenshot = await driver.screenshot()
            if not auto_submit:
                return PublishResult(
                    state="ready",
                    submitted=False,
                    screenshot=screenshot,
                    message="表单已填好：请在弹出的浏览器窗口中确认内容，然后点「发布」",
                    meta={
                        "driver": getattr(driver, "name", "unknown"),
                        "hint_key": "xhsNote.publishReadyHint",
                        "kept_open": keep_open,
                    },
                )
            outcome = await driver.submit()
            return self._result_from_outcome(outcome, screenshot)
        except PublishError:
            raise
        except Exception as exc:  # 页面结构变更等，保留取证截图
            shot = await self._safe_screenshot()
            logger.warning("xhs rpa 发布失败，截图=%s err=%s", shot, exc)
            raise PublishError("submit_failed", f"发布流程失败：{exc}") from exc
        finally:
            await self._safe_close(keep_open=keep_open)

    # ── 内部工具 ────────────────────────────────────────────
    def _ensure_driver(self) -> PublishDriver:
        if self._driver is None:
            self._driver = self._driver_factory()
        return self._driver

    def _keep_open_enabled(self) -> bool:
        try:
            from app.common.config import settings

            return bool(getattr(settings, "XHS_RPA_KEEP_OPEN", True))
        except Exception:  # noqa: BLE001 — 配置不可读时按"保留窗口"处理（更安全）
            return True

    def _result_from_outcome(
        self, outcome: DriverOutcome, fallback_screenshot: str | None
    ) -> PublishResult:
        return PublishResult(
            state=outcome.state,
            submitted=outcome.submitted,
            note_url=outcome.note_url,
            screenshot=outcome.screenshot or fallback_screenshot,
            message=outcome.message,
            meta={"driver": "playwright", "hint_key": "xhsNote.publishDoneHint"},
        )

    async def _safe_screenshot(self) -> str | None:
        try:
            return await self._driver.screenshot() if self._driver else None
        except Exception:  # noqa: BLE001 — 取证失败不掩盖原始错误
            return None

    async def _safe_close(self, *, keep_open: bool) -> None:
        driver, self._driver = self._driver, None
        if driver is None:
            return
        try:
            await driver.close(keep_open=keep_open)
        except Exception:  # noqa: BLE001 — 关闭失败只记日志
            logger.debug("发布驱动关闭失败（忽略）")
