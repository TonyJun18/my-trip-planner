#!/usr/bin/env python3
"""生成行程分享链接（owner）——生产验证 / 日常运营工具。

用法：
    # 用已有账号登录（邮箱+密码）→ 列出我的行程 → 选一个生成分享链接
    .venv/bin/python scripts/create_share.py --base https://你的域名 \\
        --account 你@邮箱.com --password '密码' --trip-id <trip_id>

    # 只列出我的行程（不生成）
    .venv/bin/python scripts/create_share.py --base https://你的域名 \\
        --account 你@邮箱.com --password '密码' --list

依赖：httpx（backend/.venv 已有）。
"""
from __future__ import annotations

import argparse
import sys

import httpx

UA = "create-share/1.0"


async def main() -> int:
    p = argparse.ArgumentParser(description="生成/列出行程分享链接")
    p.add_argument("--base", required=True, help="站点根，如 https://example.com")
    p.add_argument("--account", required=True, help="登录账号（邮箱或手机号）")
    p.add_argument("--password", required=True, help="登录密码")
    p.add_argument("--trip-id", default=None, help="要生成分享链接的行程 id")
    p.add_argument("--list", action="store_true", help="只列我的行程")
    a = p.parse_args()

    base = a.base.rstrip("/")
    async with httpx.AsyncClient(base_url=base, timeout=30.0) as client:
        r = await client.post("/api/v1/auth/login",
                              json={"account": a.account, "password": a.password})
        if r.status_code != 200:
            print(f"!! 登录失败: HTTP {r.status_code}: {r.text[:300]}")
            return 1
        token = r.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}", "User-Agent": UA}

        r = await client.get("/api/v1/trips", headers=headers)
        if r.status_code != 200:
            print(f"!! 行程列表失败: HTTP {r.status_code}: {r.text[:300]}")
            return 1
        trips = r.json().get("items", r.json()) if isinstance(r.json(), dict) else r.json()
        if a.list:
            print("==> 我的行程:")
            for t in (trips if isinstance(trips, list) else []):
                print(f"  {t.get('id')}  {t.get('title')}  {t.get('destination')}  {t.get('status')}")
            return 0

        if not a.trip_id:
            print("!! 请用 --trip-id 指定行程（或 --list 先看有哪些）")
            return 1

        # 生成分享链接
        r = await client.post(f"/api/v1/trips/{a.trip_id}/share", headers=headers)
        if r.status_code != 200:
            print(f"!! 生成分享失败: HTTP {r.status_code}: {r.text[:300]}")
            return 1
        j = r.json()
        share_token = j.get("share_token")
        share_url = j.get("share_url") or f"{base}/trips/share/{share_token}"
        print(f"==> 分享链接: {share_url}")
        print(f"    token: {share_token}")
        print(f"    免登录访问: {base}/trips/share/{share_token}")
        return 0


if __name__ == "__main__":
    sys.exit(__import__("asyncio").run(main()))