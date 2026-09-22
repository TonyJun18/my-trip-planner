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

## 2026-09-23 竞品分析追加（格局快照：预订闭环 vs 规划层）

- [ ] task-trip-collab-vote: 行程协作投票最小版——分享行程页加评论 + 每日站点 👍/👎 投票（Mindtrip co-edit、Wanderlog 免费实时协作、MonkeyTravel 群组投票均验证多人出行刚需）（验收：分享页可投票/评论 + 测试覆盖；待 task-trip-share 合并稳定后评估）
- [ ] content-planning-vs-booking: 写一篇发布就绪文章《AI 旅行规划正在变成预订漏斗——独立工具的机会在"规划层"》（Mindtrip agentic 机票 + Expedia 收购 Layla 的行业分层观察；免费/透明/可修订规划层定位）（验收：docs/articles/06-planning-vs-booking.md 存在且内容完整）
- [ ] task-manual-edit: 行程手动细粒度编辑——站点卡片行内编辑（标题/时间/顺序拖拽），与 AI 修订并存（Wanderlog 手动自由改 + 地图联动是最强交互）（验收：行程详情页可改单日单点 + build 通过 + 测试覆盖；排在 task-roadtrip-mode 之后）