"""社交收藏导入 API：粘贴社交分享文本（caption + 链接）→ 地点候选。

与 note/email/link/screenshot 导入为姊妹接口（输入四通道之外的新通道）：
- POST /trips/note/import       —— 粘贴攻略/种草文本 → 站点候选
- POST /trips/screenshot/import —— 上传截图 → OCR → 站点候选
- POST /trips/email/import      —— 粘贴预订确认邮件 → 预订条目 + 候选
- POST /trips/link/import       —— 粘贴公开分享链接 → 提取（失败降级链接收藏）
- POST /trips/social/import     —— 粘贴社交分享文本 → 地点候选（本模块）

设计（task-social-collection-eval，Feedtrip 2026 新赛道启发）：
- 纯规则解析（app.services.social_import.parse_social），不依赖 LLM、不抓 URL，
  零凭证：不接 TikTok/IG/小红书 API、不碰反爬，用户自己粘贴 caption 文本；
- 外部内容当敌意源：指令型行被标记剥离（flagged_lines），不进候选，
  绝不把文本当指令执行；输出经 Pydantic schema 强校验；
- 候选复用 note-import 结构：前端可「勾选并入行程」。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.database import get_session
from app.models import User
from app.schemas.social_import import (
    SocialCandidateOut,
    SocialFlaggedLineOut,
    SocialImportRequest,
    SocialImportResultOut,
)
from app.services.social_import import parse_social

router = APIRouter()


@router.post(
    "/trips/social/import",
    response_model=SocialImportResultOut,
    summary="粘贴社交分享文本（caption+链接），解析为地点候选（外部内容按敌意输入处理）",
)
async def import_social(
    data: SocialImportRequest,
    _: User = Depends(get_current_user),
    __: AsyncSession = Depends(get_session),
) -> SocialImportResultOut:
    """把用户粘贴的社交分享文本解析为地点候选。

    - 纯规则解析，无 LLM 调用、无外部 API、不抓 URL（无成本、无密钥、零凭证）；
    - 输入按敌意内容处理：指令型行被标记剥离（flagged_lines），不进候选；
    - 返回地点候选清单（可勾选并入行程）与来源平台；
    - 需要登录（与行程管理一致）；text 超长（>20000 字符）由请求校验 422 拒绝。
    """
    result = parse_social(data.text)
    return SocialImportResultOut(
        candidates=[
            SocialCandidateOut(
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
            SocialFlaggedLineOut(
                line_number=f.line_number,
                content=f.content,
                reason=f.reason,
            )
            for f in result.flagged_lines
        ],
        dropped_lines=result.dropped_lines,
        source_platform=result.source_platform,
    )