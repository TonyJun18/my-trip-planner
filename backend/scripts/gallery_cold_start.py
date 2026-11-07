"""灵感画廊冷启动运营脚本（task-gallery-cold-start，2026-11-07）。

把 3–5 条「真实存在且内容完整」的官方行程标记 ``is_featured=True`` 并写卖点，
铺满画廊首屏。诚实口径：不做假数据——不创建评分、不编造内容；画廊卡片
无评分时已诚实显示「还没有评分」。

决策依据（2026-11-07 库存审计，详见 docs/nightly/evaluations/task-gallery-cold-start-2026-11-07.md）：
- 大理（5b42a245）：质检 passed=True（84 分），已 featured，本脚本仅优化卖点。
- 上海（03fed36e）：内容完整 12 站点；质检 critical（地理绕行）对应的站点在
  DB 中已是修订后版本（青浦晚餐替代徐汇绕行），卖点只写真实内容。
- 成都（3a854e92）：内容完整 13 站点（丹景山/白鹿音乐小镇/鹤鸣山徒步线）；
  残余质检 warning（编造返程城市/餐饮 0 计价/占位 POI）如实记录，待用户白天修订。
- 厦门（1544f4ad）**不标记**：质检 critical「三天行程全是餐饮无任何景点」，
  未达「打磨过」标准。
- 青岛（603de374）**不标记**：无 plan，行程内容整段复制成都行程的脏数据。

用法（幂等，可重复执行；默认 dry-run 不写库）：
    ENV=dev PYTHONPATH=backend .venv/bin/python backend/scripts/gallery_cold_start.py
    ENV=dev PYTHONPATH=backend .venv/bin/python backend/scripts/gallery_cold_start.py --apply

只操作 trips.is_featured / trips.gallery_blurb / trips.share_token 三列，
不改任何其他数据；不读 .env 内容（由 app 配置加载）。
"""
from __future__ import annotations

import argparse
import sys
from secrets import token_urlsafe

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models import Trip

# (trip_id, 卖点) —— 卖点全部从 DB 实际站点内容提炼，无编造
COLD_START_ITEMS: list[tuple[str, str]] = [
    (
        "5b42a245-70ac-4644-831a-b2d280345c0f",
        "洱海湿地栈道看海鸥、大理古城慢逛、野生菌火锅，2 人 3 日 6000 元预算",
    ),
    (
        "03fed36e-0fc5-4d5b-ad2e-ab469be8ff3e",
        "青西郊野水上森林+长兴岛湿地候鸟，2 人 3 日 3000 元自然慢行",
    ),
    (
        "3a854e92-f7ca-4cc0-bbd2-37a01c348453",
        "丹景山徒步+白鹿音乐小镇+鹤鸣山道源文化，1 人 4 日山林人文线",
    ),
]


async def apply_one(db, trip_id: str, blurb: str, *, apply: bool) -> bool:
    stmt = select(Trip).where(Trip.id == trip_id)
    trip = (await db.execute(stmt)).scalar_one_or_none()
    if trip is None:
        print(f"  [SKIP] {trip_id} 行程不存在（已删除或 id 失效）")
        return False
    old_featured = trip.is_featured
    old_blurb = trip.gallery_blurb
    action = "APPLY" if apply else "dry-run"
    print(f"  [{action}] {trip.title}（{trip.destination}）"
          f" featured: {old_featured} -> True | blurb: {old_blurb!r} -> {blurb!r}")
    if not apply:
        return True
    trip.is_featured = True
    trip.gallery_blurb = blurb
    if not trip.share_token:
        # 画廊读侧要求 share_token 非空；复用分享令牌生成逻辑（token_urlsafe(32)）
        trip.share_token = token_urlsafe(32)
    await db.flush()
    return True


async def main() -> None:
    parser = argparse.ArgumentParser(description="灵感画廊冷启动运营脚本（幂等）")
    parser.add_argument("--apply", action="store_true", help="实际写库；缺省为 dry-run")
    args = parser.parse_args()

    print(f"gallery cold start: {'APPLY' if args.apply else 'DRY-RUN'} ({len(COLD_START_ITEMS)} 条)")
    async with SessionLocal() as db:
        ok = 0
        for trip_id, blurb in COLD_START_ITEMS:
            if await apply_one(db, trip_id, blurb, apply=args.apply):
                ok += 1
        if args.apply:
            await db.commit()
            print(f"已提交：{ok}/{len(COLD_START_ITEMS)} 条标记为画廊精选")
        else:
            await db.rollback()
            print(f"dry-run 结束（未写库）：{ok}/{len(COLD_START_ITEMS)} 条将被标记")


if __name__ == "__main__":
    sys.exit(0 if __import__("asyncio").run(main()) is None else 0)