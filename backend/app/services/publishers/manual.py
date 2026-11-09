"""手动发布策略（方案 A，默认通道：复制文案 → 小红书 App 粘贴）。

保留它的理由：
1. 零依赖、零风控，是自动化通道挂掉时的**兜底降级**目标；
2. 作为「策略」之一证明通道可插拔——工厂切一行配置就能换回来。
"""
from __future__ import annotations

from datetime import datetime

from app.services.publishers.base import (
    BasePublisher,
    PreparedNote,
    PublishResult,
    Visibility,
)


class ManualPublisher(BasePublisher):
    """手动通道：不在服务端做任何投递，返回可复制的完整文案。"""

    mode = "manual"
    requires_images = False
    supports_auto_submit = False
    hint = "复制文案 + 导出封面图，在小红书 App 里粘贴发布（零依赖、零风控）"

    async def _submit(
        self,
        note: PreparedNote,
        assets: list[str],
        *,
        auto_submit: bool,
        schedule_at: datetime | None,
        visibility: Visibility,
        is_original: bool,
    ) -> PublishResult:
        full_text = note.body + (f"\n\n{note.tags_line}" if note.topics else "")
        return PublishResult(
            state="manual",
            submitted=False,
            message="手动模式：请复制文案并在小红书 App 内粘贴发布",
            meta={"full_text": full_text, "hint_key": "xhsNote.publishManualHint"},
        )
