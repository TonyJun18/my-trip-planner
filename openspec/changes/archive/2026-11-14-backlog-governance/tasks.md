# Tasks

## 1. 审计与计划落盘

- [x] 1.1 新增 `docs/nightly/backlog-review-2026-11-14.md`：两夜调研证据、代码核验表（1118 passed / 早到缺口 / 多币种已接线 / 英文 0/10 / 无地图深链）、4 个首批任务与关闭清单、风险登记；验证：文件存在且每条结论带出处路径与日期。
- [x] 1.2 新增 `docs/superpowers/plans/2026-11-14-backlog-governance.md`：执行顺序、验证命令、回滚方式；验证：计划中的命令可原样执行。

## 2. 任务文件重排（append-only）

- [x] 2.1 在 `docs/night-build-todo.md` 顶部插入 §0 使用说明与图例、§1 可执行队列（4 个任务卡）、§2 候选池、§3 关闭与不排期决策记录；验证：§1 任务数 = 4，每个任务行以 `- [ ] task-` 开头且含 7 字段（类型/安全区、证据、做什么、验收、规模、依赖、风险）。
- [x] 2.2 将原 197 行整体下移为 §4 历史归档（只补勾、不改写）；验证：`git diff` 显示原文新增前缀仅为 `#` 段落标题与归档说明，原文行数与新增文件行数差额可解释；`grep -c '^## 2026-'` 数量与重排前一致。
- [x] 2.3 关闭失效项并补勾：L166 多币种前端、property-qa/favorites/photo-batch 标记已完成；视频解析/文件分享/照片归位/街道点亮/gallery-community-v3/DMO 白标写入 §3 并附理由 + 重开条件；验证：§3 每条含「理由」与「重开条件」，且不再出现在 §1。
- [x] 2.4 校验流水线提取形态：`grep -n '^- \[ \] task-' docs/night-build-todo.md` 只返回 §1 的 4 条；`grep -n '^- \[~\]'` 与 §3 条数一致；验证：命令输出与预期清单逐条对比无差异。

## 3. OpenSpec 状态对齐

- [x] 3.1 核验 `trip-detail-schedule-timeline` 实现与 spec 一致（`schedule_service.py`、`trips_crud.py`、`trips_share.py`、`live_service.py`、`TripDetailDayCard.vue` 均在案），验证：`openspec validate trip-detail-schedule-timeline --strict` 通过。
- [x] 3.2 归档该 change（`openspec archive trip-detail-schedule-timeline`），将 specs 合入 `openspec/specs/trip-schedule-timeline/spec.md`；验证：`openspec list` 不再显示该 change，`openspec/specs/` 下存在新 capability。
- [x] 3.3 验证本 change artifacts：`openspec status --change backlog-governance --json` 无缺失；`openspec validate backlog-governance --strict` 通过（`skip_specs: true` 生效）。

## 4. 集成验证与交付

- [x] 4.1 确认零代码改动：`git diff --stat` 不含 `backend/`、`frontend/`；验证：输出的改动路径仅 `docs/`、`openspec/`。
- [x] 4.2 汇总验证证据到审计报告（测试基线、grep 结果、openspec 状态、diff 清单）；验证：报告「验证证据」小节逐条列出命令与结果。

## Workflow follow-up

- 用户 review 后归档 `backlog-governance`（归档后 §1 队列仍保留在 todo 文件中，供后续实现任务使用）。
- 首批 4 个任务后续按「Superpowers 设计 → OpenSpec change → TDD」逐个交付，不在本 change 内实现。
- 分支合并顺序与本 change 无关；合并前重新跑后端基线。
