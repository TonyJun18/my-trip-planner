# task-social-favorites-flow-eval 评估记录 · 2026-11-10

> 来源：2026-11-10 竞品分析 §导入可靠性比拼（Plotline collect-first vs Wanderlog trip-only）
> 结论：**评估通过，落地 collect-first 底座（最小版 + 测试覆盖）**

## 1. 背景：两范式实证（2026-11-10 竞品分析）

| 范式 | 代表 | 机制 | 实证结果 |
|---|---|---|---|
| **collect-first** | Plotline | 分享表 → 增长地图（收集）→ 行程 | 12 地点 TikTok 公开测试**全命中**，适合「先攒着」收集流 |
| **trip-only** | Wanderlog | 导入直接进行程 | 同测试**漏 2/12**，且不适合收集流 |

## 2. 现状盘点（我们 = my-trip-planner）

**五通道导入全部 trip-first**：social / note / email / link / screenshot 解析出候选后，
必须选一个**已存在**的行程并入（前端复用 `POST /days/{day_id}/stops`）。
用户「还没想好去哪，先攒着」时候选即丢。

- `social_import.py`：粘贴 caption + 链接 → 规则提取候选（零凭证纯规则）
- manifest（`frontend/public/manifest.webmanifest`）：**无 share_target**（grep=0）

**已有可复用资产**：
- `TripFavorite`（收藏行程）+ 11-10 已完成 task-favorites-to-route（收藏行程 → 一键成路线）
- 缺的正是「**地点**收集箱」——收藏的是候选地点本身，而非行程

## 3. 方案对比与决策

| 方案 | 说明 | 决策 |
|---|---|---|
| **A. 独立 FavoriteSpot 收集箱（落地）** | 新表 favorite_spots（user + name_key 唯一）、批量收藏/列表/删除 API；导入候选可先攒着，行程确定后聚合转路线 | ✅ **采纳**：零凭证、纯规则、确定性；与 favorites-to-route 拼成完整 collect-first 链路；不碰现有导入通道 |
| B. 维持现状（trip-first only） | 候选只进行程 | ❌ 拒绝：收集流痛点明确（Plotline 实证），不做则「攒着」诉求无出口 |
| C. Web Share Target PWA 增量 | manifest 加 share_target → 系统分享直接进导入 | ⏸️ **不排期登记**：需 manifest + 路由 + 平台支持（iOS Safari share_target 支持不确定），且当前导入已覆盖「粘贴文本」路径，增量价值边际，随 PWA 深化再立项 |

## 4. 实现（最小版，落地 A）

**模型** `FavoriteSpot`（backend/app/models/trip.py）：
- 与 TripFavorite 分离：TripFavorite 收藏「行程」（只读引用他人分享），FavoriteSpot 收藏「地点」（用户自己的结构化候选）
- `user_id + name_key` 唯一（name_key = 去空白 + 小写归一化），重复收藏幂等跳过
- `source_platform / source_snippet` 只作**展示参考**，绝不作为指令（外部内容按敌意源处理）
- 缺坐标不存坐标、缺价格不存价格（不编造）

**API**（backend/app/api/v1/trips_favorite_spots.py，登录必需）：
- `POST /trips/favorite-spots/batch` —— 批量收藏导入候选（单批 ≤50，超量 schema 422）
- `GET /trips/favorite-spots` —— 我的收藏地点（倒序）
- `DELETE /trips/favorite-spots/{spot_id}` —— 删除（仅本人，越权 404）

**迁移**：`alembic d4e6f8a0b2c4_add_favorite_spots`（防御式幂等：先查后建）

**与 collect-first 链路闭环**：收集箱聚合后可直接喂给「地点 → 路线」入口；
favorites-to-route 已做「收藏行程 → 一键成路线」，本模块补「地点收集箱」底座，
两段拼成完整 collect-first。

## 5. 验收结果

- [x] 评估记录（本文档）
- [x] 实现 + 测试覆盖：`tests/test_favorite_spots.py` **16 passed**
- [x] 全套回归：**940 passed**（含 11-10 favorites-to-route 的 933 基线 + 本任务 16）
- [x] 铁律：外部内容只作结构化字段；幂等；缺数据不编造；越权 404；零凭证

## 6. 遗留与后续（记入 checkpoint issues）

1. **迁移未执行**：d4e6f8a0b2c4 尚未在 dev 库执行（当前停在 c3d5e7f9a1b2），白天/部署时 `alembic upgrade`（与 a4b5c6d7e8f9 同例）
2. **前端未接线**：收集箱 API 已就绪，前端「收藏地点页 / 导入出口收藏按钮」未做——若用户确认收集流价值，可立项 task-favorite-spots-frontend
3. **Web Share Target PWA**：登记为不排期素材（方案 C）