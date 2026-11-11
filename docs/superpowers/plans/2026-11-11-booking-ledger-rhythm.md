# 实现计划：booking-ledger-rhythm（OTA 预订管理 · 台账 + 节奏）

- 日期：2026-11-11
- 工作流：openspec-superpowers-workflow（OpenSpec artifacts 已完成并校验通过，本计划为 Superpowers 执行交接件）
- OpenSpec change：`openspec/changes/booking-ledger-rhythm/`（proposal / design / specs×2 / tasks）
- 状态：**等待用户批准开工**——按用户要求，批准前不改动任何代码

## 一、目标（两能力合一 change）

1. **booking-ledger（订单台账）**：预订条目获得 `service_date` / `service_note` 维；邮件导入结果一键归并台账（幂等、pending 落库、confirmed 凭证防线不变）；台账排序 + 倒计时；确认预订投影到日卡片；导出补 bookings（share 路径脱敏）。
2. **booking-rhythm（预订节奏规则库）**：确定性「什么时候该订什么」——火车 15 天预售、热门场馆放票日、机票关注窗口、酒店取消检查四类规则，`basis=rule_based` 诚实标注，读路径实时计算、零事件污染。

硬边界（两次既有评估已关单，本 change 维持）：零库存、零资金、零返佣、不接分销/联盟 API、不做价格抓取。

## 二、执行顺序（TDD：Red → Green，逐组回归）

| # | 组 | 内容 | 验证命令 |
|---|---|---|---|
| 1 | 模型/迁移 | TripBooking + `service_date`/`service_note`；schema 三处补可选字段 | `pytest tests/test_booking_ledger.py -x` → `alembic upgrade head` |
| 2 | 邮件归并 | `POST /bookings/merge-email`；`reference=email.import`；`em-` 合成幂等键 | `pytest tests/test_booking_ledger.py tests/test_email_import.py -q` |
| 3 | 台账读 + 导出 | 列表按 service_date 排序 + `days_until`；export 加 bookings 段（`_sanitize_booking` share 脱敏单处集中） | `pytest tests/test_booking_ledger.py` → 全套 `pytest -q` |
| 4 | 节奏库 | 新建 `booking_rhythm.py` 纯函数 + `GET /bookings/rhythm` 端点 | `pytest tests/test_booking_rhythm.py -q` |
| 5 | 前端 | i18n ~12 键；`api/modules/bookings.js` 两封装；`ImportDialog.vue` 归并入口；`BookingPanel.vue` 台账化 + 节奏卡；`TripDetailDayCard.vue` 订单徽标 | `npm run build` + `npm run check:i18n` |
| 6 | 真机端到端 | 邮件→归并→确认→日卡片徽标全链路；节奏卡去重与 basis；导出脱敏核验 | 截图留档 `/tmp/booking-ledger-*.png` |

## 三、关键决策（详见 design.md D1-D9）

- **D1** 独立列不塞 `probe_plan` JSON（排序键需进 ORDER BY，语义分离）
- **D2** 归并是显式动作（解析是候选、落库是决定），防止静默落库制造虚假「已订」观感
- **D3/D4** `reference` 扩 `email.import`；无码条目 `em-sha1(...)[:16]` 合成幂等键，重复归并不重复落行
- **D7** 脱敏单处集中：share 路径 `credential` 永不输出、`order_no` 仅 `****+尾4`
- **D8/D9** 节奏 = 纯函数 + 日期数学零外部源；不落 trip_events（append-only 事件不混计算结果）、不接推送（零后台任务约束）

## 四、风险与缓解

- 规则常量会过时 → 集中一处 + `basis=rule_based` + 「以官方渠道为准」文案（DynamicFacts 同模式）
- 归并 pending 被误读为已订 → 台账「待确认」文案 + hint 明示确认需真实凭证
- 脱敏遗漏 → `_sanitize_booking` 单点 + 单测断言键不存在
- 既有 453+ 测试回归 → 新字段全部可选，无破坏性契约变更

## 五、批准后动作

1. 从 main 拉分支 `nightly/2026-11-11/0-booking-ledger-rhythm`（遵循仓库分支纪律：只本地 commit）
2. 按上表顺序 TDD 执行；每组完成跑对应验证命令，全绿后才进下一组
3. 全部完成后：`openspec archive booking-ledger-rhythm` + README「中立立场」小节补一句 + night-build-todo 登记
