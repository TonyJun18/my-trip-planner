"""Agent Pipeline：声明式步骤编排（方案 A：Agent 平台化第一步）。

目标：把 ``app/agent/agents.py`` 里 1,849 行手写 asyncio 编排收敛为
「声明 steps → 调度器执行」的显式流水线，新增 Agent 只需注册一个步骤。

设计：
- ``PipelineStep``：一个编排阶段（采集 / 整合 / 质检 / 门控 / 服务化）
  - ``name``：步骤名（trace / 事件里标注）
  - ``deps``：并行依赖的上游步骤产物 key（fan-in 用）
  - ``run(ctx)``：执行此步骤（可并行调用子 agent）
- ``PlanningPipeline``：步骤注册表 + 执行器
  - 顺序步骤依次执行；``deps`` 非空的步骤并行 fan-in
  - 步骤产物写入 ``ctx.artifacts``（结构化传递，下游步骤按需取用）
  - 每步完成/失败发出结构化 trace（与 agents.py 现有事件契约一致）

当前落地范围（渐进迁移）：
- 先承接采集段（attraction/weather/hotel/food/transport/discount 六路并行
  + foods 降级补位）；Planner/Critic/DrivingGate/TimeGate 等后续步骤逐段迁移，
  迁移前保持 agents.py 现有实现不变（本文件仍为骨架 + 采集步骤）。

关键契约（与 agents.py 对齐）：
- trace 每步带 ``agent`` / ``action`` / ``observation`` / ``status``
- 步骤失败不整体阻断：采集步骤失败由编排层降级补位（foods fallback）
- 事件：步骤开始时发 ``phase`` running，完成后发 ``phase`` completed
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)


class PipelineContext:
    """一次规划运行的上下文：请求 + 步骤产物 + trace。"""

    def __init__(self, request: dict[str, Any]) -> None:
        self.request = request
        self.artifacts: dict[str, Any] = {}     # 步骤产物（key = step.name）
        self.trace: list[dict[str, Any]] = []   # 结构化 trace（与 agents.py 对齐）
        # 错误收集（并行步骤中部分失败不整体抛错；由依赖方决定是否降级）
        self.errors: dict[str, str] = {}

    def put(self, key: str, value: Any) -> None:
        self.artifacts[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        return self.artifacts.get(key, default)

    def append_trace(self, entry: dict[str, Any]) -> None:
        self.trace.append(entry)


@dataclass
class PipelineStep(ABC):
    """一个编排步骤。

    - ``name``：唯一步骤名（作为 artifacts 的 key）
    - ``deps``：并行依赖的上游步骤名；为空表示顺序步骤（在执行器中按序跑）
    - ``on_failure``：步骤失败时的降级策略（默认 ``raise``；采集步骤用 ``degrade``）
    """

    name: str
    deps: list[str] = field(default_factory=list)
    on_failure: str = "raise"  # raise | degrade | ignore

    @abstractmethod
    async def run(self, ctx: PipelineContext, **kwargs: Any) -> Any:
        """执行本步骤，返回产物（写入 ctx.artifacts[name]）。"""


class PlanningPipeline:
    """步骤注册表 + 执行器。

    用法：:

        pipe = PlanningPipeline()
        pipe.add(CollectAttractionsStep())
        pipe.add(PlannerStep(deps=["collect"]))
        result = await pipe.run(request)
    """

    def __init__(self) -> None:
        self._steps: dict[str, PipelineStep] = {}

    def add(self, step: PipelineStep) -> None:
        self._steps[step.name] = step

    def _check_deps(self, step: PipelineStep) -> None:
        missing = [d for d in step.deps if d not in self._steps]
        if missing:
            raise ValueError(f"步骤 {step.name} 依赖未注册: {missing}")

    async def run(self, request: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        """顺序 + 依赖并行执行全部步骤（kwargs 透传给每个 step.run）。"""
        ctx = PipelineContext(request)
        for name, step in self._steps.items():
            self._check_deps(step)
        # 当前实现：顺序执行（后续按 deps 分波并行 fan-in）
        for name, step in self._steps.items():
            logger.info("pipeline step=%s start", name)
            try:
                result = await step.run(ctx, **kwargs)
                ctx.put(name, result)
            except Exception as exc:
                ctx.errors[name] = str(exc)
                if step.on_failure == "raise":
                    raise
                logger.warning("pipeline step=%s degraded err=%s", name, exc)
            logger.info("pipeline step=%s done", name)
        return {
            "artifacts": ctx.artifacts,
            "trace": ctx.trace,
            "status": "completed" if not ctx.errors else "degraded",
            "errors": ctx.errors,
        }


# ── 采集步骤（首批迁移：六路并行 + foods 降级） ─────────────────
@dataclass
class CollectAgentsStep(PipelineStep):
    """采集阶段：六个 Agent 并行执行（景点/天气/酒店/美食/大交通/折扣）。

    产物写入 ctx.artifacts["collect"]：
    {attractions, weather, hotels, foods, transport, discount}（各自为 agent 返回 dict）
    trace 由主流程（agents.py run_planning_agents）统一打点（保持本地化文案契约），
    本步骤不重复发 trace / artifact / phase。

    失败策略：单 agent 异常不整体抛错（return_exceptions），产物标记 failed，
    由依赖方（foods 降级补位等）决定如何处理——系统始终产出某种东西。
    """

    def __init__(self) -> None:
        super().__init__(name="collect", deps=[], on_failure="degrade")

    async def run(self, ctx: PipelineContext, **kwargs: Any) -> Any:
        from app.agent.agents import (
            _accommodation_hints,
            _food_hints,
            attraction_agent,
            discount_agent,
            flight_deal_agent,
            food_agent,
            hotel_agent,
            transport_agent,
            weather_agent,
        )
        from app.i18n import normalize_locale
        from app.i18n.prompts import preference_keys_to_keywords

        city = ctx.request.get("destination", "")
        prefs = ctx.request.get("preferences") or []
        provider = kwargs.get("provider", "auto")
        max_iterations = kwargs.get("max_iterations")

        # 偏好关键词（语言无关契约；与 agents.py _request_locale 同口径）
        locale = normalize_locale(ctx.request.get("language"))
        pref_keywords = preference_keys_to_keywords(locale, prefs)

        tasks = {
            "attractions": attraction_agent(city, pref_keywords, request=ctx.request, provider=provider, max_iterations=max_iterations),
            "weather": weather_agent(city),
            "hotels": hotel_agent(city, _accommodation_hints(ctx.request), request=ctx.request, provider=provider, max_iterations=max_iterations),
            "foods": food_agent(city, _food_hints(pref_keywords), request=ctx.request, provider=provider, max_iterations=max_iterations),
            "transport": transport_agent(ctx.request.get("departure"), city, date=ctx.request.get("start_date"), provider=provider, max_iterations=max_iterations),
            "discount": discount_agent(city),
            # 机票特价（确定性搜索+抽取；无出发地/失败只降级，不阻塞其余六路）
            "flights": flight_deal_agent(ctx.request),
        }
        import asyncio

        gathered = await asyncio.gather(*tasks.values(), return_exceptions=True)
        results: dict[str, Any] = {}
        for key, res in zip(tasks.keys(), gathered):
            if isinstance(res, Exception):
                results[key] = {"status": "failed", "error": str(res)}
            else:
                results[key] = res
        return results


async def run_collect_stage(
    request: dict[str, Any],
    *,
    provider: str = "auto",
    max_iterations: int | None = None,
) -> dict[str, Any]:
    """便捷入口：只跑采集阶段（prod 路径由 agents.py 调用，保持事件/制品契约不变）。"""
    pipe = PlanningPipeline()
    pipe.add(CollectAgentsStep())
    result = await pipe.run(request, provider=provider, max_iterations=max_iterations)
    return result["artifacts"].get("collect") or {}


# ── 评审循环步骤（第二批迁移：Planner → DrivingGate → Critic → fix） ──
@dataclass
class PlanAssembleStep(PipelineStep):
    """Planner 整合 + Evaluator-Optimizer 评审循环 + 自驾 DrivingGate。

    **依赖注入（由调用方先行准备，本步骤不重复执行）**：
    - ``materials``（kwargs）：采集产物组装的材料（attractions/hotels/foods/weather/transport/discount_rules）
    - ``trace``（kwargs）：追加 trace 的目标列表（与 agents.py 主流程共享同一 trace）

    循环语义（与 agents.py 原实现等价）：
    - Planner 生成 → 预算校准（compute_budget + 大交通往返价）→ DrivingGate 自驾校验
      （未过且还有轮次 → 带自驾反馈重生成，不进 Critic 省 token）
    - TravelCriticAgent 评审：通过/无待修改项 → 定稿；不通过 → 优先应用 Critic fix
      （站点级精确修订），fix 失败回退整段重生成；达 max_review_rounds 强制定稿
    - ``plan.quality`` 由本步骤注入（_plan_quality 汇总 review_history）

    事件/制品/WS 推送：惰性调用 agents.py 模块级 ``_fire_phase`` / ``_fire_artifact`` /
    ``_emit_plan_event``，保持现有前端阶段视图契约。

    返回：``{plan, status, error, review_rounds, review_history, driving_reports, planner_status}``
    （plan=None 表示规划失败；调用方据此返回 failed 终态）
    """

    def __init__(self) -> None:
        super().__init__(name="assemble", deps=[], on_failure="raise")

    async def run(self, ctx: PipelineContext, **kwargs: Any) -> Any:
        from app.agent import agents as A
        from app.agent import tools as agent_tools
        from app.agent.agents import (
            _critic_feedback,
            _driving_feedback,
            _has_actionable_issues,
            _normalize_hotels,
            _pass_critique,
            _plan_quality,
            critic_agent,
            planner_agent,
        )
        from app.i18n.translations import t
        from app.services import budget_service
        from app.services.driving_service import check_plan_driving_async

        request = ctx.request
        locale = A._request_locale(request)
        provider = kwargs.get("provider", "auto")
        max_corrections = kwargs.get("max_corrections", 3)
        max_review_rounds = kwargs.get("max_review_rounds", 2)
        trace = kwargs.get("trace") or ctx.trace
        materials: dict[str, Any] = kwargs.get("materials") or {}

        def _append_trace(entry: dict[str, Any]) -> None:
            """追加一条 trace 并向 WS 订阅者实时推送（推送失败不影响主流程）。"""
            trace.append(entry)
            import asyncio

            asyncio.create_task(A._emit_plan_event({"type": "trace", "trace": entry}))

        # ── 评审循环（原 agents.py run_planning_agents 第 3 段，原样迁移）──
        plan: dict[str, Any] | None = None
        planner: dict[str, Any] = {"status": "failed", "error": "未执行"}
        review_rounds = 0
        review_history: list[dict[str, Any]] = []
        driving_reports: list[dict[str, Any]] = []

        for round_idx in range(max_review_rounds + 1):
            review_feedback = _critic_feedback(review_history[-1], locale) if review_history else None
            if round_idx > 0:
                A._fire_phase("reviewing", "running")
                A._fire_phase("assembling", "running")
            planner = await planner_agent(
                request, materials, provider=provider, max_corrections=max_corrections,
                review_feedback=review_feedback,
            )
            _append_trace({
                "agent": "PlannerAgent",
                "action": "integrate" if round_idx == 0 else f"revise (round {round_idx})",
                "observation": (
                    f"integrate {len(materials.get('attractions', []))} attractions / {len(materials.get('hotels', []))} hotels / {len(materials.get('foods', []))} restaurants"
                    + ("; revised per review" if round_idx > 0 else "")
                ),
                "status": planner.get("status"),
            })
            if planner.get("status") != "completed" or planner.get("plan") is None:
                return {
                    "plan": None, "status": "failed",
                    "error": planner.get("error") or t(locale, "agent.ctx.planner_failed"),
                    "review_rounds": review_rounds, "review_history": review_history,
                    "driving_reports": driving_reports, "planner_status": planner.get("status"),
                }

            candidate = planner["plan"]

            # 预算校准前置：全口径（站级兜底 + 住宿缺口 + 大交通 + 对账），
            # 与详情页 GET /budget / 修订后 / 分享页一致（compute_full_budget）。
            candidate["budget"] = budget_service.compute_full_budget(
                days=candidate.get("days", []),
                start_date=request.get("start_date"),
                end_date=request.get("end_date"),
                destination=request.get("destination"),
                travelers=request.get("travelers", 1),
                planned=request.get("budget"),
                plan_data=materials.get("transport") and {"transport": materials.get("transport")} or None,
            )
            candidate["hotels"] = _normalize_hotels(materials.get("hotels") or [])

            # 行程草案制品（每代都发；前端「编排阶段」实时展示天数/主题）
            A._fire_artifact("draft", {
                "days": len(candidate.get("days", [])),
                "themes": [f"Day {d.get('day_number')} {d.get('theme') or ''}".strip()
                           for d in candidate.get("days", [])][:10],
                "round": round_idx + 1,
            })
            if round_idx == 0:
                A._fire_phase("assembling", "completed", summary=t(locale, "plan.phase.assembling.draft", n=len(candidate.get("days", []))))

            # ── DrivingGate：自驾约束校验（确定性代码）──
            driving = await check_plan_driving_async(candidate, locale=locale)
            driving_reports.append(driving)
            if not driving["passed"] and round_idx < max_review_rounds:
                # 拒绝该站点组合：带自驾反馈重新生成（不进 Critic，省一次评审 token）
                logger.info("自驾校验未通过 round=%d critical=%d，进入修订", round_idx + 1, driving["critical_count"])
                _append_trace({
                    "agent": "DrivingGate",
                    "action": "check_driving",
                    "observation": (
                        t(locale, "plan.trace.driving.fail",
                          n=driving["critical_count"], summary=driving["summary"])
                    ),
                    "status": "failed",
                })
                review_history.append(_driving_feedback(driving, locale))  # 作为修订反馈
                review_rounds += 1
                continue

            review_rounds += 1

            # 交给 TravelCriticAgent 评审（最后一代无需再评：强制定稿）
            if round_idx >= max_review_rounds:
                plan = candidate
                _append_trace({"agent": "TravelCriticAgent", "action": "review",
                              "observation": t(locale, "plan.trace.review.max_rounds", n=max_review_rounds), "status": "completed"})
                break

            critic = await critic_agent(request, candidate, provider=provider)
            critique = critic.get("critique") or _pass_critique(t(locale, "agent.ctx.planner_review_degraded"))
            review_history.append(critique)
            n_issues = len(critique.get("issues") or [])
            # 质检评分制品：前端「AI 质检」阶段实时展示分数与问题数
            A._fire_artifact("quality", {
                "score": critique.get("score"),
                "passed": bool(critique.get("passed")),
                "round": round_idx + 1,
                "max_rounds": max_review_rounds,
                "issues": critique.get("issues") or [],
            })
            if round_idx == 0:
                A._fire_phase("reviewing", "completed", summary=t(locale, "plan.phase.reviewing.score", score=critique.get("score")))
            _append_trace({
                "agent": "TravelCriticAgent",
                "action": "review",
                "observation": (
                    t(locale, "plan.trace.review.score",
                      score=critique.get("score"),
                      n=len([i for i in critique.get("issues") or [] if i.get("severity") in ("critical", "warning")]))
                    + (f"（{critique.get('summary') or ''}）" if critique.get("summary") else "")
                ),
                "status": "completed" if critic.get("status") == "completed" else "degraded",
            })

            if critique.get("passed") or n_issues == 0 or not _has_actionable_issues(critique):
                plan = candidate
                break  # 质检通过 / 无待修改项 → 定稿

            logger.info("行程评审未通过 round=%d score=%s issues=%d，进入下一轮修订",
                        round_idx + 1, critique.get("score"), n_issues)

            # ── Critic 协作者：优先应用精确修订 diff（复用修订执行器语义）──
            fix = critique.get("fix")
            if isinstance(fix, dict) and fix.get("actions"):
                applied = A._apply_critic_fix(candidate, fix)
                if applied:
                    review_history[-1] = {**critique, "fix_applied": True}
                    plan = candidate
                    _append_trace({
                        "agent": "TravelCriticAgent",
                        "action": "apply_fix",
                        "observation": (
                            t(locale, "plan.trace.review.fix_applied", n=len(fix.get("actions") or []))
                            + (f"（{fix.get('summary') or ''}）" if fix.get("summary") else "")
                        ),
                        "status": "completed",
                    })
                    break  # 已按 Critic 指令修正 → 定稿
                logger.info("Critic fix 应用失败，回退 Planner 整段重生成 (round=%d)", round_idx + 1)

        # 兜底：若循环异常退出（理论上不会），仍保留最后一代
        if plan is None:
            return {
                "plan": None, "status": "failed",
                "error": t(locale, "plan.error.qa_loop_exit"),
                "review_rounds": review_rounds, "review_history": review_history,
                "driving_reports": driving_reports, "planner_status": planner.get("status"),
            }

        # 质检摘要注入 plan.quality（随 plan JSON 落库，前端可直接消费）
        plan["quality"] = _plan_quality(review_history, review_rounds, max_review_rounds)

        return {
            "plan": plan, "status": "completed", "error": None,
            "review_rounds": review_rounds, "review_history": review_history,
            "driving_reports": driving_reports, "planner_status": planner.get("status"),
        }


async def run_assemble_stage(
    request: dict[str, Any],
    materials: dict[str, Any],
    *,
    trace: list[dict[str, Any]] | None = None,
    provider: str = "auto",
    max_corrections: int = 3,
    max_review_rounds: int = 2,
) -> dict[str, Any]:
    """便捷入口：只跑评审循环阶段（prod 路径由 agents.py 调用，保持事件/制品契约不变）。"""
    pipe = PlanningPipeline()
    pipe.add(PlanAssembleStep())
    result = await pipe.run(
        request,
        materials=materials, trace=trace or [], provider=provider,
        max_corrections=max_corrections, max_review_rounds=max_review_rounds,
    )
    return result["artifacts"].get("assemble") or {"plan": None, "status": "failed"}


# ── 定稿后处理（第三批迁移：finalize 回填 + 确定性门控） ─────────
@dataclass
class FinalizePlanStep(PipelineStep):
    """定稿后处理：采集产物回填 + 自驾报告注入 + MultiCity/TimeGate/DynamicFacts 门控。

    **依赖注入（kwargs）**：
    - ``plan``：已通过评审循环的候选（原地修改并返回）
    - ``t_res`` / ``d_res``：采集阶段 transport / discount 产物（回填用）
    - ``driving_reports``：评审循环各代自驾报告（最终代注入 plan.driving）
    - ``trace``：追加 trace 的目标列表

    门控语义（与 agents.py 原实现等价）：全部只报告不阻断——
    插件式规则库（MultiCity 分段 / TimeGate 营业校验 / DynamicFacts 日期特例），
    任一失败降级为 warnings，绝不整体失败。

    依赖关系：``deps`` 留空——本步骤通过 kwargs 接收上游产物（plan / t_res /
    d_res / driving_reports），顺序由调用方（agents.py 主流程）编排保证。
    返回：原地修改后的 ``plan``。
    """

    def __init__(self) -> None:
        super().__init__(name="finalize", deps=[], on_failure="degrade")

    async def run(self, ctx: PipelineContext, **kwargs: Any) -> Any:
        from app.agent import agents as A
        from app.i18n.translations import t

        request = ctx.request
        locale = A._request_locale(request)
        plan = kwargs.get("plan")
        if plan is None:
            raise ValueError("FinalizePlanStep 需要 plan（来自 assemble 步骤）")
        t_res = kwargs.get("t_res") or {}
        d_res = kwargs.get("d_res") or {}
        driving_reports = kwargs.get("driving_reports") or []
        # trace: 显式传入（可能为空 list）优先；仅当 None 时用 ctx.trace。
        # 不能写 `or ctx.trace`——空 list 是 falsy 会被替换，导致 append 丢失。
        trace_arg = kwargs.get("trace")
        trace: list = trace_arg if trace_arg is not None else ctx.trace

        def _append_trace(entry: dict[str, Any]) -> None:
            trace.append(entry)
            import asyncio

            asyncio.create_task(A._emit_plan_event({"type": "trace", "trace": entry}))

        # ── 采集产物回填（详情页大交通/折扣/天气；预算口径依赖此数据）──
        plan["transport"] = (t_res.get("transport") or {}) if isinstance(t_res, dict) else None
        plan["discount_rules"] = (d_res.get("rules") or []) if isinstance(d_res, dict) else []
        # 机票特价方案（FlightDealAgent；无出发地/降级时为 None，前端不展示卡片）
        fl_res = kwargs.get("f_res")
        plan["flight_deals"] = (fl_res.get("flight_deals") or None) if isinstance(fl_res, dict) else None
        # 天气快照回填：WeatherGate 消费 plan.weather（降水/酷暑 → 室内替代建议）；
        # 同时供行中「今日天气卡」与导出快照使用（weather_card 纯函数读取）。
        w_res = kwargs.get("w_res")
        plan["weather"] = (w_res.get("weather") or {}) if isinstance(w_res, dict) else {}
        # 自驾校验报告注入 plan.driving（最终一代；历史各代摘要进 driving_history）
        if driving_reports:
            final_driving = driving_reports[-1]
            plan["driving"] = {
                **{k: v for k, v in final_driving.items() if k != "legs"},
                "legs": final_driving.get("legs") or [],
                "history": [{"passed": r.get("passed"), "critical_count": r.get("critical_count"),
                             "summary": r.get("summary")} for r in driving_reports],
            }
            _append_trace({
                "agent": "DrivingGate",
                "action": "check_driving",
                "observation": (
                    (t(locale, "plan.trace.driving.pass") if final_driving["passed"] else t(locale, "plan.trace.driving.warn", n=final_driving["critical_count"]))
                    + t(locale, "plan.trace.driving.distance", km=final_driving["total_km"])
                ),
                "status": "completed" if final_driving["passed"] else "warning",
            })

        # 阶段收尾：assembling/reviewing 完成（servicing 阶段事件由 ServicingStep 发）
        A._fire_phase("assembling", "completed", summary=t(locale, "plan.phase.assembling.final", n=len(plan.get("days", []))))
        A._fire_phase("reviewing", "completed", summary=t(locale, "plan.phase.reviewing.completed"))

        # ── MultiCity：多城市分段 + 段间交通占位 + 衔接校验（规则估算，零 LLM）──
        _cities = request.get("cities") or []
        if isinstance(_cities, list) and len(_cities) >= 2:
            from app.services.multi_city import apply_multi_city

            multi_city = apply_multi_city(plan, _cities, locale=locale)
            plan["multi_city"] = {
                **{k: v for k, v in multi_city.items() if k != "issues"},
                "issues": multi_city.get("issues") or [],
                "basis": "rule_based",
            }
            for iss in multi_city.get("issues") or []:
                plan.setdefault("warnings", []).append(
                    f"[{t(locale, 'multicity.summary.warn', n=multi_city.get('warning_count', 0))}] {iss.get('message')}"
                )
            _append_trace({
                "agent": "MultiCity",
                "action": "apply_segments",
                "observation": multi_city.get("summary") or "",
                "status": "completed" if multi_city.get("passed") else "warning",
            })
            A._fire_artifact("multi_city", {
                "enabled": multi_city.get("enabled"),
                "segments": multi_city.get("segments") or [],
                "warning_count": multi_city.get("warning_count", 0),
            })

        # ── TimeGate：营业时间/游玩时长确定性校验（规则库，零 LLM）──
        from app.services.time_validation import check_plan_time_gate

        time_gate = check_plan_time_gate(plan, locale=locale)
        plan["time_gate"] = {
            **{k: v for k, v in time_gate.items() if k != "issues"},
            "issues": time_gate.get("issues") or [],
            "basis": "rule_based",
        }
        for iss in time_gate.get("issues") or []:
            plan.setdefault("warnings", []).append(
                t(locale, "plan.warning.timegate", message=iss.get("message") or "",
                  extra=(t(locale, "plan.warning.timegate.sugg", suggestion=iss.get("suggestion")) if iss.get("suggestion") else ""))
            )
        _append_trace({
            "agent": "TimeGate",
            "action": "check_time",
            "observation": (
                (t(locale, "plan.trace.timegate.pass") if time_gate.get("passed") else t(locale, "plan.trace.timegate.warn", n=time_gate.get("warning_count", 0)))
                + t(locale, "plan.trace.timegate.basis")
            ),
            "status": "completed" if time_gate.get("passed") else "warning",
        })
        A._fire_artifact("time_gate", {
            "passed": time_gate.get("passed"),
            "warning_count": time_gate.get("warning_count", 0),
            "issues": time_gate.get("issues") or [],
        })

        # ── DynamicFacts：日期特例规则库校验（周一闭馆/每月免费日/节假日）──
        from app.services.dynamic_facts import check_plan_dynamic_facts

        dyn_facts = check_plan_dynamic_facts(plan, locale=locale)
        plan["dynamic_facts"] = {
            **{k: v for k, v in dyn_facts.items() if k != "issues"},
            "issues": dyn_facts.get("issues") or [],
            "basis": "rule_based",
        }
        for iss in dyn_facts.get("issues") or []:
            plan.setdefault("warnings", []).append(
                t(locale, "plan.warning.dynfacts", message=iss.get("message") or "",
                  extra=(t(locale, "plan.warning.dynfacts.sugg", suggestion=iss.get("suggestion")) if iss.get("suggestion") else ""))
            )
        if dyn_facts.get("issues"):
            _append_trace({
                "agent": "DynamicFacts",
                "action": "check_dynamic_facts",
                "observation": t(locale, "plan.trace.dynfacts.warn", n=dyn_facts.get("warning_count", 0)),
                "status": "warning",
            })
        A._fire_artifact("dynamic_facts", {
            "passed": dyn_facts.get("passed"),
            "warning_count": dyn_facts.get("warning_count", 0),
            "issues": dyn_facts.get("issues") or [],
        })

        # ── WeatherGate：天气感知排程校验（task-weather-gate-eval，2026-11-09）──
        # 雨天/酷暑 → 室内替代建议 warning（预报非事实，只提示不裁决，basis 诚实标注）。
        # 与 TimeGate 同构：只报告不阻断；无对应日期天气数据 → 保持沉默。
        from app.services.weather_validation import check_plan_weather_gate

        weather_gate = check_plan_weather_gate(plan, locale=locale)
        plan["weather_gate"] = {
            **{k: v for k, v in weather_gate.items() if k != "issues"},
            "issues": weather_gate.get("issues") or [],
            "basis": "weather_forecast",
        }
        for iss in weather_gate.get("issues") or []:
            plan.setdefault("warnings", []).append(
                t(locale, "plan.warning.weathergate", message=iss.get("message") or "",
                  extra=(t(locale, "plan.warning.weathergate.sugg", suggestion=iss.get("suggestion")) if iss.get("suggestion") else ""))
            )
        if weather_gate.get("issues"):
            _append_trace({
                "agent": "WeatherGate",
                "action": "check_weather",
                "observation": t(locale, "plan.trace.weathergate.warn", n=weather_gate.get("warning_count", 0)),
                "status": "warning",
            })
        A._fire_artifact("weather_gate", {
            "passed": weather_gate.get("passed"),
            "warning_count": weather_gate.get("warning_count", 0),
            "issues": weather_gate.get("issues") or [],
        })

        # ── RepeatGate：重复站点确定性查重（task-repeat-stop-detector，2026-11-14）──
        # 同一地点重复安排 → warning（同天/相邻天始终检测；远端重复仅长行程）。
        # 与 TimeGate/DynamicFacts 同构：只报告不阻断，basis=rule_based 诚实标注。
        from app.services.repeat_detector import check_plan_repeat_gate

        repeat_gate = check_plan_repeat_gate(plan, locale=locale)
        plan["repeat_gate"] = {
            **{k: v for k, v in repeat_gate.items() if k != "issues"},
            "issues": repeat_gate.get("issues") or [],
            "basis": "rule_based",
        }
        for iss in repeat_gate.get("issues") or []:
            plan.setdefault("warnings", []).append(
                t(locale, "plan.warning.repeatgate", message=iss.get("message") or "",
                  extra=(t(locale, "plan.warning.repeatgate.sugg", suggestion=iss.get("suggestion")) if iss.get("suggestion") else ""))
            )
        if repeat_gate.get("issues"):
            _append_trace({
                "agent": "RepeatGate",
                "action": "check_repeats",
                "observation": t(locale, "plan.trace.repeatgate.warn", n=repeat_gate.get("warning_count", 0)),
                "status": "warning",
            })
        A._fire_artifact("repeat_gate", {
            "passed": repeat_gate.get("passed"),
            "warning_count": repeat_gate.get("warning_count", 0),
            "issues": repeat_gate.get("issues") or [],
        })

        # ── SolverGate：确定性求解（任务floattrip-borrow Story 4）──
        # LLM 候选 → 规则排序 + 时间/距离硬约束校验 + 有限修复。
        # 产出 plan.solver_meta（排序依据/校验结果/修复记录）；不通过 → warnings
        # 注入「确定性校验未通过」，绝不静默当成功（诚实口径，与 TimeGate 同源）。
        from app.services.solver_service import solve

        solver_meta = solve(plan, locale=locale)
        plan["solver_meta"] = solver_meta
        hc = solver_meta.get("hard_constraints") or {}
        if hc.get("passed") is not True:
            n_unresolved = len(hc.get("unresolved") or [])
            plan.setdefault("warnings", []).append(
                t(locale, "plan.warning.solver", n=n_unresolved)
            )
        _append_trace({
            "agent": "SolverGate",
            "action": "solve",
            "observation": (
                t(locale, "plan.trace.solver.pass")
                if hc.get("passed") is True
                else t(locale, "plan.trace.solver.warn", n=len(hc.get("unresolved") or []))
            ),
            "status": "completed" if hc.get("passed") is True else "warning",
        })
        A._fire_artifact("solver", {
            "basis": solver_meta.get("basis"),
            "passed": hc.get("passed"),
            "unresolved_count": len(hc.get("unresolved") or []),
        })

        return plan


async def run_finalize_stage(
    plan: dict[str, Any],
    request: dict[str, Any],
    *,
    trace: list[dict[str, Any]] | None = None,
    t_res: dict[str, Any] | None = None,
    d_res: dict[str, Any] | None = None,
    f_res: dict[str, Any] | None = None,
    w_res: dict[str, Any] | None = None,
    driving_reports: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """便捷入口：定稿后处理（finalize 回填 + 确定性门控）。返回原地修改后的 plan。"""
    pipe = PlanningPipeline()
    pipe.add(FinalizePlanStep())
    await pipe.run(
        request,
        plan=plan,
        # 显式传入的 trace（可为空 list）必须原样透传，不能 `or []`
        # 否则 append 到新列表，调用方拿不到 step 内追加的 trace。
        trace=trace if trace is not None else [],
        t_res=t_res or {}, d_res=d_res or {}, f_res=f_res or {}, w_res=w_res or {},
        driving_reports=driving_reports or [],
    )
    return plan


# ── 第二段 servicing（第四批迁移：定稿后的可执行服务） ────────────
@dataclass
class ServicingStep(PipelineStep):
    """第二段 servicing：市内通勤 / 入住办理 / 折扣比价。

    **依赖注入（kwargs）**：
    - ``plan``：已定稿 plan（原地修改：transit / checkin / discounts 回填）
    - ``provider`` / ``locale``：LLM 提供商与输出语种

    语义（与 agents.py 原实现等价）：消费已定稿 plan，与采集/规划解耦；
    任一失败只记 warnings，绝不阻断主流程。

    依赖关系：``deps`` 留空——plan 经 kwargs 传入，顺序由调用方编排保证。
    """

    def __init__(self) -> None:
        super().__init__(name="servicing", deps=[], on_failure="degrade")

    async def run(self, ctx: PipelineContext, **kwargs: Any) -> Any:
        from app.agent import agents as A
        from app.i18n.translations import t

        request = ctx.request
        locale = A._request_locale(request)
        plan = kwargs.get("plan")
        if plan is None:
            raise ValueError("ServicingStep 需要 plan")
        provider = kwargs.get("provider", "auto")
        trace = kwargs.get("trace") or ctx.trace

        def _append_trace(entry: dict[str, Any]) -> None:
            trace.append(entry)
            import asyncio

            asyncio.create_task(A._emit_plan_event({"type": "trace", "trace": entry}))

        A._fire_phase("servicing", "running")
        from app.services.servicing_service import run_servicing

        servicing = await run_servicing(plan, provider=provider, locale=locale)
        if servicing.get("transit"):
            plan["transit"] = servicing["transit"]
            A._fire_artifact("transit", {
                "count": servicing["transit"].get("count", 0),
                "legs": servicing["transit"].get("legs", [])[:10],
            })
        if servicing.get("checkin"):
            plan["checkin"] = servicing["checkin"]
            A._fire_artifact("checkin", {
                "hotel_name": servicing["checkin"].get("hotel_name"),
                "docs_required": servicing["checkin"].get("docs_required", []),
                "steps": servicing["checkin"].get("steps", [])[:8],
                "source": servicing["checkin"].get("source"),
            })
        if servicing.get("discounts"):
            plan["discounts"] = servicing["discounts"]
            A._fire_artifact("discounts", {
                "count": servicing["discounts"].get("count", 0),
                "items": servicing["discounts"].get("items", [])[:10],
                "note": servicing["discounts"].get("note"),
            })
        _append_trace({
            "agent": "ServicingGate", "action": "servicing",
            "observation": (
                t(locale, "plan.trace.servicing",
                  n=len((servicing.get("transit") or {}).get("legs", [])),
                  checkin=(t(locale, "plan.servicing.checkin.yes") if servicing.get("checkin") else t(locale, "plan.servicing.checkin.degraded")),
                  d=len((servicing.get("discounts") or {}).get("items", [])))
            ),
            "status": "completed" if not servicing.get("warnings") else "warning",
        })
        for w in servicing.get("warnings", []):
            plan.setdefault("warnings", []).append(w)
        A._fire_phase("servicing", "completed", summary=t(
            locale, "plan.phase.servicing.summary",
            n=len((servicing.get("transit") or {}).get("legs", [])),
            src=servicing.get("checkin", {}).get("source", "-"),
            d=len((servicing.get("discounts") or {}).get("items", [])),
        ))
        return plan


async def run_servicing_stage(
    plan: dict[str, Any],
    request: dict[str, Any],
    *,
    trace: list[dict[str, Any]] | None = None,
    provider: str = "auto",
) -> dict[str, Any]:
    """便捷入口：第二段 servicing。返回原地修改后的 plan。"""
    pipe = PlanningPipeline()
    pipe.add(ServicingStep())
    await pipe.run(request, plan=plan, trace=trace or [], provider=provider)
    return plan


# ── 可预订建议（第五批：BookingStep——纯规则零 LLM，失败降级不阻断） ──
@dataclass
class BookingStep(PipelineStep):
    """预订化收尾：从定稿 plan 产出可预订外链建议（plan.bookings）。

    **依赖注入（kwargs）**：
    - ``plan``：已定稿 plan（原地修改：``bookings`` 回填为 BookingSuggestedOut 列表）

    设计（与 servicing 同哲学，零 LLM）：
    - 大交通：plan.transport 有方案 + request 有出发地 → 生成 train 建议；
      价格取 transport.options 最低单程参考价（无则不填，绝不编造）；
    - 酒店：days[].stops[type=hotel]（已安排酒店）→ 每个生成 hotel 建议；
      未进 days 时兜底 plan.hotels 候选池前几项（复用 hotel 候选）；
    - 每项 provider_url 由 booking_service.build_deeplink 纯规则组装；
    - reference=plan.generated / status=suggested：明确定义为「建议跳转」，
      绝不伪造成「已订」（confirmed 只经 trips_bookings API 凭证回填产生）；
    - 失败（任一输入缺失/异常）→ 静默不产出（空数组），绝不阻断主流程。

    返回：原地修改后的 plan。
    """

    def __init__(self) -> None:
        super().__init__(name="booking", deps=[], on_failure="degrade")

    async def run(self, ctx: PipelineContext, **kwargs: Any) -> Any:
        from app.agent import agents as A
        from app.i18n.translations import t

        request = ctx.request
        locale = A._request_locale(request)
        plan = kwargs.get("plan")
        if plan is None:
            raise ValueError("BookingStep 需要 plan（来自 servicing 步骤）")
        trace = kwargs.get("trace") or ctx.trace

        def _append_trace(entry: dict[str, Any]) -> None:
            trace.append(entry)
            import asyncio

            asyncio.create_task(A._emit_plan_event({"type": "trace", "trace": entry}))

        from app.services.booking_service import build_deeplink

        departure = (request.get("departure") or "").strip()
        destination = (request.get("destination") or plan.get("destination") or "").strip()
        start_date = (request.get("start_date") or "").strip()

        bookings: list[dict[str, Any]] = []

        # 1) 大交通（train）：有 transport 方案 + 出发地 → 生成 train 建议
        transport = plan.get("transport") or {}
        options = transport.get("options") if isinstance(transport, dict) else None
        if departure and destination and isinstance(options, list):
            price: float | None = None
            for opt in options:
                if not isinstance(opt, dict):
                    continue
                p = opt.get("price") or opt.get("price_estimate")
                try:
                    p = float(p) if p is not None else None
                except (TypeError, ValueError):
                    p = None
                if p is not None:
                    price = min(price, p) if price is not None else p
            url = build_deeplink("ctrip", "train", {
                "departure": departure, "destination": destination, "date": start_date,
            })
            if url:
                bookings.append({
                    "kind": "train",
                    "provider": "ctrip",
                    "title": f"{departure} → {destination}",
                    "provider_url": url,
                    "price_estimate": price,
                    "currency": "CNY",
                    "reference": "plan.generated",
                    "status": "suggested",
                })

        # 2) 酒店：已安排酒店（days[].stops[type=hotel]）优先，候选池兜底
        seen: set[str] = set()
        hotel_names: list[tuple[str, float | None]] = []
        for day in plan.get("days") or []:
            for stop in day.get("stops") or []:
                if isinstance(stop, dict) and stop.get("type") == "hotel":
                    name = (stop.get("name") or "").strip()
                    if name and name not in seen:
                        seen.add(name)
                        hotel_names.append((name, stop.get("estimated_cost")))
        if destination and not hotel_names:
            for h in plan.get("hotels") or []:
                if len(hotel_names) >= 3:
                    break
                if not isinstance(h, dict):
                    continue
                name = (h.get("name") or "").strip()
                if name and name not in seen:
                    seen.add(name)
                    hotel_names.append((name, h.get("estimated_cost")))
        for name, price in hotel_names[:5]:
            url = build_deeplink("ctrip", "hotel", {"city": destination})
            if not url:
                continue
            bookings.append({
                "kind": "hotel",
                "provider": "ctrip",
                "title": name,
                "provider_url": url,
                "price_estimate": float(price) if price is not None else None,
                "currency": "CNY",
                "reference": "plan.generated",
                "status": "suggested",
            })

        plan["bookings"] = bookings
        _append_trace({
            "agent": "BookingGate",
            "action": "generate_suggestions",
            "observation": (
                t(locale, "plan.trace.booking", n=len(bookings))
                if bookings else t(locale, "plan.trace.booking.none")
            ),
            "status": "completed" if bookings else "warning",
        })
        A._fire_artifact("bookings", {
            "count": len(bookings),
            "items": bookings[:10],
        })
        return plan


async def run_booking_stage(
    plan: dict[str, Any],
    request: dict[str, Any],
    *,
    trace: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """便捷入口：预订化收尾（BookingStep）。返回原地修改后的 plan。"""
    pipe = PlanningPipeline()
    pipe.add(BookingStep())
    await pipe.run(request, plan=plan, trace=trace or [])
    return plan