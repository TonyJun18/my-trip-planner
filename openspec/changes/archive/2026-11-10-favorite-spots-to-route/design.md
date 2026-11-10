# Design

## Context

收集箱已有完整底座：`FavoriteSpot` 模型（`favorite_spots` 表，user+name_key 唯一）、`favorite_spots_service`（collect/list/remove，零凭证纯规则）、API（`POST /favorite-spots/batch`、`GET /favorite-spots`、`DELETE /favorite-spots/{spot_id}`）、前端收集箱 UI（`FavoritesView.vue` 收集箱区块 + `ImportDialog`「存入收集箱」）。本 change 补第二段：**从收集箱地点生成行程**。见 `proposal.md - Why`。

既有可复用参照（独立实现、不动已测路径）：
- `favorites_route_service.create_route_from_favorite`：收藏行程 → 复制草稿（TripOut 序列化需 eager-load `TRIP_LOADS`）。
- `trip_service.create_trip / add_day / add_stop`：建行程/日程/站点。
- `time_validation.MAX_STOPS_PER_DAY = 5`（权威常量，LLM 与规则同口径）；`plan_b` 展示过分天/装箱思路（`_is_overfull` / `_curated_variant`）。

## Goals / Non-Goals

**Goals:**
- 确定性（零 LLM）地把勾选收藏地点分到 N 天行程，每天 ≤ 5 站，可单测、可复现。
- 诚实报告溢出（放不进的地点数）。

**Non-Goals:**
- 不做 AI 编排/调 LLM 生成路线（那是 planner 的职责；本 change 是规则快速成路线）。
- 不自动补齐缺失坐标（不调高德 geocode；缺坐标按原样入站，诚实标注）。
- 不改 collect-first 底座（不动 `favorite_spots_service` / 现有测试）。
- 不做按真实距离的 TSP/最优聚类（O(n²) 邻近排布超出本 change）；用确定性排序 + 顺序装箱。

## Decisions

### D1: 独立服务模块，不并入 favorites_route_service

新增 `services/favorite_spots_route_service.py`，与 `favorites_route_service`（收藏行程→复制）平行。两者语义不同（复制 vs 从零生成），保持已测路径零改动。

### D2: API 形状

- `POST /api/v1/trips/favorite-spots/route`（登录必需，挂 `trips_favorite_spots` router）
- 请求 `FavoriteRouteIn`: `spot_ids: list[str]`（**顺序 = 用户勾选顺序**，服务端按 id 查本人收藏，杜绝任意地点/越权）、`title`、`destination`、`start_date`、`days: int (1–14)`、`travelers: int (默认 1)`。
- 响应 `FavoriteRouteOut`: `{trip: TripOut, report: {placed: int, overflow: int, hotel_overflow: int, skipped: int}}`。
  - `skipped`：请求中不存在的 id / 他人收藏 → 静默忽略（不 404 整个请求；一个都有效都不剩则 400）。
- 为什么 spot_ids 而非直接传地点对象：服务端是权威（只生成本人收藏，防枚举/注入），前端不传 name/lat/lng。

### D3: 分天算法（确定性，纯函数可单测）

```
输入: spots（按勾选顺序的本人收藏列表）, days
1. 分组: hotels = [stop_type == hotel]; others = 其余
2. 若 others 全部有坐标: 按 (lat, lng) 字典序排序; 否则保持勾选顺序
3. 每站依次装箱（桶 = days 个, 每桶容量 MAX_STOPS_PER_DAY）:
   - others 依次放入「容量未满的最小编号桶」
   - hotels: 每天至多 1 家 —— 放入「空序位最小且无 hotel 的桶」首位 (order_index=0 占位, 桶内已有 others 时挤到其后? 否: hotel 先入桶占首位)
算法修正（保证 hotel 首位）: 先处理 hotels —— 第 i 家 hotel 放桶 i（i < days）首位; 多余的 hotel 计 hotel_overflow。
   再处理 others —— 依序放入容量未满的最小编号桶（hotel 已占 1 位, 该桶剩 4 位）。
4. 溢出 = 未放完的 others 数 + hotel_overflow
5. 输出: [{day_number, date, stops: [StopIn...]}] + placed/overflow
```

- 桶容量 = `MAX_STOPS_PER_DAY`（`from app.services.time_validation import MAX_STOPS_PER_DAY`，单一权威来源，避免两处常量漂移）。
- date 分配：`start_date + (i)`；note 留空。
- **Why 字典序而非贪心最近邻**：O(n log n) 确定性、可复现、无随机；贪心 O(n²) 对 ≤ 50 点收益微小且难测。跨天坐标不连续不做优化（诚实：用户自行在详情页调整）。

### D4: 落库直接批量 insert（不走 add_day/add_stop 逐条 HTTP 语义）

用一个事务内 `db.add(Trip)` + flush + N 个 `TripDay` + 全部 `Stop`（order_index 从 1 递增），最后 `TRIP_LOADS` eager-load 后返回 `TripOut`。
- 不走 `trip_service.add_day`（它按 `day_number` 冲突校验 + 独条 flush，批量 N 天会 N 次往返；且本 change 是「生成」语义，非用户逐天添加）。
- 不触发行为记忆（`_record_behavior_safely` 是手动操作触点；批量生成属模板生成，与 `create_route_from_favorite` 同构——它也没记行为）。

### D5: 前端

`FavoritesView.vue` 收集箱区块新增「一键成路线」按钮 → `el-dialog`（勾选列表 + 标题/目的地/出发日期/天数/人数表单）→ `api.createFavoriteSpotRoute(payload)` → 成功后 `router.push('/trips/' + trip.id)`，`report.overflow > 0` 时 `ElMessage.warning`（用 i18n 文案，如「N 个地点超出每天上限未加入」）。
- `api/modules/favorites.js` 新封装 `createFavoriteSpotRoute` → `http.post('/trips/favorite-spots/route', payload)`。
- i18n：`zh-CN.js` + `en-US.js` 双组键（沿用 `check:i18n` 纪律）。

## Risks / Trade-offs

- [酒店多于天数 → 溢出丢弃] → 记 `hotel_overflow`，报告含「N 家酒店因天数不足未加入」提示；用户可加天数再试。
- [日期无周末/节假日感知，景点开放日不可知] → 诚实：本 change 不做当日可访校验（那是 planner/TimeGate 职责）；生成后详情页仍可调整。
  - **是否复核 TimeGate？** 简洁决策：**不校验**（避免 480 分钟/站数双重拦截误伤用户的明确选择；spec 已框定「每天 ≤ 5 站」为唯一硬上限）。如需，后续可加。
- [字典序分天导致相邻地点分散] → 明确非目标，详情页可拖拽（既有能力）。

## Migration Plan

- 部署：后端新服务+端点（零迁移，无新表）+ 前端新按钮/对话框。发布顺序：后端先行（前端调新端点前，手动 curl 可验收），随后前端。
- 回滚：前端隐藏入口即可（后端端点保留兼容，不破坏旧功能）；后端回滚 = 撤代码即可，无数据迁移依赖。
- 无 alembic 变更；无依赖新增。

## Open Questions

（无——分天策略、API 形状、是否校验 TimeGate 已在 D3/D2/Risks 定案。）