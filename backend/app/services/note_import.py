"""笔记/种草文本导入：把用户粘贴的攻略笔记结构化提取为站点候选。

定位：规划层的「想法搬运工」——Tripnotes 范式复活 + 去哪儿小红书导入验证的
国内刚需。用户随手粘贴一段种草文案/攻略笔记，即可得到可勾选的站点候选清单，
勾选后并入行程（落库复用现有 POST /days/{day_id}/stops）。

设计决策（本文件为纯函数、零外部依赖）：
- 不用 LLM：解析规则完全本地化，无延迟、无成本、无 API key；
- 外部内容当敌意源：粘贴文本视同「不可信输入」，指令型内容被标记并剥离，
  绝不把文本内容当指令执行；输出经 Pydantic schema 强校验；
- 确定性：同一输入永远得到同一输出，便于测试与回归。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

StopType = Literal["attraction", "food", "hotel"]

# 输入上限（字符）。攻略笔记通常几千字，20k 足够；防超大粘贴拖垮 worker。
MAX_TEXT_LENGTH = 20_000
# 单次解析最多返回的候选数（勾选并入行程的合理上限，超过的丢弃并计数）。
MAX_CANDIDATES = 50
# 候选名称长度上限（与 StopSchema.name max_length=200 对齐但更严格，避免长句当站名）。
MAX_NAME_LENGTH = 60
# 候选描述长度上限。
MAX_DESC_LENGTH = 300
# 单个候选最多携带的来源行数（防同站被 30 行描述重复引用撑爆响应）。
MAX_SOURCE_LINES = 3

# 行首启发前缀：序号/符号/emoji 开头的行更可能是「站点条目」而非散文正文。
_LINE_PREFIX_RE = re.compile(
    r"^\s*(?:\d{1,2}[\.、\)）]\s*|[\-•·*]\s*|"
    r"[①②③④⑤⑥⑦⑧⑨⑩]\s*|[（(]\d{1,2}[)）]\s*|"
    r"📍|✅|✨|⭐|🔥|👍|🍜|🏨|🏛|🎫|\.\.\.)?\s*"
)
# 攻略语境动词/名词：命中即把该行视为「候选站点」而非普通描述。
_POI_MARKER_RE = re.compile(
    r"推荐|打卡|必去|必游|不容错过|不去|种草|强推|值得|好吃|好喝|"
    r"超赞|绝了|yyds|YYDS|网红|必吃|必住|攻略|景点|门票|人均|"
    r"博物馆|寺|庙|塔|山|湖|公园|街|古镇|遗址|美术馆|馆|园|广场|"
    r"餐厅|饭店|小吃|咖啡|奶茶|店|民宿|酒店|客栈|度假村"
)
# 类型推断关键词。
_FOOD_RE = re.compile(r"吃|餐厅|美食|小吃|咖啡|奶茶|面|烧烤|火锅|夜宵|点心|甜品|卤味|饭馆|菜馆")
_HOTEL_RE = re.compile(r"住|酒店|民宿|客栈|住宿|度假村|青旅|公寓|旅馆")
# 金额/时长解析。
_PRICE_RE = re.compile(r"(?:人均|门票|票价|价格|花费|约|大概)?\s*[¥￥]?\s*(\d{2,4})\s*(?:元|块|rmb|RMB)?")
_DURATION_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:小时|个?小时|h)\s*(?:左右|以上|以内)?|[半一][天日]")

# 注入/指令型内容特征：命中即视为敌意输入行，不进入候选。
_INJECTION_RE = re.compile(
    r"忽略(?:以上|之前|前面|所有)?(?:内容|指令|提示|要求)|"
    r"(?:现在|接下来|请)你(?:是|扮演|需要|必须)|"
    r"你现在(?:是|扮演|需要|必须)|"
    r"你(?:扮演|是)|"
    r"system\s*[:：]|<\|?system\|?>|<系统|系统提示|"
    r"prompt\s*[:：]|指令[:：]|"
    r"注入|越狱|jailbreak|"
    r"调用(?:工具|api)|执行(?:命令|脚本)|"
    r"请(?:输出|返回|忽略).{0,10}(?:json|指令|prompt)|"
    r"无视(?:以上|之前).{0,10}(?:规则|指令|设定)"
)


@dataclass
class NoteStopCandidate:
    """解析出的一个站点候选（可勾选并入行程）。"""

    name: str
    stop_type: StopType = "attraction"  # attraction / food / hotel
    description: str = ""
    estimated_cost: float | None = None
    estimated_duration_minutes: int | None = None
    # 来源行号（1-based），供前端回溯原文；最多保留 MAX_SOURCE_LINES 个。
    source_lines: list[int] = field(default_factory=list)
    # 去重键：名称归一化后的小写/去空白形式。
    dedup_key: str = ""


@dataclass
class FlaggedLine:
    """被判定为敌意/指令型内容的行（剥离展示，不进入候选）。"""

    line_number: int
    content: str
    reason: str


@dataclass
class NoteImportResult:
    candidates: list[NoteStopCandidate]
    flagged_lines: list[FlaggedLine]
    dropped_lines: int = 0  # 超出 MAX_CANDIDATES 丢弃的候选行数


def _normalize_name(name: str) -> str:
    """归一化站点名：去空白、统一大小写，用于去重与长度截断。"""
    compact = re.sub(r"\s+", "", name).strip("。，,、.．")
    return compact


def _clean_line(line: str) -> str:
    """清洗一行：去掉行首序号/符号前缀与行尾标点，保留正文。"""
    line = _LINE_PREFIX_RE.sub("", line).strip()
    line = re.sub(r"^[📍✅✨⭐🔥👍🍜🏨🏛🎫...\-\*•·]+", "", line).strip()
    return line.rstrip("。，,、；;！!？?）)】】")


def _first_sentence(name: str) -> str:
    """取句子主干作为站点名：按标点/空格切第一段，截断到 MAX_NAME_LENGTH。"""
    for sep in ("，", ",", "、", "：", ":", "；", ";", "！", "!", "。", ".", " "):
        if sep in name:
            name = name.split(sep, 1)[0]
            break
    # 去除尾部攻略语气词（西湖必打卡 → 西湖）
    name = re.sub(
        r"(必打卡|打卡|推荐|必去|必游|强推|种草|不容错过|yyds|YYDS|网红|必吃|必住|值得一去?|超赞|绝了)$",
        "",
        name,
    )
    # 先切「吃 + 菜品」片段（楼外楼人均200元吃东坡肉 → 楼外楼人均200元 → 再剥价格 → 楼外楼）
    if len(name) >= 3:
        idx = name.find("吃", 2)
        if idx > 0:
            name = name[:idx]
    # 去除尾部价格语境（必须带价格词/符号才算：灵隐寺门票75元 → 灵隐寺；景点10 的裸数字不算）
    name = re.sub(
        r"(?:门票|票价|价格|人均|花费)\s*[¥￥]?\s*\d{2,4}\s*(?:元|块|rmb|RMB)?(?:左右|起)?$"
        r"|[¥￥]\s*\d{2,4}\s*(?:元|块)?(?:左右|起)?$",
        "",
        name,
    )
    return name.strip("，,、 ：:。；;！!？?" "’\"'")[:MAX_NAME_LENGTH].strip()


def _split_lines(text: str) -> list[str]:
    """按换行 + 常见句子边界切分文本为「候选行」。"""
    lines = [ln.strip() for ln in text.splitlines()]
    # 没有换行的长文本：按句号/分号/感叹号切句，保证短文本也能解析。
    if len(lines) == 1 and len(lines[0]) > 4:
        lines = [s.strip() for s in re.split(r"[。；;！!？?]\s*", lines[0]) if s.strip()]
    return lines


def _classify(line: str) -> StopType:
    """类型推断：food / hotel / attraction（默认）。"""
    if _FOOD_RE.search(line):
        return "food"
    if _HOTEL_RE.search(line):
        return "hotel"
    return "attraction"


def _extract_price(line: str) -> float | None:
    """提取金额（元）。仅当行内含明确的金额语境（¥ / 元 / 人均 / 门票 / 价格）。"""
    if not re.search(r"[¥￥]|元|块|人均|门票|票价|价格|花费", line):
        return None
    m = _PRICE_RE.search(line)
    if not m:
        return None
    return float(m.group(1))


def _extract_duration(line: str) -> int | None:
    """提取停留时长（分钟）。"""
    m = _DURATION_RE.search(line)
    if not m:
        return None
    if m.group(0) in ("半天", "半日"):
        return 240
    if m.group(0) in ("一天", "一日"):
        return 480
    if m.group(1):
        hours = float(m.group(1))
        if hours <= 0 or hours > 24:
            return None
        return int(hours * 60)
    return None


def _looks_like_poi_line(clean: str) -> bool:
    """判断清洗后的行是否像「站点条目」：
    - 太短（<2 字）或太长（>80 字且无攻略标记）都不是站名；
    - 命中攻略语境标记 或 长度在 2-40 字且以常见地名结尾词收尾；
    - 英文行：命中英文收尾词 或 逗号分隔的大写专名行（task-import-recall-en）。
    """
    if len(clean) < 2:
        return False
    if _POI_MARKER_RE.search(clean):
        return True
    if len(clean) > 40:
        return False
    # 英文行识别（英文文本通常无中文字符；先看是否含拉丁字母）
    if re.search(r"[A-Za-z]", clean):
        # 名称段 = 逗号前的部分（英文攻略行 "Sensoji Temple, must-see, 1 hour"
        # 的名称是 "Sensoji Temple"）；收尾词锚定名称段行尾，负例
        # "The market was great" 行尾是 great 不命中。
        name_part = clean.split(",", 1)[0].strip()
        if _EN_POI_END_RE.search(name_part):
            return True
        # 逗号分隔的大写专名行（Akihabara, anime shopping）
        if _EN_TITLE_COMMA_RE.match(clean) and not _EN_STOP_WORDS_RE.match(clean):
            return True
        return False
    # 裸站名启发：以地名常用收尾词结尾（山/湖/寺/塔/街/馆/园/店/庄/村…）
    return bool(re.search(r"(山|湖|寺|塔|街|馆|园|店|庄|村|岛|湾|洞|谷|峰|桥|楼|城|滩|港|草原|古镇)$", clean))


# ── 英文地名收尾词（task-import-recall-en，2026-11-14）──────────────
# 英文攻略行级识别：与中文收尾词互补，命中即视为「站点条目」。
# 匹配范围是「逗号前的名称部分」以收尾词结尾——英文攻略行格式为
# "Sensoji Temple, must-see" / "Tokyo Tower, 900 yen"；负例
# "The market was great" / "a park bench" 的名称部分不以收尾词结尾，
# 不会误判。
_EN_POI_END_RE = re.compile(
    r"\b(Temple|Shrine|Park|Garden|Gardens|Market|Tower|Skytree|Crossing|Street|Museum|"
    r"Castle|Beach|Bridge|Square|Gallery|Zoo|Aquarium|Cathedral|Palace|District|"
    r"Forest|Island|Bay|Harbor|Harbour|Station|Centre|Center|Falls|Hill|Hills|"
    r"Valley|Cafe|Restaurant|Hotel|Inn|Lane|Alley|Gate|Gates|Church|Chapel|Fort|"
    r"Stadium|Theatre|Theater|Library|University|College|School|Tunnel|Pier|"
    r"Docks|Quay|Botanical|Mountain|Peak|Lake|River|Coast|Seafront)$",
    re.IGNORECASE,
)
# 英文专名行启发：逗号分隔的「大写专名, 描述」行——Akihabara, anime shopping
# / Ginza, luxury shopping 这类无收尾词专名也识别为站点。描述可小写开头或
# 数字开头（"2 hours"），但不能是句子主语（First/We/The…由 _EN_STOP_WORDS_RE 挡）。
_EN_TITLE_COMMA_RE = re.compile(
    r"^[A-Z][A-Za-z0-9'’\-\u00c0-\u024f]*(?:\s+[A-Z][A-Za-z0-9'’\-\u00c0-\u024f]*){0,3}"
    r",\s+[a-z0-9]",
)
# 英文站名禁用特征：落在词表内但不以收尾词结尾的散文行。
_EN_STOP_WORDS_RE = re.compile(
    r"^(The|A|An|We|I|You|They|He|She|It|This|That|There|Here|After|Before|First|Then|Next)\b"
)


def parse_note(text: str) -> NoteImportResult:
    """把粘贴的攻略/种草文本解析为站点候选（外部内容，一律按敌意输入处理）。"""
    result = NoteImportResult(candidates=[], flagged_lines=[], dropped_lines=0)
    if not text or not text.strip():
        return result
    if len(text) > MAX_TEXT_LENGTH:
        text = text[:MAX_TEXT_LENGTH]  # 超长截断（服务层边界；API 层另有 422 校验）

    seen: dict[str, NoteStopCandidate] = {}
    for idx, raw_line in enumerate(_split_lines(text), start=1):
        # 1) 敌意输入检测：指令型内容 → 标记并剥离，绝不进入候选。
        if _INJECTION_RE.search(raw_line):
            reason = "疑似指令/注入内容"
            if re.search(r"忽略|无视", raw_line):
                reason = "包含「忽略/无视」指令词"
            elif re.search(r"你(?:现在|接下来|请)?(?:是|扮演|需要|必须)", raw_line):
                reason = "包含角色扮演指令"
            elif re.search(r"system|系统提示|prompt|指令", raw_line, re.IGNORECASE):
                reason = "包含 system/prompt/指令特征"
            elif re.search(r"工具|api|执行|命令|脚本", raw_line, re.IGNORECASE):
                reason = "包含工具/命令调用特征"
            elif re.search(r"注入|越狱|jailbreak", raw_line, re.IGNORECASE):
                reason = "包含注入/越狱关键词"
            result.flagged_lines.append(FlaggedLine(line_number=idx, content=raw_line[:200], reason=reason))
            continue

        clean = _clean_line(raw_line)
        if not clean:
            continue
        if not _looks_like_poi_line(clean):
            continue

        name = _first_sentence(clean)
        if len(name) < 2:
            continue
        key = _normalize_name(name).lower()
        if not key:
            continue

        price = _extract_price(clean)
        duration = _extract_duration(clean)
        desc = clean[:MAX_DESC_LENGTH]
        # 描述里若已含站名本身，去掉前缀避免冗余（「西湖，环湖绿道」→「环湖绿道」）。
        if desc.startswith(name):
            desc = desc[len(name):].lstrip("，,、 ：:")
        desc = desc[:MAX_DESC_LENGTH]

        if key in seen:
            exist = seen[key]
            if price is not None:
                exist.estimated_cost = price
            if duration is not None:
                exist.estimated_duration_minutes = duration
            if desc and not exist.description:
                exist.description = desc
            if len(exist.source_lines) < MAX_SOURCE_LINES:
                exist.source_lines.append(idx)
            continue

        if len(seen) >= MAX_CANDIDATES:
            result.dropped_lines += 1
            continue

        cand = NoteStopCandidate(
            name=name,
            stop_type=_classify(clean),
            description=desc,
            estimated_cost=price,
            estimated_duration_minutes=duration,
            source_lines=[idx],
            dedup_key=key,
        )
        seen[key] = cand

    result.candidates = list(seen.values())
    return result