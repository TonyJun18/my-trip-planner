# 实现计划 — trip-detail-schedule-timeline（方案 A：日程时间轴化）

**Date**: 2026-11-11
**输入**: 经确认的 Superpowers 设计稿（`docs/superpowers/specs/2026-11-11-trip-detail-schedule-timeline-design.md`）
与 OpenSpec change `openspec/changes/trip-detail-schedule-timeline/`（proposal/design/specs/tasks 四件齐全，validate 通过）。
**方法**: TDD（Red → Green → Refactor），任务 = OpenSpec tasks.md 的约束与检查清单。

## 环境注意

- 当前分支 `nightly/2026-11-11/0-task-weather-probability-eval`：工作区仅有本次新增文档（docs/superpowers、openspec change、docs/code-map 均未跟踪），实现直接在其上进行与既有夜间任务惯例一致；提交时单独成 commit。
- 本地后端 uvicorn (127.0.0.1:8090) 运行中——改后端代码后需重启再真机验证（昨日 QA 卡 404 事故即旧进程所致）。
- 前端 dev server (5173) 运行中，HMR 自动生效。
- 测试跑法：`cd backend && uv run pytest tests/test_schedule_service.py -x`（FakeLLM 替身，零 token）；前端 `npm run build`。

## 执行序（对应 OpenSpec tasks.md 1.1–4.2）

### 阶段 1：排程器纯函数（tasks 1.1–1.3）
1. 写 `backend/tests/test_schedule_service.py`（失败优先）：覆盖正常日/住宿站/占位站两路径/跨夜 overflow/无坐标兜底 — Red
2. 最小实现 `backend/app/services/schedule_service.py::schedule_day`（DAY_START import 自 time_validation；gap 用 estimate_drive_minutes；钳制 24:00）— Green + 回归 test_time_validation

### 阶段 2：响应层注入（tasks 2.1–2.5）
3. 失败测试 `test_trip_schedule_api.py`（owner GET 含派生字段；PATCH/PUT 响应不含；重排后派生一致）— Red
4. StopOut 加可选字段 + attach 函数挂 `trips_crud.get_trip` — Green
5. 失败测试：share token 路径 + live 快照含时刻 — Red → 同一注入函数接 `trips_share.py`、`live_service.live_snapshot` — Green
6. details 白名单补 is_transfer（失败测试先行：多城市落库 details.is_transfer=true）
7. 后端全套回归 `uv run pytest -q`（453+ 零失败）

### 阶段 3：前端（tasks 3.1–3.4）
8. i18n schedule 组 ~8 键 zh/en
9. TripDetailDayCard：时刻徽标 / 入住 / 交通占位样式 / 段间交通 chip（≤1.5km 步行、≤8km 公交、否则打车）/ 日头窗口聚合 / overflow 红色高亮 + AI 压缩 hint / None 兜底 — `npm run build`
10. TripDetailLiveToday：站点行时刻（缺失兜底）
11. TripDetailQaCard：错误态与空态分离 + 重试按钮 + 2 i18n 键（轻量顺带）

### 阶段 4：真机验证（tasks 4.1–4.2）
12. 重启后端 → Playwright 验证上海行程日程卡时间轴 + D2 过载高亮 + QA 卡错误态（断网或改错 URL 模拟）→ 截图留档
13. 手动改 D1 时长 → 观察时间轴刷新（派生一致性真机证据）

## 红线（来自 OpenSpec design.md Decisions）

- 不改写路径（revise 白名单 / PATCH / reorder 不动）；不做持久化时刻列；不让 LLM 出时刻。
- export 路径不注入派生字段。
- 口径：DAY_START 单一出处；无坐标跳过 gap 不编造；QA 卡错误态绝不冒充空态。

## 提交切分

1. `feat(schedule): 行程时间轴排程器与读取路径派生时刻注入（含 QA 卡错误态分离）`（后端 + 测试）
2. `feat(frontend): 日程卡时刻流水线渲染 + 行中今日卡时刻 + QA 卡错误态`（前端 + i18n + build 证据）
3. 文档与 OpenSpec 状态更新随后归档时一并处理。
