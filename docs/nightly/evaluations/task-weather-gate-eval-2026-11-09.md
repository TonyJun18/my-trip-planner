# 评估记录 · task-weather-gate-eval（2026-11-09）

> 天气感知排程——候选评估 + 实现（worker-1 立项，worker-3 收编凌晨被掐断 WIP 并完成）。
> 来源：docs/nightly/competitive-analysis/2026-11-09.md（Journelyx v3.2.1「15 天预报 + 降雨 >60% 自动室内替代」付费卖点 + GuruWalk 六工具横测「4/6 编造远期天气」）。

## 1. 评估结论：**通过，落地最小版方案 A**

| 方案 | 内容 | 结论 |
|---|---|---|
| **A（落地）** | 排程校验注入天气 warning（雨天/酷暑 → 室内替代建议）+ live 快照当日天气卡，纯规则库零凭证 | ✅ 实现 |
| B | 接真实天气 API（高德 AMAP 已有规划期调用、wttr.in 降级）做行中实时刷新 | 🟡 规划期已用（query_weather），行中不重取（预报时效短） |
| C | 降雨概率 >60% 阈值（Journelyx 卖点） | ❌ 数据源能力边界：高德未来 4 天含降水概率但天数短、wttr.in 中文语义弱；维持 text_day 关键词，概率信号另立 task-weather-probability-eval |

## 2. 数据源矩阵（与 task-open-hours-real-eval 同构的「预报不可作硬约束」口径）

| 数据源 | 凭证 | 概率信号 | 天数 | 结论 |
|---|---|---|---|---|
| 高德 AMAP（规划期已用） | ✅ 已有 key | 有（未来 4 天） | 4 | 已用；天数短不适合行中 |
| wttr.in（规划期降级） | ❌ 零凭证 | hourly 有 | 3 | 已用；中文语义弱 |
| OpenWeather / WeatherAPI | 需注册 | 有 | 16 | 凭证 + 合规，铁律 9 不做 |
| Google Places | 需凭证 | 无 | — | 关单 |

**口径**：天气是预报不是事实，WeatherGate 只产出 warning + 建议，**绝不阻断排程**（critical_count 恒 0）；无对应日期数据 → 保持沉默（绝不编造）。

## 3. 实现摘要（收编凌晨被掐断 WIP 到 commit 7c6e4d5，分支 nightly/2026-11-09/0-task-weather-gate-eval）

- `backend/app/services/weather_validation.py`：纯函数规则库
  - `check_plan_weather_gate(plan)`：雨天（text_day 含 雨/雪/雷/阵/雹/霰）→ 户外站点（attraction/park）室内替代建议；酷暑（temp_max ≥ 35°C）→ 补水/避正午建议；室内豁免关键词（博物馆/美术馆/展览/科技馆/图书馆/室内/商城/购物/水族馆/剧院）；输出与 CritiqueIssueSchema 兼容（severity=warning, category=schedule, basis=weather_forecast）
  - `weather_card(plan, day_date)`：行中「今日天气卡」摘要（date/text_day/temp_min/temp_max/source/summary）；失败/无数据 → None
- `FinalizePlanStep`（pipeline.py）：注入 `plan.weather` 快照（从采集阶段 w_res）+ `plan.weather_gate`（含 warnings [天气] 前缀 + trace + artifact）
- `revise_service._recompute_budget`：随修订重算 WeatherGate（从最新 TripPlan 快照沿用原 weather；无快照 → 沉默）
- `live_service.live_snapshot`：今日天气卡（weather_card 纯函数；无数据/非 live → None）
- `LiveSnapshotOut.weather` 字段（schemas/share.py）
- i18n：weathergate.* 14 键 zh/en 双侧
- 测试：`tests/test_weather_validation.py` 16 例全绿（雨天/酷暑/豁免/沉默/编排接线/天气卡三路径/ORM 集成）；**全套 814 passed**

## 4. 核验修复（收编时发现并修复）

1. 测试桩缺陷：live 测试未初始化 relationship → MissingGreenlet（显式 `day.stops=[]; trip.plans=[]`）
2. 测试断言缺陷：天气卡摘要断言「雨」→ 实际文案「降水」（按 i18n 文案修正）
3. **实现缺陷**：`revise_service._recompute_budget` 调 weather_gate 未传原 weather 快照 → **修订后天气门永远沉默**（修复：从最新 TripPlan 快照取 weather 传入）

## 5. 遗留

- **前端行中天气卡未接线**（weather_card 后端就绪，TripDetailView 今日卡片无天气透出）→ 已立 task-weather-card-frontend（队列）
- 降雨概率信号（>60% 阈值）→ 已立 task-weather-probability-eval（队列）
- 真实天气 API 行中刷新 → 不做（预报时效短 + 凭证，与评估矩阵一致）

## 6. 与新竞品实证的呼应

- GuruWalk 横测（2026-08-13，六工具同 brief）：63 天后天气问题 **4/6 编造预报**（Layla 高低温/Perplexity 10 条引用仍错/Mindtrip 连风速都编），只有 Kiara（明说 10 天窗口 + 给雨天备选版）与 ChatGPT 承认不可知——「诚实边界」是横测可衡量的产品维度，我们的「无数据→沉默」与 Tier 1 同构。
- Journelyx 把天气做进排程（15 天预报 + 概率 + 室内替代）是「AI 做不好天气预判」（新浪横测点名）被产品化的信号——我们以规则库最小版跟进，不碰凭证。