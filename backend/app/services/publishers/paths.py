"""发布通道运行时目录（**唯一**的路径解析入口）。

为什么单独抽一层：服务端部署时容器里没有"源码相对布局"的保证，
所有可写目录必须能通过环境变量指到挂载卷。禁止在业务代码里拼
``Path(__file__).parents[...]`` 这类路径——那是把开发机布局写死进项目。

解析规则：
1. 显式目录变量（``XHS_ASSET_DIR`` / ``XHS_SCREENSHOT_DIR`` / ``XHS_STATE_DIR``）优先；
   相对路径按 backend/ 解析，绝对路径原样用（容器里通常给 ``/data/xhs/...``）。
2. 否则回落到 ``XHS_DATA_DIR`` 下的子目录（默认 ``backend/var/xhs``）。
"""
from __future__ import annotations

import os
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parents[3]


def _settings():
    from app.common.config import settings

    return settings


def _resolve(raw: str | None, fallback: Path) -> Path:
    if raw:
        path = Path(os.path.expanduser(str(raw)))
        if not path.is_absolute():
            path = _BACKEND_ROOT / path
    else:
        path = fallback
    path.mkdir(parents=True, exist_ok=True)
    return path


def data_dir() -> Path:
    """数据根目录（默认 ``backend/var/xhs``；容器里建议挂卷 + 设绝对路径）。"""
    settings = _settings()
    raw = getattr(settings, "XHS_DATA_DIR", None) or "var/xhs"
    return _resolve(raw, _BACKEND_ROOT / "var" / "xhs")


def assets_dir() -> Path:
    """发布的图片资产。"""
    settings = _settings()
    return _resolve(getattr(settings, "XHS_ASSET_DIR", None), data_dir() / "assets")


def screenshots_dir() -> Path:
    """发布现场截图（失败取证 / 半自动现场）。"""
    settings = _settings()
    return _resolve(getattr(settings, "XHS_SCREENSHOT_DIR", None), data_dir() / "screenshots")


def states_dir() -> Path:
    """登录态目录（单机/自用模式；多用户走数据库加密存储，不落这里）。"""
    settings = _settings()
    return _resolve(getattr(settings, "XHS_STATE_DIR", None), data_dir() / "states")
