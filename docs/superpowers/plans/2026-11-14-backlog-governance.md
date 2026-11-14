# 实施计划：开发任务清单治理（2026-11-14）

- 设计：`docs/superpowers/specs/2026-11-14-backlog-governance-design.md`
- OpenSpec：`openspec/changes/backlog-governance/`
- 范围：docs / OpenSpec only；零运行时改动
- 执行顺序：审计报告 → 重排 todo → 归档滞留 change → 结构验证 → 证据回填

## 前置检查

```bash
cd /Users/pengjun/Documents/my-agent/my-trip-planner
git status --short
openspec validate backlog-governance --strict
```

预期：仅白天 untracked 文件与本次新增 docs/openspec；validate 通过。

## 步骤 1：写审计报告

产出 `docs/nightly/backlog-review-2026-11-14.md`，包含：

- 数据来源清单（11-13 竞品分析、三个评估记录、11-13/14 报告）。
- 代码核验表：1118 passed、TimeGate 无早到分支、多币种前端已接线、英文召回 0/10、无地图深链、`trip-detail` 已实现未归档。
- 4 个首批任务卡摘要（详见 todo §1）。
- 关闭/不排期清单与重开条件。
- 风险登记（治理/任务两类）。
- 验证证据（步骤 4 回填）。

验证：`test -f` + 人工核对每条结论有路径与日期。

## 步骤 2：重排 `docs/night-build-todo.md`

### 2.1 安全备份

```bash
cp docs/night-build-todo.md /private/var/folders/p1/6k2v376j0xjc1518fr5dcqs80000gn/T/opencode/todo-backlog-governance-backup.md
wc -l docs/night-build-todo.md
```

### 2.2 结构

- §0 使用说明与图例（状态机、任务卡 7 字段、维护规则）。
- §1 可执行队列（4 条，硬上限 6）：
  1. `task-early-arrival-check`（backend，S）
  2. `task-day-map-deeplink`（frontend，S）
  3. `task-import-recall-en`（backend，M/2 槽）
  4. `task-byo-ai-import-kit`（frontend，M/2 槽）
- §2 候选池：booking 4 Minor、import quota、manual 路径修正、repeat_gate 独立面板、Android 真机 E2E（用户动作）。
- §3 关闭与不排期：视频解析、文件分享、照片归位、街道点亮、gallery-v3、DMO；已完成闭环：多币种前端、property-qa、favorites、photo-batch。
- §4 历史归档：原 197 行整体保留（仅补勾）。

### 2.3 关键约束

- §1 每条严格以 `- [ ] task-` 开头，否则 night-start 提取不到。
- §3 用 `- [~]`，每条含「理由」「重开条件」。
- 备注保留 `- [ ]（备注）` / `- [ ]（素材·不排期）`，不含 slug。
- 历史区不改写。

验证：

```bash
grep -c '^- \[ \] task-' docs/night-build-todo.md   # 预期 4
grep -n '^- \[ \] task-' docs/night-build-todo.md
grep -c '^- \[~\]' docs/night-build-todo.md         # 预期 = §3 条数
grep -c '^## 2026-' docs/night-build-todo.md        # 与备份一致
```

## 步骤 3：归档 `trip-detail-schedule-timeline`

### 3.1 核验实现与 spec

```bash
openspec validate trip-detail-schedule-timeline --strict
grep -n "schedule_day\|attach_trip_schedule" backend/app/services/schedule_service.py \
  backend/app/api/v1/trips_crud.py backend/app/api/v1/trips_share.py backend/app/services/live_service.py
grep -n "visit_start" frontend/src/components/trip-detail/TripDetailDayCard.vue | head
```

### 3.2 归档

```bash
openspec archive trip-detail-schedule-timeline
openspec list
openspec list --specs
```

预期：change 从列表消失；`openspec/specs/trip-schedule-timeline/spec.md` 出现。

## 步骤 4：集成验证

```bash
openspec status --change backlog-governance --json
openspec validate backlog-governance --strict
git diff --stat
git status --short
```

预期：

- status `isComplete: true`，specs 为 `skipped`（skip_specs 生效）。
- validate 通过。
- diff 仅含 `docs/`、`openspec/`，无 `backend/`、`frontend/`。
- 将上述命令与结果回填审计报告「验证证据」。

## 回滚

```bash
cp /private/var/folders/p1/6k2v376j0xjc1518fr5dcqs80000gn/T/opencode/todo-backlog-governance-backup.md docs/night-build-todo.md
git checkout -- openspec/  # 或 mv 回归档目录
```

无数据库/运行时影响。

## 完成标准

- [ ] 审计报告存在且证据可追溯。
- [ ] todo 四层结构生效，§1=4 条，§3 关闭项齐全。
- [ ] `trip-detail-schedule-timeline` 已归档。
- [ ] `openspec validate backlog-governance --strict` 通过。
- [ ] 零运行时改动。
- [ ] 验证证据回填。
