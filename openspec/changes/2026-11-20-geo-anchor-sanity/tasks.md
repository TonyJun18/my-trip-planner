# Tasks — geo-anchor-sanity

> TDD 执行顺序：先失败测试（Red），再最小实现（Green）。验证命令见各任务。

## 1. 纯函数规则库（geo_sanity）

- [ ] 1.1 **失败测试** `backend/tests/test_geo_sanity.py`：
  ①单城 8 站质心锚定，全部 <80km → 无 warning；
  ②7 站市区 + 1 站 300km 离群 → 仅该站 1 条 warning（CritiqueIssue 形状 + suggestion + basis=rule_based）；
  ③交通占位站（is_transfer / 名称含「交通占位」）200km → 豁免不告警；
  ④多城段：杭州段 8 站 + 上海段 6 站（段距 170km）→ 无跨段误报；上海段内某站距段质心 150km → 仅该站告警；
  ⑤全站无坐标 → 无输出。
  运行 `cd backend && .venv/bin/python -m pytest tests/test_geo_sanity.py -x` 确认 Red（模块不存在）
- [ ] 1.2 最小实现：新建 `services/geo_sanity.py`——`_centroid(stops)` / `_segments(plan)`（多城段结构识别，复用 `multi_city` 段约定）/ `check_geo_sanity(plan)`（`GEO_OUTLIER_KM=80` 常量 + CritiqueIssue 输出，复用 `day_optimizer._haversine_km` 同源或抽取共享）。运行 1.1 确认 Green
- [ ] 1.3 专项回归：`.venv/bin/python -m pytest tests/test_geo_sanity.py -q` 全绿

## 2. 质检链路接入（pipeline / revise / property_qa）

- [ ] 2.1 **失败测试**：①生成链路 FinalizePlanStep 后 plan 含 `geo_gate`（checked+issues，与 time_gate 同形状）；②plan.warnings 追加 geo warning；③trace 含 basis=rule_based；④revise_service 修订重算后 geo_gate 更新（移除离群站后 warning 消失）；⑤property_qa 预警汇总含 geo_sanity issues。运行确认 Red
- [ ] 2.2 最小实现：`pipeline.py` FinalizePlanStep 调 `check_geo_sanity` 注入；`revise_service` 复用（与 weather_gate 重算同位置）；`property_qa_service` 汇总纳入。运行 2.1 确认 Green
- [ ] 2.3 后端全套回归：`cd backend && .venv/bin/python -m pytest -q` 既有测试零失败（重点确认 2 geogate 相关既有断言不破坏）

## 3. 前端质检卡地理片段

- [ ] 3.1 i18n：`zh-CN.js`/`en-US.js` 补键（geoSectionTitle、geoOutlierMessage、geoBasisNote 等约 5 键），`npm run check:i18n` 通过
- [ ] 3.2 `TripDetailView.vue` 质检卡区域加「地理一致性」片段（从 plan.geo_gate 读，warning 列表 + suggestion + basis 标注；无 warning 不渲染片段）。验证：`cd frontend && npm run build` 通过
- [ ] 3.3 手动：构造含离群站的行程（或 mock geo_gate）→ 质检卡显示地理 warning；正常行程不显示

## 4. 端到端验证

- [ ] 4.1 真机：规划一个含离群站（如杭州行程手动加 300km 外站）→ 生成后质检卡出现地理一致性 warning + revision 后消失
- [ ] 4.2 归档：`openspec archive geo-anchor-sanity` + `docs/night-build-todo.md` 登记完成项