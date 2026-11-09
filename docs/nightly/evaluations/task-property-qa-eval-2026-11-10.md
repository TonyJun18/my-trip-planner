# 评估记录 · task-property-qa-eval（2026-11-10）

> 行程内结构化事实问答——候选评估 + 最小版实现（worker-7）。
> 来源：docs/nightly/competitive-analysis/2026-11-10.md（Expedia Property Expert 把「grounded 问答」产品化：答案来自 property details + reviews + 自己的 reservation；我们 trip/站点有结构化数据但只有单向透出，无问答）。

## 1. 评估结论：**通过，落地最小版方案 A（纯规则 FAQ，零 LLM）**

| 方案 | 内容 | 结论 |
|---|---|---|
| **A（落地）** | 行程内 FAQ 端点：基于结构化字段直接回答（营业时间 / 预算 / 质检预警 / 评分 / 站点费用 / 游玩时长），纯规则 + i18n 模板，零 LLM、零凭证 | ✅ 实现 |
| B | LLM 自由问答（检索 plan_data + 站点字段后让模型生成答案） | ❌ 明确不做：可答范围外的问题交给 LLM 会引入编造风险（Expedia 的 ground 回答来自其私有 property 数据库 + reservation；我们无私有富数据源，自由问答 = 幻觉温床） |
| C | 接外部 POI 富数据 API（评分/营业时间实时源） | ❌ 需凭证（铁律 9 不碰）；且与 task-open-hours-real-eval 的「静态规则库零凭证」路线一致 |

## 2. 可答范围 vs 不可答范围（防编造口径）

### 可答（结构化字段真实存在）

| 问题类型 | 数据源 | basis 标注 |
|---|---|---|
| 「XX 几点关门/营业时间」 | plan_data.days[].stops[].open_hours（显式）；无显式 → time_validation 类目规则库（attraction 09:00-18:00 / museum 09:00-17:00…） | explicit / rule_based |
| 「预算还剩多少」 | trip.budget（用户预设）+ plan_data.budget.total_estimated（AI 汇总估算），分开返回 | explicit（预设）/ rule_based（估算口径） |
| 「行程有什么预警」 | plan_data.time_gate / dynamic_facts / weather_gate 的 issues 汇总（TimeGate/DynamicFacts/WeatherGate 已有产物） | rule_based |
| 「XX 评分怎么样」 | stops.details.rating（高德真实采集，落库 details） | explicit（有数据）/ none（无） |
| 「XX 门票多少钱」 | stops.estimated_cost（估算字段） | explicit / none |
| 「XX 玩多久」 | stops.estimated_duration_minutes（显式）/ 类目基准（attraction 120 / museum 150 / park 90 / food 60） | explicit / rule_based |

### 不可答（明确拒绝，绝不编造）

- 站点不存在于行程数据 → `available=false + basis=none + 暂无该数据`（站点级问题必须先命中行程内站点）
- 无可答字段（无评分 / 无价格 / 无营业数据）→ unknown，**绝不猜数字/时间/评分**
- 自由问答（「推荐附近的餐厅」「明天天气怎么样」）→ `matched_type=unknown`，返回能力边界说明
- 意图词同时命中预算与站点价格（「西湖门票多少钱」）→ 语义修正转 price（answer 层按 target + 站点价格词）

### 口径（诚实标注，对齐 Price-Realism / WeatherGate 哲学）

- `basis`：explicit（字段真实存在）/ rule_based（类目规则库推断）/ none（无数据）
- `available=false` 时前端应透出「暂无数据」而非假装有答案——防编造是硬约束
- 规则库推断的答案文案带「估算，以现场为准」（rule_based 口径）

## 3. 实现摘要（分支 nightly/2026-11-10/4-task-property-qa-eval）

- `backend/app/services/property_qa_service.py`：纯函数规则问答
  - `answer_property_question(trip, plan, question, locale)`：意图解析（hours/budget/warning/rating/price/duration/unknown）→ 目标站点匹配 → 答案
  - `collect_property_facts(trip, plan, locale)`：不带 q 时的「当前可答事实清单」（facts ≤ 20 条 + budget + warnings + suggestions）
  - 意图优先级：rating → hours → strong_price（门票/票价）→ budget → warning → price → duration；预算意图+站点价格词 → 转 price
- `backend/app/api/v1/trips_property_qa.py`：`GET /trips/{trip_id}/property-qa`（登录鉴权，owner 隔离）
  - 带 `?q=` → `PropertyQaOut`（question/matched_type/target/available/answer/basis/detail）
  - 不带 q → `PropertyQaFactsOut`（trip 摘要 + facts + budget + warnings + suggestions）
- `backend/app/schemas/property_qa.py`：`PropertyQaFact / PropertyQaOut / PropertyQaFactsOut`
- `backend/app/i18n/translations.py`：propertyqa.* 18 键 zh/en 双侧
- 注册：`api/v1/__init__.py` 在 trips_crud 之前注册（字面量段优先惯例）
- 测试：`backend/tests/test_property_qa.py` **26 例**（意图解析 / hours explicit·rule·unknown / budget 三路径 / warnings 汇总·无 / rating 有·无 / price 有·无 + 强词优先 / duration explicit·rule / collect_facts / API 鉴权·归属隔离·unknown）

## 4. 验收结果

- 专项：`tests/test_property_qa.py` 26 passed
- 全套：**950 passed**（2 分 0 秒，无失败）
- 无前端改动（后端评估任务；前端接线可另立项）

## 5. 遗留

- 前端「行程内问答」入口未接线（详情页可加一个 FAQ 折叠卡 / 提问框，消费 /property-qa）→ 可立项 task-property-qa-frontend
- 自由问答（LLM grounded RAG）仍为明确不做（防编造）；若未来接私有富数据源（真实 reservation/POI 库），再评估检索增强问答
- 营业时间规则库为静态类目基准（rule_based），真实时间以现场为准；接实时源需凭证，不追
- 与 chat_trip_context（对话注入行程上下文）互补：对话助手走 LLM 带上下文，本端点走确定性规则，互不替代