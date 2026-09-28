"""分享令牌生命周期服务：过期 / 吊销 / 最近使用审计 + 收藏灵感夹。

设计目标（task-share-token-lifecycle，需求文档「匿名令牌协作」局限的补齐）：
- 与 trips.share_token / trips.edit_token 旧列并存：旧列承载「当前生效令牌」，
  本表承载「过期 / 吊销 / 最近使用」等生命周期元数据。
- 旧数据零迁移：trips 列已有 token 但 share_tokens 无记录 → 按永久、未吊销、
  免审计兼容（legacy=True）。
- 读取侧统一门禁：expired（expires_at 非空且已过）或 revoked（revoked_at 非空）
  的令牌即时失效（HTTP 410 / 403），且只在「有生命周期记录」时执行——
  旧 token 不受影响（兼容）。
- 审计：每次成功访问更新 last_used_at（尽力而为，不阻断读取）；
  owner 通过 lifecycle 端点查看过期/吊销/最近使用状态。
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import GoneError, NotFoundError, PermissionDeniedError
from app.models import ShareToken, Trip, TripFavorite, User
from app.services import trip_service


# ── 生命周期辅助 ─────────────────────────────────────────────
def _is_token_expired(rec: ShareToken, *, now: datetime | None = None) -> bool:
    """是否已过期：expires_at 非空且已过。"""
    if rec.expires_at is None:
        return False
    return rec.expires_at <= (now or datetime.now(UTC))


def _is_token_revoked(rec: ShareToken) -> bool:
    """是否已吊销：revoked_at 非空。"""
    return rec.revoked_at is not None


def _is_token_active(rec: ShareToken, *, now: datetime | None = None) -> bool:
    """令牌是否仍有效（未过期且未吊销）。"""
    return not _is_token_expired(rec, now=now) and not _is_token_revoked(rec)


# ── upsert：为 trips 列上的现有令牌登记生命周期记录（幂等） ─────
async def _upsert_share_token(
    db: AsyncSession,
    *,
    trip_id: str,
    token: str | None,
    kind: str,
) -> ShareToken | None:
    """为某个生效令牌登记生命周期记录；token 为空则 no-op。

    - 已存在（同 trip+kind+token）→ 复用（幂等，不重置 expires/revoked）
    - 不存在 → 新建（永久、未吊销）
    """
    if not token:
        return None
    stmt = select(ShareToken).where(
        ShareToken.trip_id == trip_id,
        ShareToken.kind == kind,
        ShareToken.token == token,
    )
    rec = (await db.execute(stmt)).scalar_one_or_none()
    if rec is not None:
        return rec
    rec = ShareToken(trip_id=trip_id, token=token, kind=kind)
    db.add(rec)
    await db.flush()
    return rec


async def ensure_share_token_record(db: AsyncSession, trip: Trip, kind: str = "share") -> ShareToken | None:
    """确保 trips 列上的现有令牌有生命周期记录（读取侧自动 upsert，幂等）。

    旧数据（无记录）→ 首次访问自动登记为永久有效，之后才能执行过期/吊销。
    """
    token = trip.share_token if kind == "share" else trip.edit_token
    return await _upsert_share_token(db, trip_id=trip.id, token=token, kind=kind)


# ── 读取侧门禁：由 trip_service 的公开读取端点调用 ────────────
def raise_if_token_inactive(rec: ShareToken | None, *, now: datetime | None = None) -> None:
    """生命周期门禁：有记录且失效 → 抛异常。

    - rec 为 None（旧令牌无记录）→ 兼容放行
    - 已过期 → 410（Gone，前端可提示「分享已过期」）
    - 已吊销 → 403（Forbidden，前端可提示「链接已被分享者收回」）
    """
    if rec is None:
        return
    if _is_token_expired(rec, now=now):
        raise GoneError("分享链接已过期", code="share_token_expired")
    if _is_token_revoked(rec):
        raise PermissionDeniedError("分享链接已被分享者收回", code="share_token_revoked")


async def touch_token_usage(db: AsyncSession, rec: ShareToken | None) -> None:
    """审计：最近一次成功访问。尽力而为，失败不阻断读取。"""
    if rec is None:
        return
    try:
        rec.last_used_at = datetime.now(UTC)
        await db.flush()
    except Exception:  # noqa: BLE001 — 审计写失败不影响主流程
        await db.rollback()


# ── owner 管理 API ───────────────────────────────────────────
async def _lifecycle_for_token(
    db: AsyncSession,
    trip: Trip,
    kind: str,
    *,
    base_url: str,
) -> dict[str, Any]:
    """查询某个令牌（share/edit）的生命周期状态（owner 视角）。"""
    token = trip.share_token if kind == "share" else trip.edit_token
    if not token:
        raise NotFoundError(
            "该行程还没有开放分享" if kind == "share" else "该行程还没有开放受邀编辑",
            code="share_token_not_found" if kind == "share" else "edit_token_not_found",
        )
    rec = await _upsert_share_token(db, trip_id=trip.id, token=token, kind=kind)
    if rec is None:  # 理论不可达（token 非空必 upsert），窄化给类型检查器
        raise NotFoundError("分享链接无效", code="share_token_not_found")
    share_url = None
    if kind == "share":
        share_url = f"{base_url.rstrip('/')}/share/{token}"
    return {
        "trip_id": trip.id,
        "kind": kind,
        "token": token,
        "share_url": share_url,
        "expires_at": rec.expires_at,
        "revoked_at": rec.revoked_at,
        "created_at": rec.created_at,
        "last_used_at": rec.last_used_at,
        "legacy": False,
    }


async def get_share_lifecycle(
    db: AsyncSession,
    trip: Trip,
    *,
    base_url: str,
) -> list[dict[str, Any]]:
    """owner 查看该行程 share + edit 两个令牌的生命周期状态。

    未开放的令牌（无 token）跳过——只展示已生成的链接，避免整端点 404。
    """
    items: list[dict[str, Any]] = []
    for kind in ("share", "edit"):
        try:
            items.append(await _lifecycle_for_token(db, trip, kind, base_url=base_url))
        except NotFoundError:
            continue
    return items


async def revoke_token(
    db: AsyncSession,
    trip: Trip,
    *,
    kind: str,
    owner: str | None = None,
) -> None:
    """吊销某个令牌（share/edit）。幂等：已吊销/无令牌均为 no-op。

    吊销 = 设置 revoked_at（保留记录用于审计，不清 token 列）→ 读取侧立即失效。
    """
    await trip_service._load_trip(db, trip.id, owner=owner)  # owner 隔离校验
    token = trip.share_token if kind == "share" else trip.edit_token
    if not token:
        raise NotFoundError(
            "该行程还没有开放分享" if kind == "share" else "该行程还没有开放受邀编辑",
            code="share_token_not_found" if kind == "share" else "edit_token_not_found",
        )
    rec = await _upsert_share_token(db, trip_id=trip.id, token=token, kind=kind)
    if rec is not None:
        rec.revoked_at = datetime.now(UTC)
        await db.flush()


async def set_token_ttl(
    db: AsyncSession,
    trip: Trip,
    *,
    kind: str,
    days: int,
    owner: str | None = None,
) -> dict[str, Any]:
    """设置令牌有效期（TTL）：days=0 永久，否则按 now + days 计算 expires_at。

    - 幂等：重复设置覆盖旧值（上次设置的过期时间被新值替换）
    - 与吊销正交：吊销后仍可设置 TTL（记录保留），但读取侧仍被 revoked 拦截
    """
    await trip_service._load_trip(db, trip.id, owner=owner)
    token = trip.share_token if kind == "share" else trip.edit_token
    if not token:
        raise NotFoundError(
            "该行程还没有开放分享" if kind == "share" else "该行程还没有开放受邀编辑",
            code="share_token_not_found" if kind == "share" else "edit_token_not_found",
        )
    rec = await _upsert_share_token(db, trip_id=trip.id, token=token, kind=kind)
    if rec is None:  # 理论不可达
        raise NotFoundError("分享链接无效", code="share_token_not_found")
    rec.expires_at = None if days == 0 else datetime.now(UTC).replace(microsecond=0) + timedelta(days=days)
    await db.flush()
    return {
        "trip_id": trip.id,
        "kind": kind,
        "expires_at": rec.expires_at,
        "revoked_at": rec.revoked_at,
    }


# ── 收藏灵感夹 ───────────────────────────────────────────────
async def _favorite_trip_for_user(
    db: AsyncSession,
    trip: Trip,
    user: User,
) -> TripFavorite:
    """收藏一条行程（幂等：已收藏返回已有记录）。"""
    stmt = select(TripFavorite).where(
        TripFavorite.user_id == user.id,
        TripFavorite.trip_id == trip.id,
    )
    fav = (await db.execute(stmt)).scalar_one_or_none()
    if fav is not None:
        return fav
    fav = TripFavorite(user_id=user.id, trip_id=trip.id)
    db.add(fav)
    await db.flush()
    return fav


async def add_favorite(db: AsyncSession, trip_id: str, user: User) -> TripFavorite:
    """收藏指定行程（登录用户，收藏的是只读引用，不复制行程）。"""
    trip = await db.get(Trip, trip_id)
    if trip is None:
        raise NotFoundError("行程不存在", code="trip_not_found")
    return await _favorite_trip_for_user(db, trip, user)


async def remove_favorite(db: AsyncSession, trip_id: str, user: User) -> None:
    """取消收藏（幂等：未收藏为 no-op）。"""
    stmt = select(TripFavorite).where(
        TripFavorite.user_id == user.id,
        TripFavorite.trip_id == trip_id,
    )
    fav = (await db.execute(stmt)).scalar_one_or_none()
    if fav is not None:
        await db.delete(fav)
        await db.flush()


async def list_favorites(db: AsyncSession, user: User) -> list[TripFavorite]:
    """当前用户的收藏列表（按收藏时间倒序）。"""
    stmt = (
        select(TripFavorite)
        .where(TripFavorite.user_id == user.id)
        .order_by(TripFavorite.created_at.desc())
    )
    return list((await db.execute(stmt)).scalars().all())


async def favorite_ids(db: AsyncSession, user: User, trip_ids: list[str]) -> set[str]:
    """批量查询某批行程中哪些已被当前用户收藏（列表页状态）。"""
    if not trip_ids:
        return set()
    stmt = select(TripFavorite.trip_id).where(
        TripFavorite.user_id == user.id,
        TripFavorite.trip_id.in_(trip_ids),
    )
    return set((await db.execute(stmt)).scalars().all())