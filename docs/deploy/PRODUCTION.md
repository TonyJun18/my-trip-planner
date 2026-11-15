# 生产部署检查清单 · my-trip-planner（to-C 上线验证 · 2026-11-15）

> 孪生文档：`docs/plans/2026-11-15-core-value-launch.md`（12 条决策 + 4 周计划）。
> 配套脚本：`backend/scripts/verify_production.py`（上线后一键验证判定线）+ `backend/scripts/create_share.py`（分享链接工具）。
> 本文档只写「怎么部署 + 怎么验证」，不重述决策理由。

## 0. 前置：需要准备的东西（一次性）

| 项 | 规格 | 备注 |
|---|---|---|
| 服务器 | 香港轻量 2C2G（腾讯云/阿里云均可，免备案） | 目标 1–2 天上线 |
| 域名 | 1 个（如 my-trip-planner.example.com），A 记录指向服务器 IP | HTTPS 证书用宝塔自动签发 |
| 预算 | ¥190 封顶（服务器 ¥40/月 × 3 + 域名 ¥70），与止损线绑定 | 不追加 |

> **2026-11-15 核验记录（部署资产本次入库）**
> - 本文档 + `backend/scripts/verify_production.py` + `backend/scripts/create_share.py` **此前一直未入库**（untracked），服务器 clone 下来会缺件；本批已提交入 main。
> - `verify_production.py` 规划契约已修正：`POST /planner/plan` 收 **PlanRequest 直接字段**（destination/dates/travelers/budget/pace…），**不传 trip_id**；服务端规划完成时自动建行程并回填 `task.trip_id`（对应 `planning_service._persist_trip`）。旧版误传 `{"trip_id": …}` 会 422。
> - 实测暴露并修复一个真实产品 bug：**带 TripPlan 快照的行程 DELETE 500**（`Trip.plans` relationship 缺 `cascade="all, delete-orphan"`，ORM 对已加载子行执行 nullify → 违反 `trip_plans.trip_id NOT NULL` → IntegrityError）。已修 `backend/app/models/trip.py` + 回归测试 `tests/test_trip_delete_with_plan.py`。用户侧影响：任何 AI 规划生成的行程都无法删除。
> - 本地冒烟实测（8095 临时实例，2026-11-15）：全绿 7/7——health / register / plan submit(202) / plan done(completed,4天) / share(公开可读200) / analytics(跳过) / cleanup(删除成功)。

目标架构（与 docker-compose 一致，直接搬）：
```
域名 → 宝塔 nginx(443) → 反代 :8080（前端容器 nginx） → :8090（后端 uvicorn）
                                          ↘ :5432（Postgres，仅容器内网，不暴露公网）
```

## 1. W1 上线（3 晚 / ~5h）

### 1.1 服务器初始化（香港轻量）
- [ ] 创建轻量服务器（2C2G，Ubuntu 22.04 / Debian 12），记录公网 IP
- [ ] 安全组/防火墙只放行 `80`、`443`、`22`（**不放行 5432/8090**）
- [ ] SSH 登录，`apt update && apt upgrade -y`
- [ ] 安装 Docker + Compose 插件（`curl -fsSL https://get.docker.com | sh`）

### 1.2 域名 + HTTPS
- [ ] 域名 A 记录 → 服务器 IP（TTL 300）
- [ ] 宝塔面板（可选，但计划已调研）或纯 nginx：签发 Let's Encrypt 证书
- [ ] 宝塔反代：`域名:443` → `http://127.0.0.1:8080`
  - ⚠️ 必须补 WebSocket Upgrade 头（否则 `/ws/*` 握手 403，实时推送静默退化为轮询）：
    ```nginx
    location /ws/ {
      proxy_pass http://127.0.0.1:8080;
      proxy_http_version 1.1;
      proxy_set_header Upgrade $http_upgrade;
      proxy_set_header Connection "upgrade";
    }
    ```
  - ⚠️ 参考 `frontend/nginx.conf` 的 `location /ws/` 段（已含完整 Upgrade 头），宝塔默认反代配置**不含**，必须手动补

### 1.3 拉代码 + 配置
```bash
cd /opt && git clone https://github.com/TonyJun18/my-trip-planner.git && cd my-trip-planner
cp .env.example .env
```
- [ ] 编辑 `.env`：
  - `POSTGRES_PASSWORD` → 强随机（`openssl rand -hex 24`）
  - `JWT_SECRET` → `openssl rand -hex 32`（**必须固定**，否则重启全部 token 失效，本项目 2026-11-08 实测教训）
  - `CORS_ORIGINS` → `["https://你的域名"]`（生产收紧；nginx 反代同源其实可留空）
  - `DEFAULT_LLM_PROVIDER` / `DEEPSEEK_API_KEY` / `TAVILY_API_KEY` / `AMAP_API_KEY` → 填真实值（**不配 → 规划接口明确报错**）
  - `XHS_PUBLISH_MODE=manual`（默认，保持）

### 1.4 起服务 + 迁移
```bash
docker compose up -d --build
# 首次会拉镜像 + 构建后端（uv sync）+ 前端构建，约 5-10 分钟
docker compose ps          # 三个服务都 healthy
docker compose logs backend | tail -50   # 确认 alembic upgrade head 成功、uvicorn 起来了
```
- ⚠️ **全新空库**：compose 的 `pgdata` 卷首次创建就是空库（dev 测试数据绝不带上去）。`backend` 容器启动时会自动 `alembic upgrade head`（幂等）
- ⚠️ 若之前 pull 过旧镜像/旧卷：`docker compose down -v` 清掉重来

### 1.5 冒烟验收（上线当天）
```bash
# 服务器上：
curl -s https://你的域名/api/v1/health          # 应返回 {"status":"ok",...}
curl -s -o /dev/null -w "%{http_code}" https://你的域名/   # 200
curl -s -o /dev/null -w "%{http_code}" https://你的域名/gallery  # 200（SPA 回退）

# 本地（本仓库 backend/.venv）跑全量验证脚本：
cd backend && .venv/bin/python scripts/verify_production.py --base https://你的域名
# 通过 = 注册/规划/分享/事件 四条链路全绿（见第三节）
```

### 1.6 生产安全最小项（逐项确认）
- [ ] `.env` 已 gitignore（仓库已在），**绝不提交**
- [ ] `DEBUG=false`、`ENV=prod`（compose environment 已兜底）
- [ ] 防火墙不放行 5432/8090（仅 80/443/22）
- [ ] `JWT_SECRET` 固定（见 1.3）
- [ ] `CORS_ORIGINS` 收紧（见 1.3）
- [ ] 服务器 SSH 密钥登录（关闭密码登录可选，建议）
- [ ] 备份：`pgdata` 卷定期 `pg_dump`（可选但建议，至少上线当天做一次基线）

### 1.7 最小埋点 5 事件（**待实现**，本次只备清单不写代码）
> 现状：`POST /api/v1/analytics/events` 已存在但**204 不落库**（只写日志，`backend/app/api/v1/analytics.py`）；判定线需要**落库可查**，所以这是 W1 的代码项。
- [ ] 新表 `analytics_events`（alembic 迁移，防御式幂等 `has_table` 先查后建——参考 `c7a9d1e2b3f4` behavior_memory 模板）
- [ ] `POST /analytics/event`（独立端点，新 schema `AnalyticsEventIn2`，白名单 5 事件：`page_view` / `register` / `plan_submitted` / `plan_completed` / `share_created`）
- [ ] 前端打点（复用 `frontend/src/api/modules/analytics.js` 的 `trackEvent` 模式 + `keepalive`；页面级事件：LandingPage `page_view`、register 成功 `register`、PlanWizard 提交 `plan_submitted`、规划完成 `plan_completed`、分享创建 `share_created`；`fire-and-forget` 失败静默）
- [ ] ⚠️ 不挂 `trip_events`（避免污染行程事件流）
- [ ] 测试：`tests/test_analytics_events.py`（5 事件白名单 + 落库 + 幂等 + 未登录）

### 1.8 朋友内测 5 人
- [ ] 选取标准：未来 4–8 周有真实出行计划，含 ≥1 非技术用户
- [ ] 发链接（不带外链跳转阻力），记录反馈渠道（微信/私信）

## 2. W2-W4 执行（获客 / 观察 / 结算）

### 2.1 W2：修 bug + 小红书种草 + 访谈
- [ ] 修朋友筛出的 bug（预期集中：表单认知/修订入口/注册摩擦）
- [ ] 小红书 2–3 篇真实种草（诚实基调，配真实截图；站外链接限流 → 引导主页/私信，不放外链）
- [ ] 3–5 人种子访谈（10 分钟）：哪里卡住/哪里不信任/哪步想放弃/什么让你想回来

### 2.2 W3：观察与轻干预（1 晚）
- [ ] 只看数据，不加功能；可选：对已注册未完成用户发 1 次回访邀请 + 1 篇不同角度笔记
- [ ] 顺带攒 G1–G5 判定线数据（埋点已带 tab/from/on）

### 2.3 W4：判定线结算（第 14 天晚）
- [ ] 跑数据聚合脚本（`backend/scripts/verify_production.py --verify-metrics`，或 SQL 直查 `analytics_events`）：
  ```sql
  -- 访问（page_view 去重会话/设备）
  SELECT count(DISTINCT payload->>'device_id') FROM analytics_events WHERE name='page_view';
  -- 注册
  SELECT count(*) FROM analytics_events WHERE name='register';
  -- 规划提交
  SELECT count(*) FROM analytics_events WHERE name='plan_submitted';
  -- 规划完成
  SELECT count(*) FROM analytics_events WHERE name='plan_completed';
  -- 分享创建
  SELECT count(*) FROM analytics_events WHERE name='share_created';
  ```
- [ ] 判定：✅ 20 真实陌生人访问 → 5 完成真实规划 → 2 分享/收藏 → **解锁 §2 候选池**（open-slot / multicity-optimizer / price-watch-mini / paste-any-plan 等）
- [ ] ❌ 未达 → **执行止损**：停服务器（或降配保留 demo）→ 回退作品集定位 → 内容发布清单继续（A 信号：收藏>50）→ 写《一个 AI 旅行工具的 14 天真实数据》新文章

## 3. 验证脚本（`backend/scripts/verify_production.py`）

上线当天 + 判定线各跑一次。用法：
```bash
# 上线冒烟（默认）：注册→规划→分享→事件 四条链路 + 健康检查
cd backend && .venv/bin/python scripts/verify_production.py --base https://你的域名

# 判定线（W4）：只查 analytics_events 指标，不写数据
.venv/bin/python scripts/verify_production.py --base https://你的域名 --verify-metrics
```
- 通过 = 退出码 0，输出每条链路 OK + 判定线指标表
- 网络不通/被墙：脚本有 30s 超时，会明确报「不可达」，不误报

## 4. 已知坑（部署时对照）

| 坑 | 表现 | 处理 |
|---|---|---|
| `JWT_SECRET` 空 | 后端每次重启，所有已签发 token 全 401 | `.env` 固定 `openssl rand -hex 32` |
| 宝塔反代缺 `Upgrade` 头 | `/ws/*` 握手 403，实时推送静默退化为轮询 | 手动补 `location /ws/` 的 Upgrade 头（见 1.2） |
| alembic 落后 | 新功能「假装 500」（如 `column does not exist`） | 容器启动已自动 `upgrade head`；手动：`docker compose exec backend uv run alembic upgrade head` |
| 防火墙放行 5432 | Postgres 暴露公网，爆破风险 | 只放行 80/443/22 |
| 旧卷脏数据 | `docker compose down -v` 清掉重来（全新空库原则） | 上线前一次性确认 |
| `CORS_ORIGINS` 未收紧 | 任意源可跨域调 API | `.env` 只留你的域名 |
| LLM/搜索 key 未配 | 规划接口明确报错（README 已知局限） | 填 `DEEPSEEK_API_KEY` / `TAVILY_API_KEY` / `AMAP_API_KEY` |

## 5. 上线后回传物（做完一项勾一项）

- [ ] `verify_production.py --base https://…` 输出贴回本会话
- [ ] 服务器 IP / 域名记录在此文档标题下方
- [ ] 判定线结算截图/输出归档到 `docs/nightly/`

---

*配套：`docker-compose.yml`（镜像构建）· `frontend/nginx.conf`（反代 + WS Upgrade 头）· `backend/Dockerfile`（uv + 迁移 + uvicorn）· `verify_production.py`（验证）· `create_share.py`（分享工具）*