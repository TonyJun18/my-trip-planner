"""分享页协作服务：评论 / 站点投票 / 受邀编辑（免登录，凭相应令牌授权）。"""
from __future__ import annotations

import hashlib
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models import Stop, StopVote, Trip, TripComment, TripDay
from app.schemas.collab import CommentIn, InvitedStopUpdate, VoteIn


# ── 分享令牌基础：所有协作接口都要求持有效令牌（与只读分享同信任级别） ──
async def _get_trip_by_token(db: AsyncSession, token: str) -> Trip:
    stmt = select(Trip).where(Trip.share_token == token)
    trip = (await db.execute(stmt)).scalar_one_or_none()
    if trip is None:
        raise NotFoundError("分享链接无效或已失效", code="share_token_invalid")
    return trip


async def _get_trip_by_edit_token(db: AsyncSession, token: str) -> Trip:
    """按受邀编辑令牌读取行程（403 → 404：令牌等同于授权，不存在即视为无效）。"""
    stmt = select(Trip).where(Trip.edit_token == token)
    trip = (await db.execute(stmt)).scalar_one_or_none()
    if trip is None:
        raise NotFoundError("协作编辑链接无效或已失效", code="edit_token_invalid")
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


# ── 受邀编辑（凭 edit_token，受限字段直写，不经 AI 修订） ─────────────
async def update_invited_stop(
    db: AsyncSession, token: str, stop_id: str, data: InvitedStopUpdate
) -> Stop:
    """受邀者更新站点受限字段：name / description / checked（exclude_unset，其余不动）。"""
    trip = await _get_trip_by_edit_token(db, token)
    stop = await _belongs_to_trip(db, stop_id, trip.id)
    for field, value in data.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(stop, field, value)
    await db.flush()
    await db.refresh(stop)
    return stop


async def reorder_invited_stops(db: AsyncSession, token: str, day_id: str, order: list[str]) -> list[Stop]:
    """受邀者重排某日全部站点顺序（受限编辑，不经 AI 修订）。"""
    trip = await _get_trip_by_edit_token(db, token)
    day = await db.get(TripDay, day_id)
    if day is None or day.trip_id != trip.id:
        from app.core.exceptions import NotFoundError

        raise NotFoundError("日程不存在", code="day_not_found")
    stmt = select(Stop).where(Stop.day_id == day.id).order_by(Stop.order_index)
    stops = list((await db.execute(stmt)).scalars().all())
    if len(order) != len(stops) or set(order) != {s.id for s in stops}:
        from app.core.exceptions import AppError

        raise AppError("顺序列表必须包含该日全部站点", code="stop_order_invalid")
    by_id = {s.id: s for s in stops}
    for idx, stop_id in enumerate(order, start=1):
        by_id[stop_id].order_index = idx
    await db.flush()
    for s in stops:
        await db.refresh(s)
    return [by_id[sid] for sid in order]