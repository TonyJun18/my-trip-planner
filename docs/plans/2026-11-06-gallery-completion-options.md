# 灵感画廊完善方案（3 选 1 / 可叠加）— 2026-11-06

## 现状盘点（已核实）

**后端能力已存在**（`backend/app/services/gallery_service.py`、`api/v1/trips_gallery.py`、`trips_ratings.py`）：

| 能力 | 接口 | 状态 |
|---|---|---|
| 公开画廊列表 | `GET /api/v1/trips/gallery?limit&offset` | 有，但 `total` 返回的是 `len(items)`（假总数），只能按 `updated_at` 倒序 |
| 城市模板 | `GET /api/v1/trips/gallery/templates` | 有（23 目的地知识库规则生成，零 LLM） |
| 发布 / 撤回 | `POST /{id}/gallery/publish`、`DELETE /{id}/gallery/publish` | 有；**撤回无前端入口** |
| 复制为我的行程 | `POST /gallery/{source_id}/clone` | 有（日程/站点全量，不带令牌/协作数据） |
| 评分热度 | `GET /trips/ratings/summary`、`/{id}/rating` | 有，画廊列表已附带 `rating_count/avg/visited_count` |
| 只读行程页 | `GET /trips/share/{token}` + `/share/:token` 前端页 | 有（完整逐日/站点/评论，966 行，可直接当详情页） |

**前端缺口**（这才是"空壳"的根因）：

1. **没有 `/gallery` 路由**。导航「灵感画廊」跳到 `/?view=gallery`（`App.vue:81`），命中 `LandingPage`——面向陌生访客的营销首页，画廊只是页面最底部（页面高 3469px，画廊在 y≈2330）的一个 `<section id="gallery">`。
2. 画廊区块文案**硬编码中文**（`LandingPage.vue:262-306`：社区精选与城市模板 / 用它开工 / 以此为基础创建），英文界面下仍是中文；`check:i18n` 扫不到模板字面量。
3. 卡片点击**直接 clone**，没有预览、没有二次确认——用户不知道会被复制什么。
4. 发布后**没有「我发布的」管理视图**，想撤回只能调接口。
5. 空态缺失：库里目前只有 1 条真实发布（"大理行程"）+ 8 张城市模板。

> 环境注记：自动化浏览器里 `IntersectionObserver` 不触发，Landing 的 `.reveal` 区块截图为空白——这是截图工具的假象，不是页面 bug。真机上该区块正常显示。

---

## 方案 1｜「先能到」：独立 /gallery 页面（约 1 天）

**做什么**
- 新增路由 `{ path: '/gallery', name: 'gallery', component: GalleryView, meta: { public: true } }`；导航改 `router.push('/gallery')`，`/?view=gallery` 保留为 302 兼容跳转。
- 新建 `views/GalleryView.vue`：页头（标题 + 一句话）→ 筛选条（目的地 / 天数档 / 预算档）→ 网格卡片 → 分页。
- 卡片：标题、目的地、天数、预算、blurb、★ 评分（N 人评）、M 人去过；两个动作：
  - 「看详情」→ `/share/:share_token`（已有只读页）
  - 「以此为基础创建」→ `cloneGalleryTrip()` → 跳新行程
- 页首单独一块「城市模板」（8–23 张），点击深链 `/plan?destination=…&days=…`（现有 prefill 链路）。
- 把 `LandingPage` 里的画廊区块抽成 `<GalleryCard>` 组件复用，并补齐 `gallery.*` i18n（zh/en 两组）。

**后端顺手补（半天内）**
- `list_gallery` 返回真 `total`（`select(func.count())`）+ `sort=new|hot`（hot=rating_count/avg）+ `destination=` 过滤；`limit/offset` 已有。

**取舍**：解决"点了回首页"的核心体验，有筛选有分页；但仍无详情预览，复制是"盲复制"。
**验收**：导航直达独立页；中英双语无硬编码中文；20 条数据下分页正确；筛选生效。

---

## 方案 2｜「闭环」：画廊 + 详情预览 + 我的发布（约 2.5–3 天，推荐）

在方案 1 之上：

1. **详情预览**：`/share/:token` 已能渲染完整行程。在 `ShareView` 加一条 CTA——当来源是画廊（`?from=gallery`）或行程 `is_featured` 时显示「以此为蓝本创建我的行程」+ 作者 blurb + 评分入口（rating API 已有）。
2. **评分/去过**：卡片与详情页接 `POST/PUT /trips/{id}/rating`（count/avg/visited 已在列表聚合里）。
3. **我的发布**：画廊页加「我发布的」tab → 列出自己 `is_featured=True` 的行程，行内「撤回发布」调用已存在的 `unpublishFromGallery()`（当前前端零调用）。
4. **空态引导**：0 条时显示「把你最满意的一条行程发到画廊」+ 一键跳 `/trips`；每条行程的详情菜单里已有「发布到画廊」（`TripDetailMoreMenu`），补一个「已发布」状态回显与取消。
5. **列表增强（可选）**：`view_count` 浏览计数、`mine=1`（我的发布）、`q=` 关键字搜索。

**取舍**：从"能到"到"能逛、能选、能管"，是完整版本；工作量可控，不动数据模型（除可选的 view_count）。
**验收**：卡片→详情→复制全链路可走；发布后能在「我发布的」撤下；详情页能看到逐日行程再决定复制。

---

## 方案 3｜「社区化」（约 1.5–2 周，暂不建议）

- 城市聚合页 `/gallery/city/:name`（SEO 入口）+ 榜单：本周热门 / 编辑精选（需把现有 `is_featured` 拆成 `published` + `editorial_pick`，或新增 `gallery_rank` 字段）。
- 互动：点赞、收藏、评论聚合、"被复制 N 次"社会证明。
- 运营位：专题（"秋天适合去的 8 个地方"）、OG 分享图（复用导出长图能力）。
- UGC 治理：举报、敏感词、人工下架队列——公开内容上量后是必须项。

**取舍**：需要内容量与运营投入；当前只有 1 条发布，做完就是"空城"，建议等方案 1/2 有数据再决定。

---

## 冷启动（无论选哪个方案都要做）

1. **官方精选先铺满首屏**：把 3–5 条打磨过的行程 `is_featured=True` 并写卖点（可直接改库或加脚本），让画廊首屏不空。
2. **模板排前**：城市模板 23 张里先展示 8 张热门城市，点击直达预填规划。
3. **发布动机**：发布成功文案里给出"你的路线被复制 N 次"回执（需 view/clone 计数，方案 2 可加）。

## 建议

**今晚做方案 1，明晚做方案 2 的 1/3/4 三项**（详情 CTA + 我的发布 + 空态），方案 3 看数据。理由：1 解决导航错位，2 的三项补齐闭环且都不依赖新表。
