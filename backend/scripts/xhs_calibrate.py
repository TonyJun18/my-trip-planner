"""小红书创作服务平台：发布页选择器校准（登录态下运行）。

用途：小红书前端改版后，`playwright_creator.py` 里的 `SELECTORS` 会失配。
本脚本把发布页的真实结构 dump 出来（输入框 / 可编辑区 / 按钮 / tab / file input），
并留一张截图，照着改 `SELECTORS` 即可。

用法（backend 目录下）::

    # 只看结构（登录态来自 storage_state，或 --cdp 接管已登录 Chrome）
    .venv/bin/python scripts/xhs_calibrate.py
    .venv/bin/python scripts/xhs_calibrate.py --cdp http://127.0.0.1:9333

    # 顺手验证「填表」是否真的能填进去（绝不点发布）
    .venv/bin/python scripts/xhs_calibrate.py --fill /tmp/cover.png

输出：JSON（结构 + 命中情况）+ 截图路径。脚本不会点「发布」。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.publishers.drivers.playwright_creator import (  # noqa: F401
    CREATOR_PUBLISH_URL,
    SELECTOR_SET_VERSION,
    SELECTORS,
    PlaywrightCreatorDriver,
)

DUMP_JS = """
() => {
  const pick = (el) => ({
    tag: el.tagName.toLowerCase(),
    type: el.getAttribute('type') || undefined,
    placeholder: el.getAttribute('placeholder') || undefined,
    cls: (el.className && String(el.className).slice(0, 120)) || undefined,
    text: (el.innerText || '').trim().slice(0, 40) || undefined,
    accept: el.getAttribute('accept') || undefined,
    editable: el.getAttribute('contenteditable') || undefined,
  });
  const uniq = (arr) => {
    const seen = new Set();
    return arr.filter((x) => {
      const k = JSON.stringify(x);
      if (seen.has(k)) return false;
      seen.add(k);
      return true;
    });
  };
  return {
    url: location.href,
    title: document.title,
    inputs: uniq([...document.querySelectorAll('input')].map(pick)).slice(0, 40),
    editables: uniq([...document.querySelectorAll('[contenteditable="true"], .ql-editor, .ProseMirror')].map(pick)).slice(0, 20),
    buttons: uniq([...document.querySelectorAll('button, [role="button"]')].map(pick)).slice(0, 40),
    tabs: uniq([...document.querySelectorAll('[class*="tab"], [class*="Tab"]')].map(pick)).slice(0, 30),
    fileInputs: uniq([...document.querySelectorAll('input[type="file"]')].map(pick)),
    textSnippets: (document.body.innerText || '').split('\\n').map(s => s.trim()).filter(Boolean).slice(0, 60),
    // 「发布」按钮在真机上不是 <button>（2026-11-09 实测），单独挖它的真实标签/类名
    publishCandidates: [...document.querySelectorAll('*')]
      .filter((el) => (el.textContent || '').trim() === '发布' && el.children.length <= 1)
      .map((el) => ({
        tag: el.tagName.toLowerCase(),
        cls: (el.className && String(el.className).slice(0, 140)) || undefined,
        role: el.getAttribute('role') || undefined,
        parentTag: el.parentElement ? el.parentElement.tagName.toLowerCase() : undefined,
        parentCls: el.parentElement ? String(el.parentElement.className).slice(0, 140) : undefined,
      }))
      .slice(0, 10),
  };
}
"""


async def _probe(driver: PlaywrightCreatorDriver) -> dict:
    """逐条试 SELECTORS，报告命中数量（= 当前选择器是否还有效）。"""
    page = driver._require_page()  # 运维脚本，直接用受保护方法
    report: dict[str, dict[str, int]] = {}
    for group, candidates in SELECTORS.items():
        if not isinstance(candidates, list):
            continue
        report[group] = {}
        for sel in candidates:
            try:
                report[group][sel] = await page.locator(sel).count()
            except Exception:  # noqa: BLE001 — 非法选择器记 -1
                report[group][sel] = -1
    return report


async def main() -> int:
    parser = argparse.ArgumentParser(description="小红书发布页选择器校准")
    parser.add_argument("--state", default=None, help="storage_state 路径")
    parser.add_argument("--cdp", default=None, help="接管已登录 Chrome 的 CDP 地址")
    parser.add_argument("--headless", action="store_true", help="无头运行（默认有头，便于看页面）")
    parser.add_argument("--fill", default=None, help="给这张图片填一遍表单做验证（不点发布）")
    parser.add_argument(
        "--tab",
        choices=["none", "image"],
        default="none",
        help="dump 之前先切到「上传图文」tab（--fill 时自动切）",
    )
    args = parser.parse_args()

    driver = PlaywrightCreatorDriver(
        headless=args.headless,
        cdp_url=args.cdp,
        state_path=args.state,
    )
    try:
        await driver.open()
        logged_in = await driver.is_logged_in()
        page = driver._require_page()

        tab_clicked = None
        if args.tab == "image" or args.fill:
            tab_clicked = await driver._click_any(SELECTORS["image_tab"])
            await asyncio.sleep(1.5)

        fill_result = None
        if args.fill:
            from app.services.publishers.base import PublishError
            from app.services.publishers.drivers.protocol import PublishForm

            form = PublishForm(
                title="校准测试标题",
                body="这是一次填表校准，不会点发布。",
                topics=["校准", "测试"],
                image_paths=[str(Path(args.fill).resolve())],
            )
            try:
                await driver.fill_form(form)
                fill_result = {"ok": True}
            except PublishError as exc:
                fill_result = {"ok": False, "reason": exc.reason, "message": exc.message}
            except Exception as exc:  # noqa: BLE001
                fill_result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            await asyncio.sleep(1.5)

        # dump 放在填表之后：这样拿到的是**编辑页**（标题/正文/发布按钮都在这一步）
        dump = await page.evaluate(DUMP_JS)
        selector_probe = await _probe(driver)
        shot = await driver.screenshot()

        out = {
            "selector_set_version": SELECTOR_SET_VERSION,
            "logged_in": logged_in,
            "url": page.url,
            "tab_clicked": tab_clicked,
            "fill": fill_result,
            "screenshot": shot,
            "selector_probe": selector_probe,
            "dom": dump,
        }

        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        return 1
    finally:
        await driver.close(keep_open=False)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
