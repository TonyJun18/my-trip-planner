# Tasks — launch-deploy

> 执行顺序：先部署底座（W1），再埋点，后运营取数。验证命令见各任务。

## 1. 生产部署（W1 · 3 晚 / ~5h）

- [ ] 1.1 服务器与域名：香港轻量 2C2G 开通 + 域名 A 记录解析 + HTTPS 证书（宝塔反代）。验证：浏览器 `https://<域名>` 可达（200）
- [ ] 1.2 空库初始化：docker-compose 全新起 PG（新库名），**不导入 dev 数据**。验证：生产库 trips/users 表计数为 0
- [ ] 1.3 生产安全最小项：`JWT_SECRET` 固定（随机生成非空）、`CORS_ORIGINS`=真实域名、`DEBUG=false`、PG 5432 不暴露公网（仅容器内网 + 宝塔内网代理）。验证：`.env` 检查 + 公网扫描 5432 不通
- [ ] 1.4 前端部署：nginx 静态托管 + `/api` `/ws` 反代。验证：登录注册流程在生产可达

## 2. 最小漏斗埋点（5 事件）

- [ ] 2.1 **迁移**：`analytics_events` 表（event_name/created_at/user_id?/trip_id?/anonymous_session_id/payload JSON，索引 event_name+created_at）；`models/analytics.py`；Alembic 迁移。验证：`cd backend && .venv/bin/python -m alembic upgrade head` 成功
- [ ] 2.2 **后端端点**：`POST /analytics/event` 支持 `dedicated: true`（或独立 `/analytics/funnel` 端点）落库 5 类事件（白名单：page_view/register/plan_submitted/plan_completed/share_created）；`dedicated=false`/缺省 → 既有日志 204 行为不变。测试 `tests/test_analytics_funnel.py`：5 类落库 / 白名单外 422 / 匿名可记录 / 既有意图埋点零回归。运行 `cd backend && .venv/bin/python -m pytest tests/test_analytics_funnel.py -x` 确认 Red → Green；全套回归零失败
- [ ] 2.3 **前端打点**：路由切换（page_view）、注册成功（register）、提交规划（plan_submitted）、完成规划（plan_completed）、创建分享（share_created）五处调用；`api/modules/analytics.js` 封装（fire-and-forget，失败不影响业务）。验证：`cd frontend && npm run build` 通过 + i18n 检查

## 3. 判定线脚本与 14 天结算（W4）

- [ ] 3.1 聚合脚本 `backend/scripts/launch_judgment.py`（或 docs/nightly 脚本）：从 analytics_events 聚合 访问→注册→提交→完成→分享 逐层转化率；输出判定线对比（20/5/2 是否达标）。验证：本地造数跑通，输出各层计数 + 达标布尔
- [ ] 3.2 第 14 天结算：跑脚本 → 对照判定线 → 记录结果到 `docs/nightly/`（达标：解锁 §2 候选池；未达：执行止损预案）

## 4. 运营（W2-W3）

- [ ] 4.1 朋友内测 5 人（未来 4-8 周有出行计划，含 ≥1 非技术用户）：收集 bug/摩擦点
- [ ] 4.2 小红书 2-3 篇真实种草（诚实基调 + 真实截图，不放外链，引导主页/私信）
- [ ] 4.3 3-5 人种子访谈（哪里卡住/哪里不信任/哪步想放弃/什么让你想回来）
- [ ] 4.4 W3 可选：对已注册未完成用户发回访邀请 + 再发 1 篇不同角度笔记

## Workflow follow-up（归档相关）

- 全部 tracked 完成且判定线结算后：`openspec archive launch-deploy` + `docs/night-build-todo.md` 登记完成项（`task-launch-deploy` 移 §3）