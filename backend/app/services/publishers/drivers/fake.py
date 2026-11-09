"""假驱动：不碰网络/浏览器的发布驱动（测试与「演练模式」共用）。

为什么要有它：
- 让「策略 + 模板方法 + 工厂」的编排逻辑可以被**真实执行**地单测，
  不需要 Playwright、不需要登录态、不产生副作用；
- 演练模式（``XHS_PUBLISH_MODE=rpa`` + 假驱动）可以在不碰小红书的情况下
  跑通「上传图片 → 建任务 → 填表单 → ready」的整条链路。
"""
from __future__ import annotations

from pathlib import Path

from app.services.publishers.drivers.protocol import DriverOutcome, DriverState, PublishForm


class FakeDriver:
    """记录所有调用的内存驱动。"""

    name = "fake"

    def __init__(
        self,
        *,
        logged_in: bool = True,
        submit_state: DriverState = "published",
        note_url: str | None = "https://www.xiaohongshu.com/explore/fake-note-1",
        fail_in: str = "",
        screenshot_path: str | None = None,
    ) -> None:
        self.logged_in = logged_in
        self.submit_state = submit_state
        self.note_url = note_url
        # fail_in ∈ {"open","fill","submit"}：模拟对应阶段抛错
        self.fail_in = fail_in
        self._screenshot_path = screenshot_path
        self.calls: list[str] = []
        self.form: PublishForm | None = None
        self.closed = False
        self.kept_open = False

    async def open(self) -> None:
        self.calls.append("open")
        if self.fail_in == "open":
            raise RuntimeError("fake driver: open failed")

    async def is_logged_in(self) -> bool:
        self.calls.append("is_logged_in")
        return self.logged_in

    async def fill_form(self, form: PublishForm) -> None:
        self.calls.append("fill_form")
        if self.fail_in == "fill":
            raise RuntimeError("fake driver: fill failed")
        self.form = form

    async def submit(self) -> DriverOutcome:
        self.calls.append("submit")
        if self.fail_in == "submit":
            raise RuntimeError("fake driver: submit failed")
        state = self.submit_state  # type: ignore[assignment]
        return DriverOutcome(
            state=state,
            submitted=True,
            note_url=self.note_url if state == "published" else None,
            screenshot=self._screenshot_path,
            message=None if state == "published" else "点了发布但未读到回执",
        )

    async def screenshot(self) -> str | None:
        self.calls.append("screenshot")
        return self._screenshot_path

    async def close(self, *, keep_open: bool = False) -> None:
        self.calls.append("close")
        self.closed = True
        self.kept_open = keep_open


def fake_screenshot(tmp_path: Path | None = None) -> str | None:
    """给测试用的截图路径（不需要真文件）。"""
    if tmp_path is None:
        return "fake://screenshot.png"
    return str(tmp_path / "shot.png")
