# Tasks — trip-detail-schedule-timeline

> TDD 执行顺序：每个实现任务先写失败测试（Red），再最小实现（Green），最后重构。验证命令见各任务。

## 1. 后端排程器（schedule_service）

- [ ] 1.1 新建 `backend/app/services/schedule_service.py` 的**失败测试** `backend/tests/test_schedule_service.py`：正常日排程（3 个非住宿站，起点 09:00、逐站累加、gap 计算、末站 travel=null）、住宿站（不占时段、渲染语义到店时刻）、交通占位站（details.is_transfer 与名称「（交通占位）」兜底两路径）、跨夜钳制与 overflow 信号（end>24:00 及跨度>720min）、无坐标站（gap 跳过、时刻顺延不编造）。运行 `cd backend && uv run pytest tests/test_schedule_service.py -x` 确认 Red（模块不存在）
- [ ] 1.2 最小实现 `schedule_day` 纯函数（起点常量 import 自 `time_validation.DAY_START`、gap 用 `driving_service.estimate_drive_minutes`、跨夜钳制 24:00），运行 1.1 命令确认 Green
- [ ] 1.3 后端专项回归：`cd backend && uv run pytest tests/test_schedule_service.py tests/test_time_validation.py -q` 全绿（口径不漂移）

## 2. 响应层注入（三个读路径）

- [ ] 2.1 **失败测试** `backend/tests/test_trip_schedule_api.py`：`schemas/trip.py` StopOut 增加可选派生字段后，`GET /trips/{id}`（owner）响应 days[].stops[] 含 `visit_start/visit_end/travel_to_next_minutes/is_transfer`；写路径回归——`PATCH /days/{day_id}/stops/{stop_id}` 与 `PUT /days/{day_id}/stops/order` 响应**不含**派生字段（契约面不变）；派生一致性——重排后 GET 反映新顺序时刻。运行确认 Red
- [ ] 2.2 最小实现：StopOut 加字段（`schemas/trip.py`）+ `schedule_service.attach_trip_schedule` 注入 `trips_crud.get_trip`（`trips_crud.py:79`）+ owner 侧写路径零挂钩；运行 2.1 确认 Green
- [ ] 2.3 **失败测试**（append 2.1 文件）：分享只读路径 `GET /trips/share/{token}` 响应含派生字段；行中快照 `GET /trips/{id}/live` stops 含时刻字段。运行确认 Red 后在 `trips_share.py` 与 `live_service.live_snapshot` 接同一注入函数，运行确认 Green
- [ ] 2.4 details 白名单补 `is_transfer`（`planning_service.py:314-319`）+ 失败测试先行（多城市 plan 落库后占位站 details.is_transfer=true），`uv run pytest tests/test_planning_service.py tests/test_schedule_service.py -q` 绿
- [ ] 2.5 后端全套回归：`cd backend && uv run pytest -q` 453+ 测试零失败

## 3. 前端渲染

- [ ] 3.1 i18n 键：`zh-CN.js`/`en-US.js` schedule 组约 8 键（startTime/checkin/transfer/travelWalk/travelTransit/travelTaxi/overflowTitle/overflowHint），`grep` 确认 zh/en 键数一致
- [ ] 3.2 `TripDetailDayCard.vue`：站点行时刻徽标（➕ hotel→「入住 HH:MM」、is_transfer→交通样式与图标）、段间交通 chip（travel_to_next_minutes ≤1.5km 步行 / ≤8km 公交 / 其他 打车——本地换算，复用 servicing 阈值口径）、日头时间窗口聚合（首站 start → 末站 end）与 overflow 红色高亮 + 「让 AI 压缩该日」hint；派生字段缺失时回退现行无时刻渲染（None 兜底）。验证：`cd frontend && npm run build` 通过
- [ ] 3.3 `TripDetailLiveToday.vue`：今日卡站点行展示时刻徽标（live snapshot 新字段，缺失兜底）。验证：`npm run build` 通过
- [ ] 3.4 QA 卡错误态分离（`TripDetailQaCard.vue`）：请求 catch 分支渲染「数据加载失败 + 重试按钮」，与「暂无结构化数据」空态独立；i18n 2 键 zh/en。验证：build 通过 + 手动模拟接口失败展示错误态

## 4. 真机验证

- [ ] 4.1 Playwright 真机验收：重启后端（最新代码）后打开上海行程详情页——日程卡呈现时刻流水线与日头窗口、D2 过载高亮、行中视角（若有行中行程）今日卡时刻；截图留档 `/tmp/trip-detail-timeline-*.png`
- [ ] 4.2 修订联动一致性观测：详情页手动编辑 D1 某站时长（PATCH）→ 页面 load() 重载 → 时间轴反映新时长（派生一致性真机证据）

## Workflow follow-up（归档相关，非 tracked）

- 全部 tracked 任务完成且验证证据齐全后：`openspec archive trip-detail-schedule-timeline`
- 归档后按需更新 `README.md` 功能列表（日程时间轴一句话）与 `docs/night-build-todo.md` 登记完成项
