"""本机发布器策略（方案 B）：服务端只下发任务，账号凭证不出用户浏览器。

与 `rpa` 的区别：
- `rpa`：服务器起浏览器，用（单机/托管）登录态填表 → 需要代持凭证、吃服务器内存；
- `agent`：服务器只建任务；用户自己浏览器里的扩展领任务、填表、点发布 → 零凭证。

本类存在的意义是"通道可插拔 + 能力可描述"：前端通过 `/xhs-channels` 拿到
`mode=agent` 就知道该提示"装发布助手"，而不是显示一个点不动的按钮。
真正投递不经过这里（`_submit` 显式抛错），由 `xhs_agent_service` + 扩展完成。
"""
from __future__ import annotations

import os
from datetime import datetime

from app.services.publishers.base import (
    BasePublisher,
    PreparedNote,
    PublishError,
    PublishResult,
    Visibility,
)


class AgentPublisher(BasePublisher):
    """外部发布器通道（浏览器扩展领取任务）。"""

    mode = "agent"
    requires_images = True
    supports_auto_submit = False
    external_agent = True
    hint = "任务下发到你自己浏览器里的发布助手：服务器不接触你的账号，填好后由你点发布"

    async def _deliver_assets(self, note: PreparedNote, assets: list[str]) -> list[str]:
        """图片必须是服务端已落盘的文件（扩展通过鉴权接口取回）。"""
        resolved: list[str] = []
        for raw in assets:
            path = os.path.abspath(os.path.expanduser(raw))
            if not os.path.isfile(path):
                raise PublishError("asset_missing", f"图片文件不存在：{path}")
            resolved.append(path)
        return resolved

    async def _submit(
        self,
        note: PreparedNote,
        assets: list[str],
        *,
        auto_submit: bool,
        schedule_at: datetime | None,
        visibility: Visibility,
        is_original: bool,
    ) -> PublishResult:  # pragma: no cover - 正常路径由 API 分支处理
        raise PublishError(
            "agent_required",
            "agent 通道由用户浏览器里的发布助手执行，不经过服务端任务执行器",
        )
