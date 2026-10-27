"""API v1 路由。"""
from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import auth, email_import, export, health, inspiration, link_import, map_edit, note_import, plan_b, planner, profile, screenshot_import, trips, ws

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(health.router, tags=["health"])
# inspiration 先于 trips 注册：/trips/inspiration 是字面量路径，
# 若排在 trips.router 之后会被 GET /{trip_id} 吞掉（trip_id="inspiration" → 404）
api_router.include_router(inspiration.router, prefix="/trips", tags=["trips"])
api_router.include_router(trips.router, prefix="/trips", tags=["trips"])
# export 路由（/trips/{trip_id}/export 与 /trips/share/{token}/export）：
# 声明在 trips 之后即可，段数不同不冲突；字面量 /share/ 由 trips.py 先注册，
# /share/{token}/export 多一段，Starlette 按精确段匹配互不吞并。
api_router.include_router(export.router, prefix="/trips", tags=["trips"])
api_router.include_router(note_import.router, tags=["trips"])
api_router.include_router(screenshot_import.router, tags=["trips"])
api_router.include_router(email_import.router, tags=["trips"])
api_router.include_router(link_import.router, tags=["trips"])
api_router.include_router(map_edit.router, tags=["trips"])
api_router.include_router(plan_b.router, tags=["trips"])
api_router.include_router(planner.router, prefix="/planner", tags=["planner"])
api_router.include_router(ws.router, tags=["ws"])  # WebSocket 端点（prefix 在 ws.py 内）
api_router.include_router(profile.router, prefix="/profile", tags=["profile"])