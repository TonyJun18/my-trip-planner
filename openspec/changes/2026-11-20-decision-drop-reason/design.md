# Design

## Context

- 既有资产：`solver_service`（`rank_candidates` 贪心排序 / `check_hard_constraints` / `repair_violations` / `solve` 产出 `solver_meta`）、`plan_b`（三个纯规则变体：节奏/预算/取舍）、hotel 候选（`HotelRecommend` 评分降序）、`driving_service` haversine 阈值、预算档口径（budget_service）。
- 核验（2026-11-20）：现有透出全非决策理由（`xhs_agent task.reason`=任务状态、`email_import.dropped_lines`=计数）。
- 约束：零 LLM（方案 B 明确不做）/ 只记录不改结果 / rule_based 可追溯 / i18n 渲染。

## Goals / Non-Goals

- **Goals**：五类 drop_reason 规则库、三个筛选出口挂载、QA 卡折叠区 + 酒店对照展示。
- **Non-Goals**：LLM 理由；外部评分 API；全量候选落库；深层漏斗 UI；改变筛选逻辑。

## Decisions

### D1. drop_reason 是纯函数 + 审计记录，零行为改变
`compute_drop_reasons` 接收「筛选前候选 + 筛选后入选」→ 算出被淘汰项 + 规则理由。挂载点只**记录**（solver_meta.drops / plan_b drop 记录 / hotel drop_reasons），不参与筛选判定（避免了「理由与决定互相影响」的耦合）。既有筛选逻辑与断言零回归。

### D2. 五类 reason 枚举 + i18n 键映射
reason_code 用机器码（budget_over 等），文案全走 i18n 键（`dropReason.*`）——前端按 locale 渲染、后端只出键。`basis="rule_based"` 恒定（无 LLM）。规则阈值复用既有常量（budget 档 / DrivingGate haversine / 当日容量 5 站 / pacing 档），不新造魔法数。

### D3. hotel drop_reasons 附在入选项上（对照式）
「入选 1 家 + 其余被淘汰理由」作为该家的 drop_reasons 列表展示——最小交互（无独立淘汰列表 UI），与 SearchSpot「为什么选它/为什么淘汰它」的精华对齐。备选「每家候选都带自己的淘汰理由」被否：入选项才是用户最终看到的，对照信息放一处即可。

### D4. 前端默认收起，无 drops 不渲染
QA 卡折叠区（或 TripDetailPlanTools 下缘）默认收起，避免信息噪音；`drops` 为空/缺失时整区隐藏（诚实：没有淘汰就不展示「没有淘汰」）。酒店卡用既有卡片小字行。