"""偏好推理服务（task-preference-inference）：行为记忆 → 稳定偏好。

与 ``profile_service`` 的声明式画像（用户主动填）和观察式行为记忆（修订/编辑
触点回写）不同，本服务把**行为记忆信号**进一步归纳为**可指导下次规划的稳定偏好**：

- ``infer_preferences``：纯规则推理（零 LLM、零 API key、确定性、可测试）。
  输入 ``behavior_memory_json`` 的 signals，输出结构化推断（偏好/回避/节奏提示）。
- 规则引擎设计（与 DrivingGate/TimeGate 同哲学：**确定性规则库优先于 LLM**）：
  - 同一目的地的「缩短/精简」行为 ≥2 次 → pace_hint = 轻松/松弛
  - 「删除」信号累计 → avoid 清单（明确不感兴趣）
  - 「新增」某种类型站点（attraction/food）→ 偏好该类型
  - 出现次数多的非空目的地 → 常去城市倾向（与 favorite_cities 去重合并）
- 结果写回 ``UserProfile.inferred_preferences_json``；**用户声明画像永远优先**，
  推断段只作为补充上下文（带 source 标注，与声明区分）。
- 规划注入时（``profile_for_request``）把推断段合并进注入文本，让 Planner 拿到
  「用户没直说、但行为出卖了」的偏好。

注意：推断是尽力而为的辅助，不是断言。信号不足时返回空结构（不产生误导）。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)

# 信号类型：与 profile_service._record_behavior 的 signal_kind 一致
_KIND_REVISE = "revise"
_KIND_MANUAL_ADD = "manual_add"
_KIND_MANUAL_EDIT = "manual_edit"
_KIND_MANUAL_REMOVE = "manual_remove"

# 触发「节奏变轻松」的摘要关键词（与 profile_service._summarize_behaviors 同口径）
_PACE_RELAX_KEYWORDS = ("缩短", "半天", "精简", "太赶", "减少", "别排太满")
# 追加某类站点的摘要关键词 → 类型偏好
_ADD_PREFERENCE_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("美食", "food"),
    ("餐厅", "food"),
    ("吃", "food"),
    ("景点", "attraction"),
    ("博物馆", "attraction"),
    ("公园", "attraction"),
)

# 推断结果的来源标注（诚实口径：规则推理，不是用户声明）
_SOURCE = "rule_based"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _signal_kind(signal: dict[str, Any]) -> str:
    return (signal.get("kind") or "").strip()


def _signal_destination(signal: dict[str, Any]) -> str:
    return (signal.get("destination") or "").strip()


def _summary_text(signal: dict[str, Any]) -> str:
    return signal.get("summary") or ""


def infer_preferences(behavior_memory_json: dict[str, Any] | None) -> dict[str, Any]:
    """从行为记忆 signals 规则推理稳定偏好。

    返回结构（均为可选，无信号时返回空推断，绝不误导）::

        {
          "preferences": [{"type": "food|attraction", "reason": "..."}],  # 偏好类型
          "avoid": ["雷峰塔", ...],                                        # 明确回避
          "pace_hint": "relaxed|compact|balanced",                         # 节奏提示
          "favorite_cities": ["杭州", ...],                                 # 高频目的地
          "source": "rule_based",
          "updated_at": "..."
        }

    设计约束：
    - 纯函数、无副作用（写库由调用方负责），便于单元测试
    - 关键词匹配用 ``in`` 而非正则，避免误伤；计数阈值避免单次行为过度泛化
    - 数据不足（<2 条有效信号）时返回空推断，宁缺毋滥
    """
    signals = (behavior_memory_json or {}).get("signals") or []
    if not isinstance(signals, list) or not signals:
        return {}

    # ── 1. 节奏提示：同一目的地多次「缩短/精简/太赶」 → 轻松倾向 ──
    relax_by_dest: dict[str, int] = {}
    compact_by_dest: dict[str, int] = {}
    for s in signals:
        kind = _signal_kind(s)
        if kind not in (_KIND_REVISE, _KIND_MANUAL_EDIT):
            continue
        dest = _signal_destination(s)
        summary = _summary_text(s)
        if not dest:
            continue
        # 先查「变宽松」信号（缩短/精简/太赶…），再查「变紧凑」信号
        # （加长/排满/太松/多排…），两条路径互斥
        if any(kw in summary for kw in _PACE_RELAX_KEYWORDS):
            relax_by_dest[dest] = relax_by_dest.get(dest, 0) + 1
        elif any(kw in summary for kw in ("加长", "太松", "多排", "排满", "太闲", "再加")):
            compact_by_dest[dest] = compact_by_dest.get(dest, 0) + 1

    pace_hint: str | None = None
    if relax_by_dest and max(relax_by_dest.values()) >= 2:
        pace_hint = "relaxed"
    elif compact_by_dest and max(compact_by_dest.values()) >= 2:
        pace_hint = "compact"

    # ── 2. 回避清单：明确的「删除」信号 → avoid ──
    avoid: list[str] = []
    seen_avoid: set[str] = set()
    for s in signals:
        if _signal_kind(s) == _KIND_MANUAL_REMOVE:
            summary = _summary_text(s)
            # 提取被删站点名：摘要形如「删除 雷峰塔」「楼外楼 删除」
            for token in summary.replace("删除", " ").replace("删掉", " ").split():
                token = token.strip("，。、()（）\"' ")
                if len(token) >= 2 and token not in seen_avoid:
                    avoid.append(token)
                    seen_avoid.add(token)
                    break  # 每条删除信号只取首个站点名，避免过度提取

    # ── 3. 类型偏好：新增/编辑中带美食/景点关键词 → 偏好类型 ──
    type_counts: dict[str, int] = {}
    type_reason: dict[str, str] = {}
    for s in signals:
        kind = _signal_kind(s)
        if kind not in (_KIND_MANUAL_ADD, _KIND_MANUAL_EDIT, _KIND_REVISE):
            continue
        summary = _summary_text(s)
        for kw, pref_type in _ADD_PREFERENCE_KEYWORDS:
            if kw in summary:
                type_counts[pref_type] = type_counts.get(pref_type, 0) + 1
                type_reason[pref_type] = (
                    f"常规划/添加{kw}相关（来自你的近期行程编辑行为）"
                )
                break

    preferences = [
        {"type": t, "reason": type_reason[t]}
        for t, cnt in sorted(type_counts.items(), key=lambda kv: -kv[1])
        if cnt >= 2 and t in type_reason  # 同一类型至少 2 次才视为稳定偏好
    ]

    # ── 4. 高频目的地（与声明式 favorite_cities 不同：这是行为统计） ──
    city_counts: dict[str, int] = {}
    for s in signals:
        dest = _signal_destination(s)
        if dest:
            city_counts[dest] = city_counts.get(dest, 0) + 1
    favorite_cities = [
        c for c, cnt in sorted(city_counts.items(), key=lambda kv: -kv[1])
        if cnt >= 2
    ][:5]

    # 数据不足（有效信号太少）→ 空推断，绝不误导
    effective_signals = len(signals)
    if effective_signals < 2 and not (preferences or avoid or pace_hint):
        return {}

    result: dict[str, Any] = {"source": _SOURCE, "updated_at": _now_iso()}
    if preferences:
        result["preferences"] = preferences
    if avoid:
        result["avoid"] = avoid[:10]
    if pace_hint:
        result["pace_hint"] = pace_hint
    if favorite_cities:
        result["favorite_cities"] = favorite_cities
    return result


def inferred_to_text(inferred: dict[str, Any] | None) -> str:
    """把推断偏好转成给 Agent 的纯文本段落（无推断返回空串）。

    与原行为记忆摘要的差异：这里是**跨会话稳定推断**（不再逐条罗列信号），
    只给 Planner 高信号结论；且明确标注「系统推断，非你亲口所说」，避免
    让 LLM 把推断当用户声明（诚实口径）。
    """
    if not inferred or not isinstance(inferred, dict):
        return ""
    lines: list[str] = []
    if inferred.get("pace_hint") == "relaxed":
        lines.append("节奏提示：你近期多次把行程改得更宽松（缩短/精简），新行程默认优先松弛节奏、少排站点")
    elif inferred.get("pace_hint") == "compact":
        lines.append("节奏提示：你近期多次把行程改得更充实，新行程可适当多排一些体验")
    for pref in inferred.get("preferences") or []:
        t = pref.get("type") if isinstance(pref, dict) else None
        reason = pref.get("reason") if isinstance(pref, dict) else ""
        if t == "food":
            lines.append(f"偏好提示：你更在意美食（{reason}），请优先纳入当地特色餐饮")
        elif t == "attraction":
            lines.append(f"偏好提示：你更看重景点体验（{reason}），请优先纳入有代表性的景点")
    avoid = inferred.get("avoid") or []
    if avoid:
        lines.append(f"回避提示：你近期删除过「{'、'.join(avoid[:5])}」等条目，除非用户明确要求，否则避免重复推荐")
    if not lines:
        return ""
    return "【系统推断 · 基于你近期的行程行为】\n" + "\n".join(lines)


def ensure_inferred(db_session: Any, profile: Any) -> dict[str, Any]:
    """确保画像的推断偏好存在且新鲜（懒计算 + 写回）。

    - 已有推断且签名（行为记忆 updated_at/信号数）未变 → 直接复用
    - 否则重新推理并写回（调用方负责 commit）

    返回推断 dict（可能为空）。
    """
    mem = profile.behavior_memory_json or {}
    signals = mem.get("signals") or []
    existing = profile.inferred_preferences_json or {}
    # 新鲜度签名：行为记忆变化时才重算（避免每次规划都全量推理）
    signature = f"{mem.get('updated_at', '')}:{len(signals)}"
    if existing.get("_signature") == signature and existing.get("source") == _SOURCE:
        return existing
    inferred = infer_preferences(mem)
    if inferred:
        inferred["_signature"] = signature
    profile.inferred_preferences_json = inferred or None
    return inferred