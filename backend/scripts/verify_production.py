#!/usr/bin/env python3
"""生产环境上线验证脚本（my-trip-planner · to-C 判定线配套）.

用法：
    # 上线冒烟（默认）：注册 → 提交规划（自动建行程）→ 轮询完成 → 生成分享 → 上报 5 事件
    .venv/bin/python scripts/verify_production.py --base https://你的域名

    # 判定线（W4，只查 analytics_events 指标，不写任何数据）
    .venv/bin/python scripts/verify_production.py --base https://你的域名 --verify-metrics

    # 自定义用户名前缀/密码（默认 random + 测试密码）
    --prefix e2e  --password 'Xx#12345678'

退出码：0 = 全部通过/指标输出；1 = 任一链路失败（附失败点）。
依赖：httpx（backend/.venv 已有）。

契约（2026-11-15 核验）：
    - POST /api/v1/planner/plan 收 PlanRequest 直接字段（destination/dates/travelers/budget/pace...），
      不传 trip_id；任务完成时服务端自动创建行程并回填 task.trip_id（planning_service._persist_trip）。
    - POST /api/v1/trips/{trip_id}/share 返回 ShareOut{trip_id, share_token, share_url}。
    - 分享页 GET /api/v1/trips/share/{token} 免登录只读 200。
"""
from __future__ import annotations

import argparse
import asyncio
import random
import string
import sys
import time

import httpx

UA = "verify-production/1.0 (my-trip-planner deploy check)"


def _rand_email() -> str:
    return f"verify_{int(time.time())}_{random.randint(1000, 9999)}@example.com"


def _rand_password() -> str:
    return "Vrfy!" + "".join(random.choices(string.ascii_letters + string.digits, k=10))


def _future_date(days: int) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(time.time() + 86400 * days))


async def _request(client: httpx.AsyncClient, method: str, url: str, *, token: str | None = None,
                   expect: int | None = None, **kw) -> httpx.Response:
    headers = {"User-Agent": UA}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if "headers" in kw:
        headers.update(kw.pop("headers"))
    r = await client.request(method, url, headers=headers, timeout=30.0, **kw)
    if expect is not None and r.status_code != expect:
        raise AssertionError(f"{method} {url} → HTTP {r.status_code}（期望 {expect}）: {r.text[:300]}")
    return r


async def smoke(base: str, prefix: str, password: str | None, fire_events: bool) -> list[str]:
    """注册→规划（自动建行程）→分享→5 事件 全链路冒烟。返回 OK 步骤列表。"""
    ok: list[str] = []
    async with httpx.AsyncClient(base_url=base) as client:
        # 1. 健康检查
        r = await client.get("/api/v1/health", timeout=15.0)
        assert r.status_code == 200, f"health → HTTP {r.status_code}: {r.text[:200]}"
        j = r.json()
        assert j.get("status") == "ok", f"health status ≠ ok: {j}"
        ok.append(f"health: {j.get('status')}")

        # 2. 注册（随机账号；判定线只认真实用户，测试账号独立验证）
        email = _rand_email()
        pwd = password or _rand_password()
        r = await _request(client, "POST", "/api/v1/auth/register",
                           json={"email": email, "password": pwd, "display_name": f"{prefix}_verify"},
                           expect=201)
        token = r.json()["access_token"]
        ok.append(f"register: {email[:28]}… (201, token ok)")

        # 3. 提交规划（真实用户路径：PlanWizard 直接 POST /planner/plan，不先建行程）
        plan_payload = {
            "destination": "杭州",
            "departure": "上海",
            "trip_type": "休闲旅游",
            "start_date": _future_date(7),
            "end_date": _future_date(10),
            "travelers": 2,
            "budget": 3000,
            "preferences": ["food", "nature"],
            "pace": "balanced",
            "provider": "auto",
        }
        r = await _request(client, "POST", "/api/v1/planner/plan",
                           json=plan_payload, token=token, expect=202)
        task_id = r.json().get("task_id") or r.json().get("id")
        assert task_id, f"plan task 无 id: {r.text[:200]}"
        ok.append(f"plan submit: task={task_id} (202, async)")

        # 4. 轮询规划完成（completed / degraded 都算通过——degraded 是诚实降级，不是失败）
        deadline = time.time() + 180
        status = None
        trip_id = None
        plan_days = None
        while time.time() < deadline:
            r = await _request(client, "GET", f"/api/v1/planner/tasks/{task_id}", token=token)
            jr = r.json()
            status = jr.get("status")
            trip_id = jr.get("trip_id")
            plan_days = (jr.get("plan") or {}).get("days")
            if status in ("completed", "failed", "degraded"):
                break
            await asyncio.sleep(3)
        assert status in ("completed", "degraded"), f"plan 未完成: status={status} (task={task_id})"
        assert trip_id, f"plan {status} 但 task 无 trip_id（服务端未回写行程）: {r.text[:300]}"
        ok.append(f"plan done: task={task_id} status={status} trip_id={trip_id} days={len(plan_days or [])}")

        # 5. 生成分享链接（owner 主动分享）→ 免登录读分享页
        r = await _request(client, "POST", f"/api/v1/trips/{trip_id}/share", token=token, expect=200)
        j = r.json()
        share_token = j.get("share_token")
        share_url = j.get("share_url")
        assert share_token, f"share 响应无 share_token: {r.text[:200]}"
        r = await client.get(f"/api/v1/trips/share/{share_token}", timeout=15.0)
        assert r.status_code == 200, f"share/{share_token[:12]}… → HTTP {r.status_code}"
        ok.append(f"share: token={share_token[:12]}… url={share_url} (公开可读 200)")

        # 6.（可选，W1 埋点实现后开）上报 5 个最小埋点事件
        if fire_events:
            events = ["page_view", "register", "plan_submitted", "plan_completed", "share_created"]
            for name in events:
                r = await _request(client, "POST", "/api/v1/analytics/event",
                                   json={"name": name, "payload": {"trip_id": trip_id, "phase": "planning"}},
                                   token=token)
                assert r.status_code in (200, 204), f"analytics {name} → HTTP {r.status_code}: {r.text[:200]}"
            ok.append("analytics: 5 事件上报")
        else:
            ok.append("analytics: 跳过（W1 埋点未实现；--events 开启后验证）")

        # 7. 收尾：删除测试行程（保持库干净；判定线只认真实用户）
        r = await _request(client, "DELETE", f"/api/v1/trips/{trip_id}", token=token, expect=204)
        ok.append("cleanup: 测试行程已删除")
    return ok


async def verify_metrics(base: str) -> dict:
    """判定线：统计 analytics_events 中的 5 事件去重计数（不写数据）。"""
    async with httpx.AsyncClient(base_url=base, timeout=30.0) as client:
        r = await client.get("/api/v1/analytics/metrics")
        if r.status_code == 404:
            return {"error": "analytics/metrics 未实现——判定线需先落地 §1.7 埋点（analytics_events 表 + POST /analytics/event + 查询端点）",
                    "note": "当前 analytics/events 仅 204 写日志不落库，无法直接聚合；请先实现 W1 埋点再跑本命令"}
        if r.status_code != 200:
            return {"error": f"analytics/metrics → HTTP {r.status_code}"}
        return r.json()


async def main() -> int:
    p = argparse.ArgumentParser(description="my-trip-planner 生产验证")
    p.add_argument("--base", required=True, help="站点根，如 https://example.com")
    p.add_argument("--verify-metrics", action="store_true", help="判定线模式：只查指标")
    p.add_argument("--prefix", default="e2e", help="测试账号 display_name 前缀")
    p.add_argument("--password", default=None, help="测试账号密码（默认随机）")
    p.add_argument("--events", action="store_true", help="上报 5 个埋点事件（W1 埋点实现后开；默认跳过）")
    a = p.parse_args()

    base = a.base.rstrip("/")
    print(f"==> 目标: {base}")
    try:
        if a.verify_metrics:
            out = await verify_metrics(base)
            if "error" in out:
                print(f"!! {out['error']}")
                return 1
            print("==> 判定线指标:")
            for k, v in out.items():
                print(f"    {k}: {v}")
            return 0

        ok = await smoke(base, a.prefix, a.password, fire_events=a.events)
        print("\n==> 冒烟结果（全绿 = 可上线）")
        for line in ok:
            print(f"  OK  {line}")
        print(f"\n==> 共 {len(ok)} 步全部通过 ✅")
        return 0
    except AssertionError as e:
        print(f"\n!! 验证失败: {e}")
        return 1
    except httpx.HTTPError as e:
        print(f"\n!! 网络/HTTP 错误: {e}（站点不可达或超时，请检查域名解析/防火墙/宝塔反代）")
        return 1
    except Exception as e:  # noqa: BLE001
        print(f"\n!! 未知错误: {type(e).__name__}: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))