# Proposal

## Why

Roamy/Rhyme 真实差评群（2026-11-17 竞品分析 §3.1）暴露 AI 行程生成器的「地理翻车」：用户「飞进 Dallas 并从那开始」→ 行程直接跳到 8 小时外城市；Costa Brava 优化到巴黎；Azores 小岛被带到葡萄牙大陆；「Disney + 8 个其他地点塞进同一天」。我们现状：`day_optimizer` 有**日内**最近邻贪心（`_haversine_km`，`services/day_optimizer.py:35`）与首站锚定，但**无行程级地理一致性检查**——跨天/整个行程的离群站点（从市中心跑到 80km 外、或单日塞进物理上不可能的地理范围）不会被发现，也不会进质检。

数据基点核验（2026-11-20）：`inspiration_service.py` 的 `DESTINATIONS` 知识库**无坐标字段**（只有 name/tags/budget/seasons），不能作为「城市中心锚」数据源 → 锚定改用**行程内站点坐标的质心**（纯内部数据，零外部依赖，多城段按段分组质心）。这与 time_validation / weather_validation / repeat_detector 同构：纯函数规则库 + plan warning + 质检 trace（basis=rule_based）。

## What Changes

- 新建 `services/geo_sanity.py` 纯函数规则库（零 LLM 零网络）：
  - `_centroid(stops)`：有坐标站点的地理质心（经纬度平均）；
  - `check_geo_sanity(plan)`：逐站计算到所属质心（单城=全行程质心；多城段=段内质心）的 haversine 距离，> `GEO_OUTLIER_KM`（默认 80）且非豁免 → 产出离群 warning（`basis=rule_based`）。
  - 豁免：交通占位站（`is_transfer` / 名称含「交通占位」——与 repeat_detector 豁免同构）；多城段站点按段质心（不跨段误报）。
  - 输出结构复用质检契约（CritiqueIssue 形状：issue + suggestion），进 `plan.warnings` + `plan.geo_gate` + 质检 trace。
- 接入：`pipeline.py` 生成链路 FinalizePlanStep 后挂 `geo_sanity`（与 time_gate/weather_gate 同位置）；`revise_service` 修订重算复用；`property_qa` 预警汇总纳入。
- 前端：质检卡 timegate-card 区域增「地理一致性」片段（warning 列表 + basis 标注）；i18n zh/en 键。
- **不做**：调外部地理 API；LLM 判断地理（防编造）；地图交互改动；把「离群」当硬错误拒绝（只是 warning + 建议）。

## Capabilities

### New Capabilities

- `geo-anchor-sanity`: 行程级地理一致性检查——质心锚定、离群检测、交通占位/多城段豁免、质检 warning 与 trace。

### Modified Capabilities

<!-- 无：day_optimizer 日内优化保持不动，本能力是其行程级补充 -->

## Impact

- **后端**：新建 `services/geo_sanity.py`；`pipeline.py`（FinalizePlanStep 注入）、`revise_service.py`（重算）、`property_qa_service.py`（预警汇总）小改；测试 `tests/test_geo_sanity.py`（命中/未命中/交通占位豁免/多城段豁免四路径）。
- **前端**：`TripDetailView` 质检卡地理片段 + i18n（约 4–6 键 ×2）。
- **零破坏**：全部 warning 增量，无 schema/迁移/硬约束变更；既有测试零回归。
- **依赖**：零新依赖（math.haversine 自实现，与 day_optimizer 同源）。