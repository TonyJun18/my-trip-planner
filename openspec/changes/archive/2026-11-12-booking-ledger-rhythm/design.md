# Design

## Context

- 既有资产：`TripBooking` 状态机（suggested → pending → confirmed ⇄ cancelled，confirmed 必须带凭证）、`_deeplink` 纯函数外链、`scan_bookable_stops` 规则扫描、`email_import.parse_email` 纯规则解析、`booking.*` 事件流、`BookingPanel.vue`（详情页行前准备 Tab）。
- 约束（硬边界，见 proposal Why）：零库存、零资金、零返佣；`confirmed` 凭证防线不放松；诚实口径（`basis` / `reference`）标注。
- 本 change 的两块能力共享「确定性代码兜底、LLM 不碰管理数据」哲学，与 TimeGate / DynamicFacts 同构。

## Goals / Non-Goals

- **Goals**：邮件导入 → 台账归并的最短路径；预订条目获得服务日期维（排序/倒计时/按日投影）；导出数据自由补齐预订维度；「什么时候订」的确定性节奏表。
- **Non-Goals**：接分销/联盟 API；代收资金；自动比价或价格抓取；Gmail OAuth 级邮箱集成；打卡/行中逻辑改动；为「已取消」预订做退款追踪。

## Decisions

### D1. `service_date` 用独立列而不是塞 `probe_plan` JSON
`probe_plan` 是「预订状态投影」预留挂载点，语义是渠道回调数据，不是用户主观数据；服务日期是台账的一级排序/倒计时键，进 WHERE/ORDER BY，独立列（Date, nullable, 索引）才能稳定排序与将来按日查询。备选「复用 probe_plan JSON」被否：JSON 列内排序需全表反序列化，且语义混淆。

### D2. 邮件归并走独立端点而不是解析时自动落库
`POST /bookings/merge-email` 接收前端回传的条目子集（用户勾选后提交），服务端**不信任**解析结果直接入库——保持「解析是候选、落库是决定」的两段式（与站点候选勾选并入同构）。幂等沿用 `provider+order_no` upsert；解析出 code 为空的条目以 `provider="manual"` + `order_no=None` 落 pending（不进幂等匹配，允许重复归并由前端按 `email_import_id` 去重，见 D4）。备选「解析成功自动 upsert」被否：邮件正文常含多行程/旧订单，静默落库会制造垃圾台账与虚假「已订」观感。

### D3. `reference` 扩展 `email.import` 字面量
现有三值（plan.generated / user.confirmed / channel.callback）不足以区分归并来源；新增 `email.import`（Literal 扩一项，向后兼容——旧值行为不变）。凭证防线不变：`confirmed` 必须带 order_no/credential 的校验按 reference 无差别执行。

### D4. 邮件条目幂等键：有码用码，无码用确定性合成键
有 `code`：`provider+order_no` 天然幂等。无码：前端传 `fingerprint`（`sha256(kind|name|datetime|amount)` 截断，纯前端计算即可，服务端只做长度校验）填入 `order_no` 字段并加 `em-` 前缀落库——同一封邮件重复归并命中同一键，幂等成立；合成键在台账可见（order_no 展示为「—」当以 `em-` 开头），不与真实凭证混淆。备选「无码条目拒绝归并」被否：大量酒店邮件确认码在图片里，粘贴文本版拿不到，拒绝会让功能形同虚设。

### D5. 台账排序在服务层做，不新增聚合端点
`list_bookings` 改为「service_date 非空升序在前（NULLS LAST）→ created_at 升序」；`days_until` 在响应模型构造时计算（Python 端日期差，含负数=已过去 N 天）。备选「前端排序」被否：分享路径将来复用同一顺序，服务层是唯一事实源。

### D6. 日卡片订单投影走前端本地匹配
详情页已拉 `GET /bookings`（行前 Tab 用），日卡片从同一份响应按 `service_date == day.date` 过滤，零后端改动、零新端点。备选「后端在 get_trip 响应注入 per-day bookings」被否：耦合两个聚合读路径，收益（省一次已存在的请求）不抵契约面扩大。

### D7. 导出脱敏：share 路径 `order_no` 尾 4 位、`credential` 剔除
沿用 export 既有「令牌字段绝不输出」先例；owner 路径全量（自己导给自己备份）。`em-` 合成键在两条路径都视为非凭证：share 路径展示为「—」。规则：`credential` 字段 share 路径**永不输出**（即使空），`order_no` 输出 `****{last4}` 或「—」。

### D8. 节奏规则库 = 纯函数 + 日期数学，不接任何外部源
`booking_rhythm.py` 四类规则（均 `basis=rule_based`，输出带「以官方渠道为准」提示）：
1. **train**：12306 预售期 15 天 → `window_open = service_date - 15d`（起售日精确到早 8 点/整点分批的细节不做，标注口径）；
2. **ticket**：复用 `scan_bookable_stops` 的 timed-entry 关键词表 → 放票日规则表（故宫 7 天 20:00 等已知条目，规则表 `{关键词: 提前天数}`，未命中给通用「提前 7 天关注」档）；
3. **flight**：国内启发式「T-30 前后关注、T-14 后大幅涨价风险上升」→ 输出「建议关注窗口」而非价格断言；
4. **hotel**：入住前 7 天「检查免费取消截止」提醒（不假设具体截止时刻）。
输入 = trip（start_date/end_date + stops）+ 既有 bookings（去重：已有建议的站点不重复产出）；输出 = `[{kind, target, window_open, window_deadline, phase(open/upcoming/closing), basis, note}]`。**不做**：真实放票时间 API、价格监控（免费源不存在，task-price-alert-eval 已关单）。

### D9. 节奏提醒复用事件流，不新增推送设施
「窗口已开」不落 `trip_events`（事件是业务动作事实，规则推算是读路径派生，落事件会让 append-only 流混入计算结果）——节奏条目只在 `GET /bookings/rhythm` 响应实时计算；前端行前准备 Tab 渲染 + 未处理条目计数徽标。PWA Notification 通道暂不接（避免常驻定时任务），与「零凭证零后台任务」约束一致。

## Risks / Trade-offs

- [12306/故宫等规则会过时] → 规则表集中在一处常量 + `basis=rule_based` + 「以官方渠道为准」文案，与 DynamicFacts 同一维护模式
- [`em-` 合成键撞真实订单号] → 前缀 `em-` 命名空间 + 合成键不参与 confirmed 凭证展示；真实订单号以 `em-` 开头的概率与危害（仅影响幂等合并）可接受
- [归并 pending 可能被误解为「已订」] → 台账 pending 徽标文案「待确认」，hint 明示「确认需回填真实凭证」；`reference=email.import` 保留归并痕迹
- [导出脱敏遗漏] → share 路径构造函数集中一处（`_sanitize_booking`），单测断言 credential 键不存在、order_no 匹配 `^\*{4}\d{4}$|—`
- [service_date 与行程日期矛盾（订了行程外的日期）] → 不拦截：台账是用户事实记录，不是排程约束；仅投影时按日期匹配（无命中就不显示，不报错）

## Migration Plan

1. Alembic 迁移：`trip_bookings` 加 `service_date DATE NULL` + `service_note VARCHAR(500) NULL`（两者可空，零数据回填，可 downgrade）。
2. 后端 schema/服务/端点/导出按 tasks 顺序 TDD 落地；全量回归 `uv run pytest -q`。
3. 前端面板/导入/日卡片 + i18n；`npm run build` + `npm run check:i18n`。
4. 回滚：迁移 downgrade -1 即回；新端点独立 router 无存量调用方。

## Open Questions

<!-- 无：service_date 语义、幂等键方案、脱敏口径均已在 D1-D9 定案；节奏规则的常量值（15 天/7 天/T-30）以现行公开规则为准并在规则表注释标明「2026-11 口径，以官方为准」。 -->
