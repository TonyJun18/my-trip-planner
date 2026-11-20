# 竞品分析 → 待验证需求清单（2026-11-20 整理）

> 来源：2026-11-15 / 17 / 18 / 20 四夜竞品分析（`docs/nightly/competitive-analysis/`），全部已登记 §2 候选池（`docs/night-build-todo.md`）。
> 本清单按「**验证视角**」汇总：每项都标出——竞品证据、要验证什么（评估点）、现状、验证出口（可行→最小版+测试 / 不可行→降级关单）。
> 处理原则：竞品分析新增任务只能进候选池，由用户/队列腾位后晋升 §1（手册 §5）；验证出口需正式评估记录（`docs/nightly/evaluations/`）。

## A. 行前整理链（Everway 线 · 11-20）——「生成之后、出发之前」新缝隙，四项全缺

| slug | 竞品证据 | 要验证什么 | 验证出口 |
|---|---|---|---|
| `task-free-cancel-deadline-eval` | Everway「reminds before free cancellation ends」 | TripBooking 能否加 `free_cancel_deadline` 可选字段（回填确认单时录入）→ 台账 `days_until` 倒计时（复用 11-12 模式）+ 截止前 N 天行程内事件提醒（复用 trip_events）；零凭证 | 可行→最小版+测试（录入/倒计时/到期不产出/不编造四路径）；不可行→降级关单 |
| `task-confirmation-batch-import-eval` | Everway 转发私有地址→AI 批量归集确认单 | 粘贴区多封确认邮件（分隔符/多段）→ 逐段复用 email_import 解析 → 候选合并去重（与截图批量 OCR 同构）；**私有邮箱归集需邮件基础设施，明确不做** | 可行→最小版+测试；不可行→维持单条粘贴 |
| `task-visa-rules-eval`（P3） | Everway「checks visa and passport rules for each traveller」 | 数据源矩阵：静态规则库（中国护照免签/落地签/电子签，零凭证但更新需运营、误报风险高）vs 官方 API（需凭证）；与 open-hours-real-eval 同构 | 大概率「静态表维护成本高→P3 或不排期」，但需正式评估记录 |
| `task-mcp-export-eval` | Everway 提供 MCP（Claude/ChatGPT/Cursor 查总花费） | MCP 只读薄壳包既有 API（get_my_trips / get_trip_overview / export / property_qa，10-28 chat_trip_tools 内核已在）；零新后端逻辑 + README 自托管；风险：MCP 生态演进 + 运行基础设施 | 可行→最小版+文档；不可行→降级关单 |

## B. 地理/行程真实性（Roamy→Rhyme 差评群线 · 11-17）

| slug | 竞品证据 | 要验证什么 | 验证出口 |
|---|---|---|---|
| `task-geo-anchor-sanity-eval` | Rhyme 差评群：Dallas 起点被拉 8 小时外 / Costa Brava→巴黎 / Azores→大陆 | dest 城市中心为锚（既有 destinations 知识库）→ 全站 haversine 离群阈值（如 >80km 且非交通占位/非多城段）→ plan warning + 质检 trace（basis=rule_based）+ 修订重算；与 time/weather 校验同构 | 可行→最小版+测试（命中/未命中/交通占位豁免/多城段豁免四路径）；不可行→降级 |
| `task-hotel-switch-conflict-eval` | Rhyme「12 日退房+12 日入住无法安排」 | 同一天两个 hotel 类 stop：按顺序表达（上午退房→下午入住）+ 质检 warning（换宿日行李处理建议，纯规则）；结合 task-open-hours 时间真实度 | 可行→最小版+测试；不可行→降级 |

## C. 决策透明度（SearchSpot 线 · 11-17）

| slug | 竞品证据 | 要验证什么 | 验证出口 |
|---|---|---|---|
| `task-decision-drop-reason-eval` | SearchSpot「250→50→12→4 + 为什么被淘汰」 | 候选/淘汰时附 `drop_reason`（rule_based：超预算/距离过远/类目不匹配/容量已满）→ 行程卡或 QA 卡透出「备选与淘汰理由」折叠区；**方案 B（LLM 生成理由）防编造口径明确不做** | 可行→最小版+测试；不可行→降级 |

## D. 结构化输入（Wonderplan 线 · 11-18 + Butter 线 · 11-15）

| slug | 竞品证据 | 要验证什么 | 验证出口 |
|---|---|---|---|
| `task-dietary-filter-chips-eval` | Wonderplan Halal/Vegan/素食直接进表单 | PlanWizard 增结构化饮食 chips（素食/清真/海鲜忌口等）→ 复用 prompts.py L148-150 口味偏好 freeform 转换预填；零后端大改 + i18n 键 | 可行→最小版前端+测试；不可行→降级 |
| `task-open-slot-eval` | Butter「2–4pm around Shibuya, something relaxed」 | 开放时段占位结构化表示（时间段+自由度+偏好类别，无固定 POI）→ 排程/质检/修订链路如何表示（不打破 DrivingGate/TimeGate）；规模 M | 可行→最小版（占位透出+不硬塞站点+质检豁免）；不可行→降级 |
| `task-paste-any-plan-eval` | Butter「paste a plan from Notes/chat/doc→保留天/时间/地点」 | 整段已有行程 → 天/时间/地点骨架识别 → 候选勾选并入；与 email-import 零凭证粘贴版同构 | 可行→最小版+测试；不可行→降级 |

## E. 行中/台账（11-15 线）

| slug | 竞品证据 | 要验证什么 | 验证出口 |
|---|---|---|---|
| `task-price-watch-mini-eval` | Stardrift Pro 盯价 / Mindtrip PTA | 零凭证中间档：对用户已录入预订金额做台账 + 变更提醒（不接外部实时价；task-price-alert-eval 降级结论不动摇） | 可行→台账+变更事件+测试；维持既有降级 |
| `task-multicity-optimizer-eval` | Fortrip Transport Optimizer / Stardrift 多城一条龙 | 城市级重排/交通组合优化入口（task-multi-city-segments 已有排程底座，缺城市级优化动作）；复用 day_optimizer 贪心 + DrivingGate 语义 | 可行→最小版+测试；不可行→降级 |

## F. 内容沉淀（docs，纯写作无代码）

| slug | 证据 | 定位 |
|---|---|---|
| `content-acquisition-season-2`（17 文） | 11-17 OpenAI acqui-hire Odessia + Expedia $676M 三并购；11-18 证据升级（Layla 两转向 + 市场三分层 + 口径打架） | 收购从「收编品牌」到「收编能力」；接 15/16 文，证据已齐，队列腾位即晋升 |
| `content-google-maps-ask-maps`（18 文） | 11-20 Google Ask Maps（11-16 官宣欧洲 30 国）+ 豆包找店 + 携程 Trip.Planner/TripGenie | 「规划被嵌入地图/对话/OTA 主流程」平台挤压第三波；接 15/16/17 文；独立层剩「规划后链路深度+中立+免费」 |

## G. 观察/触发条件类（更早入池，非竞品分析直接驱动）

| slug | 触发条件 | 说明 |
|---|---|---|
| `task-launch-deploy`（**P0 to-C**） | 2026-11-14 决裁：to-C 上线验证主线 | 香港轻量上线+空库+最小埋点 5 事件+14 天判定线（20/5/2）；`docs/plans/2026-11-15-core-value-launch.md`；W1 启动时晋升 §1 |
| `task-import-quota-eval` | 导入量或滥用上升 | 对标 Triparchi 免费档 10 imports |
| `task-schedule-overflow-cta` | 有真实过载行程样本 | 日卡 overflow 目前只有 tooltip，无「让 AI 压缩该日」动作 |
| `task-share-target-android-e2e` | 有 Android 设备 | Android Chrome 装 PWA 后实测 TikTok→随行 |
| `task-gallery-cold-start-2` | 真实发布 ≥20 条 | 内容量前置；届时再启 gallery-community-v3 |

## 已决裁/已关闭（不进验证队列）

- **免注册/guest-trial**（10-15 关单：LLM 多轮成本敞口+无 IP 限流；11-15/18 再确认维持关闭）
- **IM 通道**（Escapada/GuideGeek WhatsApp 系，11-07 关单：第三方合规与凭证）
- **credits/付费经济**（Butter/GoVoyage/Butter credits 明示，已决裁不做付费，quota 软提示足够）
- **盯价接外部实时价**（task-price-alert-eval 已降级；Layla PriceLock 从官网消失）
- **一键结清/资金动作**（违反零资金边界）
- **视频解析**（Reels 视频需视频模型+反爬，维持零凭证不做）

## 建议下一步（决策点）

1. **P0 主线**：`task-launch-deploy` 是 to-C 验证主线，最先排。
2. **A 组性价比最高**：11-20 四项全部是「小步零凭证增量」，且复用既有内核（台账倒计时/email_import/screenshot 合并/chat_trip_tools），其中 **free-cancel-deadline 与 confirmation-batch-import** 属 P2 可直接评估→晋升；visa 大概率关单留评估记录；MCP 视用户群（AI 重度用户）定。
3. **B 组地理真实性**：与「四维质检」主线同向，Roamy 差评群是最强实证，建议紧随 A 组。
4. **F 组内容**：17/18 文证据已齐，随时可写（纯 docs 无冻结约束）。