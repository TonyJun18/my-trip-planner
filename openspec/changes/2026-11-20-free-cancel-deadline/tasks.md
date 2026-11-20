# Tasks — free-cancel-deadline

> TDD 执行顺序：每个实现任务先写失败测试（Red），再最小实现（Green）。验证命令见各任务。

## 1. 数据模型与迁移（free_cancel_deadline）

- [ ] 1.1 **失败测试** `backend/tests/test_free_cancel_deadline.py::test_deadline_roundtrip`：`BookingIn` 带 `free_cancel_deadline="2026-12-01"` 创建预订 → 响应含该字段；省略字段创建成功且为 None。运行 `cd backend && .venv/bin/python -m pytest tests/test_free_cancel_deadline.py -x` 确认 Red（字段不存在）
- [ ] 1.2 Alembic 迁移：`trip_bookings` 加 `free_cancel_deadline DATE NULL`（索引）；`models/trip.py` TripBooking 补列；`schemas/booking.py` 三个模型补可选字段。运行 1.1 确认 Green；`cd backend && .venv/bin/python -m alembic upgrade head` 成功
- [ ] 1.3 专项回归：`.venv/bin/python -m pytest tests/test_booking_service.py tests/test_free_cancel_deadline.py -q` 全绿

## 2. 倒计时与截止前提醒

- [ ] 2.1 **失败测试**（append 1.1 文件）：列表响应含 `cancel_deadline_days`（+3 → 3、无 → null）；`scan_cancel_deadline_reminders` 纯函数四路径——窗口内产出事件 / 重复扫描幂等（同窗口只一条）/ 已截止不产出 / 无截止日不产出。运行确认 Red
- [ ] 2.2 最小实现：`booking_service` 倒计时在响应构造时计算（与 `days_until` 同口径）；`event_service.EVENT_TYPES` 注册 `booking.cancel_deadline`（**顺带注册 booking.confirmed / booking.cancelled**——核验发现既有 booking_service 已 record 但未注册，消除 warning 历史债，与 10-28 chat_edit 同款）；提醒扫描纯函数（窗口 `(today, today+3]`、幂等凭 payload 指纹或已提醒标记）。运行 2.1 确认 Green
- [ ] 2.3 后端全套回归：`cd backend && .venv/bin/python -m pytest -q` 既有测试零失败

## 3. 前端倒计时徽标

- [ ] 3.1 i18n：`zh-CN.js`/`en-US.js` booking 组补键（cancelDeadlineDays 正/零/负三态、basisNote「以预订条款为准」等约 6–8 键），`npm run check:i18n` 通过
- [ ] 3.2 `api/modules/bookings.js`：响应透出 `cancel_deadline_days`；`BookingPanel.vue` 每条目渲染截止倒计时徽标（三态文案 + 截止前 3 天琥珀醒目）；无截止日不渲染。验证：`cd frontend && npm run build` 通过
- [ ] 3.3 手动检查：行前 Tab 台账含截止日/无截止日/已截止三条，徽标三态正确

## 4. 端到端验证

- [ ] 4.1 真机：创建酒店预订回填 free_cancel_deadline=今天+2 天 → 行前台账出现「2 天后可免费取消」+ 行程事件流出现 `booking.cancel_deadline`；截止日设昨天 → 无提醒
- [ ] 4.2 归档：全部 tracked 完成后 `openspec archive free-cancel-deadline` + `docs/night-build-todo.md` 登记完成项