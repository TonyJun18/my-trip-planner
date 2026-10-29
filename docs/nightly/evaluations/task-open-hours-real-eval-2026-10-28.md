# task-open-hours-real-eval 评估记录（2026-10-28）

> 背景：TimeGate / dynamic_facts 已把「周一闭馆/免费周日/节假日」做成规则库特例表
> （诚实标注 basis=rule_based），但本质是猜测、用户需自行确认，一次翻车即信任崩塌。
> 本任务评估真实营业时间数据源：高德 POI 详情字段是否含营业时间 / Google Places（需凭证）/
> 无免费全局源则维持规则库 + 特例表运营维护路线。
>
> 结论：**本夜降级关单（维持规则库 + 特例表运营维护）；高德 v5 POI 2.0 提供了真实营业时间
> 字段但处于「企业开发者试用阶段」，列为未来路径，需用户向高德申请配额后另行立项。**

## 一、数据源矩阵（真实营业时间）

| 数据源 | 能力 | 凭证/成本 | 合规/接入 | 判定 |
|---|---|---|---|---|
| **高德 v3 place/text（现状接口）** | `extensions=all` 返回 `biz_ext`（rating/cost/tag），**文档返回参数表无 opentime 字段** | 已有 AMAP_API_KEY，零新增凭证 | 官方 v3 搜索 POI 文档（2026-07-15 更新）返回参数逐项核对，无营业时间字段 | ❌ **字段不存在，不可用** |
| **高德 v5 place/text（POI 2.0）** | `show_fields=business` 返回 `opentime_today`（今日营业时间，如 `08:30-17:30`）/ `opentime_week`（周营业描述，如 `周一至周五:08:30-17:30；周六日:09:00-13:00`） | 同一 Web 服务 key 可用 | 官方文档标注「本服务目前是**面向企业开发者试用阶段**，上线使用需求请通过工单确认流量配额」 | ⚠️ **技术可行但生产依赖有合规/配额风险** → 未来路径 |
| Google Places API | 真实营业时间（opening_hours） | 需 API key + 计费 | 与零凭证自托管哲学冲突（同 price-alert-eval / price-realism-eval 结论） | ❌ 不做 |
| 高德 v3 ID 查询（place/detail） | 详情报价 | 同 v3 系列 | 返回参数与 v3 搜索一致，无 opentime | ❌ 字段不存在 |
| 免费全局源（OSM 等） | 营业时间覆盖不全、非结构化 | 零凭证 | 数据质量不稳定 | ❌ 不可靠 |
| **现状：类目基准规则库 + 日期特例表** | OPEN_HOURS_BY_TYPE（类目基准时段）+ DATE_EXCEPTION_RULES（周一闭馆/每月免费日/节假日） | 零凭证、零依赖 | 诚实标注 basis=rule_based，前端 timegate-card 透出「出行前再次确认」 | ✅ **本夜维持** |

## 二、代码链路现状核验（本夜逐项确认）

1. **主数据链路**：`backend/app/agent/tools.py::search_pois_amap` 用高德 **v3** `/v3/place/text`
   （`extensions=base`，worker-5 的 price-realism 分支已改为 `all` 并解析 `biz_ext.cost/rating`）。
   v3 返回参数表**不含 opentime 字段** → 即使 extensions=all 也拿不到营业时间。
2. **校验层**：`backend/app/services/time_validation.py::check_plan_time_gate` 消费
   `stop.open_hours`（显式优先）→ 否则类目基准 OPEN_HOURS_BY_TYPE（attraction 09:00-18:00 等），
   校验闭馆到达 + 单日过饱和 + 体力负荷；所有 issue 为 warning，basis=rule_based。
3. **动态层**：`backend/app/services/dynamic_facts.py::check_plan_dynamic_facts` 消费日期特例表
   （weekly 周一闭馆 / monthly_free 每月首个周日免票 / holiday 节假日调整），
   `_match_rules` 对已声明 open_hours 的站点跳过 weekly 规则（避免双报）。
4. **编排注入**：`backend/app/agent/agents.py` TimeGate 段把 time_gate/dynamic_facts 结果注入
   `plan.time_gate` / `plan.dynamic_facts` + 前端 timegate-card 透出 + 质检 trace。
5. **注入点已就绪**：`time_validation._stop_open_hours` 显式 `stop.open_hours` 优先于规则库、
   `dynamic_facts._weekly_closed` 跳过已声明特例——**未来若有真实营业时间数据，
   透传到 stop.open_hours 即可被现有校验链路消费，无需改动校验逻辑**。
6. **Schema 契约注意**：`backend/app/schemas/plan.py::StopSchema` **无 open_hours 字段**且
   `extra="ignore"`（会丢弃多余字段）——未来接入 v5 时需在 StopSchema 增加 open_hours 字段
   （与 LLM 生成输出校验联动），本夜不动。

## 三、结论：本夜降级关单（维持规则库 + 特例表运营维护）

**判定：不可行（本夜）→ 降级关单。** 理由：

1. **v3 现有接口无营业时间字段**：零改动拿不到，不是解析问题而是字段不存在；
2. **v5 POI 2.0 有条件可行但不宜立即接**：
   - 字段确实存在（opentime_today / opentime_week），且与 time_validation 显式 open_hours 契约天然吻合；
   - 但官方标注「企业开发者试用阶段，上线需工单确认流量配额」→ 作为生产默认主源有合规与
     配额不确定性；且 v5 参数体系与 v3 不同（page_size/page_num/region/city_limit/show_fields
     替代 offset/page/city/citylimit/extensions），切换属中等工程，超出「候选评估」一步到位范围；
3. **Google Places 需凭证**：与零凭证自托管哲学冲突（与 2026-10-22 price-alert-eval、
   2026-10-28 price-realism-eval 同构降级）；
4. **无免费全局源**：免费源数据覆盖与质量不足以支撑「闭馆到达」级校验。

**维持现状已覆盖主要翻车场景**：类目基准时段（避免推荐到达即闭馆）+ 日期特例表（周一闭馆/
免费周日/节假日）+ 诚实标注 basis=rule_based + 前端「出行前再次确认」提示——与 task-dynamic-facts-eval
（2026-10-19 罗马九工具实测）的运营侧特例表路线一致。

## 四、未来路径（用户决策项）

- **task-open-hours-real（建议立项条件）**：用户向高德开放平台申请 v5 POI 2.0 上线配额/
  工单确认后，可立项接入：
  1. `search_pois_amap` 增加 v5 分支（`show_fields=business`）或独立 v5 搜索函数；
  2. 解析 `opentime_week` → 透传 `stop.open_hours`（v3/v5 双读，缺失降级规则库）；
  3. StopSchema 增加 open_hours 字段（extra 显式声明）+ planner prompt 引导写入；
  4. time_validation 显式优先逻辑已就绪，零校验逻辑改动；
  5. 测试覆盖（v5 透传/缺失降级/schema 兼容三路径）。
- 在此之前：规则库 + 特例表运营维护路线继续有效（DATE_EXCEPTION_RULES 可运营侧增删）。

## 五、遗留

- 未改任何后端代码（纯评估记录 + todo 勾选），无 pytest / build 需求；
- 与 worker-5 price-realism 的 v5 观察（顶层字段 vs biz_ext）同源：v5 的 opentime 在
  `business` 对象（show_fields=business），与 v3 的 biz_ext 机制不同，接入时需注意字段位置。