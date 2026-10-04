"""邮件导入 API：粘贴预订确认邮件 → 结构化预订条目 + 站点候选。

与 note_import 姊妹接口：
- POST /trips/note/import       —— 粘贴攻略/种草文本 → 站点候选
- POST /trips/screenshot/import —— 上传截图 → OCR → 站点候选
- POST /trips/email/import      —— 粘贴预订确认邮件 → 预订条目 + 候选

设计：
- 纯规则解析（app.services.email_import.parse_email），不依赖 LLM/邮箱协议，
  零凭证：不接 Gmail OAuth、不连邮件服务器，用户自己粘贴邮件文本；
- 外部内容当敌意源：指令型行被标记剥离（flagged_lines），不进条目/候选，
  绝不把文本当指令执行；输出经 Pydantic schema 强校验；
- 金额字段（amount + currency）由前端并入预算视图（post-booking 整理最小版）。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.database import get_session
from app.models import User
from app.schemas.email_import import (
    EmailBookingOut,
    EmailFlaggedLineOut,
    EmailImportRequest,
    EmailImportResultOut,
)
from app.services.email_import import parse_email
from app.services.note_import import NoteStopCandidate

router = APIRouter()


def _to_candidate_dict(c: NoteStopCandidate) -> dict:
    """候选转 dict（与 note-import 的 NoteStopCandidateOut 同构）。"""
    return {
        "name": c.name,
        "stop_type": c.stop_type,
        "description": c.description,
        "estimated_cost": c.estimated_cost,
        "estimated_duration_minutes": c.estimated_duration_minutes,
        "source_lines": c.source_lines,
    }


@router.post(
    "/trips/email/import",
    response_model=EmailImportResultOut,
    summary="粘贴预订确认邮件，解析为预订条目 + 站点候选（外部内容按敌意输入处理）",
)
async def import_email(
    data: EmailImportRequest,
    _: User = Depends(get_current_user),
    __: AsyncSession = Depends(get_session),
) -> EmailImportResultOut:
    """把用户粘贴的预订确认邮件解析为结构化预订条目与可勾选候选。

    - 纯规则解析，无 LLM 调用、无外部 API（无成本、无密钥、零凭证）；
    - 输入按敌意内容处理：指令型行被标记剥离（flagged_lines），不进条目/候选；
    - 返回预订条目（航班/酒店/活动，含确认码/日期/金额）与候选清单；
    - 需要登录（与行程管理一致）；text 超长（>20000 字符）由请求校验 422 拒绝。
    """
    result = parse_email(data.text)
    return EmailImportResultOut(
        bookings=[
            EmailBookingOut(
                kind=b.kind,
                name=b.name,
                code=b.code,
                datetime=b.datetime,
                amount=b.amount,
                currency=b.currency,
                source_lines=b.source_lines,
            )
            for b in result.bookings
        ],
        candidates=[_to_candidate_dict(c) for c in result.candidates],
        flagged_lines=[
            EmailFlaggedLineOut(
                line_number=f.line_number,
                content=f.content,
                reason=f.reason,
            )
            for f in result.flagged_lines
        ],
        dropped_lines=result.dropped_lines,
    )