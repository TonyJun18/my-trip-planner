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

import hashlib
import hmac
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import GoneError, NotFoundError, PermissionDeniedError
from app.core.security import _jwt_secret, hash_password, verify_password
from app.models import ShareToken, Trip, TripFavorite, User
from app.services import trip_service


# ── 访问密码（task-share-gate-eval）─────────────────────────────
# 门禁读取侧通过 X-Share-Password header 提供；验证通过后可用
# X-Share-Gate 短期免验凭证（默认 12h）避免重复输密码。
GATE_TTL_SECONDS = 12 * 3600


def _sign_gate(token: str, kind: str, exp: int) -> str:
    """HMAC 签名免验凭证：exp.sig.token.kind（sig=HMAC-SHA256(secret, token|kind|exp)）。"""
    secret = str(_jwt_secret()).encode("utf-8")
    payload = f"{token}|{kind}|{exp}".encode("utf-8")
    sig = hmac.new(secret, payload, hashlib.sha256).hexdigest()
    return f"{exp}.{sig}.{token}.{kind}"


def issue_gate_token(token: str, kind: str) -> str:
    """签发短期免验凭证（过期时间戳 + HMAC 签名）。"""
    exp = int(datetime.now(UTC).timestamp()) + GATE_TTL_SECONDS
    return _sign_gate(token, kind, exp)


def _verify_gate_token(gate_token: str | None, token: str, kind: str) -> bool:
    """校验免验凭证：签名一致 + 未过期 + token/kind 匹配。"""
    if not gate_token:
        return False
    try:
        exp_s, sig, tok, k = gate_token.split(".", 3)
        if tok != token or k != kind:
            return False
        exp = int(exp_s)
        if exp < int(datetime.now(UTC).timestamp()):
            return False
        return hmac.compare_digest(_sign_gate(tok, k, exp), gate_token)
    except (ValueError, TypeError):
        return False


def verify_token_access(
    rec: ShareToken | None,
    *,
    password: str | None = None,
    gate_token: str | None = None,
) -> None:
    """访问密码门禁：有密码且未验明 → 403 share_password_required。

    - rec 为 None（无生命周期记录）→ 兼容放行
    - 无密码（password_hash 空）→ 放行（旧数据与未设密码链接完全兼容）
    - 提供正确 X-Share-Password 或有效 X-Share-Gate 免验凭证 → 放行
    - 其余 → 403（前端据此弹密码框）
    """
    if rec is None or not rec.password_hash:
        return
    if gate_token and _verify_gate_token(gate_token, rec.token, rec.kind):
        return
    if password and verify_password(password, rec.password_hash):
        return
    raise PermissionDeniedError("该分享链接受密码保护，请提供访问密码", code="share_password_required")


async def set_token_password(
    db: AsyncSession,
    trip: Trip,
    *,
    kind: str,
    password: str,
    owner: str | None = None,
) -> dict[str, Any]:
    """设置 / 清除分享令牌访问密码（owner 专属）。

    - password 非空 → 覆盖设置新密码（PBKDF2 哈希，与登录密码同格式）
    - password 空串 → 清除密码（取消保护，幂等）
    - 与 TTL/吊销正交：密码保护、过期、吊销三套门禁独立叠加
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
    rec.password_hash = hash_password(password) if password else None
    await db.flush()
    return {"trip_id": trip.id, "kind": kind, "has_password": bool(rec.password_hash)}


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
        "has_password": bool(rec.password_hash),
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