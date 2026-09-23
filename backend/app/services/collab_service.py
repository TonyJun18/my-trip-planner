"""分享页协作服务：评论 / 站点投票（免登录，凭 share_token 授权）。"""
from __future__ import annotations

import hashlib
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models import Stop, StopVote, Trip, TripComment, TripDay
from app.schemas.collab import CommentIn, VoteIn


# ── 分享令牌基础：所有协作接口都要求持有效令牌（与只读分享同信任级别） ──
async def _get_trip_by_token(db: AsyncSession, token: str) -> Trip:
    stmt = select(Trip).where(Trip.share_token == token)
    trip = (await db.execute(stmt)).scalar_one_or_none()
    if trip is None:
        raise NotFoundError("分享链接无效或已失效", code="share_token_invalid")
    return trip


async def _belongs_to_trip(db: AsyncSession, stop_id: str, trip_id: str) -> Stop:
    """校验站点属于该行程（防止跨行程投票）。"""
    stmt = (
        select(Stop)
        .join(TripDay, TripDay.id == Stop.day_id)
        .where(Stop.id == stop_id, TripDay.trip_id == trip_id)
    )
    stop = (await db.execute(stmt)).scalar_one_or_none()
    if stop is None:
        raise NotFoundError("站点不存在", code="stop_not_found")
    return stop


# ── 评论 ──────────────────────────────────────────────────────
async def list_comments(db: AsyncSession, token: str) -> list[TripComment]:
    """行程评论（按时间正序）。"""
    trip = await _get_trip_by_token(db, token)
    stmt = (
        select(TripComment)
        .where(TripComment.trip_id == trip.id)
        .order_by(TripComment.created_at.asc(), TripComment.id.asc())
    )
    return list((await db.execute(stmt)).scalars().all())


async def create_comment(db: AsyncSession, token: str, data: CommentIn) -> TripComment:
    trip = await _get_trip_by_token(db, token)
    comment = TripComment(
        trip_id=trip.id,
        author_name=(data.author_name or "").strip() or None,
        content=data.content.strip(),
    )
    db.add(comment)
    await db.flush()
    await db.refresh(comment)
    return comment


# ── 站点投票 ──────────────────────────────────────────────────
def _voter_key(token: str, client_ip: str | None, user_agent: str | None) -> str:
    """轻量匿名身份：share_token + IP + UA 哈希。

    - 用于「一访客一票、可翻转」去重；不是强身份认证。
    - 避免了在 URL/DB 中暴露访客真实 IP/UA。
    - token 属于行程：同一访客在不同行程的投票互不影响。
    """
    raw = f"{token}|{client_ip or ''}|{user_agent or ''}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:64]


async def _counts_for_stop(db: AsyncSession, stop_id: str) -> dict[str, int]:
    """某站点的 👍/👎 计数。"""
    rows = (
        await db.execute(
            select(StopVote.value, func.count()).where(StopVote.stop_id == stop_id).group_by(StopVote.value)
        )
    ).all()
    up = down = 0
    for value, cnt in rows:
        if value == 1:
            up = cnt
        elif value == -1:
            down = cnt
    return {"up": up, "down": down}


async def list_stop_votes(db: AsyncSession, token: str, *, voter_key: str | None = None) -> dict[str, Any]:
    """行程内全部站点的投票汇总；给定 voter_key 时附带我的选择。"""
    trip = await _get_trip_by_token(db, token)
    stmt = (
        select(StopVote.stop_id, StopVote.value, func.count())
        .select_from(StopVote)
        .join(Stop, Stop.id == StopVote.stop_id)
        .join(TripDay, TripDay.id == Stop.day_id)
        .where(TripDay.trip_id == trip.id)
        .group_by(StopVote.stop_id, StopVote.value)
    )
    rows = (await db.execute(stmt)).all()

    result: dict[str, dict[str, int]] = {}
    for stop_id, value, cnt in rows:
        item = result.setdefault(stop_id, {"stop_id": stop_id, "up": 0, "down": 0})
        if value == 1:
            item["up"] = cnt
        elif value == -1:
            item["down"] = cnt

    if voter_key:
        mine = (
            await db.execute(
                select(StopVote.stop_id, StopVote.value).where(StopVote.voter_key == voter_key)
            )
        ).all()
        for stop_id, value in mine:
            result.setdefault(stop_id, {"stop_id": stop_id, "up": 0, "down": 0})["my_value"] = value
    return result


async def cast_vote(
    db: AsyncSession,
    token: str,
    stop_id: str,
    data: VoteIn,
    *,
    client_ip: str | None = None,
    user_agent: str | None = None,
) -> dict[str, Any]:
    """投票（幂等 + 可翻转）：同 visitor 同站点不存在则新建 / 反向则更新 / 同向则不变。"""
    trip = await _get_trip_by_token(db, token)
    await _belongs_to_trip(db, stop_id, trip.id)
    key = _voter_key(token, client_ip, user_agent)

    stmt = select(StopVote).where(StopVote.stop_id == stop_id, StopVote.voter_key == key)
    vote = (await db.execute(stmt)).scalar_one_or_none()
    if vote is None:
        vote = StopVote(stop_id=stop_id, voter_key=key, value=data.value)
        db.add(vote)
        await db.flush()
    elif vote.value != data.value:
        vote.value = data.value
        await db.flush()

    counts = await _counts_for_stop(db, stop_id)
    return {"stop_id": stop_id, "up": counts["up"], "down": counts["down"], "my_value": data.value}