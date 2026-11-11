# booking-rhythm Specification

## Purpose
回答「什么时候该订什么」，且只回答时间、不回答价格与库存：用确定性规则库（纯日期数学，零 LLM、
零外部数据源、零凭证）推算火车预售窗口、场馆放票日、机票关注窗、酒店取消检查，
每条结论标注 `basis=rule_based` 并提示以官方渠道为准——读路径实时派生，不落事件、不推送、不代订。

## Requirements

### Requirement: 确定性预订节奏计算

系统 SHALL 提供预订节奏端点（owner 专属）：基于行程日期、站点与既有台账，
用**确定性规则库**（纯日期数学，零 LLM、零外部数据源、零凭证）计算「什么时候该订什么」，
覆盖四类规则：火车预售窗口（发车日前 N 天开售，N 以现行公开预售期为准）、
热门场馆放票窗口（按站点名命中放票日规则表，未命中给通用提前量）、
机票关注窗口（出发日前后的建议关注期，仅窗口建议、不作价格断言）、
酒店取消检查提醒（入住日前 N 天）。每条节奏条目 SHALL 携带
`window_open`（可订/行动窗口开启日）、`window_deadline`（建议截止日）、
`phase`（open=窗口已开 / upcoming=窗口未开 / closing=临近截止）与
`basis="rule_based"` 标注及「以官方渠道为准」提示文案。

#### Scenario: 火车预售窗口

- **WHEN** 行程含 2026-12-01 的火车出行需求（或台账中 service_date=2026-12-01 的 suggested/pending 火车票）
- **THEN** 节奏结果含一条 train 条目，window_open=2026-11-16（提前 15 天），按当前日期与窗口关系给出 phase

#### Scenario: 热门场馆放票窗口与通用档

- **WHEN** 行程某站名命中放票规则表条目（如「故宫」）
- **THEN** 该站产出一条 ticket 节奏条目，window_open=游玩日前 7 天
- **AND** 未命中规则表的 timed-entry 站点产出通用档条目（提前 7 天），不编造具体放票时刻

#### Scenario: 无成本纯计算与诚实标注

- **WHEN** 任意行程调用节奏端点
- **THEN** 计算过程不调用 LLM、不访问外部网络服务，每次调用结果一致（确定性）
- **AND** 每条条目 basis=rule_based 且携带「以官方渠道为准」提示

### Requirement: 节奏条目与台账去重

节奏计算 SHALL 跳过已满足条件的重复建议：台账中已存在 confirmed 的条目对应节奏项
SHALL 不再产出（已订完成）；suggested/pending 条目对应节奏项 SHALL 保留（提醒确认/补票）。
同一目标（kind + 日期/站点） SHALL 至多产出一条节奏条目。

#### Scenario: 已确认预订不再提醒

- **WHEN** 台账中已有一条 confirmed、service_date=2026-12-01 的火车票，再次计算节奏
- **THEN** 结果不含该火车目标的节奏条目

#### Scenario: 待确认条目保留节奏提醒

- **WHEN** 台账中该火车票为 pending（订了未确认）
- **THEN** 节奏结果仍含该目标条目（提醒回填凭证确认）

### Requirement: 节奏是派生读路径，不落事件

节奏条目 SHALL 在每次读取时实时计算，SHALL NOT 写入行程事件流（append-only 事件是业务动作
事实记录，规则推算结果不得混入），也 SHALL NOT 依赖后台定时任务或推送设施。
前端行前准备区域 SHALL 展示节奏条目列表及其 phase 状态。

#### Scenario: 重复读取结果稳定且无副作用

- **WHEN** 同一行程连续两次调用节奏端点
- **THEN** 两次结果一致，且行程事件流无新增记录
