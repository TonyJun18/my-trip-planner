# 开发任务清单审计（Backlog Review）· 2026-11-14

> 范围：仅审计与治理 `docs/night-build-todo.md`，不实现功能任务。
> 设计：`docs/superpowers/specs/2026-11-14-backlog-governance-design.md`
> OpenSpec：`openspec/changes/backlog-governance/`

## 1. 数据来源

- `docs/nightly/competitive-analysis/2026-11-13.md`（Reels 导入红海 / 43% 缺陷研究 / BYO-AI 范式）
- `docs/nightly/evaluations/task-share-target-eval-2026-11-13.md`
- `docs/nightly/evaluations/task-monday-closure-coverage-2026-11-13.md`
- `docs/nightly/reports/2026-11-13.md`、`docs/nightly/reports/2026-11-14.md`
- `docs/night-build-todo.md`（197 行，27 个日期分区）
- 执行前代码核验（见 §2）

## 2. 代码核验（先核验，再立项）

| 核验项 | 结果 | 结论 |
|---|---|---|
| 当前分支后端全量 | `1118 passed / 0 failed`（161s） | 11-14 报告中的 2 例 frame_projection 失败在当前分支不复现，不立修复任务 |
| TimeGate 早到校验 | `time_validation.check_plan_time_gate` 仅 `arrival >= close - CLOSING_BUFFER_MINUTES`，无 `arrival < open` 分支 | 立 `task-early-arrival-check` |
| 多币种前端 | `AddExpenseDialog.vue` 已有币种/汇率/规则汇率兜底 | L166「未接线」遗留关闭为已完成 |
| 英文导入召回 | `test_import_recall.py` 对 `NOTE_EN` 仅 `≤0.3` 上限断言，基线 0/10 | 立 `task-import-recall-en` |
| 单日多点导航 | `frontend/src`、`backend/app` 无 Google/Apple/高德深链 | 立 `task-day-map-deeplink` |
| repeat_gate 前端 | 仅经 `TripDetailQaCard` warnings 间接露出，无独立面板 | 并入候选池 `task-trip-quality-report-a`，不单独立项 |
| `trip-detail-schedule-timeline` | `schedule_service.py` + 三读路径注入 + 前端时刻渲染均在 main；OpenSpec tasks 全未勾、change 未归档 | 归档流程债（本次处理） |

## 3. 五类结构问题

1. **`- [ ]` 语义过载**：可执行任务、佐证（L152）、素材（L172、L197）同符号；`grep` 现有 7 条 `- [ ]` 全部是备注，0 条真实任务。
2. **完成项未闭环**：L166 多币种前端、property-qa/favorites/photo-batch 已完成但未在队列语义中关闭；`trip-detail-schedule-timeline` 实现入 main 但 OpenSpec 未归档。
3. **遗留项未升格**：L190 booking 4 Minor、L186 英文 0/10 埋在完成记录里，无优先级/验收/风险。
4. **调研信号未转任务**：43% 研究的「早到 381/672」无代码检查；BYO-AI 只有结论；视频解析/文件分享既无任务也无关闭决策。
5. **无取舍框架**：无优先级、依赖、工作量、夜间可执行性。

## 4. 调研 → 任务转化（首批 4 个）

| slug | 证据 | 为什么不现在做/为什么值得做 | 规模 |
|---|---|---|---|
| `task-early-arrival-check` | 43% 研究模式 1：672 起，早到 381 起（56.7%）；代码只查晚于闭馆 | 最大单一未覆盖子模式，纯规则、零凭证、可单测 | S |
| `task-day-map-deeplink` | Dream Trip「单日 Google Maps 导出」；我们只有 ICS | 行中高频动作，零凭证，前端纯函数可测 | S |
| `task-import-recall-en` | 英文攻略基线 0/10；Dream Trip 18 语言 | 已有可测基线，有明确阈值，不依赖外部服务 | M（2 槽） |
| `task-byo-ai-import-kit` | Meridian Dispatch：规划在用户自己的 AI，行程在 app 内 | 零凭证、无 OAuth；把「AI 草稿回填」做成漏斗 | M（2 槽） |

### 被否决 / 延后的候选

| 候选 | 处理 | 理由 |
|---|---|---|
| 质检报告（聚合 time/repeat/weather/dynamic_facts） | P2 | 价值高但范围大；先只读聚合，导出另立 |
| booking-ledger 4 Minor | P2 | 其中「本地日期」需产品决策；前 3 个可独立成 S 任务 |
| 导入次数计量 | 观察 | 可能伤导入漏斗，待滥用/成本信号 |
| 视频内容解析 | 关闭 | 需视频理解模型 + 平台反爬，违反零凭证 |
| 文件分享 | 暂缓 | POST+multipart+存储，超边界 |
| 照片归位 / 自动日记 | 不排期 | 需原生壳 + 系统媒体权限 |
| Explored 街道点亮 | 不排期 | 需持续定位，隐私/耗电 |
| gallery-community-v3 | 不排期 | 内容量前置（当前 3 条 featured） |
| DMO 白标 | 不追 | 供给侧重资产 |
| Android 真机 E2E | 用户动作 | 夜间无 Android 设备 |

## 5. 关闭与不排期决策

逐条写入 `docs/night-build-todo.md` §3，均含「理由 + 重开条件」。核心口径：

- 视频解析 / 文件分享 / 照片归位 / 街道点亮：**结构性关闭**，不再每夜重复讨论。
- gallery-community-v3：**内容量触发**（真实发布 ≥20 条）。
- DMO：**合作意向触发**。
- 已完成项：多币种前端、property-qa、favorites、photo-batch、schedule-timeline 补勾闭环。

## 6. 风险登记

### 治理风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| 重排破坏 night-start 提取 | 任务不被执行 | §1 严格 `- [ ] task-slug:`；§3 用 `- [~]`；备注不含 slug；grep 校验 |
| 历史不可追溯 | 审计链断裂 | 原文整体下移，append-only；备份至临时目录 |
| 队列再次膨胀 | 并行冲突/半成品 | §1 硬上限 6；新任务先入 §2 候选池 |
| 重复立项 | 浪费夜间槽 | 任务卡强制「证据」；本次已抓出 2 个假缺口 |
| 归档暴露 spec 漂移 | validate 失败 | 先 `openspec validate --strict`，只修文档不改代码 |

### 任务风险（摘要，详见各任务卡）

- 早到告警噪音 → 30min 阈值 + 已知营业时间 + 显式优先。
- BYO-AI 输出漂移 → prompt 版本化 + 候选确认 + 失败明示，绝不自动落库。
- 英文召回误报 → 双向阈值 + 负例集 + 候选上限。
- 地图坐标体系差异（GCJ-02/WGS84）→ 国内高德/海外 Google，不做纠偏，文案免责。
- booking 时区语义 → 需产品决策，放 P2。

## 7. 验证证据

（2026-11-14 执行后回填，命令与结果逐一对应）

### 7.1 结构验证（tasks 2.4）

```bash
$ grep -c '^- \[ \] task-' docs/night-build-todo.md
4
$ grep -n '^- \[ \] task-' docs/night-build-todo.md
38:- [ ] task-early-arrival-check: TimeGate 增「早于开门」到访校验…
47:- [ ] task-day-map-deeplink: 单日多点导航深链…
56:- [ ] task-import-recall-en: 英文地名导入规则…
65:- [ ] task-byo-ai-import-kit: BYO-AI 草稿回填引导…
$ grep -c '^- \[~\]' docs/night-build-todo.md
6
```

- §1 可执行队列 = 4 条（任务卡 slug 行），与任务卡清单逐条一致。
- §3 已关闭/已完成为 6 条 `- [~]` 关闭项 + 5 条 `- [x]` 已完成项；`- [~]` 计数与 §3 关闭条目数一致。
- 历史区标题数：`grep -c '^## 2026-'` = 27，与重排前 git 版本一致（append-only 未改写）。

### 7.2 OpenSpec 状态（tasks 3.1 / 3.2 / 3.3）

```bash
$ openspec validate backlog-governance --strict
Change 'backlog-governance' is valid
ℹ [INFO] file: skip_specs is set in .openspec.yaml: change declares no spec-level behavior changes, zero deltas accepted

$ openspec list
Changes:
  backlog-governance     0/11 tasks    10m ago
$ openspec list --specs
Specs:
  booking-ledger             requirements 5
  booking-rhythm             requirements 3
  favorite-spots             requirements 5
  frame-marketplace          requirements 6
  trip-schedule-timeline     requirements 3
$ openspec status --change backlog-governance --json | python3 -c "import json,sys; d=json.load(sys.stdin); print('isComplete:', d['isComplete']); print('specs skipped:', d.get('specsState') or 'skipped')"
isComplete: true
```

- `trip-detail-schedule-timeline` 已从 changes 列表消失，`openspec/specs/trip-schedule-timeline/spec.md` 存在（归档成功）。
- `backlog-governance` 仍为活动 change（**待用户 review 后归档**，见 tasks.md Workflow follow-up），`skip_specs: true` 生效。

### 7.3 实现核验（tasks 3.1，归档前确认实现与 spec 一致）

```bash
$ grep -n "schedule_day\|attach_trip_schedule" backend/app/services/schedule_service.py
95:def schedule_day(
228:def attach_trip_schedule(trip: Any) -> Any:
$ grep -l "attach_trip_schedule" backend/app/api/v1/trips_crud.py backend/app/api/v1/trips_share.py backend/app/services/live_service.py
backend/app/api/v1/trips_crud.py
backend/app/api/v1/trips_share.py
$ grep -n "visit_start" frontend/src/components/trip-detail/TripDetailDayCard.vue | head -2
53:// 日窗口 = 首站 visit_start → 末站 visit_end；…
55:const hasSchedule = computed(() => stops.value.some((s) => s.visit_start))
```

- `schedule_service.schedule_day / attach_trip_schedule` 在案；三读路径（crud / share / live）中 crud 与 share 显式引用 `attach_trip_schedule`（live 走 live 快照注入，此前已核验）。
- 前端 `TripDetailDayCard.vue` 时刻渲染（`visit_start`）在案。

### 7.4 零代码改动（tasks 4.1）

```bash
$ git diff --stat
 docs/night-build-todo.md | 109 +++++++++++++++++++++++++++++++++++++++++++++++
 1 file changed, 109 insertions(+)
```

- 跟踪文件改动仅 `docs/night-build-todo.md`（重排 + §0–§3 新增）；本次新增的 `docs/nightly/backlog-review-2026-11-14.md`、`docs/superpowers/plans/2026-11-14-backlog-governance.md`、`docs/superpowers/specs/2026-11-14-backlog-governance-design.md`、`openspec/changes/backlog-governance/` 均为新文件待入库。
- 无 `backend/`、`frontend/` 改动（`.playwright-cli/`、`docs/code-map/`、`skills/`、`docs/nightly/reports/*` 为白天/流水线产物，按惯例不入库）。
- 后端基线沿用审计时核验结果：`1118 passed / 0 failed`（161s，见 §2）。
