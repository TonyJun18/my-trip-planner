"""兑换码批量生成脚本（frame-marketplace）。

生成明文兑换码列表（供爱发电等外部平台上架）+ 对应 SHA-256 哈希入库。
明文码只打印到 stdout，不落库、不写日志——脚本退出后明文即弃，
用户对账只能靠外部平台的订单记录。

用法（backend 目录下）::
    uv run python scripts/gen_codes.py --pack pack-warm-memories --count 10
    uv run python scripts/gen_codes.py --pack pack-warm-memories --count 10 --note "爱发电 2026-11 批次"
    uv run python scripts/gen_codes.py --pack pack-warm-memories --count 10 --dry-run

安全设计（对应 design.md 决策 2）：
- 码空间：FRM- + 12 位 Crockford base32（~60 bit），配合限速足够防暴力枚举
- 库里只存 SHA-256 哈希（redemption_codes.code_hash 唯一）
- 明文码绝不写入数据库或日志；打印即弃
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Crockford base32：无 I/L/O/U，避免用户抄错码
_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def generate_code() -> str:
    """FRM- + 12 位 Crockford base32 随机码（~60 bit 熵）。"""
    body = "".join(_ALPHABET[b % 32] for b in os.urandom(12))
    return f"FRM-{body}"


async def run(pack_slug: str, count: int, note: str | None, dry_run: bool) -> int:
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.common.config import settings
    from app.models import FramePack, RedemptionCode
    from app.services.frame_entitlement_service import hash_code

    engine = create_async_engine(settings.DATABASE_URL)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    codes: list[str] = []
    async with factory() as session:
        pack = (
            await session.execute(select(FramePack).where(FramePack.slug == pack_slug))
        ).scalar_one_or_none()
        if pack is None:
            print(f"错误：模板包 {pack_slug!r} 不存在", file=sys.stderr)
            await engine.dispose()
            return 2

        for _ in range(count):
            code = generate_code()
            h = hash_code(code)
            exists = (
                await session.execute(
                    select(RedemptionCode).where(RedemptionCode.code_hash == h)
                )
            ).scalar_one_or_none()
            if exists is not None:  # 极小概率碰撞，跳过重试
                continue
            codes.append(code)
            if not dry_run:
                session.add(
                    RedemptionCode(
                        id=str(uuid.uuid4()),
                        code_hash=h,
                        pack_slug=pack_slug,
                        status="unused",
                        note=note,
                    )
                )
        if not dry_run:
            await session.commit()
    await engine.dispose()

    for code in codes:
        print(code)
    print(
        f"\n# pack={pack_slug} count={len(codes)} dry_run={dry_run} note={note!r}",
        file=sys.stderr,
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="生成兑换码（明文打印即弃，哈希入库）")
    parser.add_argument("--pack", required=True, help="模板包 slug，如 pack-warm-memories")
    parser.add_argument("--count", type=int, default=10, help="生成数量")
    parser.add_argument("--note", default=None, help="来源渠道备注（入库，如「爱发电 2026-11」）")
    parser.add_argument("--dry-run", action="store_true", help="只打印不写库")
    args = parser.parse_args()
    return asyncio.run(run(args.pack, args.count, args.note, args.dry_run))


if __name__ == "__main__":
    raise SystemExit(main())
