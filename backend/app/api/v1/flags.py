"""前端 feature flag 下发端点（详情页 IA v2 的服务端回滚口）。

契约（``docs/plans/2026-11-08-trip-detail-ia-v2-phase2-closeout.md`` §3.1 A2）：

- **无鉴权**：只回布尔开关，不含任何用户 / 行程维度数据
- ``Cache-Control: public, max-age=60``：开关变更最迟 1 分钟内到达所有前端
- 前端 ``primeFlags()`` 拉取失败静默降级，继续用 URL / localStorage / 内置默认值
- 只下发显式声明的 key：env 为空时返回 ``{}``，前端不会因为「远端没提」而覆盖本地
"""

from __future__ import annotations

from fastapi import APIRouter, Response

from app.services.feature_flags import current_flags, revision_of

router = APIRouter()


@router.get("/flags", summary="前端 feature flag 下发（回滚口）")
async def get_flags(response: Response) -> dict[str, object]:
    """返回当前服务端开关快照。

    ``revision`` 是开关快照的短哈希：前端 / 运维可以据此确认「改 env 后是否真的
    下发到了浏览器」，比肉眼看版面更可靠；没配置开关时为空串。
    """
    flags = current_flags()
    response.headers["Cache-Control"] = "public, max-age=60"
    return {"flags": flags, "revision": revision_of(flags)}
