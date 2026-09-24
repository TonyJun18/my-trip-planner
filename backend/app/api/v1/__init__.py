"""API v1 路由。"""
from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import auth, health, note_import, planner, profile, trips

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(health.router, tags=["health"])
api_router.include_router(trips.router, prefix="/trips", tags=["trips"])
api_router.include_router(note_import.router, tags=["trips"])
api_router.include_router(planner.router, prefix="/planner", tags=["planner"])
api_router.include_router(profile.router, prefix="/profile", tags=["profile"])