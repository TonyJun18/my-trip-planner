# 夜间开发任务队列（NIGHT BUILD TODO）

> 本文件是夜间开发的**任务来源**。`night-start` 每晚把它读入检查点。
> 每夜第一个任务固定为竞品分析（competitive-analysis），分析结论会追加到这里。
> 任务格式：`- [ ] <slug>: <描述>（验收标准）`

## 首夜种子任务（源自 2026-09-19 OPC 复盘决策 + 项目现状）

- [ ] competitive-analysis: 竞品分析（AI 旅行规划产品 3-5 个），输出差距→行动项（首夜必做，输出 docs/nightly/competitive-analysis/<date>.md）
- [ ] oss-license: 补 LICENSE（MIT）+ 开源说明段落加入 README（验收：LICENSE 文件存在，README 有 LICENSE 小节）
- [ ] oss-gitignore: 审查 .gitignore（backend/.gitignore、frontend/.gitignore、根目录），确保 .env、.venv、dist、__pycache__ 不被提交（验收：git status 干净度 + .gitignore 覆盖）
- [ ] content-readme: README 增加「夜间开发流水线」说明 + 已知局限表格同步（验收：README 内容与仓库实际一致）
- [ ] content-article-publish-list: 为 docs/articles/ 3 篇文章各写一份「发布清单」（标题变体 3 个 / 平台适配要点 / 首图建议），不自动发布（验收：docs/nightly/publish-list.md 存在）
- [ ] task-hotel-budget: 补酒店价格真实度——评估并实现「基于 POI 类目 + 城市基准价的估算模型」，让预算 hotel 项不再是空壳（验收：compute_budget 输出 hotel 有非 0 估算 + 测试覆盖）
- [ ] task-revise-ux: 前端「让 AI 调整行程」对话交互打磨（加载态、错误态、diff 预览）（验收：build 通过 + 交互状态完整）
- [ ] task-deploy-pack: Docker 化部署包（backend Dockerfile + docker-compose.yml + 部署文档），不实际部署（验收：docker compose config 通过）

## 竞品分析后追加（夜间自动填充）

- [ ] task-trip-share: 行程分享/群组协作最小版——生成分享链接 + 只读查看（Mindtrip 实时 co-edit + 投票、Layla 群组协调、MonkeyTravel 群组投票均为多人出行刚需）（验收：分享链接可打开只读行程页 + 测试覆盖）
- [ ] task-roadtrip-mode: 自驾模式最小版——站点间驾车距离约束校验 + 超时/折返告警（TripPlanner AI 主打差异化：经停优化、避免折返）（验收：路由拒绝超距站点组合 + 测试覆盖）
- [ ] content-diff-positioning: 写一篇发布就绪文章《为什么 AI 行程工具应该把"修订"做成一等公民》（差异化定位：可执行/可修订/质检透明；Tripnotes.ai 停运留出市场窗口）（验收：docs/articles/04-diff-positioning.md 存在且内容完整）

## 竞品分析后追加（2026-09-22 国内平台，来自 docs/nightly/competitive-analysis/2026-09-22.md）

- [ ] task-active-questions: 主动提问/需求挖掘——规划提交后、执行前动态追问 1-3 个问题（出行人群/节奏/避峰需求/备选方案偏好），答案并入规划上下文（马蜂窝 AI 路书「主动提问」差异化）（验收：后端规划请求支持 questions 字段 + 前端追问交互 + 测试覆盖）
- [ ] task-user-profile-memory: 跨会话用户画像记忆——用户偏好画像表（人群/节奏/预算档/常去城市）+ 规划时注入画像摘要（同程记忆关联性、飞猪微细分、Layla 个性化）（验收：画像 CRUD API + 规划注入 + 测试覆盖；不读 .env、不需要新 API key）
- [ ] content-map-edit-paradigms: 文章《表单、对话、地图拖拽：三种行程修订范式的工程代价》——对比携程地图拖拽编辑/我们 AI diff 原子应用/表单生成三种修订范式的体验与工程代价，为 task-map-drag-edit 铺路（验收：docs/articles/05-map-edit-paradigms.md 存在且内容完整，代码引用与仓库实际一致）
- 注（backlog，不单独建任务）：行程备选方案（Plan B）待 task-roadtrip-mode 完成后评估；多语种攻略输出并入 task-i18n-base 范围

## 2026-09-23 竞品分析追加（格局快照：预订闭环 vs 规划层）

- [ ] task-trip-collab-vote: 行程协作投票最小版——分享行程页加评论 + 每日站点 👍/👎 投票（Mindtrip co-edit、Wanderlog 免费实时协作、MonkeyTravel 群组投票均验证多人出行刚需）（验收：分享页可投票/评论 + 测试覆盖；待 task-trip-share 合并稳定后评估）
- [ ] content-planning-vs-booking: 写一篇发布就绪文章《AI 旅行规划正在变成预订漏斗——独立工具的机会在"规划层"》（Mindtrip agentic 机票 + Expedia 收购 Layla 的行业分层观察；免费/透明/可修订规划层定位）（验收：docs/articles/06-planning-vs-booking.md 存在且内容完整）
- [ ] task-manual-edit: 行程手动细粒度编辑——站点卡片行内编辑（标题/时间/顺序拖拽），与 AI 修订并存（Wanderlog 手动自由改 + 地图联动是最强交互）（验收：行程详情页可改单日单点 + build 通过 + 测试覆盖；排在 task-roadtrip-mode 之后）

## 用户白天下达任务（2026-09-21 追加）

- [ ] task-google-auth-frontend: 前端 Google 登录按钮——GIS 加载 + credential 回调 → POST /auth/google → 复用 setSession；按钮文案与配色融入 AuthView（后端已完成：branch nightly/2026-09-21/10-task-google-auth-backend，POST /api/v1/auth/google 已就绪）。GOOGLE_CLIENT_ID 前端可先用占位/环境变量注入，不强制真实 key（验收：build 通过 + 登录链路代码完整）
- [x] task-i18n-base: 多语言基础设施——vue-i18n@9 + zh-CN/en-US locales + 顶栏语言切换器 + Element Plus locale 联动（el-config-provider）（验收：build 通过 + 切换语言后 Element 组件文案与页面硬编码文案来源统一）。已完成基础设施 + App/Auth/TripList 壳层迁移；PlanWizard/TripDetailView/ShareView 大视图硬编码文案待后续 task-i18n-views）
- [ ] task-i18n-views: 大视图文案迁移——PlanWizard/TripDetailView/ShareView 三视图硬编码中文迁移到 locales（约 1.6 万字符）（验收：切到 en-US 后三视图主要文案为英文 + build 通过；task-i18n-base 遗留，工作量超出单 worker 窗口，拆分为独立任务）
