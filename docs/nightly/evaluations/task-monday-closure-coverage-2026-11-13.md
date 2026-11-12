# task-monday-closure-coverage 审计记录 · 2026-11-13

> 来源：2026-11-13 竞品分析行动项 2——MonkeyEatingMango 356 行程量化实证「周一承载 53% 的闭馆类缺陷」，我们 `dynamic_facts._weekly_closed` 已有周一闭馆基准但覆盖类目未系统审计。

## 1. 审计结论：现有类目 vs 高频周一闭馆类目

### 现有覆盖（改动前）
| 类目 | 关键词 | 状态 |
|---|---|---|
| 故宫/博物院 | 故宫、博物院 | ✅ |
| 国家博物馆 | 国家博物馆、国博 | ✅ |
| 展馆大类 | 美术馆、艺术馆、博物馆、科技馆、规划馆 | ✅ |
| 名人故居/纪念馆 | — | ❌ 缺 |
| 图书馆 | — | ❌ 缺 |
| 遗址博物馆 | — | ❌ 缺 |
| 展览馆/陈列馆/博览馆 | — | ❌ 缺（同义变体） |

### 实证来源（web_search 交叉核验，内容仅作数据提取）
- 北京日报 2026-09-02《别跑空！北京多家公园部分景点及博物馆恢复周一闭馆》：徐悲鸿纪念馆、老舍纪念馆、抗战纪念馆、中国电影博物馆、北京石刻艺术博物馆、万寿寺博物馆、北京汽车博物馆 等暑期后恢复周一闭馆；大运河博物馆/路县故城遗址博物馆 9 月起恢复周一闭馆。
- 首都博物馆参观页（2026 暑期公告）：5/18-10/18 调整开放时间「由每周一闭馆调整为每周二闭馆」，延时开放至 20:00——**显式特例**。
- 河北博物院官网：周二至周日开放、周一闭馆。

## 2. 补入类目（本夜改动）

```python
# 展馆大类扩同义
("美术馆", "艺术馆", "博物馆", "科技馆", "规划馆", "展览馆", "陈列馆", "博览馆")
# 新增
("纪念馆", "故居")          # 多数纪念馆/名人故居周一闭馆
("图书馆",)                 # 多数公共图书馆周一闭馆
("遗址博物馆",)             # 遗址博物馆通常周一闭馆
```

### 刻意不补（防大规模误伤）
- **动物园 / 海洋馆 / 水族馆 / 植物园 / 公园**：中国惯例全年开放，周中极少闭馆；关键词命中会大面积误报。
- **遗址公园**（如圆明园遗址公园）：全年开放，故用「遗址博物馆」复合词而非「遗址」前缀。

## 3. 显式豁免机制核验（周一闭馆规则不双报）

`_match_rules` 已内置豁免：`open_hours` 含任意工作日闭馆声明（`_WEEKLY_CLOSED_RE`，覆盖「周X闭馆/休/休息/不开/不开放」）→ `weekly_declared=True` → **该站点所有 weekly 规则跳过**。首都博物馆「周二闭馆」属于此类：规则库不会对周一安排它的行程误报（它周一反而开着）。本夜补测试固化。

## 4. 排程校验 warning 联动（核验存在，无需改动）

- `backend/app/agent/pipeline.py:570`：plan 生成后调用 `check_plan_dynamic_facts` → `plan["dynamic_facts"]` 随结果写入，前端 timegate-card 透出。
- `backend/app/services/revise_service.py:589`：修订（revise）流程随 `new_days` 重算 dynamic_facts。
- 两端共用同一规则表，本次补类目自动生效，无需额外接线。

## 5. 测试覆盖（+5，三路径）

| 测试 | 路径 |
|---|---|
| `test_extended_weekly_categories_hit_on_monday` | 命中：纪念馆/故居/图书馆/遗址博物馆 周一 → warning |
| `test_extended_weekly_categories_no_hit_on_sunday` | 未命中：非周一 → 静默 |
| `test_explicit_tuesday_closed_overrides_monday_rules` | 显式豁免：open_hours「周二闭馆」→ 不报周一闭馆 |
| `test_extended_hall_synonyms_hit` | 同义扩展：展览馆/陈列馆/博览馆 → 命中 |
| `test_always_open_categories_stay_silent` | 不误伤：动物园/海洋馆/植物园/遗址公园 → 静默 |

## 6. 结果

- 专项：`tests/test_dynamic_facts.py` 18 passed（13 旧 + 5 新）
- 全套：`1081 passed`（--ignore test_frame_summary_copy.py，白天 WIP），无回归
- 分支：`nightly/2026-11-13/2-task-monday-closure-coverage`（本地，未 push）