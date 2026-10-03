"""预订确认邮件导入：把用户粘贴的预订确认邮件文本解析为结构化预订条目。

定位：task-email-import（预订后整理最小版）——iGo 邮件自动提取 / TripNoted
booking email 为 post-booking 范式；我们不接 Gmail OAuth 凭证级集成，做
零凭证的「粘贴文本版」，与 note-import 敌意输入处理同构。

验收（docs/night-build-todo.md 2026-09-29 + tests/test_email_import.py）：
1. 粘贴典型航司/酒店确认邮件 → 结构化条目（日期时间/名称/地址/确认码/金额）
2. 金额进预算视图（条目携带 amount + currency）
3. 恶意注入文本按敌意输入处理（flagged_lines 剥离，不进条目/候选）
4. 活动条目复用 note-import 候选结构（stop_type 候选可勾选）
5. API 层 POST /api/v1/trips/email/import（登录必需，超长 422）

设计决策（本文件为纯函数、零外部依赖）：
- 不用 LLM、不接邮箱协议：本地规则解析，无延迟、无成本、无 API key；
- 外部内容当敌意源：粘贴邮件视同「不可信输入」，指令型行被标记剥离
  （复用 note_import 的 _INJECTION_RE 特征库），绝不把文本当指令执行；
- 确定性：同一输入永远得到同一输出，便于测试与回归；
- 候选结构复用 note_import.NoteStopCandidate：活动/酒店条目可直接
  「勾选并入行程」（前端复用现有 POST /days/{day_id}/stops）。
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

# 输入上限（字符）。确认邮件通常 1-5k，20k 足够；防超大粘贴拖垮 worker。
MAX_TEXT_LENGTH = 20_000

# ── 预订条目特征（规则库，全部本地、确定性） ─────────────────────
# 航班号：国航 CA1234 / 东航 MU5101 / 南航 CZ3456 等两字母+3~4位数字。
_FLIGHT_NO_RE = re.compile(r"\b([A-Z]{2}\d{3,4})\b")
# 日期时间：2026-10-01 08:30
_DATETIME_RE = re.compile(r"(\d{4}-\d{2}-\d{2})\s*(\d{1,2}:\d{2})")
# 日期区间（酒店入住）：2026-10-01 至 2026-10-03
_DATE_RANGE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})\s*[至到~\-]\s*(\d{4}-\d{2}-\d{2})")
# 行程路线：杭州 (HGH) → 北京 (PEK) / 杭州→北京 / 杭州 - 北京
_ROUTE_RE = re.compile(
    r"([\u4e00-\u9fffA-Za-z（）() ]+?)\s*[→至\-\u2014]\s*([\u4e00-\u9fffA-Za-z（）() ]+)"
)
# 确认码/订单号：预订编号 / 确认号 / 确认码 / 订单号 / 预订号
_CODE_RE = re.compile(
    r"(?:预订编号|确认号|确认码|订单号|预订号|booking\s*(?:ref|no)|confirmation)"
    r"\s*[:：]?\s*([A-Za-z0-9\-]{3,20})",
    re.IGNORECASE,
)
# 金额：¥1280.00 / ￥1980 / 300 元
_AMOUNT_RE = re.compile(r"[¥￥]\s*(\d+(?:\.\d+)?)|(\d+(?:\.\d+)?)\s*(?:元|块|rmb)\b", re.IGNORECASE)
# 酒店名：杭州西湖大酒店（「酒店名」+ 酒店/民宿/客栈/宾馆/饭店/度假村 后缀）
_HOTEL_NAME_RE = re.compile(r"([\u4e00-\u9fffA-Za-z0-9]{2,30}?(?:酒店|民宿|客栈|宾馆|饭店|度假村))")
_HOTEL_NAME_AFTER_RE = re.compile(
    r"(?:酒店|民宿|客栈|宾馆|饭店|度假村|入住)\s*[:：]\s*([\u4e00-\u9fffA-Za-z0-9·\-]{2,30})"
)
# 活动/门票名：门票已确认：故宫博物院 / 门票：故宫博物院
_ACTIVITY_NAME_RE = re.compile(
    r"(?:门票|演出|活动|预约|已确认|确认)\s*[:：]\s*([\u4e00-\u9fffA-Za-z0-9·\-]{2,40})"
)


def _is_flight_line(line: str) -> bool:
    """航班行特征：航班号 / 去程回程 / 行程：A→B（带箭头）。"""
    if _FLIGHT_NO_RE.search(line):
        return True
    if re.search(r"去程|回程", line):
        return True
    if re.search(r"行程\s*[:：].{2,}?[→至\-\u2014]", line):
        return True
    return False


def _is_hotel_line(line: str) -> bool:
    """酒店行特征：含酒店/住宿词 + 预订/确认/订单/入住语境。"""
    if not re.search(r"酒店|民宿|客栈|宾馆|饭店|度假村", line):
        return False
    return bool(re.search(r"预订|确认|订单|入住|房型|入住日期|离店", line))


def _is_activity_line(line: str) -> bool:
    """活动行特征：门票/演出/活动/预约 + 确认/成功/订单语境。"""
    if not re.search(r"门票|演出|活动|预约|入场", line):
        return False
    return bool(re.search(r"确认|成功|订单|已出票|取票|检票", line))


def _detect_kind(line: str) -> Literal["flight", "hotel", "activity"] | None:
    """判定行开头是否启动一个新预订条目（flight/hotel/activity）。"""
    if _is_flight_line(line):
        return "flight"
    if _is_hotel_line(line):
        return "hotel"
    if _is_activity_line(line):
        return "activity"
    return None


def _extract_code(line: str) -> str | None:
    m = _CODE_RE.search(line)
    return m.group(1) if m else None


def _extract_amount(line: str) -> tuple[float | None, str]:
    """提取金额与币种。只认 ¥/￥/元 前缀（默认 CNY）；$ 前缀 USD。"""
    m = re.search(r"[$]\s*(\d+(?:\.\d+)?)", line)
    if m:
        return float(m.group(1)), "USD"
    m = _AMOUNT_RE.search(line)
    if m:
        val = m.group(1) or m.group(2)
        return float(val), "CNY"
    return None, "CNY"


def _extract_datetime(line: str) -> str | None:
    m = _DATETIME_RE.search(line)
    if m:
        return f"{m.group(1)} {m.group(2)}"
    m = _DATE_RANGE_RE.search(line)
    if m:
        return f"{m.group(1)}"
    m = re.search(r"(\d{4}-\d{2}-\d{2})", line)
    return m.group(1) if m else None


def _extract_route(line: str) -> str:
    m = _ROUTE_RE.search(line)
    if m:
        return f"{m.group(1).strip()} → {m.group(2).strip()}"
    return ""


def _extract_hotel_name(line: str) -> str:
    m = _HOTEL_NAME_RE.search(line)
    if m:
        return m.group(1)
    m = _HOTEL_NAME_AFTER_RE.search(line)
    if m:
        return m.group(1)
    return ""


def _extract_activity_name(line: str) -> str:
    m = _ACTIVITY_NAME_RE.search(line)
    if m:
        return m.group(1)
    return ""


@dataclass
class EmailBooking:
    """一条结构化预订条目（航班/酒店/活动）。

    字段对齐预算视图口径：amount + currency 可直接进入预算展示
    （后端预算聚合按 by_type 归类，前端预订条目可「并入预算」）。
    """

    kind: Literal["flight", "hotel", "activity"]
    name: str = ""
    code: str | None = None
    datetime: str | None = None  # 日期时间（精确到时刻）或纯日期；空 = 未识别
    amount: float | None = None
    currency: str = "CNY"
    source_lines: list[int] = field(default_factory=list)

    def ensure(self, **kw) -> None:
        """仅填充尚未设置的可选字段（先到先得，不覆盖已有值）。"""
        for k, v in kw.items():
            if v is None:
                continue
            if getattr(self, k) in (None, ""):
                setattr(self, k, v)


@dataclass
class EmailImportResult:
    bookings: list[EmailBooking] = field(default_factory=list)
    candidates: list[NoteStopCandidate] = field(default_factory=list)
    flagged_lines: list[FlaggedLine] = field(default_factory=list)
    dropped_lines: int = 0  # 超出候选上限被丢弃的候选数


def _flush(current: EmailBooking | None, result: EmailImportResult) -> EmailBooking | None:
    """把当前累积的条目落盘（非空才留）并清空指针。"""
    if current is not None:
        result.bookings.append(current)
    return None


def parse_email(text: str) -> EmailImportResult:
    """把粘贴的预订确认邮件解析为结构化预订条目 + 站点候选。

    - 规则引擎：行级特征识别（航班/酒店/活动），跨行累积确认码/金额/日期；
    - 敌意输入：指令型行标记剥离（复用 note_import 特征库），不进条目/候选；
    - 候选：活动/酒店条目 → NoteStopCandidate（可直接勾选并入行程）。
    """
    result = EmailImportResult(bookings=[], candidates=[], flagged_lines=[], dropped_lines=0)
    if not text or not text.strip():
        return result
    if len(text) > MAX_TEXT_LENGTH:
        text = text[:MAX_TEXT_LENGTH]  # 服务层边界截断；API 层另有 422 校验

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    # 没有换行的长文本：按句号/分号切句（单行确认邮件也能解析）。
    if len(lines) <= 1:
        pieces = [s.strip() for s in re.split(r"[。；;！!？?]\s*", text) if s.strip()]
        if len(pieces) > 1:
            lines = pieces

    current: EmailBooking | None = None
    seen_candidates: dict[str, NoteStopCandidate] = {}
    # 待归属字段池：条目启动前出现的确认码/金额/日期可能属于即将出现的条目，
    # 先暂存，条目启动时并入（避免「感谢您预订…」这类前置行吞掉确认码）。
    pending: dict[str, object] = {}

    def add_candidate(name: str, stop_type: str, line_no: int) -> None:
        """把条目名登记为站点候选（去重，超限计数丢弃）。"""
        if not name:
            return
        key = re.sub(r"\s+", "", name).lower()
        if not key:
            return
        if key in seen_candidates:
            exist = seen_candidates[key]
            if len(exist.source_lines) < 3:
                exist.source_lines.append(line_no)
            return
        if len(seen_candidates) >= MAX_CANDIDATES:
            result.dropped_lines += 1
            return
        cand = NoteStopCandidate(
            name=name,
            stop_type=stop_type,  # type: ignore[arg-type]
            description=f"预订确认条目（{stop_type}）",
            source_lines=[line_no],
            dedup_key=key,
        )
        seen_candidates[key] = cand

    for idx, raw in enumerate(lines, start=1):
        # 1) 敌意输入检测：指令型内容 → 标记并剥离，绝不进入条目/候选。
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

        # 2) 行级通用字段（确认码/金额/日期时间），无论是否条目行都先提取。
        code = _extract_code(raw)
        amount, currency = _extract_amount(raw)
        dt = _extract_datetime(raw)

        kind: Literal["flight", "hotel", "activity"] | None = _detect_kind(raw)
        if kind is not None:
            # 新条目启动：先把上一个累积条目落盘。
            current = _flush(current, result)
            current = EmailBooking(kind=kind, source_lines=[idx])
            if kind == "flight":
                fm = _FLIGHT_NO_RE.search(raw)
                current.name = _extract_route(raw) or (f"航班 {fm.group(1)}" if fm else "航班")
            elif kind == "hotel":
                current.name = _extract_hotel_name(raw)
            elif kind == "activity":
                current.name = _extract_activity_name(raw)
            # 把「待归属字段池」里暂存的字段并入（条目启动前的前置行字段）。
            current.ensure(
                code=pending.get("code") if isinstance(pending.get("code"), str) else None,
                amount=pending.get("amount") if isinstance(pending.get("amount"), (int, float)) else None,
                currency=pending.get("currency") if isinstance(pending.get("currency"), str) else None,
                datetime=pending.get("datetime") if isinstance(pending.get("datetime"), str) else None,
            )
            pending.clear()
            current.ensure(code=code, amount=amount, currency=currency, datetime=dt)

            # 活动/酒店条目 → 站点候选（复用 note-import 候选结构）。
            if kind in ("hotel", "activity") and current.name:
                add_candidate(current.name, "hotel" if kind == "hotel" else "attraction", idx)
            continue

        # 3) 非条目行：给当前条目补字段（确认码/金额/日期可能单独成行）。
        if current is None:
            # 还没有任何条目：把字段暂存进待归属池，等条目启动时并入。
            if code is not None and "code" not in pending:
                pending["code"] = code
            if amount is not None and "amount" not in pending:
                pending["amount"] = amount
                pending["currency"] = currency
            if dt is not None and "datetime" not in pending:
                pending["datetime"] = dt
            continue
        current.ensure(code=code, amount=amount, currency=currency, datetime=dt)
        if not current.name:
            if current.kind == "hotel":
                current.name = _extract_hotel_name(raw)
            elif current.kind == "activity":
                current.name = _extract_activity_name(raw)

    current = _flush(current, result)
    result.candidates = list(seen_candidates.values())
    return result