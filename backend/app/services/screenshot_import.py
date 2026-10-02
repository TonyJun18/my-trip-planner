"""截图导入行程：上传攻略截图 → OCR 提取文本 → 复用 note-import 管线解析站点候选。

定位：task-note-import（粘贴文本）的姊妹范式——AiGo screenshot-to-itinerary /
去哪儿小红书图片导入验证的国内刚需。用户上传一张攻略截图（小红书/携程/马蜂窝
笔记截图），即可得到可勾选的站点候选清单，勾选后并入行程（复用现有
POST /trips/days/{day_id}/stops）。

设计决策（零外部依赖、无网络、无 API key）：
- OCR 引擎：macOS 系统 Vision framework（zh-Hans + en-US 离线识别），
  经编译好的命令行工具 `backend/bin/ocr_vision` 调用（源码 `backend/scripts/ocr_vision.swift`，
  新环境用 `swiftc -O scripts/ocr_vision.swift -o bin/ocr_vision` 编译）；
- 结构化提取：OCR 文本直接喂给 note_import.parse_note——敌意输入剥离、
  站点类型推断、价格/时长提取、去重全部复用，同一输入同一输出；
- 降级链：OCR 工具缺失/编译失败 → 返回 `ocr_error`（结构化错误，不崩溃）；
  图片无法解码 → 同上；OCR 无文本 → 空候选 + 提示；
- 外部内容当敌意源：截图是「不可信输入」，OCR 只做文本提取，
  指令型内容由 parse_note 标记剥离，绝不把图片里的文字当指令执行。
"""
from __future__ import annotations

import base64
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass, field

from app.services.note_import import NoteStopCandidate, NoteImportResult, parse_note

logger = logging.getLogger(__name__)

# 上传图片上限（原始字节）。攻略截图通常 <5MB；20MB 上限足够且防超大上传。
MAX_IMAGE_BYTES = 20 * 1024 * 1024
# OCR 超时（秒）。Vision accurate 识别一张截图一般 <5s，30s 足够防卡死。
OCR_TIMEOUT_SECONDS = 30

# OCR 工具路径：优先环境变量（测试注入 mock 用），否则包内默认路径。
OCR_TOOL_ENV = "MY_TRIP_OCR_TOOL"
_DEFAULT_OCR_TOOL = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "bin",
    "ocr_vision",
)


class ScreenshotImportError(Exception):
    """截图导入可预期失败（图片无效 / OCR 不可用 / OCR 失败）。

    携带结构化信息（code + message），API 层转为 4xx 响应，不 panic。
    """

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class ScreenshotImportResult:
    """截图导入结果：OCR 文本 + 解析出的候选（与 note-import 同构）。"""

    candidates: list[NoteStopCandidate] = field(default_factory=list)
    flagged_lines: list = field(default_factory=list)
    dropped_lines: int = 0
    ocr_text: str = ""
    ocr_notice: str | None = None  # 降级提示（如 OCR 为空文本）


def get_ocr_tool() -> str:
    """返回 OCR 工具绝对路径（环境变量优先，测试注入 mock 用）。"""
    return os.getenv(OCR_TOOL_ENV, _DEFAULT_OCR_TOOL)


def ocr_image(image_bytes: bytes) -> str:
    """把图片字节交给 OCR 工具，返回识别文本（按行拼接）。

    - 空图片 → ScreenshotImportError("empty_image")
    - 工具不存在/不可执行 → ScreenshotImportError("ocr_unavailable")
    - 工具非零退出（图片无法解码 / OCR 失败）→ ScreenshotImportError("ocr_failed")
    - 超时 → ScreenshotImportError("ocr_timeout")
    """
    if not image_bytes:
        raise ScreenshotImportError("empty_image", "图片内容为空")

    tool = get_ocr_tool()
    if not tool or not os.path.isfile(tool) or not os.access(tool, os.X_OK):
        raise ScreenshotImportError(
            "ocr_unavailable",
            f"OCR 工具不可用（{tool}）。请先编译：swiftc -O scripts/ocr_vision.swift -o bin/ocr_vision",
        )

    # 写临时文件（Vision framework 按路径解码，不走 stdin）→ /tmp，不残留业务目录
    tmp_path = f"/tmp/my_trip_ocr_{os.getpid()}.png"
    try:
        with open(tmp_path, "wb") as f:
            f.write(image_bytes)
        proc = subprocess.run(
            [tool, tmp_path],
            capture_output=True,
            timeout=OCR_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise ScreenshotImportError("ocr_timeout", "OCR 识别超时") from exc
    except OSError as exc:
        raise ScreenshotImportError("ocr_failed", f"OCR 执行失败：{exc}") from exc
    finally:
        # 临时文件清理：用 os.remove（我们刚创建的 /tmp 文件，非递归、非批量）
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", errors="replace").strip() or "未知错误"
        raise ScreenshotImportError("ocr_failed", f"OCR 识别失败：{err[:200]}")

    return proc.stdout.decode("utf-8", errors="replace").strip()


def parse_screenshot(image_bytes: bytes) -> ScreenshotImportResult:
    """主入口：图片字节 → OCR → parse_note 解析候选。

    - OCR 失败 → 抛 ScreenshotImportError（API 层转 4xx）
    - OCR 空文本 → 空候选 + ocr_notice 提示
    - 候选解析复用 note_import.parse_note（敌意输入剥离 / 类型 / 价格 / 时长全复用）
    """
    text = ocr_image(image_bytes)
    result: NoteImportResult = parse_note(text)

    notice: str | None = None
    if not text.strip():
        notice = "图片中未识别到文字，请换一张更清晰的截图"

    return ScreenshotImportResult(
        candidates=result.candidates,
        flagged_lines=result.flagged_lines,
        dropped_lines=result.dropped_lines,
        ocr_text=text[:2000],
        ocr_notice=notice,
    )


def parse_screenshot_b64(image_b64: str) -> ScreenshotImportResult:
    """base64 版入口（测试与 API 共用；base64 解码失败按敌意输入处理→结构化错误）。"""
    try:
        image_bytes = base64.b64decode(image_b64, validate=True)
    except Exception as exc:
        raise ScreenshotImportError("invalid_image", "图片 base64 解码失败") from exc
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise ScreenshotImportError("image_too_large", f"图片超过大小上限（{MAX_IMAGE_BYTES} 字节）")
    return parse_screenshot(image_bytes)