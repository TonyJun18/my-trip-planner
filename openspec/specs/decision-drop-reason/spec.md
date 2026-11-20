# decision-drop-reason Specification

## Purpose
把候选筛选从黑盒变成可解释：在三个确定性筛选出口（站点候选 top-N、备选方案取舍、酒店候选）
记录「为什么淘汰」，以 rule_based 理由透出到前端折叠区。零 LLM、可追溯、不编造。

## Requirements

### Requirement: 确定性淘汰理由

系统 SHALL 提供纯函数 `compute_drop_reasons`，对候选筛选过程的被淘汰项产出 `{stop_id, name,
reason_code, reason_i18n_key, basis="rule_based"}`。reason_code 枚举：`budget_over`（超出预算档）、
`distance_too_far`（距锚点超阈值）、`category_mismatch`（类目不匹配用户偏好）、`capacity_full`（当日容量已满）、
`pacing_conflict`（节奏冲突）。理由文本 SHALL 走 i18n 键（前端按 locale 渲染），不硬编码中文。

#### Scenario: 超预算淘汰

- **WHEN** 站点候选 top-N 中某站人均消费超过请求预算档
- **THEN** 该站产出 `{reason_code: "budget_over", reason_i18n_key: "dropReason.budgetOver", basis: "rule_based"}`

#### Scenario: 距离淘汰

- **WHEN** 某候选站距当日锚点 > 距离阈值（复用 DrivingGate haversine 阈值）
- **THEN** 产出 `{reason_code: "distance_too_far"}`

### Requirement: 站点候选筛选挂载

`solver_service.solve` SHALL 在 `plan.solver_meta` 增可选 `drops` 数组（被淘汰的站点候选 + 理由）。
既有字段（passed/violations/unresolved）语义不变；drops 只记录不改变筛选结果（纯审计）。

#### Scenario: solver 记录淘汰

- **WHEN** 某日候选 5 站、只取 3 站（2 站因超预算/距离淘汰）
- **THEN** `plan.solver_meta.drops` 含 2 条，与保留候选互斥

#### Scenario: 无淘汰零输出

- **WHEN** 候选全部入选（无淘汰）
- **THEN** `drops` 为空数组或缺失（不产出空理由）

### Requirement: 备选方案取舍理由

`plan_b` 生成的备选变体 SHALL 携带相对主案的取舍理由：每个被替换/被移除的站点带
`drop_reason`（`pacing_conflict` 或 `budget_over`，按变体类型：节奏/预算/取舍）。

#### Scenario: 节奏变体替换理由

- **WHEN** plan_b 生成「更松弛」变体，把主案某站 X 换为 Y
- **THEN** 变体携带 drop 记录：X → `pacing_conflict`（行程太赶）

### Requirement: 酒店候选淘汰理由

酒店候选（HotelRecommend / 等价响应）SHALL 每条携带 `drop_reasons`：同目的地其他酒店候选被淘汰
的原因列表（`budget_over` / `distance_too_far` / `category_mismatch`）。至少展示「为什么选这个」的
对照信息（候选 N 个、入选 1 个、淘汰 N-1 个各带理由）。

#### Scenario: 酒店候选对照

- **WHEN** 目的地有 5 家酒店候选，入选 1 家（评分最高）
- **THEN** 响应含该家 `drop_reasons`（其余 4 家各一条理由：如 2 家超预算、1 家距离远、1 家类目不符）

### Requirement: 前端折叠区透出

行程详情页 SHALL 提供「备选与淘汰理由」折叠区（默认收起）：展示被淘汰候选名单 + 理由
（i18n 渲染 + basis=rule_based 标注）。无 drops 时不显示折叠区。酒店候选卡 SHALL 展示
`drop_reasons` 对照（小字理由行）。

#### Scenario: 折叠区展示

- **WHEN** 行程含 2 条被淘汰站点 + 1 条酒店淘汰理由
- **THEN** 折叠区展开后显示全部 drops（站点 + 酒店），每条约 1 行理由 + basis 标注
