# OpenSpec §1 队列执行细则（geo-anchor-sanity / decision-drop-reason / dietary-filter-chips / launch-deploy 代码部分）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 2026-11-20 OpenSpec §1 队列剩余 4 条需求落地为可测试代码：地理一致性质检（geo-anchor-sanity）、候选淘汰理由透出（decision-drop-reason）、饮食偏好 chips（dietary-filter-chips）、最小漏斗埋点落库（launch-deploy 代码部分）。

**Architecture:** 全部为确定性纯函数规则库（复用 time_validation/weather_validation/repeat_detector 同构：CritiqueIssue 结构 + plan.*_gate + warnings + trace 契约）；前端从 plan 数据读取渲染，i18n 双侧。不新增第三方依赖；除 analytics_events 外零迁移。

**Tech Stack:** Python 3.13 / FastAPI / SQLAlchemy async / Alembic；Vue3 + Element Plus + vue-i18n。

**Spec:** 四个 change 的 spec.md + tasks.md 为 binding authority：
- `openspec/changes/2026-11-20-geo-anchor-sanity/{spec,tasks}.md`
- `openspec/changes/2026-11-20-decision-drop-reason/{spec,tasks}.md`
- `openspec/changes/2026-11-20-dietary-filter-chips/{spec,tasks}.md`
- `openspec/changes/2026-11-20-launch-deploy/{spec,tasks}.md`

## Global Constraints

- 零 LLM、零外部 API：所有新规则均为确定性纯函数，单测覆盖；数据不足 → 沉默（不编造、不告警）。
- 诚实口径：gate 缺失 → `checked=false` 绝不假装通过；无淘汰 → drops 空/缺失；无离群 → 无 warning。
- 后端测试必须 `cd backend` 后 `.venv/bin/python -m pytest` 运行（仓库根跑会 rootdir 认错）。
- 前端 i18n 新键必须 zh-CN.js 与 en-US.js 双侧齐，`npm run check:i18n` 零失败。
- 既有意图埋点 `POST /analytics/events`（日志 204）行为零破坏；新漏斗落库走 `dedicated: true` 分支。
- alembic 迁移必须防御式幂等（has_table 先查后建，仿 `a1b2c3d4e5f6` 模板）。
- plan JSON 内嵌新字段（零 schema 演进约束）：`geo_gate` / `solver_meta.drops` / 变体 `drops` / hotel `drop_reasons` / `dietary` 请求字段 / `analytics_events` 独立表（唯一例外，独立迁移）。
- geo 阈值：`GEO_OUTLIER_KM=80`、`MIN_CENTROID_STOPS=3`（<3 个有坐标站点 → 沉默）；多城段按 `plan.multi_city.segments` 分组锚定；交通占位（`is_transfer` 或名称含「交通占位」）豁免。
- drop_reason 枚举（机器码 + i18n 键）：`budget_over`→`dropReason.budgetOver`、`distance_too_far`→`dropReason.distanceTooFar`、`category_mismatch`→`dropReason.categoryMismatch`、`capacity_full`→`dropReason.capacityFull`、`pacing_conflict`→`dropReason.pacingConflict`；`basis="rule_based"` 恒定。
- 阈值复用既有常量：`solver_service.MAX_ADJACENT_KM`（40km）、`time_validation.MAX_STOPS_PER_DAY`（5）、预算档 `budget_service` 口径。
- dietary 映射表（key→中文关键词）：vegetarian→素食、halal→清真、no-seafood→不吃海鲜、no-pork→不吃猪肉、gluten-free→无麸质、none→不产生关键词。
- 漏斗 5 事件白名单：page_view / register / plan_submitted / plan_completed / share_created；匿名用 `anonymous_session_id`（前端 localStorage UUID 持久）；不要求登录。
- 部署/运营（香港服务器/域名/真机访问）属外部依赖，本 plan 只落代码 + 测试 + 脚本；真实部署与 14 天结算由用户提供服务器后执行（归档时注明）。

## Review Focus

1. **坐标残缺**：站点只有 lat 无 lng（或非法值）→ 不参与质心、不崩溃、不告警（测试：`test_geo_sanity` 补残缺坐标站）。
2. **数据不足沉默**：无预算/无坐标 → drop_reasons 空数组，不产生「无理由的淘汰」；geo 少于 3 个有坐标站点 → 无输出（Task 1 已含）。
3. **dietary 互斥不残留**：具体项全取消 → 自动恢复 none；语言切换选中态保留（内部 key）（Task 7/8）。
4. **漏斗零回归**：`dedicated` 缺省 → 既有意图事件仍 204 不落库；白名单外漏斗事件 422（Task 9）。
5. **quality-report 门数跟随**：`GATE_KEYS` 增 geo_gate 后 `test_quality_report` 断言跟随（Task 2 用测试锁住）。

---

### Task 1: geo_sanity 纯函数规则库

**Files:**
- Create: `backend/app/services/geo_sanity.py`
- Test: `backend/tests/test_geo_sanity.py`（已存在，Red 就绪——契约：`check_plan_geo_gate(plan) -> {passed, issues, ...}`，issue 含 severity/category/message/suggestion/day_number/basis）

**Interfaces:**
- Consumes: `plan.days[].stops[].{lat,lng,name,is_transfer}`；`plan.multi_city.segments`（可选）；`driving_service.haversine_km`（公共球面距离）
- Produces: `check_plan_geo_gate(plan: dict, locale: str = "zh-CN") -> dict`（{passed, issues, warning_count, summary, basis="rule_based"}）；`GEO_OUTLIER_KM=80`、`MIN_CENTROID_STOPS=3` 模块常量

- [ ] **Step 1: 运行既有测试确认 Red**
  Run: `cd backend && .venv/bin/python -m pytest tests/test_geo_sanity.py -x`
  Expected: FAIL（`ModuleNotFoundError: No module named 'app.services.geo_sanity'`）

- [ ] **Step 2: 实现 `backend/app/services/geo_sanity.py`**
  内部：`_stop_coords(stop)`（lat/lng 均为数才返回，仿 solver_service._coords 边界校验）、`_is_transfer(stop)`（is_transfer 或名称含「交通占位」）、`_segments(plan)`（有 multi_city.segments 且含 day 归属 → 按段分组 days；否则整体）、`_centroid(stops)`（经纬度均值）、`check_plan_geo_gate(plan, locale)`（每段质心 → 每站 haversine 距离 → >80km 且非交通占位 → CritiqueIssue 结构 warning；<3 有坐标站 → passed=True + 空 issues）。
  issue 形状：`{severity:"warning", category:"schedule", message: f"{name} 距行程主体质心约 {km:.0f}km，请确认该站是否应保留 / 是否属于另一城市段", suggestion: 同上提示, day_number, basis:"rule_based"}`

- [ ] **Step 3: 运行测试确认 Green**
  Run: `cd backend && .venv/bin/python -m pytest tests/test_geo_sanity.py -q`
  Expected: 7 passed

- [ ] **Step 4: 补残缺坐标测试**（Review Focus 1）——append 到 test_geo_sanity.py：含 `lat=None` 与 `lat=999` 站的行程 → 不崩溃、非法站不参与质心、passed=True。运行确认 Green。

- [ ] **Step 5: Commit**
```bash
git add backend/app/services/geo_sanity.py backend/tests/test_geo_sanity.py
git commit -m "feat(geo-sanity): 地理一致性质检纯函数——质心锚定+离群检测（80km）+交通占位豁免+多城段分组+MIN_CENTROID_STOPS 沉默保护"
```

---

### Task 2: geo 质检链路接入（pipeline / revise / property_qa / quality-report）

**Files:**
- Modify: `backend/app/agent/pipeline.py`（FinalizePlanStep，time_gate 之后）、`backend/app/services/revise_service.py`（weather_gate 重算位置）、`backend/app/services/property_qa_service.py`（_warnings_answer 元组）、`backend/app/services/quality_report_service.py`（GATE_KEYS）、`frontend/src/views/TripDetailView.vue`（WS_PLAN_KEYS + planIssues）
- Test: `backend/tests/test_geo_sanity_pipeline.py`（新建）

**Interfaces:**
- Consumes: Task 1 的 `check_plan_geo_gate`
- Produces: `plan["geo_gate"]`（{passed, issues, basis="rule_based"}）；`plan.warnings` 追加；trace agent="GeoSanity"；`quality_report` gates 含 geo_gate；`planIssues` 徽标纳入；WS key `geogate`

- [ ] **Step 1: 写失败测试 `backend/tests/test_geo_sanity_pipeline.py`**
  ①`build_quality_report` 的 GATE_KEYS 含 `geo_gate`（Review Focus 5 锁住）；②`property_qa._warnings_answer` 汇总含 geo_gate issues；③`revise_service._recompute_gates`（或等价重算路径）输出含 geo_gate（用既有 gate 重算同目录函数做集成断言——只测「重算函数调用后返回 dict 含 geo_gate 键」，顺带验证离群站移除后 issues 清空；复用 `_plan_snapshot` 形状）。
  Run: `cd backend && .venv/bin/python -m pytest tests/test_geo_sanity_pipeline.py -x`
  Expected: FAIL

- [ ] **Step 2: 实现接入**
  - pipeline.py FinalizePlanStep：time_gate 块之后，`from app.services.geo_sanity import check_plan_geo_gate` → `geo_gate = check_plan_geo_gate(plan, locale=locale)` → `plan["geo_gate"] = {**去掉 issues 的字段, "issues": ..., "basis": "rule_based"}` → warnings 追加 `t(locale, "plan.warning.geogate", message=...)`（新增 i18n 键）→ `_append_trace({agent:"GeoSanity", action:"check_geo", observation:..., status:...})`。
  - revise_service.py：weather_gate 重算后同位置加 geo_gate 重算（用新 days + 保留 multicity 段信息，若无则整体）；`plan_data` 更新 dict 加 `"geo_gate": {...}`。
  - property_qa_service.py：`_WARNING_KEYS` 循环元组加 `"geo_gate"`。
  - quality_report_service.py：`GATE_KEYS` 加 `"geo_gate"`。
  - 前端 `TripDetailView.vue`：`WS_PLAN_KEYS` 加 `'geogate'`；`planIssues` computed 加 `plan.value?.geo_gate?.issues?.length`。i18n 键：`plan.warning.geogate`（zh/en）、`qualityReport.gate.geo_gate`（zh/en：「地理一致性」/ "Geo Consistency"）。
  Run: `cd backend && .venv/bin/python -m pytest tests/test_geo_sanity_pipeline.py -q`
  Expected: PASS

- [ ] **Step 3: 后端全套回归**
  Run: `cd backend && .venv/bin/python -m pytest -q`
  Expected: 既有测试零失败（重点 test_quality_report / test_property_qa 不破坏）

- [ ] **Step 4: Commit**
```bash
git add backend/app/agent/pipeline.py backend/app/services/revise_service.py backend/app/services/property_qa_service.py backend/app/services/quality_report_service.py backend/tests/test_geo_sanity_pipeline.py frontend/src/views/TripDetailView.vue frontend/src/locales/zh-CN.js frontend/src/locales/en-US.js
git commit -m "feat(geo-sanity): 质检链路接入——FinalizePlanStep 注入 geo_gate + revise 重算 + property_qa 汇总 + quality-report 五→六类 + WS/徽标/i18n"
```

---

### Task 3: 前端质检卡地理片段展示

**Files:**
- Modify: `frontend/src/components/QualityReportPanel.vue`（gate 标题/状态已自动跟随 GATE_KEYS——只需确认渲染 i18n 键存在 + 无 warning 时不显示片段）
- Test: 无新 pytest；`npm run build` + `npm run check:i18n`

**Interfaces:**
- Consumes: Task 2 的 qualityReport gate（含 geo_gate）+ i18n 键

- [ ] **Step 1: i18n 双侧补键**
  `qualityReport.gate.geo_gate`（已含于 Task 2，若未加则补：zh「地理一致性」/ en "Geo Consistency"）。
  Run: `cd frontend && npm run check:i18n`
  Expected: 零失败

- [ ] **Step 2: 确认渲染路径**
  QualityReportPanel 已 v-for gates 渲染；无 warning（issues 空）→ 显示 passed 徽标，符合 spec「无 warning 不渲染片段」的语义（面板展示 gate 卡片，空 issues 不列 warning 行）。无代码改动或微调（若面板把空 issues gate 完全隐藏则保持现状——spec 允许无 warning 不显示）。
  Run: `cd frontend && npm run build`
  Expected: 通过

- [ ] **Step 3: Commit**
```bash
git add frontend/src/components/QualityReportPanel.vue frontend/src/locales/zh-CN.js frontend/src/locales/en-US.js
git commit -m "feat(geo-sanity): 质检卡地理一致性 gate 透出（i18n+build）"
```

---

### Task 4: drop_reason_service 纯函数规则库

**Files:**
- Create: `backend/app/services/drop_reason_service.py`
- Test: `backend/tests/test_drop_reason.py`

**Interfaces:**
- Consumes: `solver_service.MAX_ADJACENT_KM`、`time_validation.MAX_STOPS_PER_DAY`、`driving_service.haversine_km`
- Produces: `compute_drop_reasons(candidates: list[dict], kept: list[str], ctx: dict, locale: str) -> list[dict]`，每条 `{stop_id, name, reason_code, reason_i18n_key, basis:"rule_based"}`；`DROP_REASON_KEYS` 映射表（机器码→i18n 键）；`merge_food_preferences` 不在本任务（Task 7）

- [ ] **Step 1: 写失败测试 `backend/tests/test_drop_reason.py`**
  ①五类 reason 各命中场景：候选 A budget_over（estimated_cost>单日人均预算=budget/days/travelers）、B distance_too_far（距锚点>MAX_ADJACENT_KM）、C category_mismatch（类目不匹配 ctx.preferred_types）、D capacity_full（当天已满 MAX_STOPS_PER_DAY）、E pacing_conflict（行程过满被移出）；②输出契约 {stop_id,name,reason_code,reason_i18n_key,basis}；③无淘汰 → 空数组；④数据不足（无 cost/无坐标）→ 不产生理由（Review Focus 2）。
  Run: `cd backend && .venv/bin/python -m pytest tests/test_drop_reason.py -x`
  Expected: FAIL（模块不存在）

- [ ] **Step 2: 实现 `backend/app/services/drop_reason_service.py`**
  纯函数：对每个未入选候选，按优先级（budget_over → distance_too_far → category_mismatch → capacity_full → pacing_conflict）判定，命中的第一条作为 reason；数据不足跳过该条候选。阈值复用既有常量（不新造魔法数）。

- [ ] **Step 3: 运行 Green**
  Run: `cd backend && .venv/bin/python -m pytest tests/test_drop_reason.py -q`
  Expected: 全绿

- [ ] **Step 4: Commit**
```bash
git add backend/app/services/drop_reason_service.py backend/tests/test_drop_reason.py
git commit -m "feat(drop-reason): compute_drop_reasons 五类确定性淘汰理由纯函数（复用既有阈值常量，数据不足沉默）"
```

---

### Task 5: 三个筛选出口挂载 drops（solver / plan_b / hotel）

**Files:**
- Modify: `backend/app/services/solver_service.py`（solve 收 drops）、`backend/app/services/plan_b.py`（变体带 drop 记录）、`backend/app/agent/agents.py`（_normalize_hotels 后挂 hotel drop_reasons → plan.hotels 每条增 drop_reasons）
- Test: append `backend/tests/test_drop_reason.py`

**Interfaces:**
- Consumes: Task 4 `compute_drop_reasons`
- Produces: `plan.solver_meta.drops`（仅记录不改结果）；plan_b 变体 `drops: [{name, reason_code, reason_i18n_key, basis}]`；`plan.hotels[].drop_reasons`

- [ ] **Step 1: 写失败测试（append）**
  ①`solve`：构造 6 站单日（>MAX_STOPS_PER_DAY）→ solver_meta.drops 含 capacity_full 记录且与保留候选互斥；5 站内 → drops 缺失/空；②plan_b：`_relaxed_variant`/`_budget_variant`/`_curated_variant` 变体含 drops（移除站带 reason_code，relaxed→pacing_conflict、budget→budget_over、curated→pacing_conflict）；③hotel：`_normalize_hotels`（或新纯函数 `attach_hotel_drop_reasons`）对 5 候选 1 入选 → 入选家带 drop_reasons 4 条（budget/distance/category 分类正确）。
  Run: `cd backend && .venv/bin/python -m pytest tests/test_drop_reason.py -x`
  Expected: FAIL

- [ ] **Step 2: 实现**
  - solver_service.solve：对每天 stops，若 `len(stops) > MAX_STOPS_PER_DAY` → 尾部超限站点调 `compute_drop_reasons`（reason=capacity_full）；预算超档站点 → budget_over；写入 `meta["drops"]`（无淘汰则不写该键）。
  - plan_b：三个变体函数在返回 dict 里增 `drops`（被移除/被替换站名称 + reason_code；relaxed→pacing_conflict、budget→budget_over、curated→pacing_conflict）。`generate_plan_b_variant` 透传。
  - hotel：`agents.py` 新增 `attach_hotel_drop_reasons(hotels, chosen_names)`（入选=days stops 中 hotel 名归一化匹配，仿前端 normName；未入选候选按预算档/距锚点/住宿需求类目算理由；入选家 drop_reasons=其余未入选各一条理由的对照列表）。在 `_normalize_hotels` 输出后挂载（或 Finalize 组装 hotels 处）。
  Run: `cd backend && .venv/bin/python -m pytest tests/test_drop_reason.py -q`
  Expected: 全绿

- [ ] **Step 3: 后端全套回归**
  Run: `cd backend && .venv/bin/python -m pytest -q`
  Expected: solver/plan_b/hotel 既有断言零破坏（drops 为可选新增字段）

- [ ] **Step 4: Commit**
```bash
git add backend/app/services/solver_service.py backend/app/services/plan_b.py backend/app/agent/agents.py backend/tests/test_drop_reason.py
git commit -m "feat(drop-reason): 三个筛选出口挂载——solver_meta.drops 审计记录 + plan_b 变体 drop 记录 + hotel 候选 drop_reasons 对照"
```

---

### Task 6: 前端「备选与淘汰理由」折叠区 + 酒店对照

**Files:**
- Modify: `frontend/src/components/trip-detail/TripDetailPlanTools.vue`（折叠区，默认收起）、`frontend/src/components/HotelRecommend.vue`（drop_reasons 小字行）、`frontend/src/locales/zh-CN.js` / `en-US.js`（dropReason.* 约 10 键）
- Test: `npm run build` + `npm run check:i18n`

**Interfaces:**
- Consumes: Task 5 的 `plan.solver_meta.drops` / planB `drops` / `plan.hotels[].drop_reasons`；i18n `dropReason.*`

- [ ] **Step 1: i18n 补键**
  `dropReason.title`（「备选与淘汰理由」/ "Alternatives & Drop Reasons"）、`dropReason.budgetOver`（超出预算档 / Over budget）、`dropReason.distanceTooFar`（距锚点过远 / Too far from anchor）、`dropReason.categoryMismatch`（类目不匹配 / Category mismatch）、`dropReason.capacityFull`（当日容量已满 / Day capacity full）、`dropReason.pacingConflict`（节奏冲突 / Pacing conflict）、`dropReason.basisNote`（规则库判定 / Rule-based）、`dropReason.empty`（无可展示理由 / No drop reasons）、`dropReason.sectionTitle` 等。双侧齐。
  Run: `cd frontend && npm run check:i18n`
  Expected: 零失败

- [ ] **Step 2: TripDetailPlanTools 折叠区**
  新增 `drops` prop（从 plan.solver_meta.drops + planB.drops 聚合）；v-if 有 drops 才渲染；默认收起（el-collapse 或同 style 的折叠，仿既有 CollapsibleSection 模式）；每条渲染 reason_i18n_key → t() + basis 标注。
  Run: `cd frontend && npm run build`
  Expected: 通过

- [ ] **Step 3: HotelRecommend 小字行**
  每条候选卡在 meta 区下加 `v-if="h.drop_reasons?.length"` 小字行（≤2 条理由 + basis）。
  Run: `cd frontend && npm run build`
  Expected: 通过

- [ ] **Step 4: Commit**
```bash
git add frontend/src/components/trip-detail/TripDetailPlanTools.vue frontend/src/components/HotelRecommend.vue frontend/src/locales/zh-CN.js frontend/src/locales/en-US.js
git commit -m "feat(drop-reason): 前端折叠区（备选与淘汰理由）+ 酒店 drop_reasons 对照小字行 + i18n 双侧"
```

---

### Task 7: dietary 后端并入（PlanRequest.dietary + 关键词映射 + food 偏好合并）

**Files:**
- Modify: `backend/app/schemas/agent.py`（PlanRequest 增 dietary）、`backend/app/i18n/prompts.py`（DIETARY_KEYWORDS + dietary_keys_to_keywords）、`backend/app/agent/agents.py`（food 偏好合并点）、`frontend/src/views/PlanWizard.vue`（提交 payload 增 dietary——前端在 Task 8）
- Test: `backend/tests/test_dietary_chips.py`

**Interfaces:**
- Consumes: `preference_keys_to_keywords` 同构模式
- Produces: `PlanRequest.dietary: list[str] | None`；`dietary_keys_to_keywords(locale, keys) -> list[str]`（none→不产出；未知 key 原样保留）；`merge_food_preferences(pref_keywords, dietary_keys, locale) -> list[str]`（含关键词、去重保序、无 dietary 时零变化）

- [ ] **Step 1: 写失败测试 `backend/tests/test_dietary_chips.py`**
  ①`dietary_keys_to_keywords("zh-CN", ["vegetarian","no-seafood"])` == ["素食","不吃海鲜"]；②none → []；③`merge_food_preferences(["川菜"], ["vegetarian","no-seafood"], ...)` == ["川菜","素食","不吃海鲜"]（去重：["素食","素食"]→["素食"]）；④dietary=[]/缺省 → 与现状一致（== 原 pref_keywords）；⑤PlanRequest(dietary=[...]) 可解析。
  Run: `cd backend && .venv/bin/python -m pytest tests/test_dietary_chips.py -x`
  Expected: FAIL

- [ ] **Step 2: 实现**
  prompts.py：`DIETARY_KEYWORDS = {"vegetarian":"素食","halal":"清真","no-seafood":"不吃海鲜","no-pork":"不吃猪肉","gluten-free":"无麸质"}`（zh 基准 + en 对照素食→"vegetarian"、清真→"halal"、不吃海鲜→"no seafood"、不吃猪肉→"no pork"、无麸质→"gluten-free"）→ `dietary_keys_to_keywords`；`merge_food_preferences`（pref_keywords + dietary 关键词，dict.fromkeys 保序去重）。
  schemas/agent.py：`PlanRequest.dietary: list[str] | None = Field(default=None, max_length=10, description="结构化饮食偏好 key（vegetarian/halal/no-seafood/no-pork/gluten-free）")`。
  agents.py：CollectAgentsStep foods 行改 `food_agent(city, merge_food_preferences(_food_hints(pref_keywords), ctx.request.get("dietary") or [], locale), ...)`（pref_keywords 已在 scope）。
  Run: `cd backend && .venv/bin/python -m pytest tests/test_dietary_chips.py -q`
  Expected: 全绿

- [ ] **Step 3: Commit**
```bash
git add backend/app/schemas/agent.py backend/app/i18n/prompts.py backend/app/agent/agents.py backend/tests/test_dietary_chips.py
git commit -m "feat(dietary): PlanRequest.dietary 字段 + dietary_keys_to_keywords + merge_food_preferences 并入餐饮偏好（去重保序，none 零变化）"
```

---

### Task 8: dietary 前端 chips 组（PlanWizard）

**Files:**
- Modify: `frontend/src/views/PlanWizard.vue`（dietaryKeys/dietaryKeywordMap/dietaryLabelKeyMap/dietaryEmoji/toggleDietary + 模板区块 + 提交 payload）、`frontend/src/locales/zh-CN.js` / `en-US.js`（dietaryGroupTitle 等约 8 键）
- Test: `npm run build` + `npm run check:i18n`

**Interfaces:**
- Consumes: Task 7 `PlanRequest.dietary` 契约（key 形式）
- Produces: `form.dietary`（内部 key，默认 ['none']）；提交 payload `dietary: form.dietary.filter(k => k !== 'none')`

- [ ] **Step 1: i18n 补键**
  `planWizard.dietaryGroupTitle`（饮食偏好 / Dietary）、`planWizard.dietaryVegetarian`（素食 / Vegetarian）、`dietaryHalal`（清真 / Halal）、`dietaryNoSeafood`（海鲜忌口 / No seafood）、`dietaryNoPork`（不吃猪肉 / No pork）、`dietaryGlutenFree`（无麸质 / Gluten-free）、`dietaryNone`（无特别 / No preference）、`dietaryHint`（饮食偏好用于餐饮推荐，不构成医疗/过敏建议 / Dietary preferences inform restaurant picks; not medical or allergy advice）。
  Run: `cd frontend && npm run check:i18n`
  Expected: 零失败

- [ ] **Step 2: PlanWizard 数据 + 互斥逻辑**
  `dietaryKeys=['vegetarian','halal','no-seafood','no-pork','gluten-free','none']`；`dietaryLabelKeyMap`/`dietaryEmoji`；`toggleDietary(k)`：点具体项 → 从 form.dietary 增删 + 选中时移除 'none'；点 none → 清空具体项只留 none（Review Focus 3：具体全取消 → 恢复 none）。`form.dietary = ['none']` 初始。form reactive 增加 dietary 字段。
  Run: `cd frontend && npm run build`
  Expected: 通过

- [ ] **Step 3: 模板 + 提交**
  在「兴趣偏好」组下加「饮食偏好」组（chips 样式复用 .chip.pref，emoji + label + hint 小字）。提交 payload `dietary: form.dietary.filter(k => k !== 'none')`。
  Run: `cd frontend && npm run build` + 手动浏览器验证互斥（构建通过即 CI 级过关；浏览器实测留 Task 12 归档说明）
  Expected: 通过

- [ ] **Step 4: Commit**
```bash
git add frontend/src/views/PlanWizard.vue frontend/src/locales/zh-CN.js frontend/src/locales/en-US.js
git commit -m "feat(dietary): PlanWizard 饮食偏好 chips 组——none 默认/互斥/多选 + 提交 dietary 键 + i18n 双侧"
```

---

### Task 9: analytics_events 表 + 迁移 + dedicated 落库端点

**Files:**
- Create: `backend/app/models/analytics.py`、`backend/alembic/versions/<new>.py`（防御式幂等）、`backend/scripts/launch_judgment.py`（脚本放 Task 10）
- Modify: `backend/app/schemas/analytics.py`（AnalyticsEventIn 增 dedicated + FunnelEventIn）、`backend/app/api/v1/analytics.py`（dedicated 分支落库）、`backend/tests/conftest.py`（TRUNCATE 加 analytics_events）
- Test: `backend/tests/test_analytics_funnel.py`

**Interfaces:**
- Consumes: `AnalyticsEventIn`（既有）；DB session（`db.session_factory` 独立事务，仿 share_lifecycle 审计写模式）
- Produces: `AnalyticsEvent` ORM（表 analytics_events：event_name/created_at/user_id?/trip_id?/anonymous_session_id?/payload JSONB）；`FunnelEventIn` schema；`POST /analytics/events` 支持 `{dedicated: true, funnel: {...}}` → 落库 204；`dedicated=false`/缺省 → 既有日志 204 零变化

- [ ] **Step 1: 写失败测试 `backend/tests/test_analytics_funnel.py`**
  ①POST `/api/v1/analytics/events` `{dedicated: true, funnel: {name:"page_view", anonymous_session_id:"s1", payload:{page:"/"}}}` → 204 且 DB 有 1 条；②5 类白名单逐一落库（name 校验）；③白名单外 name → 422；④匿名（无 user_id）可记录；⑤既有意图 `{name:"planning_tool_open"}` 无 dedicated → 204 且 DB 计数不增（零回归）。
  Run: `cd backend && .venv/bin/python -m pytest tests/test_analytics_funnel.py -x`
  Expected: FAIL（模型/端点未实现）

- [ ] **Step 2: 实现**
  - `models/analytics.py`：AnalyticsEvent ORM（Base），表名 analytics_events，防御式列。
  - alembic 迁移：`op.create_table` + has_table 先查（仿 `a1b2c3d4e5f6` 模板）；索引 event_name+created_at。
  - schemas/analytics.py：`FunnelEventName = Literal["page_view","register","plan_submitted","plan_completed","share_created"]`；`FunnelEventIn`（name/anonymous_session_id?/user_id?/trip_id?/payload dict）；`AnalyticsEventIn` 加 `dedicated: bool = False` + `funnel: FunnelEventIn | None = None`。
  - api/v1/analytics.py `record_event`：`if data.dedicated: if not data.funnel: 422; validated = FunnelEventIn(**data.funnel)（校验白名单/422）→ 独立 session 落库 commit（失败仅日志，不阻断 204）→ 204`；else 既有日志 204。
  - conftest.py TRUNCATE 清单加 `analytics_events`。
  Run: `cd backend && .venv/bin/python -m pytest tests/test_analytics_funnel.py -q` EXPECT PASS；`cd backend && .venv/bin/python -m alembic upgrade head` 成功。

- [ ] **Step 3: 后端全套回归**
  Run: `cd backend && .venv/bin/python -m pytest -q`
  Expected: 零失败（重点 test_analytics.py 零回归）

- [ ] **Step 4: Commit**
```bash
git add backend/app/models/analytics.py backend/alembic/versions/ backend/app/schemas/analytics.py backend/app/api/v1/analytics.py backend/tests/conftest.py backend/tests/test_analytics_funnel.py
git commit -m "feat(analytics): analytics_events 落库表+迁移 + POST /analytics/events dedicated 分支（5 漏斗事件白名单/匿名可记录/既有意图零回归）"
```

---

### Task 10: 前端五处漏斗打点 + 判定线脚本

**Files:**
- Modify: `frontend/src/api/modules/analytics.js`（trackFunnel + anonymous_session_id）、`frontend/src/router/index.js`（afterEach page_view）、`frontend/src/views/AuthView.vue`（register 成功）、`frontend/src/views/PlanWizard.vue`（submit→plan_submitted；finishSuccess→plan_completed）、`frontend/src/views/TripDetailView.vue`（share 创建成功→share_created）
- Create: `backend/scripts/launch_judgment.py`
- Test: `npm run build` + `npm run check:i18n` + 脚本本地造数跑通

**Interfaces:**
- Consumes: Task 9 端点 `{dedicated:true, funnel:{...}}`
- Produces: 前端五处 fire-and-forget 打点；`launch_judgment.py` 输出逐层转化率 + 20/5/2 达标布尔

- [ ] **Step 1: analytics.js 扩展**
  `trackFunnel(name, data)`（原生 fetch + keepalive，POST /analytics/events `{dedicated:true, funnel:{name, anonymous_session_id, ...data}}`，失败静默）；`getAnonymousSessionId()`（localStorage `trip_planner_anon_session`，首次 `crypto.randomUUID()` 生成持久，SSR 守卫）。
  Run: `cd frontend && npm run build`
  Expected: 通过

- [ ] **Step 2: 五处打点**
  - router/index.js：`router.afterEach((to) => trackFunnel('page_view', { payload: { path: to.fullPath } }))`（仅首次+每次导航，避免重复计数用 payload 或直接每次导航都发——spec 语义「访问」，每次路由导航都计一次可接受；简单起见 afterEach 每次发）。
  - AuthView：register 成功分支 `trackFunnel('register', ...)`。
  - PlanWizard：submit 成功后 `trackFunnel('plan_submitted', { payload: { task_id } })`；`finishSuccess(task)` 里 `trackFunnel('plan_completed', { trip_id: task.trip_id, payload: { task_id } })`。
  - TripDetailView：share 链接创建成功处（`openShareSettings`/share 相关成功回调）`trackFunnel('share_created', { trip_id })`。
  Run: `cd frontend && npm run build`
  Expected: 通过

- [ ] **Step 3: 判定线脚本 `backend/scripts/launch_judgment.py`**
  只读聚合：连 DB（复用 app 的 settings/session_factory）→ 5 事件计数 + 逐层转化率（register/page_view、plan_submitted/register、plan_completed/plan_submitted、share_created/plan_completed）→ 输出「20/5/2 达标布尔」文本。本地造数验证：`cd backend && .venv/bin/python -m pytest` 不影响；用 `python scripts/launch_judgment.py --db-url ...` 或默认 settings 读取（脚本带 `--help` + 造数说明）。验证：在测试库/本地库插入少量事件跑通输出各层计数。

- [ ] **Step 4: Commit**
```bash
git add frontend/src/api/modules/analytics.js frontend/src/router/index.js frontend/src/views/AuthView.vue frontend/src/views/PlanWizard.vue frontend/src/views/TripDetailView.vue backend/scripts/launch_judgment.py
git commit -m "feat(analytics): 前端五处漏斗打点（page_view/register/plan_submitted/plan_completed/share_created）+ launch_judgment 判定线脚本"
```

---

### Task 11: 全量验证 + 归档

**Files:**
- Modify: `docs/night-build-todo.md`（§3 登记 4 条完成项）、OpenSpec archive（4 个 change：`openspec archive` 命令或按 archive 目录规则）

- [ ] **Step 1: 后端全量回归**
  Run: `cd backend && .venv/bin/python -m pytest -q`
  Expected: 全绿（基线 1139+ 新增，零失败）

- [ ] **Step 2: 前端 build + i18n**
  Run: `cd frontend && npm run build && npm run check:i18n`
  Expected: build 通过 + i18n 双侧齐零失败

- [ ] **Step 3: 归档**
  `openspec archive geo-anchor-sanity`、`openspec archive decision-drop-reason`、`openspec archive dietary-filter-chips`、`openspec archive launch-deploy`（launch-deploy 注明「代码部分完成，服务器部署/14 天结算待用户提供服务器后执行」）；docs/night-build-todo.md §3 登记 4 条完成项（含验证命令与结果）。

- [ ] **Step 4: Commit**
```bash
git add docs/night-build-todo.md openspec/
git commit -m "docs(openspec): §1 队列 4 条需求归档（geo-anchor-sanity / decision-drop-reason / dietary-filter-chips / launch-deploy 代码部分）+ todo 登记"
```