# 评估记录 · task-weather-probability-eval（2026-11-11）

> 降雨概率信号评估——候选评估（worker-1 执行，夜间流水线 2026-11-11）。
> 来源：docs/nightly/competitive-analysis/2026-11-09.md §5.2/§5.3（Journelyx v3.2.1「15 天预报 + 降雨概率 >60% 自动室内替代」付费卖点 + GuruWalk 横测「天气预报诚实性」）+ 11-09 评估记录 task-weather-gate-eval 遗留。
> 任务原文：评估当前 query_weather 数据源字段是否含概率/降水毫米（高德 AMAP 未来 4 天预报含降水概率但天数短，wttr.in hourly 有概率但中文语义弱），结论大概率 = 维持 text_day 规则 + 明确「概率信号来自数据源能力边界」降级关单。

## 1. 评估结论：**维持 text_day 规则库，不引入概率阈值规则；天气卡可在数据源能力边界内诚实透出概率（wttr 源），并登记两个后续行动项**

| 方案 | 内容 | 结论 |
|---|---|---|
| A（维持现状） | 高德/降级 wttr 均继续用 text_day 关键词（雨/雪/雷）做雨天检测，不引入概率阈值 | ✅ 主结论 |
| B（概率阈值） | 效仿 Journelyx「降雨概率 >60% 自动室内替代」做硬规则 | ❌ 数据源能力边界 + 「预报不可作硬约束」口径冲突（11-09 已确立），关单 |
| C（诚实透出） | wttr 源把当天 chanceofrain 如实透出到天气卡（无则沉默） | 🟡 登记为行动项（task-weather-probability-card），本夜不实现 |

## 2. 数据源矩阵（2026-11-11 一手实测）

| 数据源 | 凭证 | 概率/降水字段 | 天数 | 实测证据 | 结论 |
|---|---|---|---|---|---|
| 高德 AMAP v3 weatherInfo（主力，已有 key） | ✅ 已有 | **无**：casts 仅 date/dayweather/nightweather/daytemp/nighttemp/daywind/nightwind/daypower/nightpower/humidity | 4-5 天（11-09 记录 4 天 / 代码注释 5 天） | lbs.amap.com/api/webservice/guide/api/weatherinfo 官方文档 HTML grep 实证；amap-mcp-weather 项目同样注明「高德 API 不提供小时级预报，需模拟」 | 主力源**无概率字段**，概率信号不可来自高德 |
| wttr.in j1（规划期降级，零凭证） | ❌ 零凭证 | **有**：hourly 每 3 小时一条（time 0/300/600/900/1200/1500/1800/2100），含 `chanceofrain`/`chanceofsnow`/`precipInches`；precipMm 本次响应未返回 | 3 天×8 小时 | `curl "https://wttr.in/Hangzhou?format=j1&lang=zh"` 实测 25412 bytes：24 个 chanceofrain（13/19/21/13/6/6/13/21/26/28…）、24 个 chanceofsnow、25 个 precipInches、25 个 humidity；time 符号 0-2100 齐全 | 降级源**有概率信号**（小时粒度） |
| wttr.in lang_zh 中文 | — | — | — | `lang=zh` 参数下 `lang_zh` 实测返回**英文**（Beijing "Smoke"/"Clear"，Hangzhou "Smoky haze"/"Partly Cloudy"）——中文翻译未生效/缺失 | 坐实「中文语义弱」，且**引发英文 text_day 雨天检测缺口**（见 §4） |
| OpenWeather / WeatherAPI / 百度天气 | 需注册/凭证 | 有（pop/chance_of_rain 等） | 16/7 天 | 11-09 数据源矩阵已收录 | 凭证 + 合规，铁律 9 不做 |

## 3. 决策理由（与 11-09 WeatherGate 口径严格一致）

1. **主力数据源（高德）无概率字段**：官方 casts 字段表列全 10 个字段，无 probability/precipitation 类；「高德未来 4 天含降水概率」是 11-09 立项时的**假设**，本次一手核实**不成立**。
2. **「预报不可作硬约束」是已确立口径**（task-open-hours-real-eval / task-weather-gate-eval 同构）：天气是预报不是事实，WeatherGate 只产出 warning + 建议，绝不阻断排程（critical_count 恒 0）。概率阈值（>60% 自动替代）本质是把预报升级为自动决策，与诚实边界冲突。
3. **小时粒度聚合不透明**：wttr chanceofrain 是 8 个时段的小时值，聚合到「当天是否超过 60%」需要 max/avg 策略，Journelyx 未公开其口径；盲目实现会引入新的不可验证断言。
4. **现状已覆盖主要场景**：text_day 中文关键词（雨/雪/雷/阵/雹/霰）对高德主力源（中文 dayweather）有效，雨天→室内替代建议已在 WeatherGate 落地并测试（16 例全绿）。

## 4. 关键发现（本评估新增实证）

**wttr 降级路径存在英文 text_day 雨天检测缺口**：
- `_weather_wttr` 的 text_day 取 `hourly[4].lang_zh or weatherDesc[0].value`（tools.py:615）；
- 实测 `lang=zh` 下 `lang_zh` 返回英文（"Smoke"/"Clear"/"Partly Cloudy"），即 text_day 实际是英文；
- `weather_validation._is_rainy` 用中文 RAIN_KEYWORDS（雨/雪/雷/阵/雹/霰）正则匹配（weather_validation.py:45-57），**英文 "Light rain"/"Thunderstorm" 无法命中** → 当高德不可用降级 wttr 时，雨天室内替代建议会漏报；
- 高德主力路径不受影响（dayweather 为中文），该缺口只在降级路径出现 → 登记为行动项（task-weather-wttr-en-keywords）。

## 5. 行动项（登记至 docs/night-build-todo.md，供后续排期；本夜不实现——铁律 3 单 worker 单任务）

1. **task-weather-probability-card**（补功能，frontend+backend 候选）：天气卡透出降水概率——wttr 源把当天最大 chanceofrain 如实展示（basis=weather_forecast 标注、无概率字段的高德源不展示不编造），与 11-09 task-weather-card-frontend 同通道。优先级：低（行中卡片已可用，概率属增强）。
2. **task-weather-wttr-en-keywords**（补功能，backend 小修复候选）：RAIN_KEYWORDS 补英文关键词（rain/snow/shower/thunder/drizzle），修复 wttr 降级路径 text_day 英文不命中问题；需同步补 test_weather_validation 英文用例。优先级：中（降级路径真实缺口，但高德 key 常态配置时不易触发）。

## 6. 与竞品实证的呼应

- Journelyx 的「降雨概率 >60% 自动室内替代」是 2026 产品化卖点，但我们的诚实边界口径（Kiara「10 天窗口 + 明说不可知」Tier 1 行为）优先级更高：概率信号可以**展示**，不能**裁决**。
- GuruWalk 横测 Mindtrip「连降雨概率 ~30% + 风速 2m/s 都编」的反例：概率字段一旦展示就必须来自真实数据源，无字段→沉默（与 weather_card None 语义一致）。
- 若未来接入真实概率源（需凭证，铁律 9 不做），本评估的数据源矩阵即接入前置清单。

## 7. 验收对照

- [x] 评估记录存在（本文件）
- [x] 结论明确：维持 text_day 规则库（方案 A），概率阈值硬规则关单（方案 B）
- [x] 数据源矩阵含高德/wttr 一手字段实测
- [x] 行动项登记 todo（2 项，均标候选不排期实现）
- 纯评估任务，无 pytest/build 需求；无代码改动。