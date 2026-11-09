"""API v1 路由。"""
from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import (
    analytics,
    auth,
    chat,
    email_import,
    expenses,
    export,
    flags,
    health,
    inspiration,
    link_import,
    map_edit,
    note_import,
    plan_b,
    planner,
    profile,
    reorder_commit,
    screenshot_import,
    social_import,
    trips_bookings,
    trips_crud,
    trips_escalations,
    trips_favorites,
    trips_gallery,
    trips_journey,
    trips_passport,
    trips_ratings,
    trips_share,
    trips_story,
    xhs_agent,
)

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(health.router, tags=["health"])
# 前端 feature flag 下发（服务端回滚口）：无鉴权、只回布尔，见 api/v1/flags.py
api_router.include_router(flags.router, tags=["flags"])
# inspiration 先于 trips 注册：/trips/inspiration 是字面量路径，
# 若排在 trips_* 之后会被 GET /{trip_id} 吞掉（trip_id="inspiration" → 404）
api_router.include_router(inspiration.router, prefix="/trips", tags=["trips"])
# trips 域按子域拆分为 5 个 router，注册顺序即路由匹配优先级：
# 1) 字面量段优先：/share /edit （trips_share 前半）、/gallery、/escalations、/favorites
# 2) 动态段兜底：/{trip_id}（trips_crud）
# 3) trips_share 后半（/{trip_id}/share/*、/edit/{token}/live）与 crud 互补不冲突
api_router.include_router(trips_share.router, prefix="/trips", tags=["trips"])
api_router.include_router(trips_gallery.router, prefix="/trips", tags=["trips"])
# ratings：/ratings/summary 是字面量段，必须先于 trips_crud 的 /{trip_id} 注册
# （否则 "ratings" 会被当作 trip_id 吞掉；/gallery 同因）
api_router.include_router(trips_ratings.router, prefix="/trips", tags=["trips"])
api_router.include_router(trips_favorites.router, prefix="/trips", tags=["trips"])
api_router.include_router(trips_escalations.router, prefix="/trips", tags=["trips"])
api_router.include_router(trips_crud.router, prefix="/trips", tags=["trips"])
# reorder-commit：三段字面量路径（/trips/{trip_id}/reorder-commit），与 crud 的
# 二段 /{trip_id} 不冲突；自带 /trips 前缀，注册时不加 prefix。
api_router.include_router(reorder_commit.router, tags=["trips"])
# export 路由（/trips/{trip_id}/export 与 /trips/share/{token}/export）：
# 声明在 trips 之后即可，段数不同不冲突；字面量 /share/ 由 trips_share 先注册，
# /share/{token}/export 多一段，Starlette 按精确段匹配互不吞并。
api_router.include_router(export.router, prefix="/trips", tags=["trips"])
api_router.include_router(note_import.router, tags=["trips"])
api_router.include_router(screenshot_import.router, tags=["trips"])
api_router.include_router(email_import.router, tags=["trips"])
api_router.include_router(link_import.router, tags=["trips"])
api_router.include_router(expenses.router, prefix="/trips", tags=["trips"])
api_router.include_router(trips_bookings.router, prefix="/trips", tags=["trips"])
api_router.include_router(trips_journey.router, prefix="/trips", tags=["trips"])
api_router.include_router(trips_passport.router, prefix="/trips", tags=["trips"])
api_router.include_router(trips_story.router, prefix="/trips", tags=["trips"])
api_router.include_router(social_import.router, tags=["trips"])
api_router.include_router(map_edit.router, tags=["trips"])
api_router.include_router(plan_b.router, tags=["trips"])
api_router.include_router(planner.router, prefix="/planner", tags=["planner"])
# ⚠️ ws.router 不在这里挂：WebSocket 契约是根路径 /ws/*（README / nginx `location /ws/` /
# vite proxy / 前端 WS_BASE 全部按此假设）。并进 api_router 会让真实路径变成
# /api/v1/ws/*，前端握手一律 403、实时推送静默退化为轮询（2026-11-08 实测发现）。
# 现由 app/main.py 在根路径单独 include。
api_router.include_router(profile.router, prefix="/profile", tags=["profile"])
# 小红书本机发布器（浏览器扩展）：服务端只下发任务与选择器，零账号凭证
api_router.include_router(xhs_agent.router, prefix="/xhs/agent", tags=["xhs-agent"])
api_router.include_router(analytics.router, prefix="/analytics", tags=["analytics"])
# 对话式行程助手（B 期）：会话/消息 REST + WS 流式
# chat.router 内部已带 prefix="/chat"（含 WS 端点 /ws/chat/...），这里不再重复前缀
api_router.include_router(chat.router, tags=["chat"])