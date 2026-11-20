#!/usr/bin/env python3
"""14 天判定线取数（task-launch-deploy-eval §3）。

从 ``analytics_events`` 聚合漏斗：访问 → 注册 → 提交规划 → 完成规划 → 创建分享，
输出逐层计数、转化率与 20/5/2 判定线达标布尔。

用法（在 backend/ 下）：
    .venv/bin/python scripts/launch_judgment.py                # 默认近 14 天
    .venv/bin/python scripts/launch_judgment.py --days 30
    .venv/bin/python scripts/launch_judgment.py --db-url postgresql+asyncpg://...

判定线（spec）：page_view ≥ 20、plan_completed ≥ 5、share_created ≥ 2。
未达标 → 执行止损预案（停服务器/回退作品集定位/内容资产沉淀）。
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# 支持从仓库根或 backend/ 直接运行
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402

from app.models.analytics import AnalyticsEvent  # noqa: E402

FUNNEL = [
    ("page_view", "访问"),
    ("register", "注册"),
    ("plan_submitted", "提交规划"),
    ("plan_completed", "完成规划"),
    ("share_created", "创建分享"),
]

THRESHOLDS = {
    "page_view": 20,
    "plan_completed": 5,
    "share_created": 2,
}


async def collect(db_url: str, days: int) -> dict:
    engine = create_async_engine(db_url, pool_pre_ping=True)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    since = datetime.now(timezone.utc) - timedelta(days=days)
    counts: dict[str, int] = {}
    sessions: dict[str, int] = {}
    try:
        async with factory() as db:
            for name, _ in FUNNEL:
                counts[name] = int(
                    (
                        await db.execute(
                            select(func.count())
                            .select_from(AnalyticsEvent)
                            .where(
                                AnalyticsEvent.event_name == name,
                                AnalyticsEvent.created_at >= since,
                            )
                        )
                    ).scalar_one()
                )
                sessions[name] = int(
                    (
                        await db.execute(
                            select(func.count(func.distinct(AnalyticsEvent.anonymous_session_id)))
                            .select_from(AnalyticsEvent)
                            .where(
                                AnalyticsEvent.event_name == name,
                                AnalyticsEvent.created_at >= since,
                                AnalyticsEvent.anonymous_session_id.is_not(None),
                            )
                        )
                    ).scalar_one()
                )
    finally:
        await engine.dispose()
    return {"counts": counts, "sessions": sessions}


def _rate(num: int, den: int) -> str:
    if den <= 0:
        return "—"
    return f"{num / den * 100:.1f}%"


def render(result: dict, days: int) -> str:
    counts = result["counts"]
    sessions = result["sessions"]
    lines = [f"== 漏斗判定线（近 {days} 天）==", ""]
    prev = None
    for name, label in FUNNEL:
        c = counts.get(name, 0)
        s = sessions.get(name, 0)
        layer = _rate(c, prev) if prev is not None else "—"
        lines.append(f"{label:6s} {name:16s} 次数={c:<5d} 独立会话={s:<5d} 层转化={layer}")
        prev = c
    lines.append("")
    ok = True
    for name, threshold in THRESHOLDS.items():
        got = counts.get(name, 0)
        passed = got >= threshold
        ok = ok and passed
        lines.append(f"判定 {name}: {got} / {threshold} → {'达标' if passed else '未达'}")
    lines.append("")
    lines.append("判定结果：" + ("达标（解锁 §2 候选池）" if ok else "未达标（执行止损预案）"))
    return "\n".join(lines)


async def main() -> int:
    p = argparse.ArgumentParser(description="从 analytics_events 聚合 14 天漏斗判定线")
    p.add_argument("--days", type=int, default=14, help="统计窗口天数（默认 14）")
    p.add_argument(
        "--db-url",
        default=os.getenv("DATABASE_URL", ""),
        help="数据库连接串（默认读取环境变量 DATABASE_URL）",
    )
    args = p.parse_args()

    db_url = args.db_url
    if not db_url:
        from app.common.config import settings

        db_url = settings.DATABASE_URL or ""
    if not db_url:
        print("!! 缺少数据库连接串：请设置 DATABASE_URL 或传 --db-url", file=sys.stderr)
        return 2

    result = await collect(db_url, args.days)
    print(render(result, args.days))
    # 退出码：0 = 达标；1 = 未达标；便于 cron/结算脚本判断
    counts = result["counts"]
    return 0 if all(counts.get(k, 0) >= v for k, v in THRESHOLDS.items()) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
