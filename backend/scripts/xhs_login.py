"""小红书创作服务平台：扫码登录一次，保存登录态给发布通道复用。

用法（在 backend 目录下）::

    .venv/bin/python scripts/xhs_login.py                # 扫码登录并保存
    .venv/bin/python scripts/xhs_login.py --check        # 只检查当前登录态
    .venv/bin/python scripts/xhs_login.py --from-cdp http://127.0.0.1:9333

登录态默认写到 ``{XHS_STATE_DIR}/default.json``（默认 ``backend/var/xhs/states``，
容器里指向挂载卷）。发布通道读 ``XHS_RPA_STATE_PATH``，或由服务端按用户
从加密存储里解出后直接传给驱动（多用户模式，见部署文档）。

⚠️ 这是**单机/单账号**运维工具：服务端多用户场景不要用共享状态文件，
每个用户一份登录态且必须加密存放。

⚠️ 安全边界：脚本只负责**打开登录页**，绝不代输账号/密码/验证码；
二维码由你在小红书 App 里扫。同一账号不要在多处网页端同时登录，
否则会互相踢下线（小红书限制）。
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.publishers.base import PublishError
from app.services.publishers.drivers.playwright_creator import (
    CREATOR_HOME_URL,
    PlaywrightCreatorDriver,
)
from app.services.publishers.paths import states_dir

# 目录由配置决定（容器里通常指到挂载卷），不在脚本里写死路径
DEFAULT_STATE_NAME = "default.json"


async def _diagnose(driver: PlaywrightCreatorDriver) -> None:
    """登录轮询期间打点：URL + cookie 名（不含值），便于排查"扫了但没识别"。

    2026-11-09 踩过的坑：登录成功后停在创作平台首页，首页既没有标题框也没有
    发布按钮，早期只看元素的判定会误判成未登录 → 加了 cookie 判定与这段诊断。
    """
    try:
        page = driver._require_page()  # 运维脚本，直接用受保护方法
        context = driver._context  # 运维脚本，直接用受保护属性
        names: list[str] = []
        if context is not None:
            names = sorted(
                {
                    str(c.get("name"))
                    for c in await context.cookies("https://creator.xiaohongshu.com")
                }
            )
        print(f"   · 诊断 url={page.url}")
        print(f"   · 诊断 cookies={names}")
    except Exception as exc:  # noqa: BLE001 — 诊断失败不影响登录流程
        print(f"   · 诊断失败：{exc}")


async def main() -> int:
    parser = argparse.ArgumentParser(description="小红书创作服务平台扫码登录")
    parser.add_argument("--state", default=None, help="登录态保存路径（默认 {XHS_STATE_DIR}/default.json）")
    parser.add_argument("--check", action="store_true", help="只检查登录态，不等待扫码")
    parser.add_argument("--from-cdp", default=None, help="接管已登录 Chrome 的 CDP 地址")
    parser.add_argument("--timeout", type=int, default=180, help="等待扫码秒数")
    args = parser.parse_args()
    args.state = str(args.state or (states_dir() / DEFAULT_STATE_NAME))

    driver = PlaywrightCreatorDriver(
        headless=False,
        cdp_url=args.from_cdp,
        state_path=args.state,
    )
    try:
        await driver.open()
        if await driver.is_logged_in():
            print("✅ 已登录")
            if not args.from_cdp:
                saved = await driver.save_state(args.state)
                print(f"登录态已保存：{saved}")
            return 0
        if args.check:
            print("❌ 未登录（去掉 --check 可交互扫码登录）")
            return 1

        print("👉 请在弹出的浏览器窗口里登录小红书（脚本不会代输任何凭据）")
        print("   默认是「短信登录」；卡片右上角有二维码图标，可切换成扫码（推荐，免验证码）")
        print(f"   登录页：{CREATOR_HOME_URL}")
        page = driver._require_page()  # 一次性运维脚本，直接用受保护方法
        await page.goto(CREATOR_HOME_URL, wait_until="domcontentloaded")
        for i in range(args.timeout):
            await asyncio.sleep(1)
            if await driver.is_logged_in():
                saved = await driver.save_state(args.state)
                print(f"✅ 登录成功，登录态已保存：{saved}")
                return 0
            if i % 15 == 14:
                await _diagnose(driver)
        print("⌛ 等待超时：未检测到登录成功")
        return 2
    except PublishError as exc:
        print(f"❌ {exc.message}（reason={exc.reason}）")
        return 3
    finally:
        await driver.close(keep_open=False)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
