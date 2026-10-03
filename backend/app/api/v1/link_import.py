"""链接导入 API：粘贴公开分享链接 → 提取结构化信息（外部内容按敌意输入处理）。

与 note_import / screenshot_import / email_import 姊妹接口：
- POST /trips/note/import       —— 粘贴文本
- POST /trips/screenshot/import —— 上传截图（OCR）
- POST /trips/email/import      —— 粘贴预订邮件
- POST /trips/link/import       —— 粘贴公开分享链接（本模块）

实现注意：
- 纯服务层（app.services.link_import）：stdlib urllib 抓取 + note-import 管线
  解析，无第三方依赖、无 API key；测试用 monkeypatch 注入假 fetch（零网络）；
- URL 校验（scheme / 长度 / 内网主机）在服务层完成，非法 → 422 结构化错误；
- 抓取/解析失败 → **静默降级为链接收藏**（200 + extracted=false + 平台标题），
  与验收「失败静默降级」一致，不打断用户流程；
- 登录必需（与行程管理一致）。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.core.auth import get_current_user
from app.models import User
from app.schemas.link_import import LinkImportRequest, LinkImportResultOut
from app.services import link_import as li
from app.services.link_import import LinkImportError, parse_link

router = APIRouter()


@router.post(
    "/trips/link/import",
    response_model=LinkImportResultOut,
    summary="粘贴公开分享链接，提取站点候选或降级为链接收藏（外部内容按敌意输入处理）",
)
async def import_link(
    data: LinkImportRequest,
    _: User = Depends(get_current_user),
) -> LinkImportResultOut:
    """把用户粘贴的公开分享链接（小红书/马蜂窝/携程等）解析为可勾选的站点候选。

    - 服务层抓取页面 → 提取 og:title/og:description → note_import 管线解析候选；
    - URL 非法（scheme/长度/内网主机）→ 422 结构化错误；
    - 抓取失败 / 无 meta / 反爬壳 → 200 + extracted=false（链接收藏降级）；
    - 候选输出经 schema 强校验，外部内容只作为数据，绝不作为指令。
    """
    try:
        result = parse_link(data.url)
    except LinkImportError as exc:
        raise HTTPException(status_code=422, detail=f"{exc.code}: {exc.message}") from exc

    return LinkImportResultOut(
        url=result.url,
        title=result.title,
        platform=result.platform,
        extracted=result.extracted,
        description=result.description,
        candidates=[
            {
                "name": c.name,
                "stop_type": c.stop_type,
                "description": c.description,
                "estimated_cost": c.estimated_cost,
                "estimated_duration_minutes": c.estimated_duration_minutes,
                "source_lines": c.source_lines,
            }
            for c in result.candidates
        ],
    )