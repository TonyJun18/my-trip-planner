# task-trip-rating-signal 评估与实现记录（2026-10-29）

> 队列：docs/nightly/checkpoint.json todo[current_index=3]（2026-10-29 夜 worker-4）
> 类型：候选评估（backend + frontend）→ **评估通过并实现最小版**
> 分支：nightly/2026-10-29/3-task-trip-rating-signal

## 1. 评估结论

**结论：可行，实现最小版（零凭证、与 favorites 同语义、无资损敞口）。**

### 1.1 数据源与成本矩阵

| 方案 | 成本 | 凭证 | 合规 | 结论 |
|---|---|---|---|---|
| 登录用户评分（1-5）+「我去过」 | 零（复用现有 users/trips 表 + 唯一约束） | 零 | 无第三方数据 | ✅ 采用（最小版） |
| 第三方行程评分/点评聚合（猫途鹰/马蜂窝等） | 高（爬取/API） | 需凭证 | 数据授权不明 | ❌ 关单（与 price/guest 同构降级） |
| LLM 生成评分/热度 | 每行程 token 成本 | 零 | 编造信任信号，违反诚实口径 | ❌ 绝不做（avg 只来自真实用户） |

### 1.2 信任语义设计（诚实口径）

- `avg` 只来自真实登录用户评分，系统绝不编造/加权/兜底；
- 无评分行程 `avg=None`（0 会被误读为差评）；`count=0` 诚实展示「暂无评分」；
- 「我去过」是**事实标签**（visited），与评分同表记录、可翻转，不做成营销追踪。

### 1.3 可见性语义（与收藏一致）

- 任何登录用户可评**存在即可见**的行程（与 `TripFavorite` 完全一致，不校验 owner /
  分享/发布状态）——评分不扩权、不泄露新数据、不改变行程可见性；
- 仅评分者本人可改/删自己的评分（同 user+trip 唯一约束，幂等 upsert）。

### 1.4 风险边界

- 无资损（纯只读聚合 + 登录写）；无凭证消耗；
- 防刷：单用户单手行程一条（唯一约束）+ 前端交互自限；若出现刷分再立项 IP 限流
  （与 guest-trial 关闭时的限流缺失同构，但评分是登录态，风险显著低于匿名）。

## 2. 实现内容

### 后端（backend）

- **模型** `TripRating`（`app/models/trip.py`）：trip_id + user_id + rating(1-5) +
  visited(布尔)，`uq_trip_ratings_user_trip` 唯一约束，级联删除。
- **迁移** `c2d4e6f8a0b2_add_trip_ratings.py`（down_revision=b2c3d4e5f6a7 head）。
- **服务** `rating_service.py`：`upsert_rating`（幂等改分/翻转 visited）、
  `delete_rating`（幂等）、`get_rating`（聚合 + 我的评分）、`rating_summary`
  （批量 count/avg/visited_count，无评分 avg=None）。
- **API** `trips_ratings.py`：
  - `POST /trips/{trip_id}/rating`（登录，1-5，visited 可选）
  - `PUT /trips/{trip_id}/rating`（幂等改分/翻转）
  - `GET /trips/{trip_id}/rating`（聚合 + 我的评分，可选登录）
  - `DELETE /trips/{trip_id}/rating`（幂等）
  - `GET /trips/ratings/summary?trip_ids=...`（批量热度，免登录）
  - 注册顺序：`/ratings/summary` 字面量段先于 trips_crud 的 `/{trip_id}`。
- **画廊透出**：`gallery_service._gallery_summary` 增加 rating_count/rating_avg/
  visited_count 字段，`list_gallery` 批量 attach（尽力而为，失败降级为无评分）。

### 前端（frontend）

- **LandingPage 画廊卡片**：`rating_count > 0` 时展示 ★ 星级（四舍五入）+ 
  均分（1 位小数）+ 评分人数 + 「N 人去过」；配套 scoped 样式。

## 3. 验收对照（todo 原文）

| 验收项 | 状态 |
|---|---|
| 评估记录（数据源矩阵 + 成本 + 合规结论） | ✅ 本文件 |
| 评分模型 | ✅ TripRating + 迁移 |
| API | ✅ 增删改查 + 批量聚合 |
| 画廊透出 | ✅ gallery summary 3 字段 + LandingPage 卡片展示 |
| 测试覆盖 | ✅ tests/test_trip_rating.py 8 例 |
| 不可行记降级关单 | 不适用（评估通过） |

## 4. 测试结果

- 专项：`tests/test_trip_rating.py` **8 passed**（提交/更新/删除幂等、422/401、
  404、详情、批量聚合、画廊透出、可见性语义）。
- 全套：`backend` **668 passed**（99.7s）。
- 前端：`npm run build` **通过**（3.21s）。

## 5. 遗留 / 待用户处理

- ~~评分**交互入口**（行程详情页/分享页评分控件）本期未做~~ → **2026-11-08 已闭环**：
  - 分享页 `ShareView.vue` 画廊来源评分条（2026-10-29 同批上线）。
  - 详情页 `components/trip-detail/TripDetailRatingCard.vue`（2026-11-08）：行程结束后
    （`phase === 'finished'`）露出评分卡，1-5 星 + 「我去过」+ 聚合口径
    （`{avg} 分 · {n} 人评` / `{n} 人去过`，无评分显示「还没有人评分」）+ 「清除评分」（DELETE）；
    已有评分或被他人评过时始终可见（避免「评过就消失」）。组件自载数据，挂载在导出区**之外**
    （评分是私域操作，不进截图/PDF/打印稿）。
  - 验证：`npm run build` 4.84s 通过、`check:i18n` 944 键 ×2 对齐、`tests/test_trip_rating.py` 8 passed；
    真实浏览器实测（登录态注入 → 打分 4 星 → 勾「去过」→ 刷新持久化 → 清除归零；
    未来行程卡片不出现、评过之后仍出现）。
- 分支 `nightly/2026-10-29/3-task-trip-rating-signal` 待 review 后合并。
- 防刷限流（如未来上匿名评分或热度影响排序）另立任务。