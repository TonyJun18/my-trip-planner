"""笔记导入 API：粘贴攻略/种草文本 → 结构化站点候选（外部内容按敌意输入处理）。

不依赖真实 LLM、不消耗 API key：纯规则解析（app.services.note_import），
候选落库复用现有 POST /trips/days/{day_id}/stops（前端勾选后调用）。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.database import get_session
from app.models import User
from app.schemas.note_import import (
    NoteFlaggedLineOut,
    NoteImportRequest,
    NoteImportResultOut,
    NoteStopCandidateOut,
)
from app.services.note_import import parse_note

router = APIRouter()


@router.post(
    "/trips/note/import",
    response_model=NoteImportResultOut,
    summary="粘贴攻略/种草笔记，解析为站点候选（外部内容按敌意输入处理）",
)
async def import_note(
    data: NoteImportRequest,
    _: User = Depends(get_current_user),
    __: AsyncSession = Depends(get_session),
) -> NoteImportResultOut:
    """把用户粘贴的笔记/种草文本解析为可勾选的站点候选。

    - 纯规则解析，无 LLM 调用、无外部 API（无成本、无密钥）；
    - 输入按敌意内容处理：指令型行被标记剥离（flagged_lines），不进候选；
    - 返回候选清单，前端勾选后通过现有 POST /trips/days/{day_id}/stops 落库；
    - 需要登录（与行程管理一致）。
    """
    result = parse_note(data.text)
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