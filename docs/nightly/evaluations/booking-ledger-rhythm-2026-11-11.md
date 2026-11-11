# booking-ledger-rhythm 端到端验证（2026-11-11）

- Change：`openspec/changes/booking-ledger-rhythm`（方案一·订单台账 + 方案二·预订节奏规则库）
- 分支：`nightly/2026-11-11/0-booking-ledger-rhythm`（worktree，基于 main c731e51）
- 验证方式：worktree 后端真实进程（127.0.0.1:8091 Postgres）+ 前端 dev（127.0.0.1:5174 代理至 worktree 后端）+ Playwright（系统 Chrome）
- 回归：`cd backend && uv run python -m pytest -q` → **1026 passed, 1 skipped**（基线 997 + 台账/节奏 29 例）

## 链路 1：邮件确认邮件 → 归并台账 → 回填凭证 → 日卡片徽标

1. 粘贴酒店确认邮件（含「订单号 HT20261120001 / 确认码 A8K3M9 / 入住 2026-11-20 / ¥1280」）→ 解析出 2 条酒店条目（含「携程酒店」跨行误聚，属解析器既有行为，用户可勾选剔除）；
2. 勾选 + 并入台账 → 台账 `status=pending`、`reference=email.import`，有码条目 `order_no=HT20261120001`、`service_date=2026-11-20`；无码条目 `order_no=em-7c000d0b04691f7f`；
3. 台账内「我订好了」回填确认码 → `confirmed`（凭证防线未放松：无凭证仍 400）；
4. 日卡片出现「🏨 酒店 · 手动」订单徽标（service_date 投影）。
- 截图：`/tmp/booking-ledger-01-email-parsed.png`、`02-merged.png`、`04-confirm-dialog.png`、`05-confirmed-panel.png`、`06-day-badge.png`

## 链路 2：预订节奏（确定性规则库）

- 行程含 2026-11-20 故宫博物院站点 + 2026-11-20 入住酒店（today=2026-11-11）：
  - ticket：`故宫博物院 门票` window_open=2026-11-13（游玩日-7）、phase=upcoming、basis=rule_based；
  - hotel：`北京王府井希尔顿酒店` window_open=2026-11-13（入住日-7）；
  - 节奏卡渲染 phase 徽标 + 窗口日期 + 「规则推算（rule_based），…以官方渠道为准」；
- 确认酒店后重新计算：hotel 条目消失（confirmed 不再提醒），ticket 保留。
- 截图：`/tmp/booking-ledger-03-ledger-rhythm.png`

## 链路 3：导出核验（owner 全量 / share 脱敏）

- owner `GET /trips/{id}/export`：bookings 段含 `credential=A8K3M9`、`order_no=HT20261120001`；
- share `GET /trips/share/{token}/export`：bookings 段无 `credential` 键；`order_no` → `****0001`（尾 4 掩码）；`em-` 合成键 → `—`。

## 一致性检查

- 节奏端点两次读取结果一致（响应级断言在 `test_booking_rhythm.py::TestRhythmEndpoint`）；节奏不落 `trip_events`（纯函数签名无 db/session）。
- 中立立场未变：零库存/零资金/零返佣；归并条目一律 pending，服务端忽略请求侧 status/credential（注入防御测试覆盖）。
