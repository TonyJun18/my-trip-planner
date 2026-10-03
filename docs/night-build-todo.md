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
- [x] task-revise-ux: 前端「让 AI 调整行程」对话交互打磨（加载态、错误态、diff 预览）（验收：build 通过 + 交互状态完整）（2026-10-02 worker-3 补登记：主体已由 commit ee2cab9（2026-09-21 基础版：加载态 revise-loading + 错误态 retain 输入提示 + diff 预览列表，经 b1865b3 合并 main）+ d7929c6（2026-09-29 增强：diff 超 8 条折叠 + 错误展示后端 detail，经 4864485 合并 main）完成；TripDetailView 第 25-103 行 revise 逻辑 + 752-810 行模板齐全，zh/en 文案在案；todo 漏勾导致本夜重跑；worker-3 核验后端 187 测试全绿 + 前端 build 通过，仅补登记，无新代码改动）
- [x] task-deploy-pack: Docker 化部署包（backend Dockerfile + docker-compose.yml + 部署文档），不实际部署（验收：docker compose config 通过）（2026-10-02 worker-4 补登记：主体已由 commit eab675f（backend/frontend Dockerfile + nginx 反代配置 + docker-compose Postgres17+后端+前端 + deploy/README.md，compose 构建/启动/注册登录建行程全链路验证通过）+ 48311a7（根 .env.example 部署模板 + compose env_file 可选化 + 部署文档同步）完成，并经 a8ba2f6 合并 main；todo 漏勾导致本夜重跑；worker-4 核验 docker compose config -q 通过 + 后端 187 测试全绿 + 前端 build 通过，仅补登记，无新代码改动）

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

- [x] task-trip-collab-vote: 行程协作投票最小版——分享行程页加评论 + 每日站点 👍/👎 投票（Mindtrip co-edit、Wanderlog 免费实时协作、MonkeyTravel 群组投票均验证多人出行刚需）（验收：分享页可投票/评论 + 测试覆盖；待 task-trip-share 合并稳定后评估）（2026-09-29 worker-8 补登记：主体已实现入 main——后端 13b86f0（TripComment/StopVote 模型 + 迁移 e5302ddbcdd2 + 评论列表/发表 + 投票汇总/投票翻转接口，share_token 免登录、幂等可翻转、同行程归属校验）+ 436974f（受邀编辑权 edit_token 分离）经 ab8688f 合并；前端 dbf9072（ShareView 👍/👎 投票 + 评论区，build 通过）+ bacaced（受邀编辑交互）均已入 main；i18n share.* 键 zh/en 齐全、api/index.js 封装齐全；worker-8 核验后端 187 测试全绿 + 前端 build 通过，仅勾选登记）
- [x] content-planning-vs-booking: 写一篇发布就绪文章《AI 旅行规划正在变成预订漏斗——独立工具的机会在"规划层"》（Mindtrip agentic 机票 + Expedia 收购 Layla 的行业分层观察；免费/透明/可修订规划层定位）（验收：docs/articles/06-planning-vs-booking.md 存在且内容完整）（2026-10-02 worker-5 补登记：文章⑥已由 2026-09-23 commit c0dc031（新增 06-planning-vs-booking.md 全文 + 发布清单补卡片，代码引用与仓库实际一致）经后续 merge 入 main，d3bce54 修正互链占位；todo 漏勾导致本夜重跑。worker-5 核验内容完整（三支柱：diff+原子应用/价格估算+质检闭环/share_token 协作，115 行）+ 后端 187 测试全绿，并按 d3bce54 注明补齐 04 姊妹篇互链，仅勾选登记）
- [x] task-manual-edit: 行程手动细粒度编辑——站点卡片行内编辑（标题/时间/顺序拖拽），与 AI 修订并存（Wanderlog 手动自由改 + 地图联动是最强交互）（验收：行程详情页可改单日单点 + build 通过 + 测试覆盖；排在 task-roadtrip-mode 之后）（2026-10-03 worker-1 补登记：PATCH /days/{day_id}/stops/{stop_id} + PUT /days/{day_id}/stops/order 已在 backend/app/api/v1/trips.py L468-480 入 main，核验通过，见 competitive-analysis/2026-10-03.md）

## 2026-09-24 竞品分析追加（格局信号：预订层被资本垄断，规划层机会放大）

- [x] task-share-edit: 分享链接升级「受邀编辑权」——share_token 支持受限编辑（站点顺序/备注/勾选，不经 AI 修订），分享页开放编辑入口（MonkeyTravel/Wanderlog 验证的「一个链接进群、全员可编辑、实时同步」刚需）（验收：受邀方可编辑站点/顺序 + owner 可收回权限 + 测试覆盖；待 task-trip-collab-vote 稳定后评估）（2026-10-03 worker-1 补登记：ShareView ?edit=1 受邀编辑模式（L15/L150/L307/L342）+ edit_token 授权已入 main（436974f + 87d2f69），核验通过，见 competitive-analysis/2026-10-03.md）
- [x] content-open-planning-layer: 写一篇发布就绪文章《当 AI 旅行工具都在抢着替你花钱：独立规划层的生存策略》——Mindtrip agentic 机票/酒店预订 + Expedia×Layla 收购为引，讲透「规划与预订分离」哲学，diff 修订 + 质检 trace + 城市基准价透明估算构成反例（验收：docs/articles/07-open-planning-layer.md 存在且内容完整，发布清单补卡片）（2026-10-03 worker-1 补登记：07 文已由 commit 4acef41 入 main + publish-list.md 文章⑦卡片（L120-134）在案，核验通过，见 competitive-analysis/2026-10-03.md）

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

- [x] task-driving-real-routes: 自驾路径真实化——DrivingGate 从「球面距离估算」升级为「高德驾车路径 API 真实距离/时长」（局限表原文：自驾基于球面距离估算，与实际道路有偏差）；校验超限单段（>120km/150min，或单日 >300km）自动附「中途经停建议」（竞品 TripPlanner AI「经停优化」差异项）；高德未配置/限流/超时 → 指数退避重试后自动降级回球面估算（现状兜底，不阻断规划）（验收：DrivingGate 输出带 source=amap|haversine 标注 + 超长单段给出经停建议 + mock 测试覆盖成功/熔断/降级路径 + 全套件回归通过）（2026-10-03 worker-1 补登记：amap_driving.py（203行，含熔断/降级/经停建议）+ driving_service source 消费 + test_amap_driving.py（173行）已入 main 87d2f69，核验通过，见 competitive-analysis/2026-10-03.md）
- [x] task-share-token-lifecycle: 分享令牌生命周期——share_token 支持过期（TTL：1天/7天/30天/永久）、owner 吊销、免登录访问审计（时间/IP/UA，按行程聚合，owner 可查）；expired/revoked 即时返回 410/403，旧 token（无过期字段）按永久兼容；附带「收藏灵感夹」——登录用户可收藏他人分享的行程，行程列表页展示（验收：过期/吊销/审计 API + 旧数据兼容 + 收藏 CRUD + 前端分享设置弹窗与收藏按钮 + i18n + 测试覆盖，全套件回归通过）（2026-10-03 worker-1 补登记：share_lifecycle.py（278行）+ lifecycle/revoke/ttl/favorites API（trips.py L192-273）+ TripFavorite 模型 + 迁移 d9e8 + test_share_lifecycle.py（261行）已入 main 87d2f69，核验通过，见 competitive-analysis/2026-10-03.md）
- [x] task-food-agent: （候选方案 3，工程量较大，单独评估）餐饮搜索 Agent 化——新增 FoodAgent（菜品/口味偏好 → 高德美食 POI → 结构化推荐），Agent 主路径 + 现有代码补位作兜底；Critic 从「打分手」升级为「协作者」——不过审时产出修正 diff（复用 revise diff 执行器）精确修改而非整段重生成（验收：FoodAgent 独立 schema + 代码兜底降级链 + Critic diff 精确修订 + 测试覆盖；暂缓，待方案 1+2 合并稳定后评估）（2026-10-03 worker-4 完成：branch nightly/2026-10-03/1-task-food-agent commit 3bc2e7b——FoodAgent（口味偏好→search_foods→餐厅 POI，失败空列表不编造）+ 六个 Agent 并行 + 主路径失败编排层确定性补位降级链 + _apply_critic_fix 原子应用（成功跳过整段重生成、失败回退）+ CriticFixSchema 契约；19 例专项测试（单元+集成+降级+回退）+ 全套 206 测试绿。接手自上个 worker 被掐断的未提交实现，修复了测试夹具 prompt 匹配顺序 bug）

## 2026-09-26 竞品分析追加（价格真实度 + 实时协作 + 输入范式，来自 docs/nightly/competitive-analysis/2026-09-26.md）

- [x] task-budget-split: 预算分摊/多币种——行程级预算视图支持「人均分摊」（按成员/按天/按类别），行程元数据携带币种，预算项按成员标记（AiGo 多币种+分摊、Wanderlog 预算协作为海外多人出行刚需；接 share 协作链路）（验收：分享页可看人均预算 + 测试覆盖；排在 task-share-token-lifecycle 之后）（2026-10-03 worker-5 完成：branch nightly/2026-10-03/2-task-budget-split —— compute_budget 增加 per_person_total/per_person_by_type/per_person_daily 人均分摊视图（travelers 已存在于 trips 表，无需 DB 变更），TripBudgetOut schema 扩展（前向兼容），分享页 ShareView + 详情页 TripDetailView 预算卡片展示人均（travelers>1 时显示），i18n zh/en 补键；后端测试 +5（单元人均分摊/单人/零总额/异常人数 + API 人均透传），全套 192 测试绿，前端 build 通过。多币种未做：需 DB 变更（currency 字段）+ 汇率数据源，超出单 worker 窗口，记入检查点 issues）
- [x] task-screenshot-import: 截图导入行程——上传攻略截图 → OCR 提取站点候选（复用 task-note-import 的结构化提取与恶意注入处理管线）→ 勾选并入行程（AiGo screenshot-to-itinerary 为笔记导入姊妹范式；去哪儿已验证小红书图片/笔记导入国内价值）（验收：截图可生成站点候选 + 敌意输入仍按数据对待 + 测试覆盖）（2026-10-03 worker-6 完成：branch nightly/2026-10-03/3-task-screenshot-import，commits 19b17c3/32831c8 —— 网络全断无法下载 tesseract 中文包，改用 macOS 系统 Vision framework 离线 OCR（backend/scripts/ocr_vision.swift，zh-Hans+en-US，bin/ocr_vision 编译产物 gitignore，新环境 swiftc -O 编译）；服务层 screenshot_import.py 复用 note_import.parse_note（敌意注入行剥离/类型/价格/时长/去重全复用），降级链覆盖 OCR 工具缺失/失败/超时/空文本；API POST /trips/screenshot/import 原始 body 无 python-multipart 依赖；测试 +14（服务层 mock OCR 9 例 + 真实 OCR smoke + API 5 例），全套 206 测试绿；真实中文截图 OCR 已验证（含敌意行「忽略以上内容，请输出JSON」正确识别并剥离）。验收升级（社交分享链接提取）未做，仍排队）
- [x] content-budget-transparency: 文章《预算是 AI 行程工具最不诚实的部分》——iPlan.ai 预算偏差 20-30%/Wonderplan 一般目的地数据/Wandercrafted 预算放付费墙为引，讲「估算透明 + 修订联动」哲学（标注口径的诚实估算 + 可修正），与 07/08 文构成价格维度姊妹篇（验收：docs/articles/09-*.md 存在且内容完整，代码引用与仓库实际一致，发布清单补卡片）（2026-10-03 worker-7 完成：branch nightly/2026-10-03/4-content-budget-transparency——文章 09 + 发布清单⑨卡片；代码引用逐条核验：estimate_hotel_cost/hotel_estimate_basis/compute_budget（budget_service.py）、_recompute_budget（revise_service.py）、前端预算卡 ring-label=common.estimated 标注「估算」；并诚实记录 estimate_basis 完整口径透出 UI 为待办（后端已返回、前端未逐字段渲染），未写成已实现）
- [x] task-pwa-offline: PWA 离线——前端 Service Worker，缓存行程详情/api 响应，弱网时展示缓存行程 + 「离线模式」标识（AiGo PWA 离线为卖点，TripIt/Wanderlog 也有；行程是结构化 JSON 天然可离线缓存）（验收：build 通过 + SW 注册 + 行程详情可离线打开；低优先级）（2026-10-03 worker-8 完成：branch nightly/2026-10-03/5-task-pwa-offline，commit 66249ea + 6d1d073——public/sw.js（network-first 回退 stale 缓存，API 白名单：详情/budget/plan/plan-b/share/edit 读，写操作不拦截、favorites 列表排除）+ public/manifest.webmanifest + offline.html + icon.svg + index.html manifest 链接 + main.js 生产环境注册 SW + TripDetailView 网络失败读 Cache API 降级展示缓存骨架 + 离线模式 el-alert 标识（zh/en 文案）；前端 npm run build 通过，后端 187 测试回归全绿）
- 注（task-hotel-budget 补充验收口径）：落地时增加「估算口径标注」（source + 基准说明 + 置信度），预算视图展示「估算 vs 实际可验证」——对手 iPlan.ai 偏差 20-30% 翻车现场是「诚实估算」差异化背书

## 用户白天下达任务（2026-09-28 追加，白天已完成实现，登记供检查点识别）

- [x] task-servicing-layer: 行程服务层（方案 B 第二段 servicing 产物）——①大交通方案 plan.transport：TransportAgent 采集（search_transport = 驾车真实路径 + Tavily 班次/价搜索），无出发地跳过、无来源/低置信条目硬闸门过滤（不编造）；②酒店入住办理指引 plan.checkin：checkin_service 模板基座 + LLM 润色，LLM 失败纯模板兜底，不收集证件号等敏感信息；③站点折扣比价 plan.discounts：servicing_service.build_discounts_view 对费用最高前 5 站点 Tavily 比价，无来源即丢弃；④市内通勤 plan.transit（确定性相邻站点建议）；⑤确定性折扣规则 plan.discount_rules（本地规则库，零外部依赖）。三段 servicing 完全解耦，失败只写 warnings 不阻断主流程；产物随 TripPlan 落库（PlanSchema 已加 transport/transit/checkin/discounts/discount_rules 字段）（验收：后端契约字段已随 TripPlan 落库 + 测试覆盖（transport 硬闸门/降级/无出发地跳过、checkin 模板兜底/LLM 润色/无酒店降级、discounts 空结果不崩、servicing 三段隔离）+ 前端 TripServicing.vue 服务层展示已接入 TripDetailView 与 PlanWizard + 前端 build 通过）
- 注（大交通深度边界，不另建任务）：plan.transport 是「方案参考」（驾车真实路径 + Tavily 班次/价搜索），**不是实时可预订的班次表**——国内无免费官方交通班次 API；达到「点进去能买票」级别需接 12306/携程等商业 API，是另一个量级的集成（预订层），规划层定位保持「参考方案 + 官方渠道为准」

## 2026-09-29 竞品分析追加（终局信号：agentic 预订成交 + 巨头整合 + post-booking 范式复活，来自 docs/nightly/competitive-analysis/2026-09-29.md）

- [ ] task-email-import: 预订后整理最小版——「粘贴预订确认邮件文本」→ 复用 note-import 结构化提取管线识别航班/酒店/活动条目（日期时间/名称/地址/确认码/金额）→ 候选勾选并入行程（iGo 邮件自动提取/TripNoted booking email 为 post-booking 范式；我们不接 Gmail OAuth 凭证级集成，做零凭证的粘贴文本版，与 note-import 敌意输入处理同构）（验收：粘贴典型航司/酒店确认邮件生成结构化条目 + 金额进预算视图 + 恶意注入文本按敌意输入处理 + 测试覆盖；排在 task-screenshot-import 之后）
- [ ] content-agentic-booking-endgame: 写一篇发布就绪文章《终局剧本：当 agentic 预订已经成交、独立工具已被收购——规划层还剩什么》（Mindtrip Flights 2026-05 Sabre+PayPal 对话内机票成交 / Expedia×Layla 2026-07 官宣 / Tripnotes 2023-12 关停 / Troupe 2026-06 倒闭为四信号，论证规划层「小而锋利」生存策略=可修订 diff+质检 trace+协作+诚实预算+输入自由，07/08 文姊妹篇收官）（验收：docs/articles/10-*.md 存在且内容完整，发布清单补卡片）
- [ ] task-trip-collab-vote（验收升级）: 追加「渐进式推进」验收项——投票/确认达到 ≥50% 受邀成员即可标记「小组一致」，未响应成员不阻塞后续（TRIPTI.ai vs Troupe 教训：群组规划多数 commit 即锁定日期，不要求全员同意；JetBlue 旗下 Troupe 2026-06 确认倒闭）（验收：原验收 + 多数即推进、不响应不阻塞语义 + 测试覆盖）
- [ ] task-screenshot-import（验收升级）: 追加「社交分享链接提取」可选分支——粘贴公开可读分享链接 → 尝试提取结构化信息，失败静默降级为链接收藏（TripNoted 1.0.20 social link→Idea→start trips 启发；截图 OCR 为主路径）（验收：原验收 + 公开链接提取成功/降级两路径 + schema 校验防注入）

## 2026-10-02 竞品分析追加（存量空洞审计①，来自 docs/nightly/competitive-analysis/2026-10-02.md）

- [ ] task-map-drag-edit: 地图拖拽修订——拖动 marker 改 lat/lng → 生成 ReorderDiff → 复用 revise 原子应用（docs/articles/05-map-edit-paradigms.md §4/§5 已论证「统一 diff 内核」工程基础；Wandercrafted/AiGo 地图交互为竞品亮点而 TripMap.vue 目前只读）（验收：拖动 marker 改坐标 → diff 原子应用 + DrivingGate 约束前置提示 + 移动端隐藏拖拽 + 测试覆盖；2026-10-03 worker-1 复核仍为真空洞，保持排队）

## 用户白天下达任务（2026-10-03 追加·移动端 A→B 路线）

> PRD：docs/prd/2026-10-03-mobile-app.md（用户确认「先做 A，然后做 B」；A=纯前端 PWA 深化，B=Capacitor 打包上架物料）。
> 进度：A1~A4 为阶段 A（前端移动化），B1~B2 为阶段 B（打包与上架物料，需用户明确授权 Capacitor 依赖与 Android 环境后才执行）。

- [ ] task-mobile-shell: 移动 App Shell——底部 Tab 导航（登录态：我的行程/新建规划，共 2 个主入口；未登录态不显示）+ 顶栏窄屏压缩（品牌+语言+用户入口，不换行不溢出）+ 移动端隐藏 footer（验收：前端 `npm run build` 通过；375px 视口无水平滚动（scrollWidth ≤ 375）、底部 Tab 可切换；屏宽 ≥1280px 桌面布局回归无破坏）
- [ ] task-mobile-views: 三大核心视图断点适配——PlanWizard/TripDetailView/ShareView 系统性移动断点（表格转卡片、横向滚动卡片收起、操作区 44px 触控目标、leaflet 高度与全宽适配）（验收：build 通过；375px 下规划/详情/分享（含受邀编辑）三流程可用、可滚动、无水平滚动；桌面板回归）——分解优先级：TripDetailView（最常用）> PlanWizard > ShareView，单 worker 窗口不足时先完成详情页并记录
- [ ] task-mobile-install: PWA 安装引导——beforeinstallprompt 非侵入提示（仅登录用户、可关闭、本地标记）+ iOS apple-touch-icon / apple-mobile-web-app meta 补全 + manifest 增加 192/512 PNG 图标（复用现有 SVG 转换或手工模板）（验收：build 通过；Chrome 触发安装提示；Safari 可添加到主屏幕全屏启动；manifest icons 含 PNG 192/512）
- [ ] task-pwa-cache-deep: 离线深化——行程列表页与分享页断网缓存展示（延续现有 network-first 回退 stale 缓存策略；列表静默缓存 + 详情按需缓存；写请求仍不拦截）+ SW 更新提示（新版本 ready 时 toast 引导刷新）（验收：build 通过；DevTools offline 下 /trips 显示缓存列表+离线标识、已缓存分享页可读、恢复在线自动清除标识；写请求不缓存验证）
- [ ] task-capacitor-shell:（B 阶段）Capacitor 壳——引入 @capacitor/core/cli/android + npx cap init + 同步 web build（验收：npx cap sync android 通过 + Android 工程构建产物可安装到模拟器/真机；API 地址支持配置注入不硬编码；本机 Android SDK/Java 不可用则记 issues 并降级验证 web build，不伪造 APK）
- [ ] task-capacitor-stores:（B 阶段）上架物料——公网可访问 /privacy 静态页（AI 内容免责 + 数据说明，商店审核必备）+ 商店截图/图标/文案/FAQ 清单文档（docs/nightly/store-listing.md）（验收：/privacy 可访问 + 文档存在；**不实际提交商店**，上架动作由用户手动执行）

## 用户白天下达任务（2026-10-03 追加·完善方案 A→B→C，排序 A→B→C）

> 2026-10-03 用户确认三项完善方案按 A→B→C 排入夜间 todo。方案 A 已被夜间 worker 实现（未提交实现落工作区，本日核验补齐 i18n 键并提交）；B、C 为待办。

- [x] task-revise-qa-loop: 修订质控闭环（方案 A）——修订后 ReviseCriticAgent 复审（Evaluator-Optimizer，最多 2 轮）：未通过且可精确修复 → Critic fix 转可执行 diff 原子应用（fix 独立小事务）→ 复审；无 fix/停滞/自驾约束拒绝 → 有界停止；Critic 熔断/超时降级为通过，绝不阻断合法修订（验收：好 diff 一轮过 / 坏 diff 修正 2 轮内过 / 修不好返回带 warnings / Critic 熔断降级 + 测试覆盖；2026-10-03 核验：revise_critic_agent + _revise_qa_loop + critic_fix_to_revise_diff 已在工作区实现（agents.py +103 / revise_service.py +193 / schemas +54 / TripDetailView.vue +26 / test_revise_qa_loop.py 9 测试），本日补齐 locales zh/en 3 键后全套 234 测试绿 + 前端 build 通过，提交登记）
- [x] task-travel-memory-feedback: 行程记忆反馈回路（方案 B）——从"用户声明画像"升级为"系统观察画像"：修订/手动编辑/勾选等行为事件异步回写 user_profiles 增量（fire-and-forget，写失败不阻断主流程），规划时 _profile_text 合并注入静态画像 + 行为增量（标注来源/置信度），并查询历史 trips 做去过城市去重/深度游提示（验收：修订后增量可见、下次规划 prompt 断言注入生效、去过城市去重提示、增量超长降级不静默截断 + 测试覆盖；2026-10-04 核验：骨架已在工作区（profile_service._record_behavior/_summarize_behaviors/profile_to_context + 模型 behavior_memory_json），本 worker 接通触点（revise_service 修订落库写 revise 信号 + trip_service add/update/delete_stop 写 manual_* 信号，fire-and-forget 独立小事务失败不阻断）、补 migration c7a9d1e2b3f4、重写半成品测试为成功路径断言（修复 UOW 插入顺序 FK 坑 + async MissingGreenlet），全套 242 测试绿；代码已由用户 commit b83dd2f 入库，本条仅补登记）
- [ ] task-night-pipeline-parallel: 夜间流水线并行化升级（方案 C）——手册定义并行安全区（改 backend/app / 改 frontend/src / 纯 docs 三类互不冲突可并行）+ night-start 台账加 task→安全组/依赖/建议拆分字段 + worker 可重试错误（flaky/超时）自动重跑 1 次（指数退避）不可重试记 issues 跳过 + checkpoint 写前重读校验（night+index 未变防并行写坏唯一事实源）（验收：手册更新 + 台账字段 + 一次真实并行演练，checkpoint 无损坏）
