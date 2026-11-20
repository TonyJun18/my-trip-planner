# geo-anchor-sanity Specification

## Purpose
给行程加一道「地理一致性」质检：以行程内站点坐标的质心为锚，检测离群站点（物理上远离行程主体
的站点），产出确定性 warning（basis=rule_based）并进质检 trace。交通占位与多城段豁免；
零 LLM、零外部 API、绝不误伤。

## Requirements

### Requirement: 质心锚定

系统 SHALL 以行程内有坐标站点的地理质心（经纬度平均值）为锚。单城行程：全部有坐标站点的质心；
多城段行程（`multi_city` 段结构）：每段内站点的质心分别作为该段锚。
无任何有坐标站点时 SHALL 不产出 geo_sanity 结果（诚实沉默）。

#### Scenario: 单城质心

- **WHEN** 杭州行程含 8 个有坐标站点（均在西湖周边 10km 内）
- **THEN** 质心位于站点群中心，全部站点距离 < 80km，无离群 warning

#### Scenario: 无坐标沉默

- **WHEN** 行程所有站点均无 lat/lng
- **THEN** geo_sanity 无输出（不编造、不告警）

### Requirement: 离群检测

系统 SHALL 对每个有坐标站点计算到所属质心的 haversine 距离（复用 `day_optimizer._haversine_km` 同源实现）；
距离 > `GEO_OUTLIER_KM`（默认 80）的站点 SHALL 产出离群 warning，结构复用 `CritiqueIssue`
（issue + suggestion：建议「确认该站是否应保留 / 是否属于另一城市段」），basis=rule_based。

#### Scenario: 离群站点命中

- **WHEN** 北京行程 8 站中 7 站在市区（<80km），1 站在 300km 外的城市（如石家庄）
- **THEN** 该站产出 1 条 geo_sanity warning（suggestion 提示核对），其余站点不告警

### Requirement: 交通占位豁免

标识为交通占位（`is_transfer` 或名称含「交通占位」）的站点 SHALL 豁免离群检测——
跨城大交通站物理上必然远离市中心，不是规划错误（与 repeat_detector 豁免同构）。

#### Scenario: 交通占位豁免

- **WHEN** 行程含「杭州→黄山 交通占位」站（距杭州质心 200km）与 8 个杭州市区站
- **THEN** 交通占位站不告警，市区站无告警

### Requirement: 多城段分组锚定

多城段行程 SHALL 按段分组锚定（每段独立质心），段间大距离不误报；若某段内仍有离群站
（段内质心 > 80km），SHALL 照常告警。

#### Scenario: 多城段不跨段误报

- **WHEN** 行程含「杭州段（8 站）+ 上海段（6 站）」，杭州-上海段间距 170km
- **THEN** 两段均无跨段告警；段内若有离群站（如上海段某站距上海市中心 150km）→ 仅该站告警

### Requirement: 质检链路接入

`geo_sanity` 结果 SHALL 进入：`plan.warnings`（追加）、`plan.geo_gate`（`{checked, issues}`，与
time_gate/weather_gate 同形状）、质检 trace（`basis=rule_based` 标注）；`revise_service` 修订重算
SHALL 复用（同一纯函数）；`property_qa` 预警汇总 SHALL 纳入 geo_sanity issues。前端质检卡
SHALL 展示「地理一致性」片段（warning 列表 + basis 标注 + 建议）。

#### Scenario: 修订重算

- **WHEN** 用户修订移除离群站后重新生成
- **THEN** geo_gate 重新计算，该站 warning 消失（若已移除）

#### Scenario: 前端透出

- **WHEN** 行程含 1 条离群 warning
- **THEN** 质检卡「地理一致性」片段显示该 warning + 「规则库」basis 标注
