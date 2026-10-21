"""公开分享链接导入：粘贴小红书/马蜂窝/携程等分享链接 → 提取结构化信息。

定位：task-screenshot-import（验收升级）——TripNoted 1.0.20 social link→Idea→
start trips 启发；截图 OCR 仍是主路径，链接提取是「社交分享链接」可选分支。
用户粘贴一个公开分享链接，系统尝试提取页面标题/描述 → 复用 note-import 管线
得到可勾选的站点候选；提取失败（网络受限/平台反爬/无 meta）→ **静默降级为
链接收藏**（返回 extracted=false + 平台默认标题），不中断用户流程。

设计决策（零第三方依赖、测试零网络）：
- 抓取：stdlib urllib（无 requests/bs4 依赖），模块级 ``fetch_page`` 可被
  测试 monkeypatch 注入假响应；超时 8s、响应体上限 200KB；
- 安全边界（外部内容当敌意源 + SSRF 最小防护）：
  * 只允许 http/https scheme（拒绝 file/javascript/data 等）；
  * 拒绝明显内网/回环主机名段（localhost/127./10./192.168./172.16-31./
    169.254./::1），防止把服务端当跳板打内网；
  * 提取只读 og:title/og:description/<title> 纯文本，经 schema 强校验
    截断长度，绝不把抓取内容当指令执行；
- 站点候选：标题+描述（+深度正文，P1-5）喂给 note_import.parse_note——敌意输入
  剥离、类型/价格/时长推断全复用，同一输入同一输出；
- 深度抽取（task-link-import-zh-eval）：马蜂窝/穷游/携程/去哪儿/大众点评等中文
  攻略页额外抽取「POI 链接锚文本 + 正文块文本」→ 结构化候选（对齐圆周旅迹
  攻略转行程的核心场景）；小红书反爬壳页面无正文，明确不尝试深度抽取（保持
  og:meta 降级，不回退已可用能力）；
- 降级链：URL 非法 → 结构化错误（4xx）；抓取/解析失败 → 静默降级为
  链接收藏（200 + extracted=false），与验收「失败静默降级」一致。
"""
from __future__ import annotations

import html
import logging
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Callable

from app.services.note_import import NoteStopCandidate, parse_note

logger = logging.getLogger(__name__)

# 抓取超时（秒）与响应体上限（字节）：社交分享页通常 <100KB，200KB 足够防拖垮。
FETCH_TIMEOUT_SECONDS = 8
MAX_RESPONSE_BYTES = 200 * 1024
# 输入上限（与 schema 对齐）。
MAX_URL_LENGTH = 2048

# 平台识别表（hostname 子串 → slug / 展示名）。
_PLATFORM_RULES: list[tuple[re.Pattern, str, str]] = [
    (re.compile(r"xiaohongshu\.com|xhslink\.com"), "xiaohongshu", "小红书"),
    (re.compile(r"mafengwo\.(cn|com)"), "mafengwo", "马蜂窝"),
    (re.compile(r"qyer\.com"), "qyer", "穷游"),
    (re.compile(r"ctrip\.com|trip\.com"), "ctrip", "携程"),
    (re.compile(r"qunar\.com"), "qunar", "去哪儿"),
    (re.compile(r"dianping\.com"), "dianping", "大众点评"),
    (re.compile(r"tripadvisor\."), "tripadvisor", "Tripadvisor"),
    (re.compile(r"weibo\.com|weibo\.cn"), "weibo", "微博"),
    (re.compile(r"bilibili\.com|b23\.tv"), "bilibili", "B站"),
]

# ── 深度抽取平台（task-link-import-zh-eval）─────────────────────
# 圆周旅迹核心能力 = 粘贴中文攻略链接 → 景点结构化（85%+ 解析率）。
# 我们零凭证路线：抓正文 + POI 链接文本 → note_import.parse_note（敌意剥离复用）。
# 小红书反爬大概率挡（实测返回壳页面/空正文）→ 明确不尝试深度抽取，保持现有
# og:meta 降级（链接收藏），不回退已可用能力。
_DEEP_EXTRACT_PLATFORMS = {"mafengwo", "qyer", "ctrip", "qunar", "dianping", "generic"}
# 深度抽取正文长度上限（字符）：喂给 parse_note，防超长页面。
_DEEP_TEXT_MAX_CHARS = 6000

# 正文块标签 → 换行（保留段落/列表结构，供 parse_note 按行抽取候选）。
_BLOCK_TAG_RE = re.compile(
    r"</?(?:p|div|li|ul|ol|br|h[1-6]|section|article|td|tr)[^>]*>",
    re.IGNORECASE,
)
# POI 链接：马蜂窝/携程等的景点详情链接，锚文本即景点名（最高置信信号）。
_POI_LINK_RE = re.compile(
    r'<a[^>]+href="[^"]*(?:/poi/|/sight/|/attraction/|/scenery/|/destination/)[^"]*"[^>]*>'
    r"([^<]{2,%d})</a>" % 60,
    re.IGNORECASE,
)
# script/style 块整体丢弃（避免 JS 文本污染候选）。
_SCRIPT_STYLE_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
# HTML 标签通用剥离。
_TAG_RE = re.compile(r"<[^>]+>")
# 连续空白/换行归一。
_BLANK_RE = re.compile(r"[ \t\r\f\v]+")

# SSRF 最小防护：明显内网/回环主机名段（白名单式保守拒绝，不求完整覆盖）。
_SSRF_HOST_RE = re.compile(
    r"^(localhost|127(?:\.\d{1,3}){3}|10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2}|"
    r"169\.254(?:\.\d{1,3}){2}|172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2}|::1|0\.0\.0\.0)$",
    re.IGNORECASE,
)

# og meta 标签提取：<meta property="og:title" content="..."> / <meta name="description" ...>
_OG_TITLE_RE = re.compile(
    r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']*)["\']',
    re.IGNORECASE,
)
_OG_DESC_RE = re.compile(
    r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']*)["\']',
    re.IGNORECASE,
)
_META_DESC_RE = re.compile(
    r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']*)["\']',
    re.IGNORECASE,
)
_TITLE_RE = re.compile(r"<title[^>]*>([^<]*)</title>", re.IGNORECASE)

# 候选描述来源文本长度上限（防超长 meta 撑爆 parse_note）；
# P1-5 深度抽取后正文更长（POI 链接 + 段落），放宽到 8k（parse_note 上限 20k）。
_FEED_MAX_CHARS = 8000


class LinkImportError(Exception):
    """链接导入可预期失败（URL 非法 / scheme 不允许 / 内网主机 / 超长）。

    携带结构化信息（code + message），API 层转为 4xx，不 panic。
    """

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class LinkImportResult:
    """链接导入结果。

    - extracted=True：页面抓取成功且提取到标题/描述，candidates 为解析出的站点候选；
    - extracted=False：链接合法但提取失败 → 静默降级为链接收藏（title=平台默认），
      candidates 恒为空。
    """

    url: str
    title: str
    platform: str
    extracted: bool = False
    description: str = ""
    candidates: list[NoteStopCandidate] = field(default_factory=list)


def detect_platform(url: str) -> tuple[str, str]:
    """按 hostname 识别平台 slug 与展示名（未知 → generic/网页）。"""
    host = urllib.parse.urlparse(url).netloc.lower()
    for pat, slug, name in _PLATFORM_RULES:
        if pat.search(host):
            return slug, name
    return "generic", "网页"


def validate_url(url: str) -> str:
    """URL 合法性校验（安全边界）：

    - 长度上限（防超大粘贴）；
    - 必须能解析出 host；
    - 只允许 http/https scheme（拒绝 file/javascript/data 等）；
    - 拒绝明显内网/回环主机名段（SSRF 最小防护）。
    通过则返回原样 URL；不通过抛 LinkImportError(code, message)。
    """
    if not url or not url.strip():
        raise LinkImportError("invalid_url", "链接为空")
    url = url.strip()
    if len(url) > MAX_URL_LENGTH:
        raise LinkImportError("url_too_long", f"链接超过长度上限（{MAX_URL_LENGTH} 字符）")
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise LinkImportError(
            "unsupported_scheme",
            f"仅支持 http/https 链接（收到：{parsed.scheme or '无'}）",
        )
    host = (parsed.hostname or "").lower()
    if not host:
        raise LinkImportError("invalid_url", "链接缺少主机名")
    if _SSRF_HOST_RE.match(host):
        raise LinkImportError("blocked_host", "不允许抓取内网/回环地址")
    return url


def fetch_page(url: str, timeout: int = FETCH_TIMEOUT_SECONDS) -> str:
    """抓取页面 HTML（stdlib urllib）。可被测试 monkeypatch 替换（零网络）。

    失败（DNS/连接/超时/HTTP 错误/响应超限）→ 抛 LinkImportError("fetch_failed")，
    由上层降级为链接收藏。注意：真实抓取依赖网络，测试一律注入假 fetch。

    SSRF 重定向防御：http(s) 服务端默认跟随 3xx 重定向。初始 URL 已通过
    ``validate_url`` 的 hostname 白名单，但**重定向目标不可信**——恶意目标可以
    301 到内网/metadata 地址（169.254.169.254 等）。这里用自定义
    ``_SafeRedirectHandler`` 对**每一次**跳转目标递归执行同样的安全校验。
    """
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
            ),
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        },
    )
    try:
        opener = urllib.request.build_opener(_SafeRedirectHandler())
        with opener.open(req, timeout=timeout) as resp:
            body = resp.read(MAX_RESPONSE_BYTES + 1)
            if len(body) > MAX_RESPONSE_BYTES:
                raise LinkImportError("fetch_failed", "页面响应超过大小上限")
            return body.decode("utf-8", errors="replace")
    except LinkImportError:
        raise
    except Exception as exc:  # noqa: BLE001 - 抓取失败统一降级
        raise LinkImportError("fetch_failed", f"抓取失败：{exc}") from exc


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """重定向处理器：对每个跳转目标递归执行 validate_url（同一套 SSRF 防护）。

    防御场景：攻击者提供一个公网 URL，其 301/302 指向内网（http://169.254.169.254/...）
    或 metadata 服务。urllib 默认跟随重定向且不会再次校验 hostname → 服务端被
    变成内网探测跳板。本处理器在每次跳转前调用 validate_url，非法目标直接抛
    LinkImportError（由 fetch_page 转成 fetch_failed 降级）。
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_url(newurl)  # 抛 LinkImportError 即拒绝跟随
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _extract_meta(html_text: str) -> tuple[str, str]:
    """从 HTML 提取 (title, description)：og:title/og:description → <title>/meta description。"""
    title = ""
    m = _OG_TITLE_RE.search(html_text)
    if m:
        title = m.group(1)
    if not title:
        m = _TITLE_RE.search(html_text)
        if m:
            title = m.group(1)
    desc = ""
    m = _OG_DESC_RE.search(html_text)
    if m:
        desc = m.group(1)
    if not desc:
        m = _META_DESC_RE.search(html_text)
        if m:
            desc = m.group(1)
    title = html.unescape(title).strip()
    desc = html.unescape(desc).strip()
    # 标题里塞了站点名（「标题 - 小红书」）剥掉最右侧分隔尾。
    if re.search(r"\s+[-|–—]\s+", title):
        title = re.split(r"\s+[-|–—]\s+", title, maxsplit=1)[0].strip()
    return title, desc


def _extract_deep_text(html_text: str) -> str:
    """从攻略页正文深度抽取候选文本（task-link-import-zh-eval）。

    两步（纯 std-lib，零依赖）：
    1. **POI 链接锚文本**：`<a href="/poi/...">景点名</a>`（马蜂窝/携程/穷游等的
       景点详情链接）→ 最高置信信号，转成 `📍 名称` 行供 parse_note 识别；
    2. **正文块文本**：块级标签（p/li/h1-h6/br…）转行、剥离 script/style 与其余
       标签、反转义 HTML 实体 → 保留段落/列表结构，让 parse_note 按行抽取
       「推荐/打卡/必去」等标记行。

    小红书不在深度抽取范围（反爬壳页面无正文），保持 og:meta 降级路径。
    """
    body = _SCRIPT_STYLE_RE.sub(" ", html_text)
    # 1) POI 链接锚文本
    poi_names: list[str] = []
    for m in _POI_LINK_RE.finditer(body):
        name = html.unescape(m.group(1)).strip()
        if 2 <= len(name) <= 60 and name not in poi_names:
            poi_names.append(name)
    # 2) 块标签转行 + 剥离其余标签
    text = _BLOCK_TAG_RE.sub("\n", body)
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)
    lines: list[str] = []
    for ln in text.splitlines():
        ln = _BLANK_RE.sub(" ", ln).strip()
        if len(ln) >= 2:
            lines.append(ln)
    body_text = "\n".join(lines)
    poi_block = "\n".join(f"📍 {n}" for n in poi_names)
    combined = f"{poi_block}\n{body_text}" if poi_block else body_text
    return combined[:_DEEP_TEXT_MAX_CHARS]


def parse_link(url: str, fetch: Callable[[str], str] | None = None) -> LinkImportResult:
    """主入口：公开分享链接 → 提取结构化信息（成功）或静默降级为链接收藏。

    - validate_url 不通过 → 抛 LinkImportError（4xx）；
    - fetch 失败 / 无 meta / 解析无候选 → 返回 extracted=False 的链接收藏，
      不抛错（静默降级语义）；
    - 提取成功 → 标题/描述喂给 note_import.parse_note（敌意剥离全复用），
      输出站点候选。
    """
    url = validate_url(url)
    platform, platform_name = detect_platform(url)
    fetcher = fetch or fetch_page

    try:
        html_text = fetcher(url)
    except LinkImportError as exc:
        # 抓取失败 → 静默降级为链接收藏（不把网络错误抛给用户）。
        logger.info("link_import fetch degraded: %s (%s)", url, exc.code)
        return LinkImportResult(url=url, title=platform_name, platform=platform, extracted=False)

    title, description = _extract_meta(html_text)
    if not title:
        # 无 meta / 反爬壳页面 → 链接收藏降级。
        return LinkImportResult(url=url, title=platform_name, platform=platform, extracted=False)

    # 提取成功：把标题+描述（+深度正文，任务 P1-5）喂给 note-import 管线
    # （敌意输入剥离 / 类型推断复用）。
    feed_parts: list[str] = [title, description]
    if platform in _DEEP_EXTRACT_PLATFORMS:
        deep_text = _extract_deep_text(html_text)
        if deep_text:
            feed_parts.append(deep_text)
    feed_text = "\n".join(p for p in feed_parts if p)[: _FEED_MAX_CHARS]
    note_result = parse_note(feed_text)

    return LinkImportResult(
        url=url,
        title=title[:120],
        platform=platform,
        extracted=True,
        description=description[:300],
        candidates=note_result.candidates,
    )