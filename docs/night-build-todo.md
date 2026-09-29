# 夜间开发任务队列（NIGHT BUILD TODO）

> 本文件是夜间开发的**任务来源**。`night-start` 每晚把它读入检查点。
> 每夜第一个任务固定为竞品分析（competitive-analysis），分析结论会追加到这里。
> 任务格式：`- [ ] <slug>: <描述>（验收标准）`

## 首夜种子任务（源自 2026-09-19 OPC 复盘决策 + 项目现状）

- [ ] competitive-analysis: 竞品分析（AI 旅行规划产品 3-5 个），输出差距→行动项（首夜必做，输出 docs/nightly/competitive-analysis/<date>.md）
- [ ] oss-license: 补 LICENSE（MIT）+ 开源说明段落加入 README（验收：LICENSE 文件存在，README 有 LICENSE 小节）
- [x] oss-gitignore: 审查 .gitignore（backend/.gitignore、frontend/.gitignore、根目录），确保 .env、.venv、dist、__pycache__ 不被提交（验收：git status 干净度 + .gitignore 覆盖）
- [x] content-readme: README 增加「夜间开发流水线」说明 + 已知局限表格同步（验收：README 内容与仓库实际一致）
- [x] content-article-publish-list: 为 docs/articles/ 3 篇文章各写一份「发布清单」（标题变体 3 个 / 平台适配要点 / 首图建议），不自动发布（验收：docs/nightly/publish-list.md 存在）
- [x] task-hotel-budget: 补酒店价格真实度——评估并实现「基于 POI 类目 + 城市基准价的估算模型」，让预算 hotel 项不再是空壳（验收：compute_budget 输出 hotel 有非 0 估算 + 测试覆盖）
- [ ] task-revise-ux: 前端「让 AI 调整行程」对话交互打磨（加载态、错误态、diff 预览）（验收：build 通过 + 交互状态完整）
- [ ] task-deploy-pack: Docker 化部署包（backend Dockerfile + docker-compose.yml + 部署文档），不实际部署（验收：docker compose config 通过）

## 竞品分析后追加（夜间自动填充）

- [x] task-trip-share: 行程分享/群组协作最小版——生成分享链接 + 只读查看（Mindtrip 实时 co-edit + 投票、Layla 群组协调、MonkeyTravel 群组投票均为多人出行刚需）（验收：分享链接可打开只读行程页 + 测试覆盖）（2026-09-29 worker-5 补登记：主体已由 2026-09-21 commit 4051799(后端 share_token 生成 + 免登录只读 GET /trips/share/{token}) + 048b99c(前端详情页分享按钮 + ShareView 公开路由) 完成并经 92fec38 合并 main；test_api.py 分享链路 3 测试 + test_share_lifecycle/collab 覆盖，全套 187 绿）
- [x] task-roadtrip-mode: 自驾模式最小版——站点间驾车距离约束校验 + 超时/折返告警（TripPlanner AI 主打差异化：经停优化、避免折返）（验收：路由拒绝超距站点组合 + 测试覆盖）（2026-09-29 worker-6 补登记：主体已由 2026-09-23 commit e443cd3（backend/app/services/driving_service.py DrivingGate：单段超距/超时/单日累计 critical + 折返/缺坐标 warning，check_day_stops/check_plan_driving/check_plan_driving_async，merge 进 run_planning_agents 评审循环 + revise_service 落库前约束）+ backend/tests/test_driving_service.py（含 DrivingGate 拒绝超距组合→修订→通过、强制定稿保留告警、revise 拒绝超距 add 等 14 测试）完成，并经 2026-09-28 ab8688f 合并 main；real-routes 层 amap_driving.py 属 task-driving-real-routes 范围不在此任务。全套 187 测试绿）
- [x] content-diff-positioning: 写一篇发布就绪文章《为什么 AI 行程工具应该把"修订"做成一等公民》（差异化定位：可执行/可修订/质检透明；Tripnotes.ai 停运留出市场窗口）（验收：docs/articles/04-diff-positioning.md 存在且内容完整）（2026-09-29 worker-7 补登记：主体已由 commit d970fd6 完成（docs/articles/04-diff-positioning.md，含反直觉观察/四个设计决策/可复用模式表/小结，代码引用与仓库实际一致——PlanReviseAgent+ReviseDiff 强校验、revise_service._apply_diff 原子预检、DrivingGate 约束门+_recompute_budget、POST /trips/{id}/revise、TripDetailView diff 预览、QualityCard 质检报告、T-A-O trace），发布清单文章④卡片同步在案，均已合并 main；todo 漏勾导致本夜重跑；worker-7 补登记完成（仅文档改动，全套 187 测试绿））

## 竞品分析后追加（2026-09-22 国内平台，来自 docs/nightly/competitive-analysis/2026-09-22.md）

- [x] task-active-questions: 主动提问/需求挖掘——规划提交后、执行前动态追问 1-3 个问题（出行人群/节奏/避峰需求/备选方案偏好），答案并入规划上下文（马蜂窝 AI 路书「主动提问」差异化）（验收：后端规划请求支持 questions 字段 + 前端追问交互 + 测试覆盖）
- [x] task-user-profile-memory: 跨会话用户画像记忆——用户偏好画像表（人群/节奏/预算档/常去城市）+ 规划时注入画像摘要（同程记忆关联性、飞猪微细分、Layla 个性化）（验收：画像 CRUD API + 规划注入 + 测试覆盖；不读 .env、不需要新 API key）
- [x] content-map-edit-paradigms: 文章《表单、对话、地图拖拽：三种行程修订范式的工程代价》——对比携程地图拖拽编辑/我们 AI diff 原子应用/表单生成三种修订范式的体验与工程代价，为 task-map-drag-edit 铺路（验收：docs/articles/05-map-edit-paradigms.md 存在且内容完整，代码引用与仓库实际一致）
- 注（backlog，不单独建任务）：行程备选方案（Plan B）待 task-roadtrip-mode 完成后评估；多语种攻略输出并入 task-i18n-base 范围

## 2026-09-23 竞品分析追加（格局快照：预订闭环 vs 规划层）

- [ ] task-trip-collab-vote: 行程协作投票最小版——分享行程页加评论 + 每日站点 👍/👎 投票（Mindtrip co-edit、Wanderlog 免费实时协作、MonkeyTravel 群组投票均验证多人出行刚需）（验收：分享页可投票/评论 + 测试覆盖；待 task-trip-share 合并稳定后评估）
- [ ] content-planning-vs-booking: 写一篇发布就绪文章《AI 旅行规划正在变成预订漏斗——独立工具的机会在"规划层"》（Mindtrip agentic 机票 + Expedia 收购 Layla 的行业分层观察；免费/透明/可修订规划层定位）（验收：docs/articles/06-planning-vs-booking.md 存在且内容完整）
- [ ] task-manual-edit: 行程手动细粒度编辑——站点卡片行内编辑（标题/时间/顺序拖拽），与 AI 修订并存（Wanderlog 手动自由改 + 地图联动是最强交互）（验收：行程详情页可改单日单点 + build 通过 + 测试覆盖；排在 task-roadtrip-mode 之后）

## 2026-09-24 竞品分析追加（格局信号：预订层被资本垄断，规划层机会放大）

- [ ] task-share-edit: 分享链接升级「受邀编辑权」——share_token 支持受限编辑（站点顺序/备注/勾选，不经 AI 修订），分享页开放编辑入口（MonkeyTravel/Wanderlog 验证的「一个链接进群、全员可编辑、实时同步」刚需）（验收：受邀方可编辑站点/顺序 + owner 可收回权限 + 测试覆盖；待 task-trip-collab-vote 稳定后评估）
- [ ] content-open-planning-layer: 写一篇发布就绪文章《当 AI 旅行工具都在抢着替你花钱：独立规划层的生存策略》——Mindtrip agentic 机票/酒店预订 + Expedia×Layla 收购为引，讲透「规划与预订分离」哲学，diff 修订 + 质检 trace + 城市基准价透明估算构成反例（验收：docs/articles/07-open-planning-layer.md 存在且内容完整，发布清单补卡片）

## 用户白天下达任务（2026-09-21 追加）

- [x] task-google-auth-frontend: 前端 Google 登录按钮——GIS 加载 + credential 回调 → POST /auth/google → 复用 setSession；按钮文案与配色融入 AuthView（后端已完成：branch nightly/2026-09-21/10-task-google-auth-backend，POST /api/v1/auth/google 已就绪）。GOOGLE_CLIENT_ID 前端可先用占位/环境变量注入，不强制真实 key（验收：build 通过 + 登录链路代码完整）
- [x] task-i18n-base: 多语言基础设施——vue-i18n@9 + zh-CN/en-US locales + 顶栏语言切换器 + Element Plus locale 联动（el-config-provider）（验收：build 通过 + 切换语言后 Element 组件文案与页面硬编码文案来源统一）。已完成基础设施 + App/Auth/TripList 壳层迁移；PlanWizard/TripDetailView/ShareView 大视图硬编码文案待后续 task-i18n-views）
- [x] task-i18n-views: 大视图文案迁移——PlanWizard/TripDetailView/ShareView 三视图硬编码中文迁移到 locales（约 1.6 万字符）（验收：切到 en-US 后三视图主要文案为英文 + build 通过；task-i18n-base 遗留，工作量超出单 worker 窗口，拆分为独立任务）

## 2026-09-25 竞品分析追加（格局信号：国内 OTA 集体 AI 规划化，规划层机会放大）

- [x] task-note-import: 笔记/种草文本导入——粘贴攻略笔记 → 结构化提取站点候选 → 勾选并入行程（Tripnotes 范式复活 + 去哪儿小红书导入验证国内刚需；规划层天然入口：想法搬运工，不绑架预订）（验收：粘贴文本生成站点候选 + 恶意注入文本按敌意输入处理 + 测试覆盖）
- [x] task-plan-b: 行程备选方案 Plan B——规划同时产出 1 个备选骨架（节奏/取舍/预算档不同），详情页主案/备案对比切换（马蜂窝 AI 路书「备选方案」用户高频需求；roadtrip-mode 已落地，评估条件满足）（验收：规划响应含 plan_b + 前端对比切换 + 测试覆盖）
- [x] content-domestic-planning-layer: 文章《国内 OTA 也在做 AI 行程了——独立规划层为什么还能活》（携程一站式规划到预订/去哪儿小红书导入/马蜂窝路书备选方案/飞猪多智能体为引，承接 07 文做姊妹篇，讲国内语境下规划层与预订层的边界与生存策略）（验收：docs/articles/08-*.md 存在且内容完整，发布清单补卡片）
- [x] content-quality-fallback: README 增加「质量与兜底」小节（降级链 + 质检 trace + 已知局限表格同步；OTA 人工定制师/指路人的反向思考——我们的兜底是工程化的降级链与可回溯 trace）（验收：README 内容与仓库实际一致；兼收 09-24 content-readme 收尾）

## 用户白天下达任务（2026-09-25 追加）

> 本轮为「完善方案」评审确认后的执行项，聚焦需求文档「已知局限」表与竞品 backlog 中记录的真实差距。

- [ ] task-driving-real-routes: 自驾路径真实化——DrivingGate 从「球面距离估算」升级为「高德驾车路径 API 真实距离/时长」（局限表原文：自驾基于球面距离估算，与实际道路有偏差）；校验超限单段（>120km/150min，或单日 >300km）自动附「中途经停建议」（竞品 TripPlanner AI「经停优化」差异项）；高德未配置/限流/超时 → 指数退避重试后自动降级回球面估算（现状兜底，不阻断规划）（验收：DrivingGate 输出带 source=amap|haversine 标注 + 超长单段给出经停建议 + mock 测试覆盖成功/熔断/降级路径 + 全套件回归通过）
- [ ] task-share-token-lifecycle: 分享令牌生命周期——share_token 支持过期（TTL：1天/7天/30天/永久）、owner 吊销、免登录访问审计（时间/IP/UA，按行程聚合，owner 可查）；expired/revoked 即时返回 410/403，旧 token（无过期字段）按永久兼容；附带「收藏灵感夹」——登录用户可收藏他人分享的行程，行程列表页展示（验收：过期/吊销/审计 API + 旧数据兼容 + 收藏 CRUD + 前端分享设置弹窗与收藏按钮 + i18n + 测试覆盖，全套件回归通过）
- [ ] task-food-agent: （候选方案 3，工程量较大，单独评估）餐饮搜索 Agent 化——新增 FoodAgent（菜品/口味偏好 → 高德美食 POI → 结构化推荐），Agent 主路径 + 现有代码补位作兜底；Critic 从「打分手」升级为「协作者」——不过审时产出修正 diff（复用 revise diff 执行器）精确修改而非整段重生成（验收：FoodAgent 独立 schema + 代码兜底降级链 + Critic diff 精确修订 + 测试覆盖；暂缓，待方案 1+2 合并稳定后评估）

## 2026-09-26 竞品分析追加（价格真实度 + 实时协作 + 输入范式，来自 docs/nightly/competitive-analysis/2026-09-26.md）

- [ ] task-budget-split: 预算分摊/多币种——行程级预算视图支持「人均分摊」（按成员/按天/按类别），行程元数据携带币种，预算项按成员标记（AiGo 多币种+分摊、Wanderlog 预算协作为海外多人出行刚需；接 share 协作链路）（验收：分享页可看人均预算 + 测试覆盖；排在 task-share-token-lifecycle 之后）
- [ ] task-screenshot-import: 截图导入行程——上传攻略截图 → OCR 提取站点候选（复用 task-note-import 的结构化提取与恶意注入处理管线）→ 勾选并入行程（AiGo screenshot-to-itinerary 为笔记导入姊妹范式；去哪儿已验证小红书图片/笔记导入国内价值）（验收：截图可生成站点候选 + 敌意输入仍按数据对待 + 测试覆盖）
- [ ] content-budget-transparency: 文章《预算是 AI 行程工具最不诚实的部分》——iPlan.ai 预算偏差 20-30%/Wonderplan 一般目的地数据/Wandercrafted 预算放付费墙为引，讲「估算透明 + 修订联动」哲学（标注口径的诚实估算 + 可修正），与 07/08 文构成价格维度姊妹篇（验收：docs/articles/09-*.md 存在且内容完整，代码引用与仓库实际一致，发布清单补卡片）
- [ ] task-pwa-offline: PWA 离线——前端 Service Worker，缓存行程详情/api 响应，弱网时展示缓存行程 + 「离线模式」标识（AiGo PWA 离线为卖点，TripIt/Wanderlog 也有；行程是结构化 JSON 天然可离线缓存）（验收：build 通过 + SW 注册 + 行程详情可离线打开；低优先级）
- 注（task-hotel-budget 补充验收口径）：落地时增加「估算口径标注」（source + 基准说明 + 置信度），预算视图展示「估算 vs 实际可验证」——对手 iPlan.ai 偏差 20-30% 翻车现场是「诚实估算」差异化背书

## 用户白天下达任务（2026-09-28 追加，白天已完成实现，登记供检查点识别）

- [x] task-servicing-layer: 行程服务层（方案 B 第二段 servicing 产物）——①大交通方案 plan.transport：TransportAgent 采集（search_transport = 驾车真实路径 + Tavily 班次/价搜索），无出发地跳过、无来源/低置信条目硬闸门过滤（不编造）；②酒店入住办理指引 plan.checkin：checkin_service 模板基座 + LLM 润色，LLM 失败纯模板兜底，不收集证件号等敏感信息；③站点折扣比价 plan.discounts：servicing_service.build_discounts_view 对费用最高前 5 站点 Tavily 比价，无来源即丢弃；④市内通勤 plan.transit（确定性相邻站点建议）；⑤确定性折扣规则 plan.discount_rules（本地规则库，零外部依赖）。三段 servicing 完全解耦，失败只写 warnings 不阻断主流程；产物随 TripPlan 落库（PlanSchema 已加 transport/transit/checkin/discounts/discount_rules 字段）（验收：后端契约字段已随 TripPlan 落库 + 测试覆盖（transport 硬闸门/降级/无出发地跳过、checkin 模板兜底/LLM 润色/无酒店降级、discounts 空结果不崩、servicing 三段隔离）+ 前端 TripServicing.vue 服务层展示已接入 TripDetailView 与 PlanWizard + 前端 build 通过）
- 注（大交通深度边界，不另建任务）：plan.transport 是「方案参考」（驾车真实路径 + Tavily 班次/价搜索），**不是实时可预订的班次表**——国内无免费官方交通班次 API；达到「点进去能买票」级别需接 12306/携程等商业 API，是另一个量级的集成（预订层），规划层定位保持「参考方案 + 官方渠道为准」
