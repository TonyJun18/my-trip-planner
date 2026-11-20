# Design

## Context

- 既有资产：`day_optimizer._haversine_km`（`services/day_optimizer.py:35`，球面距离 + `_coords(stop)` 坐标提取）、`time_validation`/`weather_validation`/`repeat_detector` 三个纯函数质检规则库（CritiqueIssue 结构 + plan.*_gate + warnings + trace 契约）、`multi_city` 段结构（task-multi-city-segments）。
- 核验修正（2026-11-20）：`inspiration_service.DESTINATIONS` **无坐标字段** → 原「dest 城市中心锚」依赖不成立；改用**行程内站点质心锚**（纯内部数据，零外部依赖）。
- 约束：零 LLM / 零外部 API / 不编造 / 只 warning 不硬拒 / 与四个既有 gate 同构。

## Goals / Non-Goals

- **Goals**：质心锚定、离群检测（80km 阈值）、交通占位豁免、多城段分组、质检链路接入、前端透出。
- **Non-Goals**：外部地理 API；LLM 地理判断；硬错误；地图改动；destinations 补坐标（可另立）。

## Decisions

### D1. 锚定用行程内站点质心，不依赖 destinations 知识库
知识库无坐标（核验实证），且只覆盖 27 个目的地——用户规划任意城市时锚会缺失。质心方案：有坐标站点经纬度平均，单城全行程 / 多城按段。局限：站点稀疏时质心漂移（如只有 2 个站且都在城市边缘）——用 `MIN_CENTROID_STOPS=3`（少于 3 个有坐标站点不产出，诚实沉默）缓解。

### D2. 离群阈值 80km + 交通占位豁免
`GEO_OUTLIER_KM=80`：城市核心区外圈通常 <50km，>80km 基本是「另一个城市」级别。`is_transfer` / 名称含「交通占位」豁免（跨城大交通天然远离市中心，与 repeat_detector 同构）。不做逐类目阈值（博物馆 vs 郊区景点距离语义不同——过度设计，MVP 一个阈值 + warning 建议即可）。

### D3. 复用 CritiqueIssue 契约，不进 schema
输出结构 `{issue, suggestion}` 与 time_gate/weather_gate 同形状；`plan.geo_gate = {checked: bool, issues: [...]}`。零 schema 演进、零迁移（plan JSON 内嵌，与既有 gate 同位）。

### D4. 修订重算与 property_qa 汇总照抄 weather_gate 先例
`revise_service` 在重算 weather_gate 的位置一并重算 geo_gate（快照复用）；`property_qa_service` warning 汇总加 geo_sanity issues。前端从 plan 数据读（`WS_PLAN_KEYS` 若需要加 `geoGate`）。