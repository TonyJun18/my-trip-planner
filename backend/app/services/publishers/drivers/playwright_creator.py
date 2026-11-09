"""Playwright 驱动：小红书创作服务平台（方案 C 的真实通道）。

策略：**半自动优先**。填好标题/正文/图片后停住，由人点「发布」。

## 两种登录态来源（按优先级）

1. ``XHS_RPA_CDP_URL``（推荐）：接管一个已登录的 Chrome（调试端口）。
   配合 ``chrome-cdp-automation`` 技能克隆 profile 启动 Chrome，
   直接复用用户已有登录态，**不需要再扫码**。
2. ``XHS_RPA_STATE_PATH``：Playwright ``storage_state`` 文件
   （先用 ``backend/scripts/xhs_login.py`` 扫码登录一次生成）。

## 已知限制（诚实标注，别当 bug 查）

- **同一小红书账号不允许同时存在多个网页端会话**：发布时会把用户
  自己在浏览器里登的创作平台挤掉（社区实现 README 明确写过）。
- **选择器未经真机校准**：``SELECTOR_SET_VERSION`` 标了日期与
  ``unverified``。小红书前端改版频繁，首次真机使用请按
  ``docs/plans/2026-11-09-xhs-direct-publish-research.md`` 的验证实验
  校准，改 ``SELECTORS`` 即可（多候选 + 文本兜底，尽量不硬编码单一路径）。
- 自动化发布非官方授权能力，有风控风险：默认半自动、低频、真实内容。

## 页面结构（已知入口）

- 图文发布：``https://creator.xiaohongshu.com/publish/publish?source=official``
- 长文发布：``https://creator.xiaohongshu.com/publish/publish?target=article``
- 笔记管理：``https://creator.xiaohongshu.com/new/note-manager``
"""
from __future__ import annotations

import logging
import os
import time
from datetime import UTC, datetime
from pathlib import Path

from app.services.publishers.base import PublishError
from app.services.publishers.drivers.protocol import DriverOutcome, PublishForm

logger = logging.getLogger(__name__)

CREATOR_PUBLISH_URL = "https://creator.xiaohongshu.com/publish/publish?source=official"
CREATOR_HOME_URL = "https://creator.xiaohongshu.com/"

# 选择器版本：改页面适配时同步改这里，便于线上排查"哪一版开始坏的"
# 2026-11-09 实测：未登录访问发布页会被 302 到
#   /login?source=official&redirectReason=401
# 登录页为「短信登录」（手机号 + 验证码 + 登录按钮），卡片右上角可切二维码。
# 发布页（已登录后）的选择器仍需真机校准。
SELECTOR_SET_VERSION = "2026-11-09.login-calibrated:publish-unverified"

# 多候选 + 文本兜底：小红书前端是组件化渲染，class 名常带 hash，单一 CSS 很脆
SELECTORS: dict[str, list[str]] = {
    "image_tab": ["text=上传图文", "div[class*='tab'] >> text=图文", "span:has-text('图文')"],
    "file_input": [
        "input[type='file'][accept*='image']",
        "input[type='file'][accept*='png']",
        "input.upload-input",
        "input[type='file']",
    ],
    "title": [
        "input[placeholder*='标题']",
        "div[class*='title'] input",
        "input[class*='d-text']",
    ],
    "editor": [
        "div.ql-editor",
        "div.tiptap.ProseMirror",
        "div[contenteditable='true']",
    ],
    "submit": [
        "button:has-text('发布')",
        "div[class*='publish'] button:has-text('发布')",
        "button[class*='publish']",
    ],
    "login_marker": [
        "text=短信登录",
        "text=扫码登录",
        "text=登录即同意",
        "input[placeholder*='手机号']",
        "input[placeholder*='验证码']",
    ],
    "success_marker": ["text=发布成功", "text=笔记已发布"],
}

# 半自动模式保留下来的浏览器窗口引用：不能让它被 GC 掉，否则用户眼前
# 那个"已经填好的窗口"会突然关闭。
_KEPT_OPEN: list[object] = []


def _screenshots_dir() -> Path:
    raw = os.getenv("XHS_RPA_SCREENSHOT_DIR") or ""
    base = Path(raw) if raw else Path(__file__).resolve().parents[4] / "var" / "xhs-screenshots"
    base.mkdir(parents=True, exist_ok=True)
    return base


class PlaywrightCreatorDriver:
    """小红书创作服务平台驱动。"""

    name = "playwright-creator"

    def __init__(
        self,
        *,
        cdp_url: str | None = None,
        state_path: str | None = None,
        headless: bool | None = None,
        timeout_s: float | None = None,
        executable_path: str | None = None,
    ) -> None:
        from app.common.config import settings

        self.cdp_url = cdp_url if cdp_url is not None else getattr(settings, "XHS_RPA_CDP_URL", None)
        self.state_path = (
            state_path if state_path is not None else getattr(settings, "XHS_RPA_STATE_PATH", None)
        )
        self.executable_path = (
            executable_path
            if executable_path is not None
            else getattr(settings, "XHS_RPA_CHROME_PATH", None)
        )
        self.headless = bool(
            getattr(settings, "XHS_RPA_HEADLESS", False) if headless is None else headless
        )
        self.timeout_s = float(
            getattr(settings, "XHS_RPA_TIMEOUT", 60.0) if timeout_s is None else timeout_s
        )
        self._pw = None
        self._browser = None
        self._context = None
        self._page = None
        self._owns_browser = False
        self._last_screenshot: str | None = None

    # ── 会话 ────────────────────────────────────────────────
    async def open(self) -> None:
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:  # pragma: no cover - 依赖缺失环境
            raise PublishError(
                "driver_not_ready",
                "未安装 playwright：`pip install playwright && playwright install chromium`",
            ) from exc

        self._pw = await async_playwright().start()
        chromium = self._pw.chromium

        if self.cdp_url:
            # 接管已登录的真实 Chrome（复用登录态，不新开 profile）
            self._browser = await chromium.connect_over_cdp(self.cdp_url)
            contexts = self._browser.contexts
            self._context = contexts[0] if contexts else await self._browser.new_context()
            pages = [p for p in self._context.pages if "creator.xiaohongshu.com" in p.url]
            self._page = pages[0] if pages else await self._context.new_page()
            self._owns_browser = False
            logger.info("xhs driver: 已接管 CDP 浏览器 %s", self.cdp_url)
        else:
            launch_kwargs: dict[str, object] = {"headless": self.headless}
            if self.executable_path:
                launch_kwargs["executable_path"] = self.executable_path
                logger.info("xhs driver: 使用自定义浏览器 %s", self.executable_path)
            self._browser = await chromium.launch(**launch_kwargs)
            ctx_kwargs: dict[str, object] = {}
            if self.state_path and Path(self.state_path).is_file():
                ctx_kwargs["storage_state"] = self.state_path
                logger.info("xhs driver: 复用登录态 %s", self.state_path)
            else:
                logger.warning("xhs driver: 未找到登录态文件，发布页大概率要求扫码登录")
            self._context = await self._browser.new_context(**ctx_kwargs)
            self._page = await self._context.new_page()
            self._owns_browser = True

        if self._page is None:  # pragma: no cover - 防御
            raise PublishError("driver_not_ready", "无法创建浏览器页面")
        await self._page.goto(CREATOR_PUBLISH_URL, wait_until="domcontentloaded")
        # SPA 首屏是异步渲染的：只等 domcontentloaded 会截到白屏（实测踩过）
        await self._wait_network_idle(8.0)

    async def is_logged_in(self) -> bool:
        page = self._require_page()
        if "login" in (page.url or "").lower():
            logger.info("xhs driver: 跳转到登录页 → 未登录")
            return False
        for sel in SELECTORS["login_marker"]:
            if await self._count(sel) > 0:
                logger.info("xhs driver: 检测到登录控件 %s → 未登录", sel)
                return False
        for key in ("title", "submit"):
            for sel in SELECTORS[key]:
                if await self._count(sel) > 0:
                    return True
        # 都没有：页面可能还在渲染或已改版，按"未登录"处理（宁可让人重登）
        logger.warning("xhs driver: 未找到登录/发布特征元素（选择器版本 %s）", SELECTOR_SET_VERSION)
        return False

    # ── 填表 ────────────────────────────────────────────────
    async def fill_form(self, form: PublishForm) -> None:
        page = self._require_page()

        # 1) 切到「上传图文」tab（视频 tab 是默认时必需）
        await self._click_any(SELECTORS["image_tab"], required=False)

        # 2) 图片：直接喂给隐藏的 file input（比点按钮开系统对话框稳）
        if form.image_paths:
            target = await self._first(SELECTORS["file_input"])
            if target is None:
                raise PublishError(
                    "selector_miss",
                    f"找不到图片上传控件（选择器版本 {SELECTOR_SET_VERSION}），页面可能已改版",
                )
            await target.set_input_files(form.image_paths)
            await self._settle(1.2)

        # 3) 标题
        title_input = await self._first(SELECTORS["title"])
        if title_input is None:
            raise PublishError(
                "selector_miss",
                f"找不到标题输入框（选择器版本 {SELECTOR_SET_VERSION}），页面可能已改版",
            )
        await title_input.click()
        await title_input.fill(form.title)

        # 4) 正文（contenteditable 用 insert_text，避免 CJK 逐字输入丢字）
        editor = await self._first(SELECTORS["editor"])
        if editor is None:
            raise PublishError(
                "selector_miss",
                f"找不到正文编辑器（选择器版本 {SELECTOR_SET_VERSION}），页面可能已改版",
            )
        await editor.click()
        await page.keyboard.insert_text(form.body)
        if form.topics:
            await page.keyboard.press("Enter")
            await page.keyboard.insert_text(" ".join(f"#{t}" for t in form.topics))
        await self._settle(0.8)
        logger.info(
            "xhs driver: 表单已填好 title=%r images=%s topics=%s",
            form.title,
            len(form.image_paths),
            len(form.topics),
        )

    async def submit(self) -> DriverOutcome:
        self._require_page()
        button = await self._first(SELECTORS["submit"])
        if button is None:
            shot = await self.screenshot()
            return DriverOutcome(
                state="unknown",
                submitted=False,
                screenshot=shot,
                message=f"找不到「发布」按钮（选择器版本 {SELECTOR_SET_VERSION}）",
            )
        await button.click()
        await self._settle(2.0)

        # 只有读到明确成功标记/笔记链接才敢说 published
        for sel in SELECTORS["success_marker"]:
            if await self._count(sel) > 0:
                return DriverOutcome(
                    state="published",
                    submitted=True,
                    note_url=self._extract_note_url(),
                    screenshot=await self.screenshot(),
                )
        note_url = self._extract_note_url()
        if note_url:
            return DriverOutcome(
                state="published", submitted=True, note_url=note_url, screenshot=await self.screenshot()
            )
        return DriverOutcome(
            state="unknown",
            submitted=True,
            screenshot=await self.screenshot(),
            message="已点击「发布」，但未读到小红书回执——请到创作服务平台确认结果",
        )

    async def screenshot(self) -> str | None:
        if self._page is None:
            return self._last_screenshot
        try:
            # 截图前等渲染稳定，否则 SPA 会截到白屏（实测踩过）
            await self._wait_network_idle(4.0)
            name = f"xhs-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}.png"
            path = Path(_screenshots_dir()) / name
            await self._page.screenshot(path=str(path), full_page=False)
            self._last_screenshot = str(path)
            return str(path)
        except Exception:  # noqa: BLE001 — 取证失败不影响主流程
            logger.debug("xhs driver: 截图失败（忽略）")
            return self._last_screenshot

    async def close(self, *, keep_open: bool = False) -> None:
        """释放会话。``keep_open=True``（半自动）时保留窗口给用户点发布。"""
        if keep_open and self._owns_browser and self._context is not None:
            # 把引用挂到模块级，防止 playwright 对象被回收导致窗口自动关闭
            _KEPT_OPEN.append((self._pw, self._browser, self._context, self._page))
            logger.info("xhs driver: 半自动模式，浏览器窗口保留（等人点发布）")
            self._pw = self._browser = self._context = self._page = None
            return
        try:
            if self._owns_browser and self._browser is not None:
                await self._browser.close()
        finally:
            if self._pw is not None:
                try:
                    await self._pw.stop()
                except Exception:  # noqa: BLE001 — 停止失败不影响结果
                    logger.debug("xhs driver: playwright stop 失败（忽略）")
            self._pw = self._browser = self._context = self._page = None

    async def save_state(self, path: str | None = None) -> str | None:
        """导出当前登录态，供下次直接复用（扫码登录脚本用）。"""
        target = path or self.state_path
        if not target or self._context is None:
            return None
        await self._context.storage_state(path=target)
        return target

    # ── 内部工具 ────────────────────────────────────────────
    def _require_page(self):
        if self._page is None:
            raise PublishError("driver_not_ready", "浏览器会话未打开，请先调用 open()")
        return self._page

    async def _count(self, selector: str) -> int:
        page = self._page
        if page is None:
            return 0
        try:
            return await page.locator(selector).count()
        except Exception:  # noqa: BLE001 — 非法选择器按 0 处理
            return 0

    async def _first(self, candidates: list[str], *, timeout_s: float = 0.0):
        """按候选顺序找第一个可见元素；`timeout_s>0` 时先等一等。"""
        page = self._page
        if page is None:
            return None
        deadline = time.monotonic() + max(0.0, timeout_s)
        while True:
            for sel in candidates:
                try:
                    locator = page.locator(sel).first
                    if await locator.count() > 0 and await locator.is_visible():
                        return locator
                except Exception:  # noqa: BLE001 — 非法/失配选择器：换下一个候选
                    logger.debug("xhs driver: 候选选择器失败 %s", sel)
            if time.monotonic() >= deadline:
                return None
            await self._settle(0.3)

    async def _click_any(self, candidates: list[str], *, required: bool = False) -> bool:
        locator = await self._first(candidates, timeout_s=2.0 if required else 0.0)
        if locator is None:
            if required:
                raise PublishError(
                    "selector_miss",
                    f"找不到必要元素（选择器版本 {SELECTOR_SET_VERSION}），页面可能已改版",
                )
            return False
        await locator.click()
        await self._settle(0.6)
        return True

    async def _wait_network_idle(self, timeout_s: float) -> None:
        """等页面网络空闲（SPA 首屏）。超时不报错——有的页面常驻轮询。"""
        page = self._page
        if page is None:
            return
        try:
            await page.wait_for_load_state("networkidle", timeout=int(timeout_s * 1000))
        except Exception:  # noqa: BLE001 — 轮询型页面永远不会 idle，忽略即可
            logger.debug("xhs driver: networkidle 等待超时（忽略）")

    async def _settle(self, seconds: float = 0.5) -> None:
        """短等待（页面有异步渲染/上传进度）。"""
        page = self._page
        if page is None:
            return
        try:
            await page.wait_for_timeout(int(seconds * 1000))
        except Exception:  # noqa: BLE001 — 页面已关闭时等待会抛错
            logger.debug("xhs driver: settle 等待失败（忽略）")

    def _extract_note_url(self) -> str | None:
        """从当前页/管理页里找一个笔记链接（拿不到就返回 None，不编造）。"""
        page = self._page
        if page is None:
            return None
        try:
            url = page.url or ""
        except Exception:  # noqa: BLE001
            return None
        for marker in ("/explore/", "/discovery/item/"):
            if marker in url:
                return url
        return None
