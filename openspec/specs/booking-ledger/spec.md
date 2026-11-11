# booking-ledger Specification

## Purpose
把预订从「外链跳转」升级为**用户自己的台账**：每条预订记录服务日期与备注，能按日期排序并带倒计时；
邮件里解析出的预订条目可一键并入台账，但一律以 `pending` 落库（`reference=email.import`），
只有回填真实凭证才允许 `confirmed`。导出时 owner 全量、分享路径单点脱敏——记录归用户，凭证不外泄。

## Requirements

### Requirement: 预订条目携带服务日期与备注

预订条目 SHALL 支持可选的 `service_date`（服务日期：车次发车日 / 酒店入住日 / 门票出行日）与
可选的 `service_note`（用户自由文本备注：车次 / 房型 / 取消政策等），两者均可空；
创建（POST /bookings）与状态更新（POST /bookings/{id}/status）请求 SHALL 接受这两个可选字段，
列表与详情响应 SHALL 原样返回。服务日期 SHALL NOT 参与状态机判定——条目的合法性
（confirmed 必须带凭证）与服务日期无关。

#### Scenario: 录入带服务日期的预订

- **WHEN** owner 创建一条预订：kind=train、provider=12306、status=pending、service_date=2026-11-20
- **THEN** 响应含 `service_date="2026-11-20"`，且条目状态为 pending
- **AND** 不要求提供 order_no/credential（pending 语义即「订了待确认」）

#### Scenario: 省略可选字段零破坏

- **WHEN** 以旧客户端字段集（无 service_date/service_note）创建或更新预订
- **THEN** 请求成功，响应中两字段为 null，既有行为（状态机/幂等/事件）不变

### Requirement: 邮件导入结果归并台账

系统 SHALL 提供「邮件条目并入台账」端点（owner 专属）：接收解析出的预订条目子集，
按幂等键落库为台账条目——有确认码的条目以 `provider + order_no` 幂等；无确认码的条目
SHALL 使用确定性合成键（`em-` 前缀 + 内容指纹）落库，使同一邮件重复归并产生同一条目而非重复行。
归并条目 SHALL 以 `status=pending`、`reference=email.import` 落库；升入 confirmed 仍 MUST 满足
既有凭证防线（order_no/credential 必填），状态机其余规则不变。
解析服务本身 SHALL NOT 自动落库——归并必须是用户显式动作。

#### Scenario: 有确认码条目归并且重复归并幂等

- **WHEN** owner 将邮件解析出的酒店条目（provider=ctrip、code=BK12345678）归并两次
- **THEN** 台账中该 provider+order_no 只有一条记录，第二次归并返回同一条目（幂等更新而非新增）

#### Scenario: 无确认码条目归并

- **WHEN** owner 归并一条无确认码的航班条目（kind=flight、name、datetime、amount）
- **THEN** 生成一条 pending 台账条目，order_no 为 `em-` 前缀合成键，reference=email.import
- **AND** 同一邮件重复归并命中同一合成键，不产生重复行

#### Scenario: 归并条目升确认仍需凭证

- **WHEN** owner 请求把一条 reference=email.import 的 pending 条目置为 confirmed 且未提供凭证
- **THEN** 请求被拒绝（400 booking_invalid_transition），与既有防线一致

### Requirement: 台账排序与倒计时

预订列表（owner 路径）SHALL 按 `service_date` 升序返回（空值排在有值之后），同日期按创建时间升序；
每条响应 SHALL 携带 `days_until`（距服务日期的天数：未来为正、当天为 0、已过为负、无服务日期为 null）。

#### Scenario: 排序与倒计时

- **WHEN** 行程台账含三条预订：A（service_date=3 天后）、B（service_date=1 天后）、C（无 service_date）
- **THEN** 返回顺序为 B、A、C
- **AND** B 的 `days_until=1`，C 的 `days_until=null`

### Requirement: 已确认预订投影到日卡片

行程详情页的每日日程 SHALL 展示当天已确认预订的徽标：前端按 `service_date` 与日日期匹配
台账中 `status=confirmed` 的条目，在对应日卡片渲染 kind 与 provider 标签。
投影 SHALL NOT 改变站点数据，取消（cancelled）与待确认（pending）条目不参与日卡片徽标。

#### Scenario: 确认预订显示在对应日

- **WHEN** 某日 date=2026-11-20 且存在一条 confirmed、service_date=2026-11-20 的火车票
- **THEN** 该日卡片显示火车票订单徽标（kind 图标 + provider 标签）
- **AND** 同日一条 pending 条目不显示徽标

### Requirement: 导出含预订且分享路径脱敏

行程导出（owner 路径）SHALL 包含 `bookings` 段（全部字段，含凭证——自己备份自己）；
分享令牌导出路径 SHALL 包含 `bookings` 段但必须脱敏：`credential` 字段绝不输出，
`order_no` 仅以「尾 4 位掩码」（`****1234`）形式输出，`em-` 合成键输出为「—」。
脱敏规则 SHALL 集中实现，两条路径不得各自拼接。

#### Scenario: owner 导出全量

- **WHEN** owner 调用行程导出
- **THEN** 导出 JSON 的 bookings 段含 order_no 与 credential 原值

#### Scenario: 分享导出脱敏

- **WHEN** 凭 share_token 调用分享导出
- **THEN** bookings 段中每条目无 credential 字段，order_no 为 `****` + 尾 4 位（合成键为「—」）
