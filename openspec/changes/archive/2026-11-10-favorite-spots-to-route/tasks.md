# Tasks

## 1. 后端：服务层（分天算法 + 生成）

- [x] 1.1 新建 `backend/app/services/favorite_spots_route_service.py`：实现纯函数 `assign_spots_to_days(spots, days) -> dict`（hotels 锚定每日首位 + 坐标字典序/勾选顺序 + 顺序装箱每天 ≤ MAX_STOPS_PER_DAY），从 `time_validation` 导入 `MAX_STOPS_PER_DAY`，不硬编码 5。验证：单元测试（`tests/test_favorite_spots_route.py`）覆盖酒店锚定、坐标有序、缺坐标回退、溢出计数，全部通过
- [x] 1.2 实现 `create_route_from_spots(db, user, spot_ids, data) -> dict`：按 id 查本人收藏（不存在/他人 → skipped 计入报告）、生成 Trip + N 个 TripDay + 全部 Stop（order_index 从 1 起、lat/lng 原样保留、checked=False）、`TRIP_LOADS` eager-load 返回 TripOut-ready dict。验证：服务测试覆盖生成结构（owner/draft/无 token/站点字段）、跳过计数、**一个有效 id 都不剩 → 抛 400 类错误**
- [x] 1.3 服务层统一在单事务内落库（db.add + flush + commit），不逐条走 trip_service.add_day/add_stop；不触发行为记忆触点。验证：代码评审（无对 trip_service 写路径的调用）+ 既有测试不回归

## 2. 后端：Schemas + API

- [x] 2.1 在 `backend/app/schemas/favorite_spots.py` 新增 `FavoriteRouteIn`（`spot_ids: list[str]` 顺序即勾选顺序、`title`、`destination`、`start_date`、`days: int 1–14`、`travelers: int ≥1 默认 1`）与 `FavoriteRouteOut`（`trip` + `report{placed,overflow,hotel_overflow,skipped}`），并在 `schemas/__init__.py` 导出。验证：pydantic 校验用例（days=0 → 422、空 spot_ids → 422）通过
- [x] 2.2 `backend/app/api/v1/trips_favorite_spots.py` 新增 `POST /favorite-spots/route`（登录必需，201 返回 `FavoriteRouteOut`；请求中无有效 id → 400）。验证：API 测试覆盖 401 / 201 / 400 / 一人生成不受他人收藏影响
- [x] 2.3 `backend/app/api/v1/__init__.py` 路由注册确认（若该 router 已挂 `trips` 前缀则无改动）。验证：`from app.api.v1 import ...` 冒烟 + 既有 API 测试全绿

## 3. 后端：测试补全

- [x] 3.1 `tests/test_favorite_spots_route.py` 补齐场景：溢出提示（8 点 1 天 → placed=5/overflow=3）、酒店溢出（3 酒店 2 天 → hotel_overflow=1）、缺少 id 忽略、生成后原收藏箱不变、新行程可被 TripOut 序列化（stops 非空）。验证：`cd backend && .venv/bin/python -m pytest tests/test_favorite_spots_route.py -q` 全绿
- [x] 3.2 全量回归测试。验证：`cd backend && .venv/bin/python -m pytest -q` 通过（现有 ~982 用例 + 新增全部绿）

## 4. 前端：API + 收集箱入口

- [x] 4.1 `frontend/src/api/modules/favorites.js` 新增 `createFavoriteSpotRoute(payload)` → `POST /trips/favorite-spots/route`。验证：前端构建通过（`npm run build`）
- [x] 4.2 `FavoritesView.vue` 收集箱区块新增「一键成路线」入口（选中若干地点 + 打开对话框，标题/目的地/出发日期/天数/人数表单，提交调用 API，成功后 `router.push('/trips/' + trip.id)`，`report.overflow>0` 时 ElMessage.warning 提示溢出数）。验证：vite 本地 + 真机 API 冒烟（建行程 → 返回 TripOut、跳转成功）；`npm run check:i18n` 无缺失
- [x] 4.3 `zh-CN.js` + `en-US.js` 补齐对话框与提示文案（含溢出文案的 {count} 插值）。验证：`cd frontend && npm run check:i18n` 通过

## 5. 集成验证

- [x] 5.1 后端全量测试 + 前端 build 同时绿。验证：`cd backend && .venv/bin/python -m pytest -q` 与 `cd frontend && npm run build` 均通过
- [x] 5.2 真机冒烟（可选但推荐）：固定 `JWT_SECRET` 启动后端 → 登录 → 收藏 2 地点 → `POST /favorite-spots/route`（days=1）→ 返回 TripOut 含 1 day/2 stops、overflow=0 → 前端 FavoritesView 走通全流程。验证：curl 与浏览器目视均符合预期