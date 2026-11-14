# 0001: 内容发现层建立在「导航 + 互动 + 运营」三维

## Context

对照 Travora（OTA 全栈）竞品分析，我们识别出「内容-发现-互动」是唯一真差距：首页静态灵感区（6 张硬编码城市卡）冷启动不稳、画廊无任何公开互动信号、精选只能 owner 自助发布无法运营。三项行动项同批立项，共享「内容发现层」概念域。

## Decision

同批实施三项，构成内容发现层：

1. **导航：首页静态灵感区 → 真实城市模板行（23 条规则生成，冷启动稳）**，点击走模板深链预填 `/plan?dest=杭州&budget=3000`（只预填目的地+预算档映射金额，**不预填天数/日期**——模板无真实日期，臆造日期违反诚实口径）。底部真实画廊 teaser 保留，两个入口各有定位并存。
2. **互动：新增 `gallery_likes` 表**（trip_id+user_id 唯一，幂等 toggle，owner 不可自赞），独立于 1-5 星评分与 visited_count，**不参与 hot 排序**（与 ratings 各自独立计，三个信号并排展示）。登录可点，画廊卡显示 ❤ 计数。
3. **运营：给 User 加 `is_staff` 单字段**（不建管理后台），通过 env 白名单 `STAFF_USER_IDS` 启动同步授予；staff 可对任意公开行程标 featured（`POST /trips/{id}/gallery/feature`，仅 API 无前端入口）。owner 撤回仍 owner-only；staff 标记的行程被 owner 撤回时清 featured（保底一致，不新增贬值端点）。

## Considered Options

- **首页灵感区形态**：换真实画廊 hot 行（否决：冷启动期 featured 仅 3 条会空）；改静态+动态混排（否决：模板行冷启动已稳，无需混排）。
- **点赞模型**：复用 trip_ratings 加标志位（否决：布尔语义与 1-5 星评分不同，污染评分聚合）；把 visited_count 当互动信号（否决：语义混叠）。
- **staff 授予**：数据库手改（否决：不可审计）；内建 staff 管理 API（否决：递归授权且无 UI 场景）。
- **运营入口**：staff 前端按钮（否决：无管理后台，仅 API 契约先行，前端二期）。
- **hot 排序**：like 数并入权重（否决：语义混杂，违背信任诚实）。

## Consequences

- 新增 1 张表（gallery_likes）+ User 表加 1 字段（is_staff）→ 需 alembic 迁移（防御式幂等，遵循 c7a9d1e2b3f4 模板）。
- GalleryCard 显示三信号（❤/★/去过），卡片密度上升。
- PlanWizard 首次读 query 预填（此前只读表单状态），需补 `route.query` 接线。
- ADR 惯例从本文件建立（此前仓库无 docs/adr/ 与 GLOSSARY.md）。
- 首次登录需要同步 is_staff（登录路径从 env 读取白名单 upsert）。

## Status

accepted