# Proposal

## Why

SearchSpot.ai 把「250 家酒店 → 50 匹配 → 12 符合预算 → 4 个候选 + 每个为什么被选/被淘汰」（transparent AI reasoning）做成核心交互；2026 决策透明度成为新共识（11-17 竞品分析 §3.2）。我们现状：候选池筛选链路（`solver_service.rank_candidates` / `check_hard_constraints` / `repair_violations`、`plan_b` 备选取舍、hotel 候选 top-N）**全部是黑盒**——用户只看到「最终选的」，看不到「淘汰了谁、为什么」。核验（2026-11-20）：`xhs_agent_service.task.reason` 是任务状态（expired/superseded）、`email_import.dropped_lines` 是计数，均非用户可见的决策理由。

零 LLM 口径：drop_reason 全部由确定性规则产生（超预算/距离过远/类目不匹配/容量已满/节奏冲突），可追溯、不编造；LLM 生成理由（方案 B）明确不做。

## What Changes

- 新增纯函数 `compute_drop_reasons(plan, candidates, context)`（`services/drop_reason_service.py`，零 LLM 零网络）：对候选筛选过程的每个被淘汰项产出 `drop_reason`（enumerate：`budget_over` / `distance_too_far` / `category_mismatch` / `capacity_full` / `pacing_conflict`）+ 人类可读理由文本（i18n 键）。
- 挂载点（三个确定性筛选出口）：
  - `solver_service.solve` → `plan.solver_meta` 增 `drops`（site 候选 top-N 被淘汰的站点 + 理由，rule_based）；
  - `plan_b.generate` → 备选变体携带「相对主案为什么换掉 X」（取舍理由）；
  - hotel 候选 → `HotelRecommend`（或等价响应）每条候选带 `drop_reasons`（同城其他候选被淘汰 + 理由）。
- 输出契约：`DropReasonOut {stop_id/name, reason_code, reason_i18n_key, basis="rule_based"}`。
- 前端：QA 卡或行程卡「备选与淘汰理由」折叠区（默认收起），展示被淘汰候选 + 理由；i18n zh/en。
- **不做**：LLM 生成理由（防编造）；外部评分 API；把全部候选都存库（只透出筛选过程的 drops，内存计算）；决策树 UI。

## Capabilities

### New Capabilities

- `decision-drop-reason`: 候选淘汰理由透出——确定性 drop_reason 规则、三个筛选出口挂载、QA 卡折叠区展示。

### Modified Capabilities

<!-- solver 语义扩展：solver_meta.drops 为增量字段，既有 passed/violations/unresolved 不变 -->

## Impact

- **后端**：新建 `services/drop_reason_service.py`；`solver_service.py`（solve 收集 drops）、`plan_b.py`（备选取舍理由）、hotel 推荐路径（drop_reasons）；schemas 补可选字段。测试 `tests/test_drop_reason.py`（五类 reason + 挂载点 + 透出）。
- **前端**：`TripDetailPlanTools` 或 QA 卡折叠区 + `HotelRecommend.vue`（drop_reasons 展示）+ i18n（约 8–10 键 ×2）。
- **零破坏**：solver_meta.drops 可选字段；既有断言零回归；不碰筛选逻辑本身（只记录不改变结果）。
- **依赖**：零新依赖。