"""社交收藏导入：把用户粘贴的社交分享文本（caption + 链接）解析为地点候选。

定位：task-social-collection-eval（候选评估）——Feedtrip 2026 新赛道
（TikTok/IG 分享 → 地图 → 行程，视频删除仍保留）启发；小红书/IG/TikTok
分享页反爬大概率挡（link_import 深度抽取明确不碰），所以走「零凭证粘贴版」：
分享时系统让你复制链接/文案，用户把 caption（或 文案+链接）粘贴进来，
规则提取地点候选（与 email-import 零凭证粘贴版同构）。

验收（docs/night-build-todo.md 2026-10-23）：
1. 粘贴分享文本（caption+链接）→ 规则提取地点候选
2. 不抓 URL 不碰反爬：只处理用户粘贴的文本
3. 恶意注入文本按敌意输入处理（flagged_lines 剥离，不进候选）
4. 候选复用 note-import 结构可勾选并入行程
5. 可行则最小版 + 测试，否则降级（链接收藏已兜底）
6. API 层 POST /api/v1/trips/social/import（登录必需，超长 422）

设计决策（本文件为纯函数、零外部依赖）：
- 不用 LLM、不抓 URL：本地规则解析 caption/散文中的地点候选，无延迟无成本
  无 API key；不碰反爬（小红书/IG/TikTok 分享页是壳，抓也白抓）；
- 外部内容当敌意源：粘贴文本视同「不可信输入」，指令型行被标记剥离
  （复用 note_import 的 _INJECTION_RE 特征库），绝不把文本当指令执行；
- 确定性：同一输入永远得到同一输出，便于测试与回归；
- 候选结构复用 note_import.NoteStopCandidate：可直接「勾选并入行程」
  （前端复用现有 POST /days/{day_id}/stops）。

与 note_import 的区别（为什么不自接复用 parse_note）：
- note_import 面向「攻略笔记」：行首序号/POI 标记强，散文弱；
- social caption 是「口语化短文本 + 标签 + emoji + 链接」：行特征稀疏、
  常一整句话里带多个地点（「这家店太绝了！XX咖啡 和 YY餐厅 都在这条街上」），
  需要额外处理：标签（#西山#）、emoji 分隔、顿号列举、视频文案语气词
  （绝了/也太好吃了/谁懂啊）、以及「划掉/追评」等口语噪声。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from app.services.note_import import (
    MAX_CANDIDATES,
    FlaggedLine,
    NoteStopCandidate,
    _INJECTION_RE,
)

# 输入上限（字符）。短视频 caption 通常 <2k，20k 足够；防超大粘贴拖垮 worker。
MAX_TEXT_LENGTH = 20_000
# 候选名称长度上限（与 NoteStopCandidate 对齐，避免长句当站名）。
MAX_NAME_LENGTH = 40
# 描述长度上限。
MAX_DESC_LENGTH = 200

# ── 社交 caption 特有启发规则（规则库，全部本地、确定性） ─────────
# 通用 URL：caption 里常带分享链接/地图链接。只识别（剥除文本、识别平台），
# 绝不抓取。字符类排除中文标点与空格，但保留半角 ? 以完整剥掉 query 参数。
_URL_RE = re.compile(r"https?://[^\s，。；;！？、<>\"']+", re.IGNORECASE)
# 平台链接特征（用于识别来源平台，不抓取）。
_PLATFORM_URL_RE = re.compile(
    r"tiktok\.com|instagram\.com|xiaohongshu\.com|xhslink\.com|"
    r"douyin\.com|v\.douyin\.com|weibo\.com|bilibili\.com|b23\.tv",
    re.IGNORECASE,
)
# 标签：#杭州美食 #西山步道 之类。
_TAG_RE = re.compile(r"#[^\s#，。；;！!？?、]+")
# 口语噪声：谁懂啊/也太好吃了/绝了/yyds/家人们/姐妹们/狠狠/冲/码住/收藏/(狗头)
# 以及社交 caption 高频语气与口水词（这店/这家/都去了/去了两次…）。
_NOISE_RE = re.compile(
    r"谁懂啊|太好吃了|也太|太绝了|绝了|yyds|YYDS|家人们|姐妹们|狠狠|冲就完了|"
    r"码住|先收藏|收藏了|狗头|手动狗头|划重点|听劝|避雷|种草|拔草|真的会谢|"
    r"一整个|直接封神|天花板|宝藏|小众|本地人|攻略|打卡|必去|必吃|必逛|必玩|"
    r"推荐|强推|安利|不允许|错过|后悔|满足|幸福感|氛围感|仪式感|出片|太好拍|"
    r"巨出片|这家店|这家餐厅|那家店|那家|都去了|去了两次|真的吗|必须冲|"
    r"📍|✨|⭐|🔥|👍|🍜|🏨|🏛|🎫|❤️|💥|😍|🥹|🤤|✈️|🏝|🌅|🏔|🌊"
)
# 地点名特征：以常见地名收尾词结尾（与 note_import._looks_like_poi_line 互补）。
# 注意：收尾词是「后缀校验」，口语高频泛指（这家店/那家店）已由 _NOISE_RE 先剥。
_POI_END_RE = re.compile(
    r"(山|湖|寺|塔|街|馆|园|店|庄|村|岛|湾|洞|谷|峰|桥|楼|城|滩|港|宫|巷|庙|潭|"
    r"草原|古镇|美术馆|博物馆|公园|广场|景区|遗址|瀑布|海|沙滩|步道|"
    r"餐厅|饭店|小吃|咖啡|奶茶|菜馆|面馆|民宿|酒店|客栈|度假村|书局|书店|"
    r"夜市|市场|胡同|里弄|码头|车站|机场|动物园|植物园|大学|学院|"
    r"中心|大厦|商场|小区|公寓|酒店式公寓|银泰)"
)
# 价格语剥离（与 note_import 同构）：必须带前缀词（人均/门票/…）或 ¥ 符号，
# 避免裸数字被误剥。
_PRICE_STRIP_RE = re.compile(
    r"(?:人均|门票|票价|价格|花费|约)\s*[¥￥]?\s*\d{2,4}\s*(?:元|块|rmb|RMB)?(?:左右|起)?"
    r"|[¥￥]\s*\d{2,4}\s*(?:元|块)?(?:左右|起)?"
)


def _clean_name(piece: str) -> str:
    """清洗候选碎片为候选名：
    - 去标签/语气噪声/价格语；
    - 去「的/这家/那家/一个」等口语前缀；
    - 去「XX边的/XX附近的」方位前缀（西湖边的山外山菜馆 → 山外山菜馆）；
    - 截断到最后一个地名收尾词（灵隐寺 一定要去 → 灵隐寺）；
    - 保留内部空格（「in77 商场」），只 strip 首尾标点；截断到 MAX_NAME_LENGTH。
    """
    name = _TAG_RE.sub("", piece)
    name = _NOISE_RE.sub("", name)
    name = _PRICE_STRIP_RE.sub("", name)
    name = name.strip("，,、：:；;！!？?（）()“”\"' ··—")
    # 先 strip 首尾标点/空格，再剥口语前缀（否则「#标签 的XX」会残留「的」）
    name = re.sub(r"^的+", "", name)
    name = re.sub(r"^(这家|那家|一个|这家店)", "", name)
    name = re.sub(r"^[\u4e00-\u9fff]{1,6}?(?:边的|附近的|旁边的)", "", name)
    # 截到最后一个地名收尾词：去掉「灵隐寺 一定要去」这类尾部口水
    ends = list(_POI_END_RE.finditer(name))
    if ends:
        name = name[: ends[-1].end()].strip()
    return name[:MAX_NAME_LENGTH].strip()


def _normalize_key(name: str) -> str:
    """归一化去重键：去空白、统一大小写。"""
    return re.sub(r"\s+", "", name).lower()


def _split_caption(text: str) -> list[str]:
    """把 caption 切成候选「子句」：
    - 剥 URL（链接只识别平台、不参与候选）；
    - 按换行分行，每行再按句号/感叹号/分号/emoji 切成子句（口语 caption
      常一屏多句，句号边界比换行可靠）；
    - 顿号/逗号/冒号列举在候选阶段再拆（见 parse_social）。
    """
    text = _URL_RE.sub("", text)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    clauses: list[str] = []
    for ln in lines:
        parts = re.split(
            r"[。；;！!？?]|(?=[📍✨⭐🔥👍🍜🏨🏛🎫❤️💥😍🥹🤤✈️🏝🌅🏔🌊])",
            ln,
        )
        clauses.extend(p.strip() for p in parts if p.strip())
    return clauses


def _looks_like_place(fragment: str) -> bool:
    """判定一个文本碎片是否像「地点候选」：
    - 清洗后太短（<2 字）不算；太长（>40 字）不算；
    - 以地名收尾词结尾（收尾词表命中即算）。
    """
    frag = _clean_name(fragment)
    if len(frag) < 2 or len(frag) > MAX_NAME_LENGTH:
        return False
    return bool(_POI_END_RE.search(frag))


def _classify(name: str) -> Literal["attraction", "food", "hotel"]:
    """类型推断：food / hotel / attraction（默认）。"""
    if re.search(r"吃|餐厅|美食|小吃|咖啡|奶茶|面|烧烤|火锅|夜宵|点心|甜品|卤味|饭馆|菜馆|喝", name):
        return "food"
    if re.search(r"住|酒店|民宿|客栈|住宿|度假村|青旅|公寓|旅馆", name):
        return "hotel"
    return "attraction"


def _extract_price(fragment: str) -> float | None:
    """提取金额（元）。仅当含明确金额语境。"""
    m = re.search(r"[¥￥]\s*(\d+(?:\.\d+)?)|(\d+(?:\.\d+)?)\s*(?:元|块|rmb|RMB)", fragment)
    if not m:
        return None
    return float(m.group(1) or m.group(2))


@dataclass
class SocialImportResult:
    """社交 caption 解析结果：地点候选 + 敌意行标记。"""

    candidates: list[NoteStopCandidate] = field(default_factory=list)
    flagged_lines: list[FlaggedLine] = field(default_factory=list)
    dropped_lines: int = 0  # 超出候选上限被丢弃的候选数
    source_platform: str = ""  # 识别到的平台（tiktok/instagram/xiaohongshu/douyin/weibo/bilibili/unknown）


def _detect_platform(text: str) -> str:
    """从链接/文字识别平台（只识别，不抓取）。"""
    if re.search(r"tiktok\.com", text, re.IGNORECASE):
        return "tiktok"
    if re.search(r"instagram\.com", text, re.IGNORECASE):
        return "instagram"
    if re.search(r"xiaohongshu\.com|xhslink\.com", text, re.IGNORECASE):
        return "xiaohongshu"
    if re.search(r"douyin\.com|v\.douyin\.com", text, re.IGNORECASE):
        return "douyin"
    if re.search(r"weibo\.com", text, re.IGNORECASE):
        return "weibo"
    if re.search(r"bilibili\.com|b23\.tv", text, re.IGNORECASE):
        return "bilibili"
    return "unknown"


def parse_social(text: str) -> SocialImportResult:
    """把粘贴的社交分享文本解析为地点候选（外部内容，一律按敌意输入处理）。

    - 规则引擎：子句级特征识别（地名收尾词 / 标签 / emoji 分隔 / 顿号列举），
      跨子句累积；链接只识别平台、参与提取、不抓取；
    - 敌意输入：指令型子句标记剥离（复用 note_import 特征库），不进候选；
    - 候选：NoteStopCandidate（可直接勾选并入行程）。
    """
    result = SocialImportResult(candidates=[], flagged_lines=[], dropped_lines=0)
    if not text or not text.strip():
        return result
    if len(text) > MAX_TEXT_LENGTH:
        text = text[:MAX_TEXT_LENGTH]

    result.source_platform = _detect_platform(text)

    seen: dict[str, NoteStopCandidate] = {}
    for idx, raw in enumerate(_split_caption(text), start=1):
        # 1) 敌意输入检测：指令型内容 → 标记并剥离，绝不进入候选。
        if _INJECTION_RE.search(raw):
            reason = "疑似指令/注入内容"
            if re.search(r"忽略|无视", raw):
                reason = "包含「忽略/无视」指令词"
            elif re.search(r"你(?:现在|接下来|请)?(?:是|扮演|需要|必须)", raw):
                reason = "包含角色扮演指令"
            elif re.search(r"system|系统提示|prompt|指令", raw, re.IGNORECASE):
                reason = "包含 system/prompt/指令特征"
            elif re.search(r"工具|api|执行|命令|脚本", raw, re.IGNORECASE):
                reason = "包含工具/命令调用特征"
            elif re.search(r"注入|越狱|jailbreak", raw, re.IGNORECASE):
                reason = "包含注入/越狱关键词"
            result.flagged_lines.append(FlaggedLine(line_number=idx, content=raw[:200], reason=reason))
            continue

        # 2) 顿号/逗号/冒号列举：把「XX、YY、ZZ」/「行程名：地点」拆开逐个评估。
        pieces = [p.strip() for p in re.split(r"[、，,：:]", raw) if p.strip()]
        for piece in pieces:
            if not _looks_like_place(piece):
                continue
            name = _clean_name(piece)
            if len(name) < 2 or len(name) > MAX_NAME_LENGTH:
                continue
            key = _normalize_key(name)
            if not key or key in seen:
                continue
            if len(seen) >= MAX_CANDIDATES:
                result.dropped_lines += 1
                continue
            price = _extract_price(piece)
            desc = piece[:MAX_DESC_LENGTH]
            seen[key] = NoteStopCandidate(
                name=name,
                stop_type=_classify(name),
                description=desc,
                estimated_cost=price,
                source_lines=[idx],
                dedup_key=key,
            )

    result.candidates = list(seen.values())
    return result