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

import json
import logging
import time
from datetime import UTC, datetime
from pathlib import Path

from app.services.publishers.base import PublishError
from app.services.publishers.drivers.protocol import DriverOutcome, PublishForm

logger = logging.getLogger(__name__)

CREATOR_PUBLISH_URL = "https://creator.xiaohongshu.com/publish/publish?source=official"
CREATOR_HOME_URL = "https://creator.xiaohongshu.com/"

# 选择器版本：改页面适配时同步改这里，便于线上排查"哪一版开始坏的"
# 2026-11-09 真机校准（已登录态实测，headless Chromium）：
#   - 未登录访问发布页 → 302 `/login?source=official&redirectReason=401`
#   - 登录页：短信登录（手机号+验证码）/ 卡片右上角可切二维码
#   - 发布页默认在「上传视频」tab；图文 tab 容器 = `div.creator-tab`（同名 span 是视口外副本）
#   - 切 tab 后图片 input：`input[type=file][accept*='png']`（accept=.jpg,.jpeg,.png,.webp）
#   - 标题：`input[placeholder*='标题']`（实际 placeholder：填写标题会有更多赞哦）
#   - 正文：`div.tiptap.ProseMirror`（quill 已不再使用）
#   - 底部动作栏：`<xhs-publish-btn>` 自定义元素（**closed shadow root**），
#     CSS/文本选择器都穿不进去 → 用属性 `submit-disabled` 判可用性，
#     用栏内 ~61% 宽的坐标做真实鼠标点击。**点发布这一步未真机验证**
#     （不会为了验证而真发一篇到你的账号）。
SELECTOR_SET_VERSION = "2026-11-09.calibrated(publish-click-unverified)"

# 多候选 + 文本兜底：小红书前端是组件化渲染，class 名常带 hash，单一 CSS 很脆
SELECTORS: dict[str, list[str]] = {
    # 2026-11-09 真机：默认落在「上传视频」tab；tab 容器是 div.creator-tab，
    # 里面还有同名 <span class="title"> 副本（在视口外，点了会超时）→ 必须点容器。
    "image_tab": [
        "div.creator-tab:has-text('上传图文')",
        ".creator-tab >> text=上传图文",
        "text=上传图文",
    ],
    "file_input": [
        "input[type='file'][accept*='png']",
        "input[type='file'][accept*='jpg']",
        "input[type='file'][accept*='image']",
        "input.upload-input",
        "input[type='file']",
    ],
    "title": [
        "input[placeholder*='标题']",
        "div[class*='title'] input",
        "input[class*='d-text']",
        "input[type='text']",
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
    # 2026-11-09 真机：底部动作栏是 <xhs-publish-btn> 自定义元素（closed shadow root），
    # 里面才是「暂存离开 / 发布」两个按钮，CSS/文本选择器都穿不进去。
    # 但它把状态暴露成属性：submit-text="发布" / submit-disabled / save-text="暂存离开"，
    # 用属性定位 + 真实鼠标坐标点击（真实点击能命中最深层节点）。
    "submit_bar": [
        "xhs-publish-btn[is-publish='true']",
        "xhs-publish-btn[is-publish]",
        "xhs-publish-btn",
    ],
    "success_marker": ["text=发布成功", "text=笔记已发布", "text=发布成功！"],
    "login_marker": [
        "text=短信登录",
        "text=扫码登录",
        "text=登录即同意",
        "input[placeholder*='手机号']",
        "input[placeholder*='验证码']",
    ],
    # 登录后的页面特征（首页没有标题框/发布按钮，靠这些兜底）
    "logged_in_hint": [
        "text=发布笔记",
        "text=创作中心",
        "text=数据中心",
        "img[class*='avatar']",
        "div[class*='avatar'] img",
    ],
}

# 实测：动作栏里「发布」药丸中心位于栏宽的 ~61% 处（栏 680px 宽时 x≈700/1280 视口）。
# 这是坐标兜底值——只在拿不到 box 时才用得上，属"最后已知经验"而非稳定契约。
PUBLISH_BUTTON_X_RATIO = 0.61

# 半自动模式保留下来的浏览器窗口引用：不能让它被 GC 掉，否则用户眼前
# 那个"已经填好的窗口"会突然关闭。
_KEPT_OPEN: list[object] = []


def _screenshots_dir() -> Path:
    """截图目录（统一由 ``publishers.paths`` 解析，支持容器挂卷）。"""
    from app.services.publishers import paths

    return paths.screenshots_dir()


class PlaywrightCreatorDriver:
    """小红书创作服务平台驱动。"""

    name = "playwright-creator"

    def __init__(
        self,
        *,
        cdp_url: str | None = None,
        state_path: str | None = None,
        storage_state: dict | None = None,
        headless: bool | None = None,
        timeout_s: float | None = None,
        executable_path: str | None = None,
    ) -> None:
        from app.common.config import settings

        self.cdp_url = cdp_url if cdp_url is not None else getattr(settings, "XHS_RPA_CDP_URL", None)
        self.state_path = (
            state_path if state_path is not None else getattr(settings, "XHS_RPA_STATE_PATH", None)
        )
        # 多用户场景：登录态由调用方（按用户从加密存储解出）直接传入 dict，
        # 不落公共文件——服务端部署时每个用户一份，互不可见。
        self.storage_state = storage_state
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
            if self.storage_state:
                ctx_kwargs["storage_state"] = self.storage_state
                logger.info("xhs driver: 使用调用方传入的登录态（多用户模式）")
            elif self.state_path and Path(self.state_path).is_file():
                ctx_kwargs["storage_state"] = self.state_path
                logger.info("xhs driver: 复用登录态文件")
            else:
                logger.warning("xhs driver: 未提供登录态，发布页大概率要求扫码登录")
            self._context = await self._browser.new_context(**ctx_kwargs)
            self._page = await self._context.new_page()
            self._owns_browser = True

        if self._page is None:  # pragma: no cover - 防御
            raise PublishError("driver_not_ready", "无法创建浏览器页面")
        await self._page.goto(CREATOR_PUBLISH_URL, wait_until="domcontentloaded")
        # SPA 首屏是异步渲染的：只等 domcontentloaded 会截到白屏（实测踩过）
        await self._wait_network_idle(8.0)

    async def is_logged_in(self) -> bool:
        """登录态探测（不弹窗、不代输密码）。

        判定顺序（2026-11-09 真机踩坑后修正）：
        1. URL 带 ``login`` → 未登录；
        2. 页面出现登录控件（短信登录 / 手机号输入框）→ 未登录；
        3. **存在 ``web_session`` cookie → 已登录**（最可靠：登录后首页既没有
           标题框也没有发布按钮，只看元素会误判成未登录）；
        4. 兜底看发布页元素或首页头像/发布入口。
        """
        page = self._require_page()
        if "login" in (page.url or "").lower():
            logger.info("xhs driver: 跳转到登录页 → 未登录")
            return False
        for sel in SELECTORS["login_marker"]:
            if await self._count(sel) > 0:
                logger.info("xhs driver: 检测到登录控件 %s → 未登录", sel)
                return False
        if await self._has_session_cookie():
            return True
        for key in ("title", "submit", "logged_in_hint"):
            for sel in SELECTORS[key]:
                if await self._count(sel) > 0:
                    return True
        logger.debug("xhs driver: 未找到登录/发布特征元素（选择器版本 %s）", SELECTOR_SET_VERSION)
        return False

    async def _has_session_cookie(self) -> bool:
        """创作者侧的会话 cookie。登录成功后一定存在，登出即失效。"""
        context = self._context
        if context is None:
            return False
        try:
            cookies = await context.cookies("https://creator.xiaohongshu.com")
        except Exception:  # noqa: BLE001 — 读 cookie 失败按未登录处理
            logger.debug("xhs driver: 读取 cookie 失败")
            return False
        return any(c.get("name") == "web_session" and c.get("value") for c in cookies)

    # ── 填表 ────────────────────────────────────────────────
    async def fill_form(self, form: PublishForm) -> None:
        page = self._require_page()

        # 0) 收掉引导气泡（"图片可以编辑啦/我知道了"）——它盖住编辑区，
        #    真机上会让后续点击落到浮层上（2026-11-09 实测）。
        await self._dismiss_overlays()

        # 1) 切到「上传图文」tab（视频 tab 是默认时必需）
        await self._click_any(SELECTORS["image_tab"], required=False)

        # 2) 图片：直接喂给隐藏的 file input（比点按钮开系统对话框稳）
        if form.image_paths:
            # 切 tab 后图片上传控件是异步挂载的；且 file input 通常 display:none，
            # 不能用 is_visible 过滤（否则永远找不到）
            target = await self._first(SELECTORS["file_input"], timeout_s=8.0, require_visible=False)
            if target is None:
                raise PublishError(
                    "selector_miss",
                    f"找不到图片上传控件（选择器版本 {SELECTOR_SET_VERSION}），页面可能已改版",
                )
            await target.set_input_files(form.image_paths)
            await self._settle(1.5)
            # 上传后小红书会弹「图片可以编辑啦」引导卡，正好盖住编辑区
            await self._dismiss_overlays()

        # 3) 标题
        title_input = await self._first(SELECTORS["title"])
        if title_input is None:
            raise PublishError(
                "selector_miss",
                f"找不到标题输入框（选择器版本 {SELECTOR_SET_VERSION}），页面可能已改版",
            )
        await title_input.click()
        await title_input.fill(form.title)

        # 4) 正文 + 话题：**一次性 fill 整段**。
        #    真机踩坑（2026-11-09）：先 insert_text(body) 再 Enter + insert_text(topics)
        #    在 ProseMirror 里会有渲染竞态，正文尾部会被挤到话题之后（实测错位）。
        #    contenteditable 支持 fill()，一次性写入 + 触发 input 事件，小红书会
        #    自行把 "#话题" 解析成话题芯片。
        editor = await self._first(SELECTORS["editor"], timeout_s=6.0)
        if editor is None:
            raise PublishError(
                "selector_miss",
                f"找不到正文编辑器（选择器版本 {SELECTOR_SET_VERSION}），页面可能已改版",
            )
        text = form.body
        if form.topics:
            text = f"{text}\n\n{' '.join('#' + t for t in form.topics)}"
        await editor.click()
        await editor.fill(text)
        await self._settle(1.0)
        # 输入 "#话题" 会弹出联想浮层并盖住页面；Esc 关掉（文本保留）
        if form.topics:
            await page.keyboard.press("Escape")
        await self._settle(0.6)
        # 填完再扫一遍浮层，保证半自动留下的现场是"干净的发布页"
        await self._dismiss_overlays()
        logger.info(
            "xhs driver: 表单已填好 title=%r images=%s topics=%s",
            form.title,
            len(form.image_paths),
            len(form.topics),
        )

    async def submit(self) -> DriverOutcome:
        page = self._require_page()
        bar = await self._first(SELECTORS["submit_bar"], timeout_s=6.0)
        if bar is not None:
            disabled = (await bar.get_attribute("submit-disabled") or "").lower()
            if disabled == "true":
                raise PublishError(
                    "submit_disabled",
                    "「发布」按钮当前不可点：可能有必填项未完成，或账号被风控限制",
                )
            coords = await self._publish_button_coords(bar)
            if coords is None:
                raise PublishError("selector_miss", "拿不到发布按钮坐标")
            logger.info("xhs driver: 点击发布（坐标点击 closed shadow 按钮）coords=%s", coords)
            await page.mouse.click(*coords)
        else:
            legacy = await self._first(SELECTORS["submit"], timeout_s=3.0)
            if legacy is None:
                return DriverOutcome(
                    state="unknown",
                    submitted=False,
                    screenshot=await self.screenshot(),
                    message=f"找不到「发布」入口（选择器版本 {SELECTOR_SET_VERSION}）",
                )
            await legacy.click()
        await self._settle(2.5)
        return await self._read_submit_outcome()

    async def _publish_button_coords(self, bar) -> tuple[float, float] | None:
        """动作栏是 closed shadow 自定义元素，只能按真实坐标点。

        「发布」是栏内右侧那颗药丸；实测中心在栏宽 ~61% 处。真实鼠标点击
        会命中最深层节点（shadow 内部按钮），所以坐标点击是有效的。
        """
        box = await bar.bounding_box()
        if not box:
            return None
        return (
            box["x"] + box["width"] * PUBLISH_BUTTON_X_RATIO,
            box["y"] + box["height"] / 2,
        )

    async def _read_submit_outcome(self) -> DriverOutcome:
        """读回执：只有明确信号才说 published，否则 unknown。"""
        page = self._require_page()
        for sel in SELECTORS["success_marker"]:
            if await self._count(sel) > 0:
                logger.info("xhs driver: 读到发布成功标记 %s", sel)
                return DriverOutcome(
                    state="published",
                    submitted=True,
                    note_url=self._extract_note_url(),
                    screenshot=await self.screenshot(),
                )
        url = (page.url or "").lower()
        if "note-manager" in url or "/publish/success" in url:
            return DriverOutcome(
                state="published",
                submitted=True,
                note_url=self._extract_note_url(),
                screenshot=await self.screenshot(),
                message="已跳转到笔记管理页，视为发布成功",
            )
        note_url = self._extract_note_url()
        if note_url:
            return DriverOutcome(
                state="published",
                submitted=True,
                note_url=note_url,
                screenshot=await self.screenshot(),
            )
        return DriverOutcome(
            state="unknown",
            submitted=True,
            screenshot=await self.screenshot(),
            message="已点击「发布」，但未读到回执——请到创作服务平台确认结果",
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

    async def export_state(self) -> dict | None:
        """导出当前登录态（服务端按用户加密存库用；调用方负责加密）。"""
        if self._context is None:
            return None
        return dict(await self._context.storage_state())

    async def save_state(self, path: str | None = None) -> str | None:
        """导出登录态到文件（单机/自用模式；多用户请用 ``export_state``）。"""
        target = path or self.state_path
        if not target:
            return None
        state = await self.export_state()
        if state is None:
            return None
        Path(target).parent.mkdir(parents=True, exist_ok=True)
        Path(target).write_text(json.dumps(state), encoding="utf-8")
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

    async def _first(
        self, candidates: list[str], *, timeout_s: float = 0.0, require_visible: bool = True
    ):
        """按候选顺序找第一个元素；`timeout_s>0` 时先等一等。

        ``require_visible=False`` 用于隐藏控件（如 ``input[type=file]``）。
        """
        page = self._page
        if page is None:
            return None
        deadline = time.monotonic() + max(0.0, timeout_s)
        while True:
            for sel in candidates:
                try:
                    locator = page.locator(sel).first
                    if await locator.count() == 0:
                        continue
                    if not require_visible or await locator.is_visible():
                        return locator
                except Exception:  # noqa: BLE001 — 非法/失配选择器：换下一个候选
                    logger.debug("xhs driver: 候选选择器失败 %s", sel)
            if time.monotonic() >= deadline:
                return None
            await self._settle(0.3)

    async def _click_any(self, candidates: list[str], *, required: bool = False) -> bool:
        """按候选依次尝试点击；同一选择器有多个匹配时**挑可见的那个**点。

        真机踩坑（2026-11-09）：`text=上传图文` 会匹配到视口外的重复节点
        （header 里还有一份隐藏副本），`.first.click()` 必然超时。所以必须
        遍历所有匹配项，用 is_visible + click 逐个试。
        """
        page = self._page
        if page is None:
            if required:
                raise PublishError("driver_not_ready", "浏览器会话未打开")
            return False
        for sel in candidates:
            locator = None
            try:
                locator = page.locator(sel)
                total = await locator.count()
            except Exception:  # noqa: BLE001 — 非法选择器换下一个
                total = 0
            if locator is None:
                continue
            for index in range(total):
                candidate = locator.nth(index)
                try:
                    if not await candidate.is_visible():
                        continue
                    await candidate.click(timeout=4000)
                    await self._settle(0.8)
                    logger.info("xhs driver: 点击命中 %s [%s/%s]", sel, index + 1, total)
                    return True
                except Exception:  # noqa: BLE001 — 换下一个匹配项
                    logger.debug("xhs driver: 点击失败 %s [%s/%s]", sel, index + 1, total)
                    continue
        if required:
            raise PublishError(
                "selector_miss",
                f"找不到必要元素（选择器版本 {SELECTOR_SET_VERSION}），页面可能已改版",
            )
        return False

    async def _dismiss_overlays(self) -> None:
        """关掉新手引导气泡（"我知道了" 之类）——它们会盖住编辑区。"""
        page = self._page
        if page is None:
            return
        for sel in ("text=我知道了", ".feature-guide__close", "text=知道了"):
            try:
                locator = page.locator(sel)
                for index in range(min(await locator.count(), 3)):
                    item = locator.nth(index)
                    if await item.is_visible():
                        await item.click(timeout=2500)
                        logger.info("xhs driver: 关闭引导浮层 %s", sel)
                        await self._settle(0.4)
                        break
            except Exception:  # noqa: BLE001 — 浮层本来就可能不存在
                logger.debug("xhs driver: 关闭浮层失败 %s", sel)
                continue

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
