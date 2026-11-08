# task-multi-currency-expense-eval 评估记录（2026-11-09）

> 背景：Journelyx v3.2.1（2026-11-08 更新）把「多币种实时汇率 + 12 类自动分类 +
> 24h 超预算预警」做成行中完整度付费卖点；我们 expense 仅单币种（Trip.currency 默认
> CNY——实为基准币口径，Trip 模型本身无 currency 字段，预算整体 CNY）、手动分类、
> 无预警。本任务按 2026-11-09 竞品分析 §3 立项：评估「记账时输入当地金额 + 币种 +
> （可选）汇率 → 按 trip.currency 折算汇总」的零凭证最小版。
>
> **结论：评估通过，本夜落地最小版「录入时锁定汇率」（A 方案）。**
> 实时汇率（B 方案）与自动分类/常驻预警（C 方案）明确关单（需凭证 / 需常驻任务）。

## 一、数据源矩阵（汇率）

| 数据源 | 能力 | 凭证/成本 | 合规/接入 | 判定 |
|---|---|---|---|---|
| **用户录入时填写汇率**（Minimal Expense locked-in rate / Travel Ledger fixed daily reference rate 同范式） | 记账即锁定，历史不漂移，离线可用 | 零凭证、零依赖 | 用户自担真实汇率；append-only 可复算 | ✅ **采用（本夜）** |
| **零凭证规则库兜底**（长期稳定参考中间价） | USD/EUR/JPY/KRW/GBP/THB/SGD/MYR/AUD + CNY=1.0 | 零凭证 | basis=rule_based 诚实标注，前端可提示「参考汇率」 | ✅ **采用（本夜，兜底）** |
| Frankfurter / ExchangeRate-API（Noma 所用） | 实时汇率 | 免费但**外部 API 调用**，且非自托管 | 与零凭证自托管哲学冲突；公开汇率 API 有稳定性风险 | ❌ 不做（同 price-alert-eval / open-hours-real-eval 结论） |
| 高德 / 银行牌价 | 实时汇率 | 需凭证/接口 | 无免费稳定接口 | ❌ 不做 |
| Journelyx 式「实时汇率每 6h 刷新 + 自动分类 12 类 + 24h 超预算预警」 | 完整度卖点 | 需常驻任务/后台调度 + 外部汇率源 | 超出单 worker 窗口，与「候选评估」一步到位范围不符 | ❌ 关单（见 §三 C） |

**行业共识**（web_search 实证）：多币种记账的**主流做法不是实时换算**，而是
**「录入时锁定汇率」**——Minimal Expense Travel Ledger 明确「exchange rate is locked
at entry time, so reports never shift」；Travel Ledger 用「fixed daily reference rate」；
Noma 缓存汇率离线可用。实时汇率是增值项而非记账核心。这印证了我们零凭证 A 方案的
工程合理性：**历史结余可复算、不因汇率波动漂移**，与现有 append-only 记账语义天然吻合。

## 二、方案设计（本夜落地）

**核心权衡：0 新表、0 新端点，3 个新列 + 既有 compute_balance 改口径。**

| 决策点 | 选择 | 理由 |
|---|---|---|
| 表结构 | `trip_expenses` 增 `currency`（默认 CNY）/ `rate_to_base`（默认 1.0）/ `amount_base`（默认=amount） | 无新表；存量记录自动视为 CNY 口径，零迁移风险 |
| 汇率来源 | 显式 `rate_to_base` 优先 > 规则库 `_RULE_RATES` 兜底 > 未知币种且未给汇率 → 400 `currency_rate_required` | 诚实口径：不编造汇率（与 budget_service「无可信来源不编造」同源） |
| 折算时机 | **录入时锁定**，`amount_base = round(amount × rate, 2)` 落库 | 历史不漂移；append-only 语义完整保留 |
| 聚合口径 | `compute_balance` 一律按 `amount_base` 聚合（CNY 基准） | 多人分摊、多币种混记时可加总 |
| 新增透出 | `ExpenseOut` 增 `amount_base/currency/rate_to_base`；`ExpenseBalanceOut` 增 `currencies`（出现过的原币种集合） | 前端可展示「USD 100 @ 7.1 ≈ ¥710」 |
| 不做 | 行程级基准币切换 / 实时汇率 / 自动分类 / 24h 预警 / 修改端点 | 边界外（见下） |

**代码链路改动**（全部零凭证、纯函数可测）：
1. `backend/app/models/trip.py::TripExpense` — 3 新列 + 注释
2. `backend/app/schemas/expense.py` — `ExpenseIn.currency/rate_to_base`；`ExpenseOut` 透出；
   `ExpenseBalanceOut.currencies`
3. `backend/app/services/expense_service.py` — `_RULE_RATES` 规则库 + `resolve_rate_to_base`
   纯函数 + `add_expense` 录入时锁定 + `compute_balance` 按 `amount_base` 聚合
4. `backend/alembic/versions/a4b5c6d7e8f9_add_multi_currency_to_trip_expenses.py` —
   防御式幂等迁移（先查后加；存量 `amount_base` 回填 = amount）
5. `backend/tests/test_expense_split.py` — 专项 10 例（规则库/显式优先/未知币种 400/
   锁定折算/API 端到端/默认 CNY 兼容/存量回落）

差异化价值：Journelyx 的付费卖点我们以零凭证方式提供**核心 60%**（多币种记账 +
折算汇总），自动分类/超预算预警为付费常驻能力，诚实标注为边界——与
task-price-realism-eval（高德 cost 双读）、task-open-hours-real-eval（规则库运营）同构。

## 三、关单项（明确不做，用户决策项）

- **B. 实时汇率**：需外部 API/凭证；即便免费 API 也与零凭证自托管哲学冲突。
  维持「用户填 or 规则库」；若未来用户接受引入汇率数据源，立项后可在
  `resolve_rate_to_base` 增加外部源分支（函数已是纯函数，接入点清晰）。
- **C. 自动分类 12 类 / 24h 超预算预警**：需常驻调度任务（Journelyx「daily burn rate
  projection」），且超预算预警依赖行程级预算基准与实时汇率数据；超出最小版边界。
  已有 `quota_service` 24h 滚动窗口可作为未来「预警调度」的宿主（需用户立项）。
- 不做前端交互升级（记账弹窗币种选择器）：本夜验收仅后端 + 测试；
  现有 API 字段已就绪，前端接线由用户 daytime 或后续 worker 排期。

## 四、验收

- 专项 `tests/test_expense_split.py`：**30 passed**（原 20 + 新增 10）
- 全量后端回归：待跑（见本夜 worker 最终报告）
- 无前端改动（纯后端 + 迁移 + 测试 + 文档）
- 分支：`nightly/2026-11-09/2-task-multi-currency-expense-eval`

## 五、遗留

- 前端「记账弹窗币种选择」UI 未接线（API 已就绪，见 §三末条）；
- `_RULE_RATES` 为静态参考中间价，长期需运营维护（成本极低，纯函数字典）；
- 汇率数字（USD 7.1 等）为 2026-11 概数，非实时牌价，前端展示时建议标注
  「参考汇率，以实际结算为准」（basis=rule_based 诚实口径）。