# Proposal

## Why

收集箱（FavoriteSpot）已能「攒地点」（导入候选 → 收藏），但攒完不能变成可用的行程——「地点 → 路线」的第二段缺失，收集箱是死胡同。竞品（Plotline collect-first、问旅「收藏点变路线」）证明「攒 → 一键成路线」是 collect-first 闭环的必备一环；本 change 用确定性规则（零 LLM）补上这一段。

## What Changes

- **后端新增「从收藏地点生成行程」**：用户从收集箱勾选地点 + 指定行程基础信息（标题 / 目的地 / 出发日期 / 天数 1–14 / 人数）→ 服务端创建新草稿行程 + N 个日程，并按**确定性规则**把地点分配到各天（每日至多 5 站，复用既有常量），返回新行程与诚实报告（溢出 / 忽略计数）。
- **分配规则零 LLM、可单测**：酒店锚定（至多每天 1 家、置于该日首位）；景点 / 餐饮按地理位置邻近排序后顺序装箱；坐标缺失回退到用户选择顺序。
- **前端收集箱「一键成路线」入口**：勾选地点 + 表单 → 调 API → 跳转新行程详情页；溢出时明确提示。
- **无数据库迁移**（复用 `favorite_spots` 表与既有行程 / 日程 / 站点表）。

## Capabilities

### New Capabilities

- `favorite-spots`：收藏地点收集箱——收集导入候选为地点、管理收集箱、并从收藏地点一键生成行程（collect-first 闭环第二段）。项目当前 `openspec/specs/` 无任何已有 spec（`openspec list --specs` 为空），此为全新 capability。

### Modified Capabilities

（无）

## Impact

- **backend**：`app/services/` 新增成路线逻辑（独立模块，不动已测的 `favorites_route_service`）、`app/schemas/favorite_spots.py`（新请求 / 响应 schema）、`app/api/v1/trips_favorite_spots.py`（新端点 `POST /favorite-spots/route`）。
- **复用**：`trip_service.create_trip / add_day / add_stop`（建行程/日程/站点）、TimeGate 常量 `MAX_STOPS_PER_DAY`、`favorites_route_service.create_route_from_favorite` 的复制风格（独立实现、不动已测路径）。
- **frontend**：`FavoritesView.vue`（收集箱区块入口 + 对话框）、`api/modules/favorites.js`（新 API 封装）、`locales/zh-CN.js` + `en-US.js`（i18n 双组键）。
- **tests**：`backend/tests/` 扩展（分组算法单测 + API 测试：溢出 / 无效 id 忽略 / 越权 / 鉴权）。
- 无依赖变更；无 alembic 迁移。