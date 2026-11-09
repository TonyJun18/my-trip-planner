"""小红书发布通道单测：策略 / 工厂 / 模板方法 / 资产安全。

不碰网络、不启浏览器：真实编排（校验 → 规范化 → 资产 → 就绪 → 提交 → 收尾）
由 ``FakeDriver`` 驱动完整跑一遍，这是本套设计最关键的收益——
"能不能自动发"可以留到真机验证，"编排对不对"必须在这里锁死。
"""
from __future__ import annotations

import base64
import struct
import zlib

import pytest

from app.common.config import settings
from app.services import xhs_assets
from app.services.publishers import factory
from app.services.publishers.base import (
    BasePublisher,
    PreparedNote,
    PublishError,
    PublishResult,
    Visibility,
    XhsNote,
)
from app.services.publishers.drivers.fake import FakeDriver
from app.services.publishers.manual import ManualPublisher
from app.services.publishers.rpa import RpaPublisher


# ── 测试素材 ────────────────────────────────────────────────
def make_png(width: int = 2, height: int = 2) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + b"\xff\x00\x00" * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def png_data_url(width: int = 2, height: int = 2) -> str:
    return "data:image/png;base64," + base64.b64encode(make_png(width, height)).decode()


@pytest.fixture
def note() -> XhsNote:
    return XhsNote(title="杭州3天2夜攻略", body="西湖骑行 + 灵隐寺 + 龙井茶山。", topics=["杭州", "旅行"])


@pytest.fixture
def png_file(tmp_path):
    path = tmp_path / "cover.png"
    path.write_bytes(make_png())
    return path


@pytest.fixture(autouse=True)
def isolated_asset_dir(tmp_path, monkeypatch):
    """资产不落进仓库 var/，每个测试独立目录。"""
    monkeypatch.setattr(settings, "XHS_ASSET_DIR", str(tmp_path / "assets"))


# ── 工厂（策略切换） ────────────────────────────────────────
def test_factory_default_is_manual(monkeypatch):
    monkeypatch.setattr(settings, "XHS_PUBLISH_MODE", "manual")
    publisher = factory.create()
    assert isinstance(publisher, ManualPublisher)
    assert publisher.mode == "manual"


def test_factory_switches_to_rpa_by_config(monkeypatch):
    monkeypatch.setattr(settings, "XHS_PUBLISH_MODE", "rpa")
    assert isinstance(factory.create(), RpaPublisher)


def test_explicit_mode_overrides_config(monkeypatch):
    monkeypatch.setattr(settings, "XHS_PUBLISH_MODE", "rpa")
    assert factory.create("manual").mode == "manual"


def test_unknown_mode_falls_back_to_manual(monkeypatch):
    monkeypatch.setattr(settings, "XHS_PUBLISH_MODE", "wechat")
    assert factory.create().mode == "manual"


def test_unsupported_channel_raises():
    with pytest.raises(PublishError) as exc:
        factory.create(channel="douyin")
    assert exc.value.reason == "unsupported_channel"


# ── 模板方法：固定编排顺序 ──────────────────────────────────
class RecordingPublisher(BasePublisher):
    mode = "recording"

    def __init__(self) -> None:
        self.calls: list[str] = []

    def _validate(self, note, assets, *, auto_submit):
        self.calls.append("validate")
        super()._validate(note, assets, auto_submit=auto_submit)

    def _prepare(self, note, assets):
        self.calls.append("prepare")
        return super()._prepare(note, assets)

    async def _deliver_assets(self, note: PreparedNote, assets: list[str]) -> list[str]:
        self.calls.append("deliver")
        return await super()._deliver_assets(note, assets)

    async def _check_ready(self, note: PreparedNote, assets: list[str]) -> None:
        self.calls.append("check_ready")
        await super()._check_ready(note, assets)

    async def _submit(
        self,
        note: PreparedNote,
        assets: list[str],
        *,
        auto_submit: bool,
        schedule_at,
        visibility: Visibility,
        is_original: bool,
    ) -> PublishResult:
        self.calls.append("submit")
        return PublishResult(state="ready", submitted=False)

    def _finalize(self, note, assets, result):
        self.calls.append("finalize")
        return super()._finalize(note, assets, result)


async def test_template_method_runs_hooks_in_fixed_order(note):
    publisher = RecordingPublisher()
    result = await publisher.publish_note(note)
    assert publisher.calls == ["validate", "prepare", "deliver", "check_ready", "submit", "finalize"]
    assert result.state == "ready"
    assert result.channel == "xhs"
    assert result.mode == "recording"


# ── 校验（共用口径） ────────────────────────────────────────
@pytest.mark.parametrize(
    ("title", "body", "reason"),
    [
        ("", "正文", "empty_title"),
        ("一" * 21, "正文", "title_too_long"),
        ("标题", "", "empty_body"),
        ("标题", "字" * 1001, "body_too_long"),
    ],
)
async def test_validation_rejects_bad_note(title, body, reason):
    publisher = ManualPublisher()
    with pytest.raises(PublishError) as exc:
        await publisher.publish_note(XhsNote(title=title, body=body))
    assert exc.value.reason == reason


async def test_manual_rejects_auto_submit(note):
    with pytest.raises(PublishError) as exc:
        await ManualPublisher().publish_note(note, auto_submit=True)
    assert exc.value.reason == "auto_submit_unsupported"


async def test_topics_are_normalized(note):
    note.topics = ["#杭州", "杭州", " 旅行 ", "", *[f"tag{i}" for i in range(15)]]
    publisher = RecordingPublisher()
    captured: dict[str, PreparedNote] = {}
    original = publisher._submit

    async def spy(n, a, **kwargs):
        captured["note"] = n
        return await original(n, a, **kwargs)

    publisher._submit = spy  # type: ignore[method-assign]
    await publisher.publish_note(note)
    prepared = captured["note"]
    assert prepared.topics[0] == "杭州"
    assert prepared.topics.count("杭州") == 1
    assert "旅行" in prepared.topics
    assert len(prepared.topics) <= 10


# ── 手动策略 ────────────────────────────────────────────────
async def test_manual_publish_returns_manual_state(note):
    result = await ManualPublisher().publish_note(note)
    assert result.state == "manual"
    assert result.submitted is False
    assert result.ok is False  # 手动通道不算"已发布"
    assert "#杭州" in result.meta["full_text"]


# ── RPA 策略（假驱动） ──────────────────────────────────────
async def test_rpa_requires_images(note):
    with pytest.raises(PublishError) as exc:
        await RpaPublisher(lambda: FakeDriver()).publish_note(note, [])
    assert exc.value.reason == "no_images"


async def test_rpa_missing_asset_file(note, tmp_path):
    publisher = RpaPublisher(lambda: FakeDriver())
    with pytest.raises(PublishError) as exc:
        await publisher.publish_note(note, [str(tmp_path / "nope.png")])
    assert exc.value.reason == "asset_missing"


async def test_rpa_rejects_non_ascii_path(note, tmp_path):
    path = tmp_path / "封面.png"
    path.write_bytes(make_png())
    with pytest.raises(PublishError) as exc:
        await RpaPublisher(lambda: FakeDriver()).publish_note(note, [str(path)])
    assert exc.value.reason == "asset_path_not_ascii"


async def test_rpa_semi_auto_fills_form_and_keeps_window(note, png_file, monkeypatch):
    monkeypatch.setattr(settings, "XHS_RPA_KEEP_OPEN", True)
    driver = FakeDriver()
    result = await RpaPublisher(lambda: driver).publish_note(note, [str(png_file)])

    assert result.state == "ready"
    assert result.submitted is False
    assert result.ok is True  # 半自动"填好等点发布"算完成自动化该做的部分
    assert driver.calls == ["open", "is_logged_in", "fill_form", "screenshot", "close"]
    assert driver.form is not None
    assert driver.form.title == note.title
    assert driver.form.image_paths == [str(png_file)]
    assert driver.kept_open is True


async def test_rpa_auto_submit_returns_published(note, png_file):
    driver = FakeDriver(note_url="https://www.xiaohongshu.com/explore/abc123")
    result = await RpaPublisher(lambda: driver).publish_note(
        note, [str(png_file)], auto_submit=True
    )

    assert result.state == "published"
    assert result.submitted is True
    assert result.note_url == "https://www.xiaohongshu.com/explore/abc123"
    assert "submit" in driver.calls
    assert driver.kept_open is False


async def test_rpa_auto_submit_without_receipt_is_unknown(note, png_file):
    driver = FakeDriver(submit_state="unknown")
    result = await RpaPublisher(lambda: driver).publish_note(
        note, [str(png_file)], auto_submit=True
    )
    assert result.state == "unknown"
    assert result.submitted is True
    assert result.note_url is None  # 不编造链接


async def test_rpa_login_required(note, png_file):
    driver = FakeDriver(logged_in=False)
    with pytest.raises(PublishError) as exc:
        await RpaPublisher(lambda: driver).publish_note(note, [str(png_file)])
    assert exc.value.reason == "login_required"
    assert driver.closed is True
    assert "fill_form" not in driver.calls


async def test_rpa_fill_failure_is_wrapped(note, png_file):
    driver = FakeDriver(fail_in="fill")
    with pytest.raises(PublishError) as exc:
        await RpaPublisher(lambda: driver).publish_note(note, [str(png_file)])
    assert exc.value.reason == "submit_failed"
    assert driver.closed is True


# ── 资产：落盘 / 解析 / 越权 ────────────────────────────────
def test_save_image_parses_dimensions():
    ref = xhs_assets.save_image("trip-abc-123", png_data_url(3, 4))
    assert ref.path.is_file()
    assert (ref.width, ref.height) == (3, 4)
    assert ref.mime == "image/png"
    assert ref.path.name.isascii()


def test_decode_rejects_unsupported_mime():
    with pytest.raises(PublishError) as exc:
        xhs_assets.decode_data_url("data:image/gif;base64,R0lGODlhAQABAAAAACw=")
    assert exc.value.reason == "bad_asset_mime"


def test_decode_rejects_mime_spoof():
    """声明 PNG 但内容不是 PNG → 拦住（不信客户端）。"""
    bogus = base64.b64encode(b"not-a-png-at-all").decode()
    with pytest.raises(PublishError) as exc:
        xhs_assets.decode_data_url(f"data:image/png;base64,{bogus}")
    assert exc.value.reason == "bad_asset_mime"


def test_decode_rejects_oversize(monkeypatch):
    monkeypatch.setattr(settings, "XHS_ASSET_MAX_BYTES", 10)
    with pytest.raises(PublishError) as exc:
        xhs_assets.decode_data_url(png_data_url())
    assert exc.value.reason == "asset_too_large"


def test_resolve_blocks_traversal():
    with pytest.raises(PublishError):
        xhs_assets.resolve_asset("trip-abc-123", "../../etc/passwd")


def test_resolve_blocks_cross_trip_access():
    ref = xhs_assets.save_image("trip-aaaa-111", png_data_url())
    with pytest.raises(PublishError) as exc:
        xhs_assets.resolve_asset("trip-bbbb-222", ref.asset_id)
    assert exc.value.reason == "asset_forbidden"
