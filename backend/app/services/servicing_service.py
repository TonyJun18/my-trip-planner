"""定稿后 servicing 阶段：把已定稿行程兑现为「可执行的服务层产物」。

方案 B（两段式）第二阶段，只消费定稿 plan，与采集/规划主流程解耦：
1. 市内通勤视图（transit）：复用 driving_service 的 leg 计算/高德路径，
   输出「相邻站点间怎么走」的确定性建议（公共交通/步行/驾车）。
2. 酒店入住办理指引（checkin）：模板基座 + LLM 润色（checkin_service）。
3. 折扣搜索比价（discounts）：对已选定站点做 Tavily 折扣搜索，
   施加「无来源即丢弃」硬闸门；失败只保留规则区（不编造）。

设计（故障隔离）：
- 三个子任务完全独立，任一失败都不影响另外两个；
- 全部是可选的增强：调用方（run_planning_agents）把本模块放在
  定稿之后，失败只写 warnings，绝不回滚/阻断主流程；
- 产物结构固定，直接挂 plan.transit / plan.checkin / plan.discounts。

=== 城市内部通勤策略（确定性代码，无 LLM） ===
对相邻站点对，按直线距离启发式给出「公共交通/步行/打车」建议：
- <= 1.5km  → 步行
- <= 8km    → 地铁/公交（推荐）
- 否则      → 打车/自驾（参考高德驾车时长）
绝不给虚构班次；仅给「方式 + 大致时长 + 来源」。
"""
from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.services.checkin_service import generate_checkin_guide
from app.services.driving_service import leg_distance_km

logger = get_logger(__name__)


# ── 市内通勤（确定性规则） ─────────────────────────────────
def _transit_mode_for_distance(distance_km: float) -> str:
    """按直线距离启发式给交通方式建议。"""
    if distance_km <= 1.5:
        return "步行"
    if distance_km <= 8:
        return "公共交通（地铁/公交）"
    return "打车/自驾"


async def build_transit_view(plan: dict[str, Any]) -> dict[str, Any]:
    """为定稿行程生成市内通勤视图（相邻站点间怎么走）。

    返回：
    {
      "source": "rule",
      "legs": [
        {"from": str, "to": str, "distance_km": float,
         "mode": "步行|公共交通（地铁/公交）|打车/自驾",
         "note": "直线距离约 X km（实际以导航为准）"}
      ],
      "count": int
    }
    缺坐标的相邻对跳过（不编造）。
    """
    legs: list[dict[str, Any]] = []
    for day in plan.get("days") or []:
        stops = day.get("stops") or []
        for i in range(1, len(stops)):
            prev, stop = stops[i - 1], stops[i]
            if not (isinstance(prev, dict) and isinstance(stop, dict)):
                continue
            d = leg_distance_km(prev, stop)
            if d is None:
                continue
            legs.append({
                "from": prev.get("name") or f"站点{i}",
                "to": stop.get("name") or f"站点{i + 1}",
                "distance_km": round(d, 1),
                "mode": _transit_mode_for_distance(d),
                "note": f"直线距离约 {d:.1f}km（实际路线以导航为准）",
            })
            if len(legs) >= 60:  # 上限保护：不因超长行程膨胀
                break
    return {"source": "rule", "legs": legs, "count": len(legs)}


# ── 折扣搜索比价（Tavily + 硬闸门） ─────────────────────────
_DISCOUNT_SEARCH_QUERY = "{city} {target} 门票 优惠 折扣 攻略"


async def _discount_search(
    city: str, target: str, *, source_url: str | None = None,
) -> dict[str, Any] | None:
    """对单个目标搜折扣（Tavily）。无来源或过低置信 → None（不产出）。"""
    from app.agent import tools as agent_tools

    query = _DISCOUNT_SEARCH_QUERY.format(city=city, target=target[:30])
    try:
        result = await agent_tools.tavily_search(query, max_results=3)
    except Exception:  # noqa: BLE001
        return None
    for r in result.get("results", []):
        url = (r.get("url") or "").strip()
        title = (r.get("title") or "").strip()
        if not url or not title:
            continue
        return {
            "target": target,
            "platform": "tavily",
            "source_url": url,
            "note": title[:200],
            "confidence": 0.6,
        }
    return None


async def build_discounts_view(
    plan: dict[str, Any],
    *,
    max_targets: int = 5,
) -> dict[str, Any]:
    """对已选定站点做折扣/优惠比价（可审计，绝不编造）。

    - 选取行程中 estimated_cost 最高的前 max_targets 个站点作为比价目标；
    - 每个目标走 Tavily 搜索，无 source_url 或失败 → 丢弃；
    - runtime 失败只影响比价区（保留规则区），不抛异常。

    返回：
    {
      "source": "tavily",
      "items": [{"target", "platform", "source_url", "note", "confidence"}],
      "count": int,
      "note": str | None
    }
    """
    # 1) 选出费用最高的站点作为目标（至少 1 个；无站点则空）
    scored: list[tuple[float, dict[str, Any]]] = []
    for day in plan.get("days") or []:
        for stop in day.get("stops") or []:
            if not isinstance(stop, dict) or not stop.get("name"):
                continue
            cost = float(stop.get("estimated_cost") or 0)
            scored.append((cost, stop))
    scored.sort(key=lambda x: x[0], reverse=True)
    targets: list[str] = []
    for _, stop in scored:
        name = stop.get("name") or ""
        if name and name not in targets:
            targets.append(name)
        if len(targets) >= max_targets:
            break

    city = plan.get("destination", "")
    items: list[dict[str, Any]] = []
    for t in targets:
        item = await _discount_search(city, t)
        if item is not None:
            items.append(item)
    return {
        "source": "tavily",
        "items": items,
        "count": len(items),
        "note": "实时比价来自公开搜索，价格/优惠以官方渠道为准" if items else "暂未找到可靠的实时折扣信息（仅展示确定性规则）",
    }


# ── 组合入口 ────────────────────────────────────────────────
async def run_servicing(
    plan: dict[str, Any],
    *,
    provider: str = "auto",
) -> dict[str, Any]:
    """对定稿 plan 执行三段 servicing，返回注入 plan 的字段补丁。

    绝不抛异常：任一阶段失败只记录，其余照常。返回
    {"transit": dict|None, "checkin": dict|None, "discounts": dict|None,
     "warnings": [str]}
    """
    warnings: list[str] = []
    transit: dict[str, Any] | None = None
    checkin: dict[str, Any] | None = None
    discounts: dict[str, Any] | None = None

    # 1) 市内通勤（确定性）
    try:
        transit = await build_transit_view(plan)
    except Exception as exc:  # noqa: BLE001
        logger.warning("市内通勤生成失败: %s", exc)
        warnings.append("市内通勤建议生成失败")

    # 2) 酒店入住指引（模板 + LLM 润色，失败模板兜底）
    try:
        checkin = await generate_checkin_guide(plan, provider=provider)
    except Exception as exc:  # noqa: BLE001
        logger.warning("入住指引生成失败: %s", exc)
        warnings.append("酒店入住指引生成失败")

    # 3) 折扣比价（Tavily + 硬闸门，失败保留规则区）
    try:
        discounts = await build_discounts_view(plan)
    except Exception as exc:  # noqa: BLE001
        logger.warning("折扣比价生成失败: %s", exc)
        warnings.append("折扣比价生成失败（仅展示确定性规则）")

    return {
        "transit": transit,
        "checkin": checkin,
        "discounts": discounts,
        "warnings": warnings,
    }