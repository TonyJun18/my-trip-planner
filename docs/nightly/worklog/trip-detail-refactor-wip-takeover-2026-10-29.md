# WIP 收编记录：task-trip-detail-refactor（阶段一纯拆分 + 埋点）

**时间**: 2026-10-29（白天，用户续做）
**决策**: 核验通过 → 提交登记（含补缺：埋点端点注册到 collect 收集）
**不做**: 不重写、不重构、不进入阶段二（IA / flag / Tab 收纳）——阶段二在用户 review 阶段一后另立

## 判定依据（verify-work-before-implement 三态）
- 主工作区有 4 modified tracked + 6 untracked：9 个 `src/components/trip-detail/` 组件 + `analytics.js` + 后端 `api/v1/analytics.py` + `schemas/analytics.py` + `tests/test_analytics.py` + `useTripTypes.js` = **被掐断 worker 留下的阶段一实现**（未提交、未登记）
- `git log --all -S "TripDetailTopBar"` 只有 spec commit（c83e4ca），实现从未提交过 → WIP 态（第 3 态）
- `docs/night-build-todo.md` / `checkpoint.json` 均无 `task-trip-detail-refactor` 条目 → 需要登记

## 核验结果（全部通过）
1. 后端全套：`693 passed`（21 例埋点测试含在内；补登记前基线 672 可能不齐，本夜全套绿）
2. 前端 build：`✓ built in 4.36s`（chunk >500kB 为既有警告，非错误）
3. i18n：146 个真实键，zh/en 双侧齐全（node 脚本核对）
4. 埋点四事件接线：`top_action_click`（编辑/问AI/分享三处）、`planning_tool_open`（4 工具 emit）、`itinerary_first_view`（IntersectionObserver on `.day-section.day-card`）、`itinerary_scroll_depth`（25/50/75 一次性+节流）全部在案
5. 导出 `forceOpen` 接线：`exportAll` 由 orchestrator 透传 Toolbox → 12 处 `CollapsibleSection :force-open`（修复 solution §0 指出的「exportAll 无消费方」问题）
6. 5 对话框（xhs/import/genDays/shareSettings/edit 三合一）全部搬入 TripDetailDialogs，契约原样
7. 共享逻辑全部留在 orchestrator（useTripDetailLoad/useRevise/useEditDialog/useTripShareActions/useExport），状态所有权未动
8. 组件 CSS 各自带走（各组件 style 块在），TripDetailView 仅剩布局/打印样式；`.topbar`/`.live-card` 等打印选择器保留为防御式

## 提交计划（一组件一 commit 原则）
| commit | 内容 |
|---|---|
| 1 | 组件拆分：TripDetailTopBar/Hero/LiveToday/MapCard/DayCard/Toolbox/Sidebar/BottomBar/Dialogs + useTripTypes + TripDetailView orchestrator 收敛（1458 行 → 713 行） |
| 2 | 埋点：analytics.js + 后端 analytics.py/schemas + 路由注册 + test_analytics.py + TripDetailView 埋点接线 + exportAll forceOpen |

## 登记
- `docs/night-build-todo.md` 追加 `- [x] task-trip-detail-refactor: ...（阶段一拆分+埋点 完成）`
- `docs/nightly/checkpoint.json` issues 追加收编记录；completed 追加 task-trip-detail-refactor

## 遗留（明确不阻塞阶段一）
- checkpoint 内待办 task-price-realism-eval / task-trip-rating-signal 与 main todo 状态不一致（历史登记语义，不属本任务）
- 阶段二（IA/Tab/flag）未做：依赖 PM 口径与 cpo 裁决，单独立项