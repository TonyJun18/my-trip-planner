"""小红书发布用图片资产：base64 落盘 + 安全校验。

为什么需要它：封面卡是**前端** html2canvas 渲染的，而发布通道要的是
"服务端能读到的一个文件"（RPA 喂给 file input）。所以前端把 canvas
转 dataURL 传上来，这里落盘成 ASCII 文件名，供发布任务引用。

安全边界（都是硬规则）：
- 只收 png / jpeg / webp，用**magic bytes** 校验，不信客户端声明的 mime；
- 解码后大小上限（默认 8MB），防内存打爆；
- 文件名由服务端生成（`{trip前缀}-{uuid}.{ext}`），**永不使用客户端文件名**；
- 读取时校验 asset_id 归属当前行程前缀，阻断目录穿越与跨行程访问。
"""
from __future__ import annotations

import base64
import binascii
import logging
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

from app.services.publishers.base import PublishError

logger = logging.getLogger(__name__)

_ASSET_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{3,80}$")
_DATA_URL_RE = re.compile(r"^data:(?P<mime>[\w/+.-]+);base64,(?P<payload>.+)$", re.DOTALL)

_MAGIC = {
    "image/png": (b"\x89PNG\r\n\x1a\n", "png"),
    "image/jpeg": (b"\xff\xd8\xff", "jpg"),
    "image/webp": (b"RIFF", "webp"),
}
_MIME_ALIASES = {"image/jpg": "image/jpeg"}
_EXT_MIME = {"png": "image/png", "jpg": "image/jpeg", "webp": "image/webp"}


@dataclass
class AssetRef:
    asset_id: str
    path: Path
    mime: str
    bytes: int
    width: int | None
    height: int | None

    @property
    def rel_name(self) -> str:
        return self.path.name


def asset_dir() -> Path:
    """资产目录（统一由 ``publishers.paths`` 解析，不在业务层拼路径）。"""
    from app.services.publishers import paths

    return paths.assets_dir()


def max_bytes() -> int:
    from app.common.config import settings

    return int(getattr(settings, "XHS_ASSET_MAX_BYTES", 8 * 1024 * 1024))


# ── 解析与校验 ──────────────────────────────────────────────
def decode_data_url(data_url: str) -> tuple[str, bytes]:
    """拆 data URL → (mime, bytes)，并做 mime/magic/size 校验。"""
    match = _DATA_URL_RE.match((data_url or "").strip())
    if not match:
        raise PublishError("bad_asset", "图片格式不合法（需要 data:image/*;base64,...）")
    declared = match.group("mime").lower()
    declared = _MIME_ALIASES.get(declared, declared)
    if declared not in _MAGIC:
        raise PublishError(
            "bad_asset_mime", f"只支持 PNG / JPEG / WebP（收到 {declared}）"
        )
    try:
        raw = base64.b64decode(match.group("payload"), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise PublishError("bad_asset", f"base64 解码失败：{exc}") from exc

    if not raw:
        raise PublishError("bad_asset", "图片内容为空")
    limit = max_bytes()
    if len(raw) > limit:
        raise PublishError(
            "asset_too_large", f"图片超过 {limit // (1024 * 1024)}MB 上限（{len(raw)} 字节）"
        )
    signature, _ext = _MAGIC[declared]
    if not raw.startswith(signature):
        raise PublishError("bad_asset_mime", "文件内容与声明的图片格式不符")
    if declared == "image/webp" and raw[8:12] != b"WEBP":
        raise PublishError("bad_asset_mime", "WebP 容器标记缺失")
    return declared, raw


def image_size(data: bytes, mime: str) -> tuple[int | None, int | None]:
    """零依赖读宽高（PNG IHDR / JPEG SOFn / WebP VP8X）。读不到返回 (None, None)。"""
    try:
        if mime == "image/png" and data[12:16] == b"IHDR":
            return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
        if mime == "image/jpeg":
            i = 2
            while i < len(data) - 9:
                if data[i] != 0xFF:
                    i += 1
                    continue
                marker = data[i + 1]
                if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB):
                    height = int.from_bytes(data[i + 5 : i + 7], "big")
                    width = int.from_bytes(data[i + 7 : i + 9], "big")
                    return width, height
                seg_len = int.from_bytes(data[i + 2 : i + 4], "big")
                i += 2 + max(seg_len, 2)
            return None, None
        if mime == "image/webp" and data[12:16] == b"VP8X":
            width = 1 + int.from_bytes(data[24:27], "little")
            height = 1 + int.from_bytes(data[27:30], "little")
            return width, height
    except Exception:  # noqa: BLE001 — 解析失败不影响发布，只少一个宽高信息
        logger.debug("图片宽高解析失败 mime=%s", mime)
    return None, None


# ── 落盘 / 读取 ────────────────────────────────────────────
def _trip_prefix(trip_id: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]", "", (trip_id or "").lower())
    if not cleaned:
        raise PublishError("bad_asset", "行程 id 非法，无法生成资产名")
    return cleaned[:8]


def save_image(trip_id: str, data_url: str) -> AssetRef:
    """保存一张 data URL 图片，返回资产引用。"""
    mime, raw = decode_data_url(data_url)
    ext = _MAGIC[mime][1]
    prefix = _trip_prefix(trip_id)
    asset_id = f"{prefix}-{uuid.uuid4().hex[:10]}-{int.from_bytes(raw[:2], 'big'):04x}"
    path = asset_dir() / f"{asset_id}.{ext}"
    path.write_bytes(raw)
    width, height = image_size(raw, mime)
    logger.info(
        "xhs asset 已保存 trip=%s asset=%s bytes=%s size=%sx%s", trip_id, asset_id, len(raw), width, height
    )
    return AssetRef(
        asset_id=asset_id, path=path, mime=mime, bytes=len(raw), width=width, height=height
    )


def resolve_asset(trip_id: str, asset_id: str) -> Path:
    """按 asset_id 取回文件（校验归属 + 阻断穿越）。"""
    if not _ASSET_ID_RE.match(asset_id or ""):
        raise PublishError("bad_asset", "资产 id 非法")
    prefix = _trip_prefix(trip_id)
    if not asset_id.startswith(f"{prefix}-"):
        raise PublishError("asset_forbidden", "该图片不属于当前行程")
    base = asset_dir()
    for ext in ("png", "jpg", "webp"):
        candidate = (base / f"{asset_id}.{ext}").resolve()
        if candidate.is_file() and candidate.parent == base.resolve():
            return candidate
    raise PublishError("asset_missing", f"图片不存在：{asset_id}")


def asset_url(trip_id: str, asset_id: str) -> str:
    return f"/api/v1/trips/{trip_id}/xhs-assets/{asset_id}"
