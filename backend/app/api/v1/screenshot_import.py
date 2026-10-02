"""截图导入 API：上传攻略截图 base64 → OCR → 站点候选（外部内容按敌意输入处理）。

与 note_import 姊妹接口：
- POST /trips/note/import     —— 粘贴文本
- POST /trips/screenshot/import —— 上传截图（base64，OCR 后走同一解析管线）

实现注意：
- 无 python-multipart 依赖（venv 未装），请求体用原始 bytes + 手动 base64 解码，
  响应复用 note_import 的 schema（NoteImportResultOut）；
- OCR 工具使用 macOS 系统 Vision framework（离线、无 key），失败按结构化
  ScreenshotImportError 转 4xx，绝不静默吞错；
- 校验：登录必需；base64 可解码；大小上限 20MB；解码失败/OCR 失败 → 4xx。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.database import get_session
from app.models import User
from app.schemas.note_import import (
    NoteFlaggedLineOut,
    NoteImportResultOut,
    NoteStopCandidateOut,
)
from app.services import screenshot_import as si
from app.services.screenshot_import import ScreenshotImportError, parse_screenshot_b64

router = APIRouter()


@router.post(
    "/trips/screenshot/import",
    response_model=NoteImportResultOut,
    summary="上传攻略截图，OCR 提取站点候选（外部内容按敌意输入处理）",
)
async def import_screenshot(
    request: Request,
    _: User = Depends(get_current_user),
    __: AsyncSession = Depends(get_session),
) -> NoteImportResultOut:
    """上传一张攻略截图（PNG/JPEG 等，body 为图片原始字节），返回站点候选。

    - 请求体 = 图片二进制（不要求 multipart，无 python-multipart 依赖）；
    - 服务层 OCR（macOS Vision，离线）→ note_import.parse_note 结构化提取；
    - 指令型/注入内容被标记剥离（flagged_lines），不进候选；
    - 失败路径：空 body / 超过 20MB / OCR 工具不可用 / OCR 失败 → 4xx 结构化错误。
    """
    image_bytes = await request.body()
    if not image_bytes:
        raise HTTPException(status_code=400, detail="请求体为空：请上传图片二进制内容")
    if len(image_bytes) > si.MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"图片超过大小上限（{si.MAX_IMAGE_BYTES} 字节）",
        )

    import base64

    try:
        result = parse_screenshot_b64(base64.b64encode(image_bytes).decode("ascii"))
    except ScreenshotImportError as exc:
        raise HTTPException(status_code=422, detail=f"{exc.code}: {exc.message}") from exc

    return NoteImportResultOut(
        candidates=[
            NoteStopCandidateOut(
                name=c.name,
                stop_type=c.stop_type,
                description=c.description,
                estimated_cost=c.estimated_cost,
                estimated_duration_minutes=c.estimated_duration_minutes,
                source_lines=c.source_lines,
            )
            for c in result.candidates
        ],
        flagged_lines=[
            NoteFlaggedLineOut(line_number=f.line_number, content=f.content, reason=f.reason)
            for f in result.flagged_lines
        ],
        dropped_lines=result.dropped_lines,
    )