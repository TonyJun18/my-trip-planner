"""API v1 路由。"""
from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import auth, email_import, health, link_import, map_edit, note_import, plan_b, planner, profile, screenshot_import, trips, ws

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(health.router, tags=["health"])
api_router.include_router(trips.router, prefix="/trips", tags=["trips"])
api_router.include_router(note_import.router, tags=["trips"])
api_router.include_router(screenshot_import.router, tags=["trips"])
api_router.include_router(email_import.router, tags=["trips"])
api_router.include_router(link_import.router, tags=["trips"])
api_router.include_router(map_edit.router, tags=["trips"])
api_router.include_router(plan_b.router, tags=["trips"])
api_router.include_router(planner.router, prefix="/planner", tags=["planner"])
api_router.include_router(ws.router, tags=["ws"])  # WebSocket 端点（prefix 在 ws.py 内）
api_router.include_router(profile.router, prefix="/profile", tags=["profile"])