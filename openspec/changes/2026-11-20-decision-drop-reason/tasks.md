# Tasks — decision-drop-reason

> TDD 执行顺序：先失败测试（Red），再最小实现（Green）。验证命令见各任务。

## 1. 纯函数规则库（drop_reason_service）

- [ ] 1.1 **失败测试** `backend/tests/test_drop_reason.py`：
  ①`compute_drop_reasons` 五类 reason（budget_over / distance_too_far / category_mismatch / capacity_full / pacing_conflict）各命中场景；
  ②输出契约 `{stop_id, name, reason_code, reason_i18n_key, basis="rule_based"}`；
  ③预算判定复用预算档口径、距离判定复用 DrivingGate haversine 阈值；
  ④无淘汰 → 空数组。
  运行 `cd backend && .venv/bin/python -m pytest tests/test_drop_reason.py -x` 确认 Red（模块不存在）
- [ ] 1.2 最小实现：新建 `services/drop_reason_service.py`（纯函数 + 五类规则 + i18n 键映射）。运行 1.1 确认 Green
- [ ] 1.3 专项回归：`.venv/bin/python -m pytest tests/test_drop_reason.py -q` 全绿

## 2. 三个筛选出口挂载

- [ ] 2.1 **失败测试**（append 1.1 文件）：
  ①`solver_service.solve` 输出 `solver_meta.drops`（候选 5 取 3 → 2 条 drops，与保留互斥；全入选 → 空/缺失）；
  ②`plan_b` 变体携带取舍理由（节奏变体替换站 → `pacing_conflict`）；
  ③hotel 候选响应带 `drop_reasons`（同城 5 选 1 → 4 条理由，budget/distance/category 分类正确）。
  运行确认 Red
- [ ] 2.2 最小实现：`solver_service`（solve 收 drops，只记录不改结果）、`plan_b`（变体产出 drop 记录）、hotel 推荐路径（drop_reasons）。运行 2.1 确认 Green
- [ ] 2.3 后端全套回归：`cd backend && .venv/bin/python -m pytest -q` 零失败（重点：solver/plan_b/hotel 既有断言不因 drops 新增字段破坏）

## 3. 前端折叠区

- [ ] 3.1 i18n：`zh-CN.js`/`en-US.js` 补键（dropReason.title、dropReason.budgetOver、dropReason.distanceTooFar、dropReason.categoryMismatch、dropReason.capacityFull、dropReason.pacingConflict、dropReason.basisNote、dropReason.empty 等约 10 键），`npm run check:i18n` 通过
- [ ] 3.2 行程详情 QA 卡/工具区加「备选与淘汰理由」折叠区（默认收起，从 plan.solver_meta.drops / plan_b 读取，i18n 渲染 + basis 标注；无 drops 不渲染）。验证：`cd frontend && npm run build` 通过
- [ ] 3.3 `HotelRecommend.vue` 候选卡展示 `drop_reasons`（小字理由行 + basis 标注；无则隐藏）。验证：build 通过

## 4. 端到端验证

- [ ] 4.1 真机：规划一个含候选筛选的行程（预算档较紧制造淘汰）→ 展开「备选与淘汰理由」折叠区看到被淘汰站点 + 理由；打开酒店推荐卡看到 drop_reasons 对照
- [ ] 4.2 归档：`openspec archive decision-drop-reason` + `docs/night-build-todo.md` 登记完成项