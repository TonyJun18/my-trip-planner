"""对话助手行程修改工具（方案 2：读写打通，两阶段 HITL）。

设计文档：``docs/chat-trip-data-flow-design.md``（2026-10-28，方案 1 + 2）。

解决的问题：方案 1 让助手能读行程，但不能改。本工具把「对话即编辑」
落到真实的行程数据上——LLM 只产出结构化 diff（op=replace/add/remove/reorder），
代码应用（复用 ``revise_service`` 的原子 diff 管线 + DrivingGate + 预算重算 + 快照回填）。

两阶段 HITL（键盘式确认，非弹窗审批）：
- ``confirm=false``（预览轮）：LLM 理解用户请求 → 产出 diff → 本工具运行
  预检 + DrivingGate + 预算试算，**只返回预览卡片，不落库**。
  预览用独立 db session（``db.session_factory``）装载行程副本，避免污染
  请求级事务，并在预览后丢弃（绝无隐藏副作用）。
- ``confirm=true``（应用轮）：用户按预览卡片「确认应用」→ 助手再次调用
  本工具（带确认 + ``expected_updated_at`` 基线）→ 复用 revise 管线原子写入
  + 预算重算 + TripPlan 快照回填 + TripEvent 留痕。
  有副作用 → ``retryable=False``（AgentLoop 注释契约：有副作用绝不重试）。

并发防护：应用轮校验 ``expected_updated_at == trip.updated_at``，不匹配拒绝，
避免对话期间地图拖拽/AI 修订造成的计划漂移。

输出契约（结构化 JSON，前端渲染确认卡片）：
- preview:  {applied:false, status:"preview", driving, changed, budget_delta, expected_updated_at, next_step}
- rejected: {applied:false, status:"rejected", driving, hint}
- applied:  {applied:true,  status:"applied", applied_at, new_updated_at, plan_version, changed}
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.agent.runtime import AgentTool
from app.core.exceptions import AppError
from app.core.logging import get_logger
from app.models import Trip
from app.services import revise_service as _rs

logger = get_logger(__name__)


# ═══════════════════════════════════════════════════════════
#  参数模型（AgentTool.parameters → JSON schema → 强校验）
# ═══════════════════════════════════════════════════════════
class DiffAction(BaseModel):
    """一个 diff 动作（与 revise_service 契约一致）。"""

    op: Literal["replace", "add", "remove", "reorder"] = Field(description="操作类型")
    day_number: int | None = Field(default=None, description="目标天（1-based）")
    target: dict[str, Any] | None = Field(default=None, description="目标站点定位（name 或 index）")
    fields: dict[str, Any] | None = Field(default=None, description="新增/变更字段（replace/add）")
    index: int | None = Field(default=None, description="目标位置（reorder / add 的插入位置，1-based）")


class EditTripParams(BaseModel):
    """edit_trip 参数。"""

    trip_id: str | None = Field(default=None, description="行程 ID；缺省使用会话绑定行程")
    confirm: bool = Field(default=False, description="false=预览（不落库）；true=应用（需 expected_updated_at）")
    expected_updated_at: str | None = Field(default=None, description="应用轮校验基线（预览轮返回的 updated_at）")
    summary: str | None = Field(default=None, max_length=200, description="本次修改的一句话摘要（事件流留痕）")
    actions: list[DiffAction] = Field(default_factory=list, description="diff 动作列表（1-20 个）")


# ═══════════════════════════════════════════════════════════
#  预览轮（confirm=false）：独立事务，不落库
# ═══════════════════════════════════════════════════════════
async def _preview_edit(
    db,
    owner: str | None,
    trip_id: str,
    actions: list[dict[str, Any]],
    summary: str,
) -> dict[str, Any]:
    """预览轮：加载行程副本 → 预检 + DrivingGate + 预算试算 → 返回预览，不落库。

    使用 ``db.session_factory`` 开一个独立 session 装载行程，所有修改在这
    个副本上进行，函数退出即回滚——对请求级事务零影响，绝不产生隐藏副作用。
    """
    factory = getattr(db, "session_factory", None)
    if factory is None:
        raise AppError(
            "预览轮需要 session_factory（当前请求不支持独立事务）",
            code="chat_edit_no_factory",
        )

    async with factory() as preview_db:
        # 装载行程副本（owner 隔离）
        try:
            trip = await _rs._load_trip(preview_db, trip_id, owner=owner)
        except Exception as exc:  # noqa: BLE001 — 结构性失败：行程不存在/无权限
            return {
                "applied": False,
                "status": "error",
                "error": "trip_not_found",
                "detail": f"行程不存在或无权限访问（{exc}）",
            }

        diff: dict[str, Any] = {
            "actions": [dict(a) for a in actions],
            "summary": summary or "对话修改行程",
        }
        try:
            _rs._apply_diff(trip, diff)
        except AppError as exc:
            return {
                "applied": False,
                "status": "rejected",
                "error": exc.code or "revise_apply_failed",
                "detail": str(exc),
                "hint": "请核对站点名称/天数与当前行程一致后重试",
            }
        except Exception as exc:  # noqa: BLE001 — 未知应用失败
            logger.warning("chat_edit 预览应用失败 trip=%s: %s", trip_id, exc)
            return {
                "applied": False,
                "status": "error",
                "error": "apply_failed",
                "detail": str(exc),
            }

        # DrivingGate：拒绝 → 返回 issues，不落库
        try:
            await _rs._enforce_driving_constraints(trip)
        except AppError as exc:
            driving = (getattr(exc, "detail", None) or {}).get("driving", {})
            return {
                "applied": False,
                "status": "rejected",
                "error": exc.code or "revise_driving_violation",
                "detail": str(exc),
                "driving": driving,
                "hint": "修改后的站点组合超出自驾约束（超距/超时），请缩小范围或调整顺序后重试",
            }

        # 预算试算：用副本的快照（_plan_snapshot 预算硬编码 0.0 → 用代码重算）
        from app.agent.tools import compute_budget

        all_stops = [
            {"name": s.name, "type": s.stop_type, "estimated_cost": float(s.estimated_cost or 0)}
            for d in trip.days
            for s in d.stops
        ]
        budget = compute_budget(all_stops)

        changed = _rs._describe_actions(diff, locale="zh-CN")
        updated_at = trip.updated_at.isoformat() if trip.updated_at else None
        return {
            "applied": False,
            "status": "preview",
            "driving": {"ok": True, "issues": []},
            "changed": changed,
            "budget_delta": {"total_estimated": budget.get("total_estimated", 0.0)},
            "expected_updated_at": updated_at,
            "next_step": "回复确认后我才会应用此修改",
        }


# ═══════════════════════════════════════════════════════════
#  应用轮（confirm=true）：复用 revise 管线，原子落库
# ═══════════════════════════════════════════════════════════
async def _apply_edit(
    db,
    owner: str | None,
    trip_id: str,
    actions: list[dict[str, Any]],
    summary: str,
    expected_updated_at: str | None,
) -> dict[str, Any]:
    """应用轮：校验并发基线 → 复用 revise 原子管线 → 落库 + 快照回填 + 事件留痕。"""
    # 1) 加载 + 并发校验（owner 隔离）
    try:
        trip = await _rs._load_trip(db, trip_id, owner=owner)
    except Exception as exc:  # noqa: BLE001
        return {
            "applied": False,
            "status": "error",
            "error": "trip_not_found",
            "detail": f"行程不存在或无权限访问（{exc}）",
        }

    current_updated = trip.updated_at.isoformat() if trip.updated_at else None
    if expected_updated_at and current_updated and expected_updated_at != current_updated:
        return {
            "applied": False,
            "status": "conflict",
            "error": "trip_updated",
            "detail": "行程在预览后被修改过（地图拖拽/AI 修订），请重新预览后再确认",
            "current_updated_at": current_updated,
        }

    diff: dict[str, Any] = {
        "actions": [dict(a) for a in actions],
        "summary": summary or "对话修改行程",
    }

    # 2) 复用 revise 管线：原子应用 + DrivingGate + 预算重算 + 快照回填（同事务）
    try:
        _rs._apply_diff(trip, diff)
    except AppError as exc:
        return {
            "applied": False,
            "status": "rejected",
            "error": exc.code or "revise_apply_failed",
            "detail": str(exc),
            "hint": "请核对站点名称/天数与当前行程一致后重试",
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("chat_edit 应用失败 trip=%s: %s", trip_id, exc)
        return {
            "applied": False,
            "status": "error",
            "error": "apply_failed",
            "detail": str(exc),
        }

    try:
        await _rs._enforce_driving_constraints(trip)
    except AppError as exc:
        await db.rollback()  # 被门拒 → 丢弃未提交变更
        driving = (getattr(exc, "detail", None) or {}).get("driving", {})
        return {
            "applied": False,
            "status": "rejected",
            "error": exc.code or "revise_driving_violation",
            "detail": str(exc),
            "driving": driving,
            "hint": "修改后的站点组合超出自驾约束（超距/超时），请缩小范围或调整顺序后重试",
        }

    # 3) 落库（复用管线：预算重算 + 快照回填 + 事件留痕）
    await db.flush()
    await _rs._recompute_budget(db, trip)
    await db.commit()

    # 4) 事件留痕（append-only，失败静默）
    try:
        from app.services.event_service import record_event

        await record_event(
            db,
            trip_id=trip.id,
            event_type="chat_edit",
            payload={
                "summary": diff["summary"][:200],
                "ops": len(diff["actions"]),
                "actor": owner,
            },
            commit=False,
        )
        await db.commit()
    except Exception:  # noqa: BLE001 — 事件失败不阻断修改本身
        logger.debug("chat_edit 事件记录失败 trip=%s", trip_id, exc_info=True)
        await db.rollback()

    # 5) 组装响应（终态快照：重新加载保证新鲜）
    fresh = await _rs._load_trip(db, trip_id, owner=owner)
    new_updated = fresh.updated_at.isoformat() if fresh.updated_at else None
    changed = _rs._describe_actions(diff, locale="zh-CN")
    return {
        "applied": True,
        "status": "applied",
        "applied_at": datetime.now(timezone.utc).isoformat(),
        "new_updated_at": new_updated,
        "plan_version": 1,  # 占位：TripPlan 快照每次重算，版本由前端/事件流体现
        "changed": changed,
    }


async def _edit_trip(
    db,
    owner: str | None,
    trip_id: str | None,
    confirm: bool,
    expected_updated_at: str | None,
    summary: str | None,
    actions: list[dict[str, Any]],
) -> str:
    """edit_trip 执行入口：路由到预览轮或应用轮。"""
    if not trip_id:
        return _json_dumps({
            "applied": False,
            "status": "error",
            "error": "missing_trip_id",
            "detail": "未提供行程 ID，请先绑定或调用 get_my_trips",
        })
    if not actions:
        return _json_dumps({
            "applied": False,
            "status": "error",
            "error": "empty_actions",
            "detail": "未提供任何修改动作",
        })

    # AgentLoop 执行前已 model_validate().model_dump() → 收到的是 list[dict]；
    # 直接调用（绕过 AgentLoop）时可能是 DiffAction 或单个对象 → 统一归一化为 list[dict]。
    if not isinstance(actions, list):
        actions = [actions]
    normalized = []
    for a in actions:
        dumper = getattr(a, "model_dump", None)
        normalized.append(dumper(exclude_none=True) if dumper else dict(a))

    if confirm:
        result = await _apply_edit(
            db, owner, trip_id, normalized, summary or "", expected_updated_at
        )
    else:
        result = await _preview_edit(db, owner, trip_id, normalized, summary or "")

    logger.info(
        "chat_edit trip=%s confirm=%s status=%s ops=%d owner=%s",
        trip_id, confirm, result.get("status"), len(normalized), owner or "anon",
    )
    return _json_dumps(result)


def _json_dumps(data: dict[str, Any]) -> str:
    import json

    return json.dumps(data, ensure_ascii=False)


def make_edit_tool(*, db, owner: str | None, trip_id: str | None = None) -> AgentTool:
    """构造 edit_trip 工具（写操作：retryable=False）。

    trip_id 为会话绑定行程；用户显式传入其他 trip_id 也允许（只要属于该 owner）。
    """
    bound_trip_id = trip_id

    async def _execute(
        trip_id: str | None = None,
        confirm: bool = False,
        expected_updated_at: str | None = None,
        summary: str | None = None,
        actions: list[dict[str, Any]] | None = None,
    ) -> str:
        effective = trip_id or bound_trip_id
        return await _edit_trip(
            db,
            owner,
            effective,
            confirm,
            expected_updated_at,
            summary,
            actions or [],
        )

    return AgentTool(
        name="edit_trip",
        description=(
            "修改用户的行程（按 diff 动作：replace/add/remove/reorder）。"
            "两阶段确认：confirm=false 先预览（不落库，返回修改预览）；"
            "用户明确确认后以 confirm=true + expected_updated_at 再次调用才应用。"
            "修改受自驾约束门控（超距/超时会被拒绝）。有副作用，绝不自动重试。"
        ),
        execute=_execute,
        parameters=EditTripParams,
        retryable=False,
    )